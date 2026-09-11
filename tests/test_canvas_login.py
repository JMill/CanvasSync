"""The cookie dump contains `canvas_session`, so it must never be readable by
other local users -- not even briefly. `Path.write_text` followed by `chmod`
creates the file at the umask default (usually 0644) and only narrows it after
the secret is on disk; these tests pin the invariant that closed that window.
"""
import json
import os
import stat
import sys
import time

import pytest

import bin.canvas_login as canvas_login

COOKIES = [{"name": "canvas_session", "value": "SECRET",
            "domain": "psu.instructure.com", "path": "/"}]


def mode_of(p):
    return stat.S_IMODE(os.stat(p).st_mode)


def test_dump_is_owner_only_and_round_trips(tmp_path):
    out = canvas_login.write_cookie_dump(tmp_path / "cookies.json", COOKIES)

    assert mode_of(out) == 0o600
    assert json.loads(out.read_text()) == COOKIES


def test_dump_narrows_a_pre_existing_world_readable_file(tmp_path):
    # O_CREAT's mode is ignored for a file that already exists, so without the
    # explicit fchmod the cookies would land in a 0644 file.
    out = tmp_path / "cookies.json"
    out.write_text("stale")
    out.chmod(0o644)

    canvas_login.write_cookie_dump(out, COOKIES)

    assert mode_of(out) == 0o600


def test_permissions_are_set_before_any_content_is_written(tmp_path, monkeypatch):
    """The whole point: narrow *first*, write second.

    Sampling the mode at the moment the write handle is opened is the only way
    to catch the ordering; a test that just checks the mode afterwards passes
    against `write_text` + `chmod` too, because that reaches 0600 eventually.
    """
    out = tmp_path / "cookies.json"
    out.write_text("stale")
    out.chmod(0o644)
    seen = []

    real_fdopen = os.fdopen

    def spy(fd, *a, **kw):
        seen.append(mode_of(out))  # sampled before any content is written
        return real_fdopen(fd, *a, **kw)

    monkeypatch.setattr(canvas_login.os, "fdopen", spy)
    canvas_login.write_cookie_dump(out, COOKIES)

    assert seen, ("the dump was not written through an fd opened with 0600 -- "
                  "creating it first and chmod-ing after exposes canvas_session")
    assert seen == [0o600], f"file was {oct(seen[0])} when writing began"


def test_a_failed_write_still_leaves_nothing_world_readable(tmp_path):
    """A crash mid-dump must not strand a readable file holding partial cookies."""
    out = tmp_path / "cookies.json"
    out.write_text("stale")
    out.chmod(0o644)

    class Unserializable:
        pass

    with pytest.raises(TypeError):
        canvas_login.write_cookie_dump(out, [{"name": "s", "value": Unserializable()}])

    assert mode_of(out) == 0o600


def test_parent_directory_is_created(tmp_path):
    out = canvas_login.write_cookie_dump(tmp_path / "nested" / "d" / "c.json", COOKIES)

    assert out.exists() and mode_of(out) == 0o600


# --- reusable session store -------------------------------------------------
# canvas_session is dropped by Chrome on exit, so the login cannot be reused via
# the profile. These cover keeping our own copy: it must round-trip, stay
# owner-only, and refuse to hand back anything stale or unreadable rather than
# letting the caller present a dead cookie as a live session.

def test_saved_session_round_trips(tmp_path):
    store = tmp_path / "session.json"

    canvas_login.save_session(store, COOKIES)

    assert canvas_login.load_session(store, max_age_hours=24) == COOKIES


def test_saved_session_is_owner_only(tmp_path):
    store = tmp_path / "session.json"

    canvas_login.save_session(store, COOKIES)

    assert mode_of(store) == 0o600


def test_missing_store_returns_none(tmp_path):
    assert canvas_login.load_session(tmp_path / "absent.json", max_age_hours=24) is None


def test_store_older_than_max_age_is_ignored_and_deleted(tmp_path):
    store = tmp_path / "session.json"
    store.write_text(json.dumps({"saved_at": time.time() - 25 * 3600, "cookies": COOKIES}))

    assert canvas_login.load_session(store, max_age_hours=24) is None
    assert not store.exists(), "a session too old to use must not be left on disk"


def test_store_within_max_age_is_returned(tmp_path):
    store = tmp_path / "session.json"
    store.write_text(json.dumps({"saved_at": time.time() - 23 * 3600, "cookies": COOKIES}))

    assert canvas_login.load_session(store, max_age_hours=24) == COOKIES


def test_unreadable_store_returns_none_instead_of_crashing_the_login(tmp_path):
    store = tmp_path / "session.json"
    store.write_text("{ this is not json")

    assert canvas_login.load_session(store, max_age_hours=24) is None
    assert not store.exists()


def test_forget_removes_the_store_and_tolerates_a_missing_one(tmp_path):
    store = tmp_path / "session.json"
    canvas_login.save_session(store, COOKIES)

    canvas_login.forget_session(store)
    assert not store.exists()

    canvas_login.forget_session(store)  # must not raise


def test_forget_does_not_require_an_output_path(tmp_path, monkeypatch, capsys):
    """--forget is housekeeping: it never dumps cookies, so --out is irrelevant."""
    store = tmp_path / "session.json"
    canvas_login.save_session(store, COOKIES)
    monkeypatch.setattr(sys, "argv",
                        ["canvas_login.py", "--forget", "--session-store", str(store)])

    assert canvas_login.main() == 0
    assert not store.exists()
    capsys.readouterr()
