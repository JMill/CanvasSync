#!/usr/bin/env python3
"""Archive a Canvas course using a logged-in browser session's cookies.

Built for institutions (like PSU) that disable user-generated API tokens:
log in via a real browser, export the cookies, and this script rides the
session cookie for both API enumeration and file downloads.

Usage:
    canvas_browser_archive.py --base https://psu.instructure.com \
        --course-id 2492628 --cookies cookies.json --out /path/to/archive

Re-running updates the archive in place: content HTML/JSON is rewritten,
file downloads are skipped when size + updated_at are unchanged.
"""

import argparse
import html
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests


def slugify(text, maxlen=80):
    text = re.sub(r"[^\w\s.-]", "", str(text)).strip()
    text = re.sub(r"[\s]+", "_", text)
    return text[:maxlen] or "untitled"


def wrap_html(title, body, source_url, extra_meta=""):
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>{html.escape(str(title))}</title>
<style>body{{max-width:900px;margin:2em auto;font-family:-apple-system,sans-serif;line-height:1.5;padding:0 1em}}
.archive-meta{{color:#666;font-size:0.85em;border-bottom:1px solid #ddd;padding-bottom:0.5em;margin-bottom:1.5em}}
img{{max-width:100%}}</style></head><body>
<div class="archive-meta">Archived {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}
 &middot; source: <a href="{html.escape(str(source_url))}">{html.escape(str(source_url))}</a>{extra_meta}</div>
<h1>{html.escape(str(title))}</h1>
{body or '<p><em>(no content)</em></p>'}
</body></html>"""


class Archiver:
    def __init__(self, base, course_id, out_dir, cookies_file):
        self.base = base.rstrip("/")
        self.cid = course_id
        self.out = Path(out_dir)
        self.s = requests.Session()
        self.s.headers["User-Agent"] = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36")
        for c in json.loads(Path(cookies_file).read_text()):
            self.s.cookies.set(c["name"], c["value"], domain=c["domain"], path=c.get("path", "/"))
        self.errors = []
        self.counts = {}

    # ---------- HTTP helpers ----------

    def api(self, path, params=None):
        """GET one API endpoint, following Link-header pagination. Returns parsed JSON."""
        url = f"{self.base}/api/v1/{path.lstrip('/')}"
        params = dict(params or {})
        params.setdefault("per_page", 100)
        results = None
        while url:
            r = self.s.get(url, params=params, headers={"Accept": "application/json"}, timeout=60)
            params = None  # only on first request; Link URLs carry their own
            if r.status_code != 200:
                raise requests.HTTPError(f"{r.status_code} for {url}", response=r)
            data = json.loads(r.text.lstrip(")]}'\n"))  # strip Canvas anti-CSRF prefix if present
            if isinstance(data, list):
                results = (results or []) + data
            else:
                return data
            url = r.links.get("next", {}).get("url")
        return results

    def try_api(self, label, path, params=None):
        try:
            return self.api(path, params)
        except Exception as e:
            self.errors.append(f"{label}: {e}")
            print(f"    !! {label}: {e}")
            return None

    def save_json(self, relpath, data):
        p = self.out / relpath
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, indent=2, ensure_ascii=False))

    def save_html(self, relpath, title, body, source_url, extra_meta=""):
        p = self.out / relpath
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(wrap_html(title, body, source_url, extra_meta))

    # ---------- sections ----------

    def run(self):
        self.out.mkdir(parents=True, exist_ok=True)
        course = self.api(f"courses/{self.cid}", {"include[]": ["syllabus_body", "term", "teachers"]})
        print(f"Archiving: {course['name']}")
        self.save_json("_api/course.json", course)

        if course.get("syllabus_body"):
            self.save_html("syllabus.html", "Syllabus", course["syllabus_body"],
                           f"{self.base}/courses/{self.cid}/assignments/syllabus")

        tabs = self.try_api("tabs", f"courses/{self.cid}/tabs") or []
        self.save_json("_api/tabs.json", tabs)

        self.do_modules()
        self.do_pages()
        self.do_assignments()
        self.do_discussions(announcements=True)
        self.do_discussions(announcements=False)
        self.do_quizzes()
        self.do_files()
        self.write_index(course, tabs)

        manifest = {
            "archived_at": datetime.now(timezone.utc).isoformat(),
            "course_id": self.cid,
            "course_name": course["name"],
            "counts": self.counts,
            "errors": self.errors,
        }
        self.save_json("manifest.json", manifest)
        print(f"Done: {self.counts}" + (f"  ({len(self.errors)} errors)" if self.errors else ""))
        return manifest

    def do_modules(self):
        mods = self.try_api("modules", f"courses/{self.cid}/modules",
                            {"include[]": ["items", "content_details"]})
        self._modules = mods
        if mods is None:
            return
        # items may be omitted for large modules; fetch per-module if missing
        for m in mods:
            if "items" not in m or m["items"] is None:
                m["items"] = self.try_api(f"module {m['id']} items",
                                          f"courses/{self.cid}/modules/{m['id']}/items",
                                          {"include[]": "content_details"}) or []
        self.save_json("_api/modules.json", mods)
        self.counts["modules"] = len(mods)

        rows = []
        for m in mods:
            rows.append(f"<h2>{html.escape(m['name'])}</h2><ul>")
            for it in m.get("items", []):
                indent = "&nbsp;" * 4 * it.get("indent", 0)
                title = html.escape(it.get("title", "?"))
                url = it.get("html_url") or it.get("external_url") or "#"
                rows.append(f"<li>{indent}[{it['type']}] <a href=\"{html.escape(url)}\">{title}</a></li>")
            rows.append("</ul>")
        self.save_html("modules.html", "Modules", "\n".join(rows),
                       f"{self.base}/courses/{self.cid}/modules")
        print(f"  modules: {len(mods)}")

    def do_pages(self):
        pages = self.try_api("pages", f"courses/{self.cid}/pages")
        if pages is None:
            # Pages tab hidden: fall back to pages referenced from modules
            urls = sorted({it.get("page_url") for m in self._modules or []
                           for it in m.get("items", []) if it.get("type") == "Page" and it.get("page_url")})
            pages = [{"url": u} for u in urls]
            print(f"    (pages index hidden; using {len(pages)} pages from modules)")
        else:
            self.save_json("_api/pages.json", pages)
        self.counts["pages"] = len(pages)
        for p in pages:
            full = self.try_api(f"page {p['url']}", f"courses/{self.cid}/pages/{p['url']}")
            if not full:
                continue
            name = slugify(p["url"])
            self.save_json(f"_api/pages/{name}.json", full)
            body = full.get("body")
            if not body and full.get("locked_for_user"):
                body = ('<p><em>Not yet available &mdash; locked when archived.</em></p>'
                        + (full.get("lock_explanation") or ""))
                self.counts["pages_locked"] = self.counts.get("pages_locked", 0) + 1
            self.save_html(f"pages/{name}.html", full["title"], body,
                           full.get("html_url", ""))
        print(f"  pages: {len(pages)} ({self.counts.get('pages_locked', 0)} still locked)")

    def do_assignments(self):
        asgs = self.try_api("assignments", f"courses/{self.cid}/assignments",
                            {"include[]": ["submission", "rubric"]})
        if asgs is None:
            return
        self.save_json("_api/assignments.json", asgs)
        self.counts["assignments"] = len(asgs)
        for a in asgs:
            meta = f" &middot; due: {a.get('due_at') or 'n/a'} &middot; points: {a.get('points_possible')}"
            desc = a.get("description")
            if not desc and a.get("locked_for_user"):
                desc = ('<p><em>Not yet available &mdash; locked when archived.</em></p>'
                        + (a.get("lock_explanation") or ""))
            self.save_html(f"assignments/{a['id']}_{slugify(a['name'])}.html",
                           a["name"], desc, a.get("html_url", ""), meta)
        print(f"  assignments: {len(asgs)}")

    def do_discussions(self, announcements):
        label = "announcements" if announcements else "discussions"
        params = {"only_announcements": "true"} if announcements else {}
        topics = self.try_api(label, f"courses/{self.cid}/discussion_topics", params)
        if topics is None:
            return
        if not announcements:
            topics = [t for t in topics if not t.get("is_announcement")]
        self.save_json(f"_api/{label}.json", topics)
        self.counts[label] = len(topics)
        for t in topics:
            body = [t.get("message") or ""]
            view = self.try_api(f"{label[:-1]} {t['id']} replies",
                                f"courses/{self.cid}/discussion_topics/{t['id']}/view")
            if view:
                self.save_json(f"_api/{label}/{t['id']}_view.json", view)
                parts = self._render_entries(view.get("view", []), view.get("participants", []))
                if parts:
                    body.append("<hr><h2>Replies</h2>" + parts)
            meta = f" &middot; posted: {t.get('posted_at') or t.get('created_at') or '?'}"
            self.save_html(f"{label}/{t['id']}_{slugify(t['title'])}.html",
                           t["title"], "\n".join(body), t.get("html_url", ""), meta)
        print(f"  {label}: {len(topics)}")

    def _render_entries(self, entries, participants, depth=0):
        names = {p["id"]: p.get("display_name", "?") for p in participants}
        out = []
        for e in entries:
            if e.get("deleted"):
                continue
            who = html.escape(names.get(e.get("user_id"), "unknown"))
            when = e.get("created_at", "")
            msg = e.get("message") or ""
            out.append(f'<div style="margin-left:{depth * 2}em;border-left:2px solid #ccc;'
                       f'padding-left:1em;margin-top:1em"><b>{who}</b> <small>{when}</small>{msg}</div>')
            if e.get("replies"):
                out.append(self._render_entries(e["replies"], participants, depth + 1))
        return "\n".join(out)

    def do_quizzes(self):
        quizzes = self.try_api("quizzes", f"courses/{self.cid}/quizzes")
        if quizzes is None:
            return
        self.save_json("_api/quizzes.json", quizzes)
        self.counts["quizzes"] = len(quizzes)
        for q in quizzes:
            meta = f" &middot; due: {q.get('due_at') or 'n/a'} &middot; points: {q.get('points_possible')}"
            self.save_html(f"quizzes/{q['id']}_{slugify(q['title'])}.html",
                           q["title"], q.get("description"), q.get("html_url", ""), meta)
        print(f"  quizzes: {len(quizzes)}")

    def do_files(self):
        folders = self.try_api("folders", f"courses/{self.cid}/folders")
        files = self.try_api("files", f"courses/{self.cid}/files")
        if files is None:
            files = self._files_from_references()
            print(f"    (files index hidden; found {len(files)} files via modules + embedded links)")
        else:
            self.save_json("_api/files.json", files)
        self.save_json("_api/folders.json", folders or [])
        folder_path = {}
        for f in folders or []:
            path = re.sub(r"^course files/?", "", f.get("full_name", ""))
            folder_path[f["id"]] = path
        state_file = self.out / "_api/download_state.json"
        state = json.loads(state_file.read_text()) if state_file.exists() else {}
        downloaded = skipped = failed = 0
        for f in files:
            rel = Path("files") / folder_path.get(f.get("folder_id"), "") / f["display_name"]
            key = str(f["id"])
            sig = f"{f.get('size')}|{f.get('updated_at')}"
            dest = self.out / rel
            if state.get(key) == sig and dest.exists():
                skipped += 1
                continue
            url = f.get("url") or f"{self.base}/files/{f['id']}/download?download_frd=1"
            try:
                dest.parent.mkdir(parents=True, exist_ok=True)
                with self.s.get(url, stream=True, timeout=300) as r:
                    r.raise_for_status()
                    tmp = dest.with_suffix(dest.suffix + ".part")
                    with open(tmp, "wb") as fh:
                        for chunk in r.iter_content(1 << 16):
                            fh.write(chunk)
                    tmp.rename(dest)
                state[key] = sig
                downloaded += 1
                print(f"    file: {rel} ({f.get('size', 0):,}b)")
            except Exception as e:
                failed += 1
                self.errors.append(f"file {f['display_name']}: {e}")
                print(f"    !! file {f['display_name']}: {e}")
            time.sleep(0.2)  # be polite
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text(json.dumps(state, indent=2))
        self.counts["files"] = len(files)
        print(f"  files: {len(files)} ({downloaded} downloaded, {skipped} unchanged, {failed} failed)")

    def _files_from_references(self):
        """When the Files tab is hidden, collect file ids from module items and
        from /files/<id> links embedded in already-archived content, then fetch
        each file's metadata individually (item-level permissions still apply)."""
        ids = {it["content_id"] for m in self._modules or []
               for it in m.get("items", []) if it.get("type") == "File" and it.get("content_id")}
        pat = re.compile(r"/(?:courses/%s/)?files/(\d+)" % self.cid)
        for sub in ("_api", "pages", "assignments", "announcements", "discussions", "quizzes"):
            d = self.out / sub
            if not d.exists():
                continue
            for p in d.rglob("*"):
                if p.suffix in (".html", ".json"):
                    ids.update(int(m) for m in pat.findall(p.read_text(errors="ignore")))
        files = []
        for fid in sorted(ids):
            meta = self.try_api(f"file {fid}", f"courses/{self.cid}/files/{fid}")
            if meta:
                files.append(meta)
        self.save_json("_api/files.json", files)
        return files

    def write_index(self, course, tabs):
        sections = []
        for name, glob_pat, folder in [
            ("Pages", "pages/*.html", "pages"), ("Assignments", "assignments/*.html", "assignments"),
            ("Announcements", "announcements/*.html", "announcements"),
            ("Discussions", "discussions/*.html", "discussions"),
            ("Quizzes", "quizzes/*.html", "quizzes"),
        ]:
            items = sorted(self.out.glob(glob_pat))
            if items:
                links = "".join(f'<li><a href="{i.relative_to(self.out)}">{html.escape(i.stem)}</a></li>'
                                for i in items)
                sections.append(f"<h2>{name}</h2><ul>{links}</ul>")
        top = ['<ul><li><a href="modules.html">Modules</a></li>']
        if (self.out / "syllabus.html").exists():
            top.append('<li><a href="syllabus.html">Syllabus</a></li>')
        if (self.out / "files").exists():
            top.append('<li><a href="files/">Files</a> (browse folder)</li>')
        top.append("</ul>")
        body = "".join(top) + "".join(sections)
        self.save_html("index.html", course["name"], body,
                       f"{self.base}/courses/{self.cid}")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", required=True)
    ap.add_argument("--course-id", required=True, type=int)
    ap.add_argument("--cookies", required=True, help="JSON list of {name,value,domain,path}")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    Archiver(args.base, args.course_id, args.out, args.cookies).run()


if __name__ == "__main__":
    sys.exit(main())
