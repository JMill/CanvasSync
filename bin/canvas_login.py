#!/usr/bin/env python3
"""Open a browser for an interactive Canvas login, then dump session cookies.

PSU disables user-generated API tokens, so `canvas_browser_archive.py` rides a
real browser session's cookies. This script produces that cookie dump.

It drives Chrome with a profile owned by this repo (not the shared
playwright-mcp profiles, which any other tool may hold a lock on). The profile
persists, so a Duo login is usually only needed the first time or after the
session expires -- later runs find the session already live and exit at once.

Usage:
    canvas_login.py --out /path/to/cookies.json
    canvas_login.py --out cookies.json --base https://psu.instructure.com

Exits non-zero if no logged-in session was established before --timeout.
Keep the output in a scratch dir: it contains `canvas_session`.
"""

import argparse
import json
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
    Path(args.profile).mkdir(parents=True, exist_ok=True)

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
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(cookies, indent=2))
        out.chmod(0o600)
        names = {c["name"] for c in cookies}
        print(f"wrote {len(cookies)} cookies -> {out}"
              f"  (canvas_session: {'yes' if 'canvas_session' in names else 'NO'})")
        ctx.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
