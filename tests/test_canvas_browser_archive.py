"""An instructor can re-lock content that was already open -- AI 574's Lesson 14
was readable for weeks, then gained an `unlock_at` of 2026-11-30 and Canvas
started answering `locked_for_user` with an empty body. The archive must keep
what it already captured rather than overwrite it with a "Not yet available"
stub; for an archive, losing content it once held is the worst outcome.
"""
import json

import bin.canvas_browser_archive as cba

OPEN_PAGE = {"url": "intro-14", "title": "Introduction to Lesson 14",
             "body": "<p>Real lesson content</p>", "locked_for_user": False,
             "html_url": "https://x/courses/1/pages/intro-14"}
LOCKED_PAGE = {"url": "intro-14", "title": "Introduction to Lesson 14",
               "body": None, "locked_for_user": True,
               "lock_explanation": "This page is locked until Nov 30.",
               "html_url": "https://x/courses/1/pages/intro-14"}


def make_archiver(tmp_path, responses):
    cookies = tmp_path / "cookies.json"
    cookies.write_text("[]")
    a = cba.Archiver("https://x", 1, tmp_path / "out", cookies)
    a.try_api = lambda label, path, params=None: responses.get(path)
    return a


def run_pages(tmp_path, page):
    a = make_archiver(tmp_path, {"courses/1/pages": [{"url": "intro-14"}],
                                 "courses/1/pages/intro-14": page})
    a.do_pages()
    return a


def test_relocked_page_keeps_the_content_already_archived(tmp_path):
    run_pages(tmp_path, OPEN_PAGE)
    a = run_pages(tmp_path, LOCKED_PAGE)

    out = tmp_path / "out"
    assert "Real lesson content" in (out / "pages/intro-14.html").read_text()
    saved = json.loads((out / "_api/pages/intro-14.json").read_text())
    assert saved["body"] == "<p>Real lesson content</p>"
    assert a.counts.get("relocked_kept") == 1
    assert a.counts.get("pages_locked", 0) == 0


def test_never_opened_page_still_gets_the_lock_stub(tmp_path):
    a = run_pages(tmp_path, LOCKED_PAGE)

    html = (tmp_path / "out/pages/intro-14.html").read_text()
    assert "Not yet available" in html
    assert a.counts["pages_locked"] == 1


def test_relocked_assignment_keeps_its_description(tmp_path):
    open_a = {"id": 7, "name": "Final Project", "description": "<p>Deliverables</p>",
              "locked_for_user": False, "html_url": "https://x/a/7"}
    locked_a = dict(open_a, description=None, locked_for_user=True,
                    lock_explanation="Locked until Nov 30.")
    path = "courses/1/assignments"
    make_archiver(tmp_path, {path: [open_a]}).do_assignments()
    a = make_archiver(tmp_path, {path: [locked_a]})
    a.do_assignments()

    assert "Deliverables" in (tmp_path / "out/assignments/7_Final_Project.html").read_text()
    assert a.counts.get("relocked_kept") == 1
