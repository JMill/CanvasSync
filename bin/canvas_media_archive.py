#!/usr/bin/env python3
"""Archive the video embedded in an already-archived Canvas course.

canvas_browser_archive.py saves page HTML, but embedded video stays a dead
iframe. This walks the archived HTML/JSON, works out what each embed actually
is, and pulls down what that provider will give us:

    Kaltura (MediaSpace)  transcript (SRT + plain text), contact sheet, MP4
    Canvas native media   transcript via media_tracks, MP4
    YouTube               transcript + thumbnail via yt-dlp, MP4
    Vimeo                 transcript + MP4 where yt-dlp can still reach it,
                          otherwise title/author/duration/poster via oembed
    LinkedIn Learning     inventoried only -- licensed, DRM'd, not retrievable

Two providers now routinely refuse a stream to anything that is not a signed-in
browser: Vimeo's web client demands a login and its player config answers 403,
and PSU shuts the whole Canvas media API (media_attachments, media_objects and
the per-course listing alike). Neither is treated as a dead end. Canvas media is
recovered from the media_object that the embed iframe bootstraps into its ENV
blob, and an unreachable Vimeo stream still gets a real inventory row from
oembed. An embed that cannot be retrieved is recorded with a note saying why --
never left as a silent blank, since a missing row reads as "nothing was there".

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


MEDIA_EXT = (".mp4", ".mkv", ".webm")


def collapse_rolling(text):
    """Collapse YouTube's rolling-window auto-captions into linear prose.

    An auto-generated track re-sends the tail of one cue at the head of the next,
    so flattening it naively repeats nearly every phrase about three times -- a
    "transcript" that reads at 400+ wpm against a human ~140. For each cue, drop
    the longest leading run of tokens that the text so far already ends with.

    Only ever applied to auto-generated tracks: on a human transcript this would
    quietly eat a genuine repetition.
    """
    out = []
    for line in text.splitlines():
        toks = line.split()
        if not toks:
            continue
        overlap = 0
        for size in range(min(len(toks), len(out)), 0, -1):
            if out[-size:] == toks[:size]:
                overlap = size
                break
        out.extend(toks[overlap:])
    return " ".join(out)



def has_media_file(dest):
    """True when a finished, merged media file sits in this embed's directory.

    yt-dlp names its output after the title, not "video.mp4", so presence has to
    be tested by extension rather than by a fixed filename. It also leaves
    per-format intermediates -- "Hellmart.f251.webm" beside "Hellmart.f399.mp4.part"
    -- when a download dies before the merge. Those are single streams, often
    audio only, so counting one as the finished video makes a half-downloaded
    entry look complete and it never gets retried.
    """
    if not dest.is_dir():
        return False
    return any(f.suffix.lower() in MEDIA_EXT and not re.fullmatch(r".*\.f\d+", f.stem)
               for f in dest.iterdir())


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
                 slice_interval=60, max_slices=48, throttle=None, rate_limit=None,
                 max_height=720):
        self.dir = Path(archive_dir)
        self.out = self.dir / "media"
        self.ks = ks
        self.want = {"sheets": sheets, "video": video, "youtube": youtube}
        self.slice_interval = slice_interval
        self.max_slices = max_slices
        self.max_height = max_height
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

    def _best_mp4(self, sources):
        """Best mp4 at or below --max-height; the smallest available if all exceed it.

        Shares the ceiling with yt-dlp so every provider in one run lands at the
        same quality, rather than each having its own private idea of "good".
        """
        out = []
        for src in sources or []:
            u = src.get("url") or src.get("src")
            if not u or "mp4" not in (src.get("content_type") or src.get("fileExt") or ""):
                continue
            try:
                h = int(src.get("height") or 0)
            except (TypeError, ValueError):
                h = 0
            out.append((h, u))
        if not out:
            return None
        under = [x for x in out if x[0] <= self.max_height]
        return max(under)[1] if under else min(out)[1]

    def _iframe_media_object(self, att_id):
        """Recover Canvas media metadata from the embed page.

        PSU shuts the whole media API -- media_attachments, media_objects and
        the per-course listing all answer 404/403 -- so the documented routes
        yield nothing at all. The iframe a browser actually loads still
        bootstraps a complete media_object into its ENV blob: title, caption
        tracks and bitrate-tagged mp4 sources. Same lesson as the discussion
        attachments: when the API is closed, the rendered view still carries it.
        """
        r = self.get(f"{self.base}/media_attachments_iframe/{att_id}",
                     params={"embedded": "true", "type": "video"})
        if r is None or not r.ok:
            return None
        key = '"media_object":'
        i = r.text.find(key)
        if i < 0:
            return None
        try:
            obj, _ = json.JSONDecoder().raw_decode(r.text, i + len(key))
        except ValueError:
            return None
        return obj or None

    def canvas_media(self, att_id, dest):
        """Canvas-hosted media: metadata carries caption tracks and mp4 sources."""
        if not self.base:
            return None
        r = self.get(f"{self.base}/api/v1/media_attachments/{att_id}")
        if r is None or not r.ok:
            r = self.get(f"{self.base}/api/v1/media_objects/{att_id}")
        if r is None or not r.ok:
            d = self._iframe_media_object(att_id)
            if not d:
                return None
        else:
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
        if self.want["video"]:
            target = dest / "video.mp4"
            if not (target.exists() and target.stat().st_size > 100_000):
                src = self._best_mp4(d.get("media_sources"))
                if src:
                    self.stream_to(src, target)
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
               # YouTube resets long-lived connections on big files, and the
               # rate cap makes them longer still. Each attempt resumes from the
               # .part, so the answer is patience, not a faster download.
               "--retries", "10", "--fragment-retries", "10",
               "--retry-sleep", "linear=2:30", "--continue"]
        if self.rate_limit:
            cmd += ["--limit-rate", str(int(self.rate_limit))]
        h = self.max_height
        cmd += ["-f", f"bv*[height<={h}]+ba/b[height<={h}]"] if want_video else ["--skip-download"]
        cmd.append(url)
        # A metadata-only pass is quick; a 1080p lecture over a 2MB/s cap with
        # reset-and-resume cycles is not, and 900s silently truncated it.
        budget = 5400 if want_video else 900
        attempts = 3 if want_video else 1
        for attempt in range(attempts):
            try:
                p = subprocess.run(cmd, capture_output=True, text=True, timeout=budget)
            except subprocess.TimeoutExpired:
                self.notes.append(f"yt-dlp timed out after {budget}s: {url}")
                return False
            if p.returncode == 0:
                break
            # Resume picks up where the reset left off, so another invocation is
            # cheap and usually finishes what retries alone could not.
            if attempt == attempts - 1:
                err = (p.stderr or "").strip().splitlines()
                tail = err[-1][:200] if err else f"exit {p.returncode}"
                self.notes.append(f"yt-dlp failed for {url}: {tail}")
        self.write_transcript(dest)
        return p.returncode == 0

    def write_transcript(self, dest):
        """(Re)build transcript.txt from the best caption track already on disk.

        Called on the cached path too, so a re-run repairs a transcript that an
        earlier version of this tool built from the wrong track -- the files are
        local, so it costs nothing and the archive heals itself.
        """
        cap, is_auto = self._pick_caption(dest)
        if not cap:
            return False
        flat = srt_to_text(cap.read_text(errors="ignore"))
        (dest / "transcript.txt").write_text(
            collapse_rolling(flat) if is_auto else flat)
        return True

    @staticmethod
    def _pick_caption(dest):
        """Choose a caption track, preferring the uploader's over YouTube's ASR.

        --write-subs and --write-auto-subs both fire, and the two are not
        equivalent: the auto track is an unpunctuated rolling window with a
        unique-word ratio around 0.11, against ~0.42 for the human one. Taking
        whatever glob yields first picks the bad track roughly half the time --
        and ".en-orig.srt" sorts ahead of ".en-US.srt", so in practice it lost
        every time. Returns (path, is_auto) or (None, False).
        """
        srts = sorted(dest.glob("*.srt"))
        if not srts:
            return None, False
        manual = []
        info = next(iter(dest.glob("*.info.json")), None)
        if info:
            try:
                manual = list((json.loads(info.read_text(errors="ignore"))
                               .get("subtitles") or {}).keys())
            except ValueError:
                pass
        for lang in manual:
            for cand in srts:
                if cand.name.endswith(f".{lang}.srt"):
                    return cand, False
        return srts[0], True

    @staticmethod
    def _ytdlp_meta(dest):
        """Title and duration from the info.json yt-dlp leaves behind."""
        info = next(iter(dest.glob("*.info.json")), None)
        if not info:
            return {}
        try:
            d = json.loads(info.read_text(errors="ignore"))
        except ValueError:
            return {}
        return {"name": d.get("title"), "duration": int(d.get("duration") or 0)}

    def vimeo_oembed(self, vid):
        """Metadata for a Vimeo video yt-dlp can no longer open.

        Vimeo's web client now demands a login, and its player config endpoint
        answers 403 to anything that does not look like a browser, so even a
        fully public course video can be unreachable as a stream. oembed is
        still open and carries title, author, duration and a poster frame --
        enough to inventory the video honestly rather than leave a blank row,
        which is the same treatment LinkedIn Learning gets.
        """
        r = self.get("https://vimeo.com/api/oembed.json",
                     params={"url": f"https://vimeo.com/{vid}"})
        if r is None or r.status_code != 200:
            return None
        try:
            return r.json()
        except ValueError:
            return None

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
                # Cached metadata is not the same as cached video: asking for
                # --video after a metadata-only run must actually fetch the file,
                # not read the info.json as proof there is nothing left to do.
                if any(dest.glob("*.info.json")) and not (
                        self.want["video"] and not has_media_file(dest)):
                    # Skipping the fetch must not drop the embed from the index:
                    # restore the row from state rather than falling straight
                    # through, or a re-run silently shrinks the archive.
                    rec = dict(self.state.get(f"youtube:{vid}") or
                               {"kind": "youtube", "id": vid, "resolved": True})
                    rec["pages"] = pages
                    self.write_transcript(dest)
                    rec["transcript"] = (dest / "transcript.txt").exists()
                    rec.update({k: v for k, v in self._ytdlp_meta(dest).items() if v})
                    self.results[f"youtube:{vid}"] = rec
                    self.state[f"youtube:{vid}"] = rec
                    print(f"  -- youtube {vid} cached"); continue
                ok = self.ytdlp(f"https://www.youtube.com/watch?v={vid}", dest, self.want["video"])
                rec = {"kind": "youtube", "id": vid, "pages": pages, "resolved": bool(ok),
                       "transcript": (dest / "transcript.txt").exists()}
                rec.update({k: v for k, v in self._ytdlp_meta(dest).items() if v})
                self.results[f"youtube:{vid}"] = rec
                self.state[f"youtube:{vid}"] = rec
                print(f"  {'ok ' if ok else '!! '}youtube {vid}")
            for vid, pages in sorted(refs["vimeo"].items()):
                dest = self.out / "vimeo" / vid
                dest.mkdir(parents=True, exist_ok=True)
                prev = self.state.get(f"vimeo:{vid}") or {}
                # Retry for video only if yt-dlp reached this one before. An entry
                # that resolved via oembed has no stream to fetch, and retrying it
                # every --video run would just hammer Vimeo for a guaranteed 403.
                want_stream = (self.want["video"] and prev.get("resolved")
                               and not has_media_file(dest))
                if (any(dest.glob("*.info.json")) or (dest / "meta.json").exists()) \
                        and not want_stream:
                    rec = dict(prev or {"kind": "vimeo", "id": vid, "resolved": True})
                    rec["pages"] = pages
                    self.results[f"vimeo:{vid}"] = rec
                    print(f"  -- vimeo {vid} cached")
                    continue
                ok = self.ytdlp(f"https://vimeo.com/{vid}", dest, self.want["video"])
                rec = {"kind": "vimeo", "id": vid, "pages": pages, "resolved": bool(ok),
                       "transcript": (dest / "transcript.txt").exists()}
                if not ok:
                    meta = self.vimeo_oembed(vid)
                    if meta:
                        rec.update(name=meta.get("title"),
                                   duration=meta.get("duration") or 0,
                                   author=meta.get("author_name"),
                                   note="stream needs a logged-in Vimeo session; "
                                        "metadata and poster frame only")
                        if meta.get("thumbnail_url"):
                            self.stream_to(meta["thumbnail_url"], dest / "poster.jpg",
                                           expect="image")
                        (dest / "meta.json").write_text(
                            json.dumps({**rec, "raw": meta}, indent=1))
                self.results[f"vimeo:{vid}"] = rec
                self.state[f"vimeo:{vid}"] = rec
                flag = "ok " if ok else ("~~ " if rec.get("name") else "!! ")
                print(f"  {flag}vimeo {vid} {str(rec.get('name') or '')[:40]:<42} "
                      f"{rec.get('duration') or '?':>5}s "
                      f"transcript={'y' if rec.get('transcript') else 'n'}")

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
            elif (d / "poster.jpg").exists():
                thumb = f'<img src="{kind}/{ident}/poster.jpg" style="max-width:220px">'
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
    ap.add_argument("--max-height", type=int, default=720,
                    help="vertical resolution ceiling for --video downloads "
                         "(default 720; use 1080 or higher when disk is not the constraint)")
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
                      throttle=throttle, rate_limit=(a.limit_rate or None),
                      max_height=a.max_height)
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
