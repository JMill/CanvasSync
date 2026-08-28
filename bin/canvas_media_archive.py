#!/usr/bin/env python3
"""Archive the video embedded in an already-archived Canvas course.

canvas_browser_archive.py saves page HTML, but embedded video stays a dead
iframe. This walks the archived HTML/JSON, works out what each embed actually
is, and pulls down what that provider will give us:

    Kaltura (MediaSpace)  transcript (SRT + plain text), contact sheet, MP4
    Canvas native media   transcript via media_tracks, MP4
    YouTube               transcript + thumbnail via yt-dlp, MP4
    Vimeo                 whatever yt-dlp can reach
    LinkedIn Learning     inventoried only -- licensed, DRM'd, not retrievable

Two Kaltura sessions are needed and they see different things. An anonymous
widget session resolves public/third-party entries; an institutional KS lifted
from a logged-in MediaSpace embed resolves the institution's own recordings but
loses the public ones (different partner scope). Both are tried and unioned.

To get --ks: open a course video's MediaSpace embed in a logged-in browser and
read window.kalturaPlayer's config, or any api_v3 request's ks parameter. It is
a session token -- treat it like a password and expect it to expire in hours.

Usage:
    canvas_media_archive.py --archive-dir /path/to/COURSE [--ks <kaltura ks>]
        [--base https://psu.instructure.com --cookies cookies.json]
        [--sheets] [--video] [--youtube]

Default (no mode flags) fetches transcripts and metadata only -- cheap, and the
part that makes a course searchable offline. Re-running skips completed work.
"""

import argparse
import html
import json
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from si_archive.net import Throttle

KALTURA_API = "https://cdnapisec.kaltura.com/api_v3"
KALTURA_CDN = "https://cdnapisec.kaltura.com"


PATTERNS = {
    "kaltura": re.compile(r'entry_?[iI]d[/=]["\']?(\d_\w{8})'),
    "youtube": re.compile(r'(?:youtube(?:-nocookie)?\.com/(?:embed/|watch\?v=)|youtu\.be/)([\w-]{11})'),
    "canvas": re.compile(r'media_attachments_iframe/(\d+)'),
    "vimeo": re.compile(r'vimeo\.com/(?:video/)?(\d+)'),
    "linkedin": re.compile(r'linkedin\.com/learning/([\w/-]+)'),
}


def srt_to_text(caption):
    """Strip cue numbers and timestamps, leaving readable prose.

    Handles SRT and WebVTT. Kaltura serves both: institutional tracks tend to be
    SRT, while Zoom-sourced ones are VTT with a header, NOTE/STYLE blocks and
    named cue identifiers, all of which would otherwise land in the text.
    """
    out, buf = [], []
    skip_block = False
    for line in caption.splitlines():
        s = line.strip()
        if not s:
            skip_block = False
            if buf:
                out.append(" ".join(buf)); buf = []
            continue
        if skip_block:
            continue
        if s.startswith(("WEBVTT", "X-TIMESTAMP", "NOTE", "STYLE", "REGION")):
            skip_block = True          # these run until the next blank line
            continue
        if "-->" in s or s.isdigit():
            continue
        # A cue identifier is a short line immediately preceding a timestamp;
        # by this point timestamps are gone, so drop bare ids that carry no prose.
        if re.fullmatch(r"[\w.-]{1,40}", s) and not re.search(r"[a-z]{3}", s):
            continue
        buf.append(re.sub(r"</?[cvbi][^>]*>", "", s))   # inline VTT styling tags
    if buf:
        out.append(" ".join(buf))
    return "\n".join(out)


