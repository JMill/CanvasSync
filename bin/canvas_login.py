#!/usr/bin/env python3
"""Open a browser for an interactive Canvas login, then dump session cookies.

PSU disables user-generated API tokens, so `canvas_browser_archive.py` rides a
real browser session's cookies. This script produces that cookie dump.

It drives Chrome with a profile owned by this repo (not the shared
playwright-mcp profiles, which any other tool may hold a lock on). The profile
persists, but a Canvas login does NOT survive it: `canvas_session` is a
non-persistent cookie, which Chrome drops when the browser exits. Every run
therefore starts unauthenticated and needs a fresh Duo approval -- verified by
launching the profile cold and getting 401 unauthenticated with no Canvas
cookies restored. Budget for a human being present; unattended runs time out.

Usage:
    canvas_login.py --out /path/to/cookies.json
    canvas_login.py --out cookies.json --base https://psu.instructure.com

Exits non-zero if no logged-in session was established before --timeout.
Keep the output in a scratch dir: it contains `canvas_session`.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

DEFAULT_PROFILE = Path.home() / ".cache" / "canvas-archive-profile"


def logged_in(request, base):
    """True when the session cookie is accepted by the API as a real user."""
    try:
        r = request.get(f"{base}/api/v1/users/self",
                        headers={"Accept": "application/json"}, timeout=20000)
    except Exception:
        return None
    if r.status != 200:
        return None
    # Canvas may prefix JSON with an anti-CSRF guard.
    data = json.loads(r.text().lstrip(")]}'\n"))
    return data.get("name") or data.get("id")


def write_cookie_dump(path, cookies):
    """Write the cookie JSON to `path`, owner-readable from the first byte.

    The dump contains `canvas_session`. Creating the file at the umask default
    and chmod-ing afterwards leaves a window in which it is world-readable, and
    if the path already exists with wider bits the cookies sit exposed for the
    whole write. So open with 0600 and fchmod before any content lands -- the
    fchmod is what covers the pre-existing file, since O_CREAT's mode applies
    only to a file the call actually creates.
    """
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.fchmod(fd, 0o600)
        fh = os.fdopen(fd, "w")
    except BaseException:
        # Only the raw fd is ours to close here. Once fdopen returns, the file
        # object owns it and closing it again could shut an unrelated fd that
        # has since been handed out under the same number.
        os.close(fd)
        raise
    with fh:
        json.dump(cookies, fh, indent=2)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="https://psu.instructure.com")
    ap.add_argument("--out", required=True, help="where to write the cookie JSON")
    ap.add_argument("--profile", default=str(DEFAULT_PROFILE),
                    help=f"Chrome user-data-dir (default: {DEFAULT_PROFILE})")
    ap.add_argument("--timeout", type=int, default=420,
                    help="seconds to wait for an interactive login (default: 420)")
    args = ap.parse_args()

    base = args.base.rstrip("/")
    # The profile holds a live Canvas session in Chrome's own cookie store,
    # so keep it owner-only; exist_ok skips the mode on an existing dir.
    profile = Path(args.profile)
    profile.mkdir(parents=True, exist_ok=True, mode=0o700)
    profile.chmod(0o700)

    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            args.profile, channel="chrome", headless=False,
            viewport={"width": 1280, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(f"{base}/", wait_until="domcontentloaded")

        who = logged_in(ctx.request, base)
        if who:
            print(f"already logged in as {who}", flush=True)
        else:
            print(f"waiting up to {args.timeout}s for login at {base} "
                  f"(complete the Duo prompt in the browser window)...", flush=True)
            deadline = time.time() + args.timeout
            while time.time() < deadline:
                time.sleep(3)
                who = logged_in(ctx.request, base)
                if who:
                    print(f"logged in as {who}", flush=True)
                    break
            else:
                print("timed out with no session", file=sys.stderr)
                ctx.close()
                return 1

        cookies = [{"name": c["name"], "value": c["value"],
                    "domain": c["domain"], "path": c.get("path", "/")}
                   for c in ctx.cookies()]
        out = write_cookie_dump(args.out, cookies)
        names = {c["name"] for c in cookies}
        print(f"wrote {len(cookies)} cookies -> {out}"
              f"  (canvas_session: {'yes' if 'canvas_session' in names else 'NO'})")
        ctx.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
