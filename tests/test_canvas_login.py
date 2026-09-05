"""The cookie dump contains `canvas_session`, so it must never be readable by
other local users -- not even briefly. `Path.write_text` followed by `chmod`
creates the file at the umask default (usually 0644) and only narrows it after
the secret is on disk; these tests pin the invariant that closed that window.
"""
import json
import os
import stat

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
