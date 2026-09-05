# CanvasSync (jmill fork)

Fork of perslev/CanvasSync — Python CLI that syncs Canvas LMS courses to disk (`python bin/canvas.py`). Used here as personal backup tooling, not active upstream development.

## What this fork adds

- Env-var config for non-interactive, multi-instance use (commit `64438db`): vars in `CanvasSync/settings/settings.py` and `cryptography.py`.
- `bin/canvas_login.py`: drives a real Chrome window through the PSU/Duo login and dumps the session cookies as JSON. Keeps its own profile at `~/.cache/canvas-archive-profile`, so after the first Duo approval later runs find the session already live and exit immediately.
- `bin/canvas_browser_archive.py`: archives a course using a logged-in browser session's cookies, for institutions like PSU that disable personal API tokens. Wrapped by `~/bin/canvas-archive`.
- `bin/canvas_unlock_walk.py`: opens up prerequisite-chained courses by walking module items in order the way clicking "Next" does, fulfilling `must_view` requirements so the archiver can see the content. Run it *before* archiving.
- `bin/canvas_media_archive.py`: embedded video is a dead iframe in the archive; this pulls transcripts, contact sheets and (optionally) MP4s for Kaltura, Canvas-native, YouTube and Vimeo embeds. Run it *after* archiving.
- `si_archive/` + `bin/si_archive.py`: nine-stage pipeline that merged four partial sources into the offline Systematic Innovation archive (MIT PE, `SISH-ENG-001-FEB22`). Stages are independently re-runnable: `cartridge elucidat vimeo local reconcile media render verify`, or `all` (which skips completed network stages unless `--force`). Output at `/Volumes/Desk SSD/SystematicInnovation-Archive`; it self-verifies into `REPORT.md`.

## Workflows on this machine

- **PSU archives** (API tokens disabled by PSU): `canvas_login.py --out <scratch>/cookies.json` → `canvas_unlock_walk.py --dry-run` for prereq-chained courses → `~/bin/canvas-archive <cookies.json>`. Incremental; re-run as modules unlock.
- **Emeritus backup** (API works): `~/bin/canvassync-emeritus`.
- Interpreter: `.venv/bin/python` (repo is `pip install -e`'d into it, so local edits are live).

## Gotchas

- Instance isolation needs BOTH `CANVASSYNC_SETTINGS_PATH` and `CANVASSYNC_PW_PATH` set per wrapper; missing either silently breaks the other instance's settings decryption (PKCS#7 padding error).
- Cookie dumps contain `canvas_session` — keep them in scratch dirs, never in the repo or Dropbox.
- Two different gates look alike but aren't: date-locked modules (AI 574) just wait for a date, while prerequisite-chained ones (ENGR 820) unlock only as requirements are met. `canvas_unlock_walk.py` helps with the second and correctly does nothing for the first.
- The walker fulfils `must_view` only. `must_submit`/`must_contribute` requirements are real coursework — it reports them as walls and stops rather than submitting anything.
- Kaltura needs *two* sessions and they see different things: an anonymous widget session resolves public/third-party entries, an institutional KS (lifted from a logged-in MediaSpace embed) resolves PSU's own recordings but loses the public ones. `canvas_media_archive.py` tries both.
- LinkedIn Learning embeds are licensed and DRM-protected — inventoried, never downloadable. PSU courses lean on them heavily (138 in ENGR 801 alone).
- All network access in these tools is serial and paced (`Throttle`, now in `si_archive/net.py` and shared): randomised gaps, periodic longer rests, and backoff that persists after any 429/503. Keep it that way — a burst risks the session.
- Elucidat courses store each page's HTML **character-reversed** under an `lmth` key (`html` backwards); `window.NAVIGATION_OBJECT` in the project JS is a complete page manifest. No DRM — fully mirrorable. See `si_archive/elucidat.py`.
- Canvas cartridges are lossy in two ways worth knowing: `<id>/assessment_qti.xml` drops questions that `non_cc_assessments/<id>.xml.qti` keeps (Entry Survey 17 vs 23), and content unreachable from the module graph is invisible to a naive walk — this course had 42 such items, including its entire announcement stream. Diff the manifest against the module graph, don't follow links.
- Whisper fabricates fluent text on non-speech audio in at least three modes: silence (`you you you`), music-only (`We'll be right back.`), and a mid-recording repetition loop on long files. Guards live in `si_archive/media.py`; `--condition-on-previous-text False` recovers the loop case. Never trust a transcript's existence — check its word distribution.