class MediaArchiver:
    def __init__(self, archive_dir, ks=None, base=None, cookies=None,
                 sheets=False, video=False, youtube=False,
                 slice_interval=60, max_slices=48, throttle=None, rate_limit=None):
        self.dir = Path(archive_dir)
        self.out = self.dir / "media"
        self.ks = ks
        self.want = {"sheets": sheets, "video": video, "youtube": youtube}
        self.slice_interval = slice_interval
        self.max_slices = max_slices
        self.base = base.rstrip("/") if base else None
        self.throttle = throttle or Throttle()
        self.rate_limit = rate_limit  # bytes/sec ceiling for large downloads
        self.s = requests.Session()
        self.s.headers["User-Agent"] = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36")
        if cookies:
            for c in json.loads(Path(cookies).read_text()):
                self.s.cookies.set(c["name"], c["value"], domain=c["domain"], path=c.get("path", "/"))
        self.state_path = self.out / "_state.json"
        self.state = {}
        if self.state_path.exists():
            self.state = json.loads(self.state_path.read_text())
        self.anon_ks = None
        self.partner = None
        self.results = {}
        self.notes = []

    # ----------------------------------------------------------------- http

    def get(self, url, tries=3, **kw):
        """Every read goes through here so nothing can bypass the pacing."""
        kw.setdefault("timeout", 60)
        for attempt in range(tries):
            self.throttle.wait(url)
            try:
                r = self.s.get(url, **kw)
            except requests.RequestException as e:
                if attempt == tries - 1:
                    self.notes.append(f"{url.split('?')[0][-60:]}: {e}")
                    return None
                time.sleep(2 ** attempt * 2)
                continue
            nap = self.throttle.pushback(r)
            if nap and attempt < tries - 1:
                print(f"    (server asked us to slow down; waiting {nap}s)")
                time.sleep(nap)
                continue
            return r
        return None

    def stream_to(self, url, dest, expect="video"):
        """Download a large file politely: resumable, and bandwidth-capped so a
        long run cannot saturate the connection."""
        self.throttle.wait(url)
        try:
            with self.s.get(url, stream=True, timeout=180, allow_redirects=True) as r:
                if not r.ok or expect not in (r.headers.get("content-type") or ""):
                    return None
                tmp = dest.with_suffix(".part")
                size = 0
                window_start, window_bytes = time.monotonic(), 0
                with open(tmp, "wb") as fh:
                    for chunk in r.iter_content(1 << 18):
                        fh.write(chunk)
                        size += len(chunk)
                        if not self.rate_limit:
                            continue
                        window_bytes += len(chunk)
                        elapsed = time.monotonic() - window_start
                        target = window_bytes / self.rate_limit
                        if target > elapsed:
                            time.sleep(target - elapsed)
                        if elapsed > 5:
                            window_start, window_bytes = time.monotonic(), 0
                tmp.rename(dest)
                return size
        except requests.RequestException as e:
            self.notes.append(f"download failed: {e}")
            return None

    # ---------------------------------------------------------------- scan

    def scan(self):
        """Find every media reference in the archived course, with its page."""
        found = {k: {} for k in PATTERNS}
        for f in sorted(self.dir.rglob("*")):
            if f.suffix not in (".html", ".json") or "media" in f.parts or "rendered" in f.parts:
                continue
            try:
                txt = f.read_text(errors="ignore")
            except OSError:
                continue
            for kind, pat in PATTERNS.items():
                for m in pat.finditer(txt):
                    found[kind].setdefault(m.group(1), set()).add(str(f.relative_to(self.dir)))
        # iframe title attributes are the only human-readable name for many embeds
        self.titles = {}
        for f in self.dir.rglob("*.html"):
            if "media" in f.parts:
                continue
            for m in re.finditer(r'<iframe[^>]*?id="kmsembed-(\d_\w{8})"[^>]*?title="([^"]*)"',
                                 f.read_text(errors="ignore")):
                self.titles[m.group(1)] = html.unescape(m.group(2))
        return {k: {i: sorted(v) for i, v in d.items()} for k, d in found.items()}

    # ------------------------------------------------------------- kaltura

    def _anon_ks(self):
        if self.anon_ks is None and self.partner:
            try:
                r = self.get(f"{KALTURA_API}/service/session/action/startWidgetSession",
                             params={"widgetId": f"_{self.partner}", "format": 1})
                self.anon_ks = (r.json().get("ks", "") if r is not None and r.ok else "")
            except Exception:
                self.anon_ks = ""
        return self.anon_ks or ""

    def _find_partner(self):
        """Partner id is not in the embed URL; recover it from any CDN reference."""
        for f in self.dir.rglob("*"):
            if f.suffix not in (".html", ".json") or "media" in f.parts:
                continue
            m = re.search(r'kaltura\.com/(?:html5/html5lib/[^/]+/mwEmbedFrame\.php/)?p/(\d{6,8})/',
                          f.read_text(errors="ignore"))
            if m:
                return m.group(1)
        return None

    def _kaltura_call(self, service, action, ks, **params):
        try:
            r = self.get(f"{KALTURA_API}/service/{service}/action/{action}",
                         params={"ks": ks, "format": 1, **params})
            return r.json() if r is not None and r.ok else {}
        except Exception:
            return {}

    def kaltura_meta(self, entry):
        """Try both sessions; they resolve disjoint sets of entries."""
        for ks in (self.ks, self._anon_ks()):
            if not ks:
                continue
            m = self._kaltura_call("baseEntry", "get", ks, entryId=entry)
            if m.get("name"):
                caps = self._kaltura_call("caption_captionasset", "list", ks,
                                          **{"filter:entryIdEqual": entry})
                return ks, m, caps.get("objects", []) or []
        return None, {}, []

    def kaltura_transcript(self, entry, ks, caps, dest):
        if not caps:
            return None
        # Prefer a human/official track over an auto-generated one.
        caps = sorted(caps, key=lambda c: ("auto" in (c.get("label") or "").lower(),
                                           c.get("label") or ""))
        cap = caps[0]
        r = self.get(f"{KALTURA_API}/service/caption_captionasset/action/serve",
                     params={"ks": ks, "captionAssetId": cap["id"]})
        if r is None or not r.ok or len(r.content) < 40:
            return None
        srt = r.text
        (dest / "transcript.srt").write_text(srt)
        (dest / "transcript.txt").write_text(srt_to_text(srt))
        return cap.get("label")

    def kaltura_sheet(self, entry, duration, dest):
        """Grid contact sheet. Kaltura's own vid_slices returns one wide strip,
        useless past a few minutes, so fetch slices and tile them."""
        if not duration:
            return None
        n = max(4, min(self.max_slices, int(duration // self.slice_interval) or 4))
        cols = 4 if n <= 16 else 6
        tmp = Path(tempfile.mkdtemp(prefix="sheet_"))
        try:
            got = 0
            for i in range(n):
                u = (f"{KALTURA_CDN}/p/{self.partner}/thumbnail/entry_id/{entry}"
                     f"/width/480/vid_slices/{n}/vid_slice/{i}")
                r = self.get(u)
                if r is not None and r.ok and len(r.content) > 1500:
                    (tmp / f"s{got:03d}.jpg").write_bytes(r.content)
                    got += 1
            if got < 2:
                return None
            rows = (got + cols - 1) // cols
            p = subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error", "-i", str(tmp / "s%03d.jpg"),
                 "-filter_complex", f"scale=480:-1,tile={cols}x{rows}:margin=6:padding=4:color=white",
                 "-frames:v", "1", str(dest / "contactsheet.jpg")],
                capture_output=True, text=True)
            if p.returncode != 0:
                self.notes.append(f"{entry}: ffmpeg tile failed: {p.stderr.strip()[:120]}")
                return None
            return got
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def kaltura_video(self, entry, ks, dest):
        target = dest / "video.mp4"
        if target.exists() and target.stat().st_size > 100_000:
            return target.stat().st_size
        url = (f"{KALTURA_CDN}/p/{self.partner}/sp/{self.partner}00/playManifest"
               f"/entryId/{entry}/format/download/ks/{ks}")
        return self.stream_to(url, target)

    # -------------------------------------------------------------- canvas

    def canvas_media(self, att_id, dest):
        """Canvas-hosted media: metadata carries caption tracks and mp4 sources."""
        if not self.base:
            return None
        r = self.get(f"{self.base}/api/v1/media_attachments/{att_id}")
        if r is None or not r.ok:
            r = self.get(f"{self.base}/api/v1/media_objects/{att_id}")
        if r is None or not r.ok:
            return None
        d = r.json()
        (dest / "meta.json").write_text(json.dumps(d, indent=1))
        for t in d.get("media_tracks", []) or []:
            content = t.get("content")
            if not content and t.get("url"):
                tr = self.get(t["url"])
                content = tr.text if tr is not None and tr.ok else None
            if content:
                (dest / f"transcript.{t.get('locale','en')}.vtt").write_text(content)
                (dest / "transcript.txt").write_text(srt_to_text(content))
        return d.get("title") or d.get("media_id")

    # ------------------------------------------------------------- yt-dlp

    def ytdlp(self, url, dest, want_video):
        if not shutil.which("yt-dlp"):
            self.notes.append("yt-dlp not installed; skipped YouTube/Vimeo")
            return None
        cmd = ["yt-dlp", "--no-warnings", "--ignore-errors",
               "--write-info-json", "--write-thumbnail", "--convert-thumbnails", "jpg",
               "--write-subs", "--write-auto-subs", "--sub-langs", "en.*",
               "--convert-subs", "srt", "-o", str(dest / "%(title).80s.%(ext)s"),
               # yt-dlp does its own bursty fetching, so give it the same manners.
               "--sleep-requests", str(round(self.throttle.min_gap, 1)),
               "--sleep-interval", "2", "--max-sleep-interval", "8",
               "--retries", "3", "--retry-sleep", "linear=2:30"]
        if self.rate_limit:
            cmd += ["--limit-rate", str(int(self.rate_limit))]
        cmd += ["-f", "bv*[height<=720]+ba/b[height<=720]"] if want_video else ["--skip-download"]
        cmd.append(url)
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
        for srt in dest.glob("*.srt"):
            (dest / "transcript.txt").write_text(srt_to_text(srt.read_text(errors="ignore")))
            break
        return p.returncode == 0

    # ---------------------------------------------------------------- run

    def run(self):
        self.out.mkdir(parents=True, exist_ok=True)
        refs = self.scan()
        self.partner = self._find_partner()
        counts = {k: len(v) for k, v in refs.items()}
        print(f"scanned {self.dir.name}: " + ", ".join(f"{k}={v}" for k, v in counts.items() if v))
        if refs["kaltura"] and not self.partner:
            self.notes.append("kaltura entries found but no partner id in archive; skipping them")

        for entry, pages in sorted(refs["kaltura"].items()):
            if not self.partner:
                break
            dest = self.out / "kaltura" / entry
            dest.mkdir(parents=True, exist_ok=True)
            ks, meta, caps = self.kaltura_meta(entry)
            name = meta.get("name") or self.titles.get(entry) or entry
            dur = meta.get("duration") or 0
            rec = {"kind": "kaltura", "id": entry, "name": name, "duration": dur,
                   "pages": pages, "resolved": bool(meta.get("name"))}
            done = self.state.get(f"kaltura:{entry}", {})
            if not (dest / "transcript.srt").exists():
                lbl = self.kaltura_transcript(entry, ks, caps, dest) if ks else None
                rec["transcript"] = lbl
            else:
                rec["transcript"] = done.get("transcript", "cached")
            if self.want["sheets"] and not (dest / "contactsheet.jpg").exists():
                rec["slices"] = self.kaltura_sheet(entry, dur, dest)
            if self.want["video"] and ks:
                rec["video_bytes"] = self.kaltura_video(entry, ks, dest)
            (dest / "meta.json").write_text(json.dumps({**rec, "raw": meta}, indent=1))
            self.state[f"kaltura:{entry}"] = rec
            self.results[f"kaltura:{entry}"] = rec
            flag = "ok " if rec["resolved"] else "?? "
            print(f"  {flag}{entry} {str(name)[:44]:<46} {dur or '?':>5}s "
                  f"transcript={'y' if rec.get('transcript') else 'n'}"
                  + (f" slices={rec.get('slices')}" if self.want["sheets"] else ""))

        for att, pages in sorted(refs["canvas"].items()):
            dest = self.out / "canvas" / att
            dest.mkdir(parents=True, exist_ok=True)
            name = self.canvas_media(att, dest)
            rec = {"kind": "canvas", "id": att, "name": name, "pages": pages,
                   "resolved": bool(name),
                   "transcript": any(dest.glob("transcript*"))}
            self.results[f"canvas:{att}"] = rec
            self.state[f"canvas:{att}"] = rec
            print(f"  {'ok ' if name else '?? '}canvas media {att} {str(name)[:40]}")

        if self.want["youtube"]:
            for vid, pages in sorted(refs["youtube"].items()):
                dest = self.out / "youtube" / vid
                dest.mkdir(parents=True, exist_ok=True)
                if any(dest.glob("*.info.json")):
                    print(f"  -- youtube {vid} cached"); continue
                ok = self.ytdlp(f"https://www.youtube.com/watch?v={vid}", dest, self.want["video"])
                rec = {"kind": "youtube", "id": vid, "pages": pages, "resolved": bool(ok),
                       "transcript": (dest / "transcript.txt").exists()}
                self.results[f"youtube:{vid}"] = rec
                self.state[f"youtube:{vid}"] = rec
                print(f"  {'ok ' if ok else '!! '}youtube {vid}")
            for vid, pages in sorted(refs["vimeo"].items()):
                dest = self.out / "vimeo" / vid
                dest.mkdir(parents=True, exist_ok=True)
                ok = self.ytdlp(f"https://vimeo.com/{vid}", dest, self.want["video"])
                self.results[f"vimeo:{vid}"] = {"kind": "vimeo", "id": vid, "pages": pages,
                                                "resolved": bool(ok)}

        for slug, pages in sorted(refs["linkedin"].items()):
            self.results[f"linkedin:{slug}"] = {
                "kind": "linkedin", "id": slug, "pages": pages, "resolved": False,
                "note": "LinkedIn Learning is licensed and DRM-protected; inventory only."}

        self.state_path.write_text(json.dumps(self.state, indent=1))
        self.write_index(refs)
        return self.results

    def write_index(self, refs):
        rows = []
        for key, r in sorted(self.results.items(),
                             key=lambda kv: (kv[1]["kind"], str(kv[1].get("name") or kv[1]["id"]))):
            kind, ident = r["kind"], r["id"]
            d = self.out / kind / ident
            sheet = (d / "contactsheet.jpg")
            tx = next(iter(d.glob("transcript.txt")), None) if d.exists() else None
            dur = r.get("duration") or 0
            durs = f"{dur//60}:{dur%60:02d}" if dur else "&mdash;"
            links = []
            if tx:
                links.append(f'<a href="{kind}/{ident}/{tx.name}">transcript</a>')
            if sheet.exists():
                links.append(f'<a href="{kind}/{ident}/contactsheet.jpg">contact sheet</a>')
            if (d / "video.mp4").exists():
                links.append(f'<a href="{kind}/{ident}/video.mp4">video</a>')
            note = html.escape(str(r.get("note") or ""))
            pages = ", ".join(html.escape(p) for p in r.get("pages", [])[:3])
            thumb = ""
            if sheet.exists():
                thumb = f'<img src="{kind}/{ident}/contactsheet.jpg" style="max-width:220px">'
            rows.append(
                f"<tr><td>{html.escape(kind)}</td>"
                f"<td>{html.escape(str(r.get('name') or ident))}<br>"
                f"<span class=p>{pages}</span>{'<br>' + note if note else ''}</td>"
                f"<td>{durs}</td><td>{' &middot; '.join(links) or '&mdash;'}</td>"
                f"<td>{thumb}</td></tr>")
        have_tx = sum(1 for r in self.results.values() if r.get("transcript"))
        body = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Media &mdash; {html.escape(self.dir.name)}</title><style>
body{{max-width:1100px;margin:2em auto;font-family:-apple-system,sans-serif;padding:0 1em}}
table{{border-collapse:collapse;width:100%}}td,th{{border-bottom:1px solid #ddd;padding:.5em;
vertical-align:top;font-size:.9em}}.p{{color:#888;font-size:.85em}}
img{{border:1px solid #ccc}}</style></head><body>
<h1>Embedded media &mdash; {html.escape(self.dir.name)}</h1>
<p>{len(self.results)} embeds &middot; {have_tx} with transcripts.
LinkedIn Learning items are listed for reference only: the content is licensed and
DRM-protected, so it cannot be archived.</p>
<table><tr><th>source</th><th>title / pages</th><th>len</th><th>files</th><th></th></tr>
{''.join(rows)}</table></body></html>"""
        (self.out / "index.html").write_text(body)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--archive-dir", required=True, help="a course dir made by canvas_browser_archive.py")
    ap.add_argument("--ks", help="Kaltura session for institution-owned entries")
    ap.add_argument("--base", help="Canvas base URL, for Canvas-hosted media")
    ap.add_argument("--cookies", help="Canvas cookie JSON, for Canvas-hosted media")
    ap.add_argument("--sheets", action="store_true", help="build contact sheets (needs ffmpeg)")
    ap.add_argument("--video", action="store_true", help="download full video (large)")
    ap.add_argument("--youtube", action="store_true", help="fetch YouTube/Vimeo via yt-dlp")
    ap.add_argument("--slice-interval", type=int, default=60, help="seconds between sheet frames")
    ap.add_argument("--max-slices", type=int, default=48)
    ap.add_argument("--min-gap", type=float, default=1.5,
                    help="minimum seconds between requests to a host (default 1.5)")
    ap.add_argument("--jitter", type=float, default=1.5,
                    help="random extra delay added to each request, 0..N seconds")
    ap.add_argument("--rest-every", type=int, default=25,
                    help="take a longer pause every N requests (0 disables)")
    ap.add_argument("--limit-rate", type=float, default=2e6,
                    help="bytes/sec ceiling for video downloads (default 2MB/s; 0 = uncapped)")
    a = ap.parse_args()

    throttle = Throttle(min_gap=a.min_gap, jitter=a.jitter, rest_every=a.rest_every)
    m = MediaArchiver(a.archive_dir, a.ks, a.base, a.cookies,
                      a.sheets, a.video, a.youtube, a.slice_interval, a.max_slices,
                      throttle=throttle, rate_limit=(a.limit_rate or None))
    res = m.run()
    ok = sum(1 for r in res.values() if r.get("resolved"))
    tx = sum(1 for r in res.values() if r.get("transcript"))
    print(f"\n{len(res)} embeds: {ok} resolved, {tx} with transcripts -> {m.out}/index.html")
    print(f"{m.throttle.count} requests, {m.throttle.waited:.0f}s spent deliberately waiting")
    for n in m.notes:
        print(f"  note: {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
