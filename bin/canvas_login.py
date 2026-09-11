#!/usr/bin/env python3
"""Open a browser for an interactive Canvas login, then dump session cookies.

PSU disables user-generated API tokens, so `canvas_browser_archive.py` rides a
real browser session's cookies. This script produces that cookie dump.

It drives Chrome with a profile owned by this repo (not the shared
playwright-mcp profiles, which any other tool may hold a lock on). The profile
alone cannot carry a login forward: `canvas_session` is a non-persistent
cookie, so Chrome drops it on exit and a cold profile answers 401 with no
Canvas cookies restored. So we keep our own copy of the jar (--session-store)
and re-inject it, which does work -- a second run goes straight through in
about four seconds with no Duo prompt.

The saved jar is never trusted on its own: an expired cookie is
indistinguishable from a live one until the server is asked, so every run
verifies against /api/v1/users/self and falls back to an interactive login
when the answer is no. Whether PSU's session survives a long gap (overnight,
say) is unmeasured -- reuse is a convenience during a working day, not a
foundation for unattended scheduling.

Usage:
    canvas_login.py --out /path/to/cookies.json
    canvas_login.py --out cookies.json --base https://psu.instructure.com
    canvas_login.py --forget                    # drop the saved session

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
DEFAULT_SESSION_STORE = Path.home() / ".cache" / "canvas-archive-session.json"


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


def save_session(path, cookies):
    """Keep our own copy of the jar so the next run can skip the Duo prompt.

    Chrome drops `canvas_session` on exit, so the persistent profile cannot
    carry a login forward; holding the cookies ourselves is the only way. This
    is a reusable credential at rest, so it goes through write_cookie_dump for
    the same 0600-from-the-first-byte handling as the scratch dump.
    """
    return write_cookie_dump(path, {"saved_at": time.time(), "cookies": cookies})


def load_session(path, max_age_hours):
    """Return the saved cookies, or None if there are none fit to use.

    Anything unusable is deleted rather than left lying about: a store we will
    not reuse is a credential on disk with no purpose. Returning None only ever
    costs an interactive login, so every failure mode leads here.
    """
    path = Path(path)
    try:
        saved = json.loads(path.read_text())
        saved_at, cookies = float(saved["saved_at"]), saved["cookies"]
    except FileNotFoundError:
        return None
    except (OSError, ValueError, KeyError, TypeError):
        forget_session(path)
        return None
    if time.time() - saved_at > max_age_hours * 3600:
        forget_session(path)
        return None
    return cookies


def forget_session(path):
    """Drop the saved session. Safe to call when there isn't one."""
    Path(path).unlink(missing_ok=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="https://psu.instructure.com")
    ap.add_argument("--out", help="where to write the cookie JSON (required unless --forget)")
    ap.add_argument("--profile", default=str(DEFAULT_PROFILE),
                    help=f"Chrome user-data-dir (default: {DEFAULT_PROFILE})")
    ap.add_argument("--timeout", type=int, default=420,
                    help="seconds to wait for an interactive login (default: 420)")
    ap.add_argument("--session-store", default=str(DEFAULT_SESSION_STORE),
                    help=f"where the reusable session is kept (default: {DEFAULT_SESSION_STORE})")
    ap.add_argument("--max-session-age", type=float, default=24.0,
                    help="hours a saved session may be reused before it is discarded "
                         "unverified (default: 24). A bound on how long a live credential "
                         "sits on disk; the session is checked against the server either way")
    ap.add_argument("--forget", action="store_true",
                    help="delete any saved session and exit")
    args = ap.parse_args()

    if args.forget:
        forget_session(args.session_store)
        print(f"saved session removed: {args.session_store}")
        return 0
    if not args.out:
        ap.error("--out is required unless --forget is given")

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
        saved = load_session(args.session_store, args.max_session_age)
        if saved:
            try:
                ctx.add_cookies(saved)
            except Exception as e:
                # A jar Playwright will not accept is no reason to fail the run;
                # drop it and log in the ordinary way.
                print(f"saved session unusable ({e})", file=sys.stderr)
                forget_session(args.session_store)
                saved = None

        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(f"{base}/", wait_until="domcontentloaded")

        # Never trust the saved jar on its own -- a cookie the server has already
        # expired looks identical to a live one until it is used.
        who = logged_in(ctx.request, base)
        if who:
            print(f"already logged in as {who}"
                  f"{' (reused saved session)' if saved else ''}", flush=True)
        else:
            if saved:
                print("saved session is no longer valid; logging in again", flush=True)
                forget_session(args.session_store)
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
        save_session(args.session_store, cookies)
        out = write_cookie_dump(args.out, cookies)
        names = {c["name"] for c in cookies}
        print(f"wrote {len(cookies)} cookies -> {out}"
              f"  (canvas_session: {'yes' if 'canvas_session' in names else 'NO'})")
        ctx.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
