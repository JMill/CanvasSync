"""Stage 3 -- download the Vimeo videos the Elucidat pages embed.

Two access classes, both resolvable:
  * hashed  -- unlisted MIT PE recordings named MIT_INN_M<n>_V<n>; these are
               renditions of MP4s already on disk, reconciled in stage 5
  * bare id -- third-party reference material

Always request player.vimeo.com/video/<id>; the vimeo.com/<id> form fails
yt-dlp's OAuth token path. One id (777331374) returned a TLS-fingerprint block
during reconnaissance, so a --impersonate retry is built in.
"""
import subprocess
from pathlib import Path

from si_archive import constants


def embed_url(vid, vhash):
    base = f"https://player.vimeo.com/video/{vid}"
    return f"{base}?h={vhash}" if vhash else base


def collect_ids(elucidat_json):
    """Deduplicate every embed across all projects, keeping first-seen order."""
    order, found = [], {}
    for key, project in elucidat_json.items():
        for page in project.get("pages", []):
            for ref in page.get("vimeo", []):
                vid = ref["id"]
                if vid not in found:
                    found[vid] = {"id": vid, "hash": ref.get("hash"), "projects": []}
                    order.append(vid)
                if ref.get("hash") and not found[vid]["hash"]:
                    found[vid]["hash"] = ref["hash"]
                if key not in found[vid]["projects"]:
                    found[vid]["projects"].append(key)
    return [found[v] for v in order]


def _build_cmd(url, template, impersonate=False):
    """The yt-dlp invocation shared by the normal attempt and the retry.

    Vimeo serves these as HLS with separate video-only and audio-only
    renditions -- no single muxed format exists, and the audio rendition's
    reported extension is mp4, not m4a. A format selector that filters on
    ext=m4a or asks for a single-file `best` therefore matches nothing and
    yt-dlp exits with "Requested format is not available." bestvideo*+bestaudio
    is what yt-dlp falls back to by default when no -f is given at all, so
    this is explicit rather than novel; --merge-output-format keeps the
    ffmpeg-merged result a consistent .mp4 regardless of the source containers.
    """
    cmd = ["yt-dlp", "--no-warnings", "--no-playlist",
           "--referer", constants.ELUCIDAT_REFERER,
           "-f", "bestvideo*+bestaudio/best", "--merge-output-format", "mp4",
           "--write-subs", "--sub-langs", "all", "--convert-subs", "srt",
           "--print", "after_move:%(filepath)s|%(title)s|%(duration)s",
           "-o", template, url]
    if impersonate:
        cmd = cmd[:1] + ["--impersonate", "chrome"] + cmd[1:]
    return cmd


def _run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=1800)


def _size_of(path):
    """Local size of a completed download, or None if it can't be read.

    Task 6's match_renditions picks the canonical copy of a video by comparing
    this against the local file's size -- a missing/absent value reads as 0
    and the local copy silently wins every time, even when the Vimeo copy is
    genuinely better.
    """
    if not path:
        return None
    try:
        return Path(path).stat().st_size
    except OSError:
        return None


def _ok_record(vid, path, title, duration):
    return {"id": vid, "status": "ok", "path": path, "title": title,
            "duration": duration, "size": _size_of(path), "error": None}


def _gap_record(vid, error):
    return {"id": vid, "status": "gap", "path": None, "title": None,
            "duration": None, "size": None, "error": error}


def download(vid, vhash, out_dir):
    """Fetch one video plus any native captions. Never raises -- returns a record."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    url = embed_url(vid, vhash)
    template = str(out_dir / f"{vid} - %(title)s.%(ext)s")

    try:
        result = _run(_build_cmd(url, template))
        if result.returncode != 0 and "TLS fingerprint" in (result.stderr or ""):
            # Anti-bot fingerprinting; curl-cffi lets yt-dlp present a real browser TLS profile.
            result = _run(_build_cmd(url, template, impersonate=True))
    except (subprocess.SubprocessError, FileNotFoundError) as exc:
        # A 30-minute timeout on a large 1080p file, or yt-dlp missing from
        # PATH, must become a gap like any other failure -- not abort the
        # whole paced run over one bad video (mirror_project, probe_duration).
        return _gap_record(vid, str(exc).strip()[-500:])

    if result.returncode != 0:
        return _gap_record(vid, (result.stderr or "").strip()[-500:])

    line = (result.stdout or "").strip().splitlines()[-1]
    path, title, duration = (line.split("|", 2) + [None, None])[:3]
    try:
        duration = float(duration)
    except (TypeError, ValueError):
        duration = None
    return _ok_record(vid, path, title, duration)


def download_all(elucidat_json, out_dir, throttle):
    records = []
    targets = collect_ids(elucidat_json)
    for index, ref in enumerate(targets, start=1):
        throttle.wait("https://player.vimeo.com/")
        record = download(ref["id"], ref["hash"], out_dir)
        record["projects"] = ref["projects"]
        status = record["title"] if record["status"] == "ok" else "GAP"
        print(f"    [{index}/{len(targets)}] {ref['id']}: {status}")
        records.append(record)
    return records
