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


# --- submission attachments -------------------------------------------------
# Files a student attached to their own submissions are not course files either:
# /courses/<cid>/files/<id> 404s for them, exactly like discussion-reply
# attachments. The assignment JSON (include[]=submission) carries each one's
# metadata and a verifier-signed URL that works with the session cookie.

class FakeResponse:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def raise_for_status(self):
        pass

    def iter_content(self, n):
        yield self.body


SUBMITTED = {"id": 9, "name": "Peer Review", "description": "<p>x</p>",
             "html_url": "https://x/a/9",
             "submission": {"attachments": [
                 {"id": 555, "display_name": "review.pdf", "size": 4,
                  "updated_at": "2026-11-05T18:29:09Z",
                  "url": "https://x/files/555/download?verifier=abc"},
                 {"id": 556, "display_name": "no-url.pdf", "size": 1}]}}


def test_submission_attachments_download_from_their_signed_url(tmp_path, monkeypatch):
    queried, fetched = [], []
    a = make_archiver(tmp_path, {"courses/1/assignments": [SUBMITTED]})
    a.do_assignments()
    a._modules = []
    a.try_api = lambda label, path, params=None: queried.append(path)
    monkeypatch.setattr(cba.time, "sleep", lambda s: None)
    a.s.get = lambda url, **kw: fetched.append(url) or FakeResponse(b"%PDF")
    a.do_files()

    out = tmp_path / "out/files/_submission_attachments/555_review.pdf"
    assert out.read_bytes() == b"%PDF"
    assert fetched == ["https://x/files/555/download?verifier=abc"]
    # never routed through the course-files endpoint that 404s for these
    assert not any("files/555" in p for p in queried)
    assert not any("555" in e for e in a.errors)
    assert a.counts["files"] == 1


def test_submission_attachments_survive_the_assignment_leaving_the_api(tmp_path, monkeypatch):
    make_archiver(tmp_path, {"courses/1/assignments": [SUBMITTED]}).do_assignments()
    a = make_archiver(tmp_path, {"courses/1/assignments": []})
    a.do_assignments()
    a._modules = []
    monkeypatch.setattr(cba.time, "sleep", lambda s: None)
    a.s.get = lambda url, **kw: FakeResponse(b"%PDF")
    a.do_files()

    assert (tmp_path / "out/files/_submission_attachments/555_review.pdf").exists()


def test_attachment_names_cannot_escape_the_archive(tmp_path, monkeypatch):
    # Reply attachments carry classmate-chosen names; none may climb out.
    evil = dict(SUBMITTED, submission={"attachments": [
        {"id": 557, "display_name": "../../../../../../../escaped.txt", "size": 4,
         "updated_at": "t", "url": "https://x/files/557/download?verifier=z"},
        {"id": 558, "display_name": "..", "size": 4,
         "updated_at": "t", "url": "https://x/files/558/download?verifier=z"}]})
    a = make_archiver(tmp_path, {"courses/1/assignments": [evil]})
    a.do_assignments()
    a._modules = []
    monkeypatch.setattr(cba.time, "sleep", lambda s: None)
    a.s.get = lambda url, **kw: FakeResponse(b"data")
    a.do_files()

    out = (tmp_path / "out").resolve()
    written = [p.resolve() for p in tmp_path.rglob("*") if p.is_file() and p.read_bytes() == b"data"]
    assert len(written) == 2
    assert all(out in p.parents for p in written)
    assert not (tmp_path / "escaped.txt").exists()


def test_safe_name_keeps_ordinary_names_unchanged():
    for n in ["[Jonathan - Miller]- Assignment3.pdf", "Figure 5- digital_waveform.gif",
              "LipNet： How easy?.mkv"]:
        assert cba.safe_name(n, 1) == n
    assert cba.safe_name("a/b\\c.pdf", 1) == "c.pdf"
    assert cba.safe_name("..", 7) == "7"
    assert cba.safe_name("", 7) == "7"
