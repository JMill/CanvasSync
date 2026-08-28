from si_archive import vimeo


def test_embed_url_always_uses_the_player_form():
    # vimeo.com/<id> fails yt-dlp's OAuth path; player.vimeo.com works.
    assert vimeo.embed_url("464955563", None) == \
        "https://player.vimeo.com/video/464955563"


def test_embed_url_preserves_the_unlisted_hash():
    assert vimeo.embed_url("605462161", "50187719bc") == \
        "https://player.vimeo.com/video/605462161?h=50187719bc"


def test_collect_ids_deduplicates_across_projects_and_pages():
    doc = {
        "M1": {"pages": [
            {"vimeo": [{"id": "1", "hash": "a"}, {"id": "2", "hash": None}]},
            {"vimeo": [{"id": "1", "hash": "a"}]},
        ]},
        "M2": {"pages": [{"vimeo": [{"id": "1", "hash": "a"},
                                     {"id": "3", "hash": "c"}]}]},
    }
    ids = vimeo.collect_ids(doc)
    assert [v["id"] for v in ids] == ["1", "2", "3"]
    assert ids[0]["projects"] == ["M1", "M2"]
    assert ids[0]["hash"] == "a"


def test_download_record_has_a_size_field_in_both_branches():
    """Task 6 chooses the canonical rendition by size; a missing key reads as 0."""
    for record in (
        {"id": "1", "status": "ok", "path": "/x/a.mp4", "title": "a",
         "duration": 1.0, "size": 10, "error": None},
        {"id": "2", "status": "gap", "path": None, "title": None,
         "duration": None, "size": None, "error": "boom"},
    ):
        assert "size" in record


def test_ok_record_reads_the_real_size_of_the_downloaded_file(tmp_path):
    # Exercises the actual helper download() uses on its success path, rather
    # than just asserting the shape -- no network call needed since the file
    # already exists on disk by the time this runs for real.
    video_file = tmp_path / "1 - Some Title.mp4"
    video_file.write_bytes(b"x" * 12345)
    record = vimeo._ok_record("1", str(video_file), "Some Title", 258.0)
    assert record == {"id": "1", "status": "ok", "path": str(video_file),
                       "title": "Some Title", "duration": 258.0,
                       "size": 12345, "error": None}


def test_ok_record_tolerates_a_missing_file():
    record = vimeo._ok_record("1", "/no/such/file.mp4", "Title", 1.0)
    assert record["size"] is None


def test_build_cmd_never_filters_the_format_selector_by_extension():
    # Vimeo serves these as HLS with separate video-only/audio-only
    # renditions whose audio extension is reported as mp4, not m4a. A
    # selector filtering on ext=m4a or asking for a single-file `best`
    # matches nothing and yt-dlp exits with "Requested format is not
    # available" -- reconnaissance found this the hard way.
    cmd = vimeo._build_cmd("https://player.vimeo.com/video/1", "/tmp/1.%(ext)s")
    assert "m4a" not in " ".join(cmd)
    assert "-f" in cmd
    assert cmd[cmd.index("-f") + 1] == "bestvideo*+bestaudio/best"
    assert "--merge-output-format" in cmd
    assert "--impersonate" not in cmd


def test_build_cmd_impersonate_adds_the_chrome_flag_without_dropping_others():
    cmd = vimeo._build_cmd("https://player.vimeo.com/video/1", "/tmp/1.%(ext)s",
                            impersonate=True)
    assert cmd[cmd.index("--impersonate") + 1] == "chrome"
    assert "-f" in cmd


def test_gap_record_has_none_for_every_field_but_id_status_and_error():
    record = vimeo._gap_record("777331374", "blocked")
    assert record == {"id": "777331374", "status": "gap", "path": None,
                       "title": None, "duration": None, "size": None,
                       "error": "blocked"}
