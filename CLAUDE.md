# CanvasSync (jmill fork)

Fork of perslev/CanvasSync — Python CLI that syncs Canvas LMS courses to disk (`python bin/canvas.py`). Used here as personal backup tooling, not active upstream development.

## What this fork adds

- Env-var config for non-interactive, multi-instance use (commit `64438db`): vars in `CanvasSync/settings/settings.py` and `cryptography.py`.
- `bin/canvas_browser_archive.py` (untracked): archives a course using a logged-in browser session's cookies, for institutions like PSU that disable personal API tokens. Wrapped by `~/bin/canvas-archive`.

## Workflows on this machine

- **PSU archives** (API tokens disabled by PSU): Playwright login to psu.instructure.com → dump cookies to JSON → `~/bin/canvas-archive <cookies.json>`. Incremental; re-run as modules unlock.
- **Emeritus backup** (API works): `~/bin/canvassync-emeritus`.
- Interpreter: `.venv/bin/python` (repo is `pip install -e`'d into it, so local edits are live).

## Gotchas

- Instance isolation needs BOTH `CANVASSYNC_SETTINGS_PATH` and `CANVASSYNC_PW_PATH` set per wrapper; missing either silently breaks the other instance's settings decryption (PKCS#7 padding error).
- Cookie dumps contain `canvas_session` — keep them in scratch dirs, never in the repo or Dropbox.
