#!/usr/bin/env python3
"""Walk a Canvas course's module chain the way clicking "Next" does.

Some courses gate content by prerequisite chain rather than by date: each module
lists the previous one in prerequisite_module_ids, and with requirement_type
"all" a module only unlocks once every requirement in its predecessor is met.
Loading an item fires context_module_action(user, :read), which satisfies that
item's must_view -- so walking the items in order cascades the whole chain open.

Only must_view requirements are fulfilled. must_submit / must_contribute / quiz
requirements are never touched: those are coursework, and the wall this script
is expected to stop at. It reports them so you know why it stopped.

Run this before canvas_browser_archive.py so the archiver sees unlocked content.

Usage:
    canvas_unlock_walk.py --base https://psu.instructure.com \
        --course-id 2481527 --cookies cookies.json [--dry-run]
"""

import argparse
import json
import sys
import time
import urllib.parse
from pathlib import Path

import requests


class Walker:
    def __init__(self, base, course_id, cookies_file, dry_run=False):
        self.base = base.rstrip("/")
        self.cid = course_id
        self.dry_run = dry_run
        self.viewed = 0
        self.s = requests.Session()
        self.s.headers["User-Agent"] = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36")
        csrf = None
        for c in json.loads(Path(cookies_file).read_text()):
            self.s.cookies.set(c["name"], c["value"], domain=c["domain"], path=c.get("path", "/"))
            if c["name"] == "_csrf_token":
                # Canvas rejects cookie-authed writes unless this echoes back as a header.
                csrf = urllib.parse.unquote(c["value"])
        if csrf:
            self.s.headers["X-CSRF-Token"] = csrf
        self.s.headers["Referer"] = self.base

    def modules(self):
        out = []
        url = f"{self.base}/api/v1/courses/{self.cid}/modules?include[]=items&per_page=50"
        while url:
            r = self.s.get(url, timeout=30)
            r.raise_for_status()
            out += r.json()
            url = r.links.get("next", {}).get("url")
        return out

    @staticmethod
    def _req(item):
        return item.get("completion_requirement") or {}

    def pending_view(self, module):
        """Outstanding must_view items, in position order.

        Order matters: require_sequential_progress courses only credit items
        as they are reached, so these cannot be fired concurrently.
        """
        return [i for i in sorted(module.get("items", []), key=lambda x: x.get("position", 0))
                if self._req(i).get("type") == "must_view"
                and self._req(i).get("completed") is False]

    def blockers(self, module):
        """Outstanding requirements this script will not satisfy."""
        return [(i["title"], self._req(i)["type"]) for i in module.get("items", [])
                if self._req(i).get("completed") is False
                and self._req(i)["type"] != "must_view"]

    def _completed(self, module_id, item_id):
        r = self.s.get(f"{self.base}/api/v1/courses/{self.cid}/modules/{module_id}/items/{item_id}",
                       timeout=30)
        return (r.json().get("completion_requirement") or {}).get("completed") if r.ok else None

    def view(self, module, item):
        """Load the item the way Next does, then confirm the flag actually flipped."""
        if self.dry_run:
            print(f"      [dry-run] would view {item['id']} {item['title'][:50]}")
            return None
        try:
            status = self.s.get(item["html_url"], timeout=45, allow_redirects=True).status_code
        except requests.RequestException as e:
            status = f"ERR {e}"
        time.sleep(0.6)
        done = self._completed(module["id"], item["id"])
        if not done:
            # The page load did not register; fall back to the documented endpoint.
            p = self.s.post(f"{self.base}/api/v1/courses/{self.cid}"
                            f"/modules/{module['id']}/items/{item['id']}/mark_read", timeout=30)
            time.sleep(0.4)
            done = self._completed(module["id"], item["id"])
            print(f"      GET {status} -> mark_read {p.status_code} -> done={done}  {item['title'][:48]}")
        else:
            print(f"      GET {status} -> done={done}  {item['title'][:48]}")
        return done

    def run(self, max_sweeps=25):
        for sweep in range(1, max_sweeps + 1):
            open_mods = [m for m in self.modules()
                         if m["state"] in ("unlocked", "started") and self.pending_view(m)]
            if not open_mods:
                break
            print(f"\n--- sweep {sweep} ---")
            progressed = False
            for m in open_mods:
                pend = self.pending_view(m)
                print(f"  [{m['id']}] {m['name']} ({m['state']}) -- {len(pend)} must_view pending")
                for item in pend:
                    if self.view(m, item):
                        self.viewed += 1
                        progressed = True
                    time.sleep(0.5)
            # A sweep that unlocks nothing new means we have hit a wall, not a slow API.
            if self.dry_run or not progressed:
                break

    def report(self):
        print("\n================ FINAL STATE ================")
        walls = []
        for m in self.modules():
            blocked = self.blockers(m)
            note = ""
            if blocked:
                note = "  BLOCKED BY: " + ", ".join(f"{t} [{k}]" for t, k in blocked)
                walls += blocked
            print(f"[{m['id']}] {m['name'][:46]:<48} {m['state']:<10} "
                  f"must_view_pending={len(self.pending_view(m))}{note}")
        print(f"\nitems marked viewed this run: {self.viewed}")
        if walls:
            print(f"{len(walls)} requirement(s) need real coursework and were left alone.")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--base", required=True, help="e.g. https://psu.instructure.com")
    ap.add_argument("--course-id", type=int, required=True)
    ap.add_argument("--cookies", required=True, help="JSON list of {name,value,domain,path}")
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would be viewed without registering anything")
    a = ap.parse_args()

    w = Walker(a.base, a.course_id, a.cookies, a.dry_run)
    try:
        w.run()
    except requests.HTTPError as e:
        print(f"aborted: {e}", file=sys.stderr)
        return 1
    w.report()
    return 0


if __name__ == "__main__":
    sys.exit(main())
