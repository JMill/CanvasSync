from si_archive import reconcile


def test_normalize_title_strips_extension_case_and_punctuation():
    assert reconcile.normalize_title("MIT_INN_M1_V2.mp4") == "mit inn m1 v2"
    assert reconcile.normalize_title("MIT_INN_M1_V2") == "mit inn m1 v2"
    assert reconcile.normalize_title("Grove Our Mission -  - 2023-04-24 13-04-00") == \
        "grove our mission 2023 04 24 13 04 00"


def test_group_by_hash_collapses_duplicates_and_keeps_aliases():
    records = [
        {"path": "/a/Outline.pdf", "sha256": "aa", "size": 10},
        {"path": "/b/Outline (2).pdf", "sha256": "aa", "size": 10},
        {"path": "/c/other.pdf", "sha256": "bb", "size": 20},
    ]
    groups = {g["sha256"]: g for g in reconcile.group_by_hash(records)}
    assert len(groups) == 2
    assert groups["aa"]["canonical"] == "/a/Outline.pdf"
    assert groups["aa"]["aliases"] == ["/b/Outline (2).pdf"]
    assert groups["bb"]["aliases"] == []


def test_match_renditions_pairs_vimeo_with_the_local_mp4():
    local = [{"path": "/x/Module 1/MIT_INN_M1_V2.mp4",
              "duration": 258.0, "size": 90_000_000, "ext": ".mp4"}]
    vimeo = [{"id": "605462161", "status": "ok", "title": "MIT_INN_M1_V2",
              "duration": 258.0, "path": "/v/605462161 - MIT_INN_M1_V2.mp4"}]
    matches = reconcile.match_renditions(local, vimeo)
    assert len(matches) == 1
    assert matches[0]["vimeo_id"] == "605462161"
    assert matches[0]["local_path"].endswith("MIT_INN_M1_V2.mp4")


def test_match_renditions_prefers_the_larger_file_as_canonical():
    local = [{"path": "/x/clarke.mp4", "duration": 343.0,
              "size": 16_000_000, "ext": ".mp4"}]
    vimeo = [{"id": "493369035", "status": "ok", "title": "clarke",
              "duration": 343.0, "path": "/v/493369035 - clarke.mp4",
              "size": 90_000_000}]
    match = reconcile.match_renditions(local, vimeo)[0]
    assert match["canonical"] == "/v/493369035 - clarke.mp4"


def test_match_renditions_ignores_a_duration_mismatch():
    local = [{"path": "/x/a.mp4", "duration": 100.0, "size": 1, "ext": ".mp4"}]
    vimeo = [{"id": "9", "status": "ok", "title": "a", "duration": 400.0,
              "path": "/v/9 - a.mp4"}]
    assert reconcile.match_renditions(local, vimeo) == []


def test_match_renditions_skips_failed_downloads():
    local = [{"path": "/x/a.mp4", "duration": 100.0, "size": 1, "ext": ".mp4"}]
    vimeo = [{"id": "9", "status": "gap", "title": None, "duration": None,
              "path": None}]
    assert reconcile.match_renditions(local, vimeo) == []


def test_match_renditions_tolerates_integer_truncation_of_vimeo_durations():
    """yt-dlp reports whole seconds; a 259.5s local file must still match 258
    at tolerance=2.0. The 1.5s delta is strictly between the old tolerance
    (1.0) and the new one (2.0), so this fails if tolerance regresses to 1.0."""
    local = [{"path": "/x/MIT_INN_M1_V2.mp4", "duration": 259.5,
              "size": 90_000_000, "ext": ".mp4"}]
    vimeo = [{"id": "605462161", "status": "ok", "title": "MIT_INN_M1_V2",
              "duration": 258.0, "path": "/v/605462161 - MIT_INN_M1_V2.mp4",
              "size": 80_000_000}]
    assert len(reconcile.match_renditions(local, vimeo)) == 1


def test_match_renditions_does_not_let_two_vimeo_videos_claim_one_local_file():
    """Two Vimeo records with the same normalized title, both within tolerance
    of a single local file, must produce one rendition, not two -- the local
    file can't be canonical for two different renditions at once."""
    local = [{"path": "/x/clarke.mp4", "duration": 343.0,
              "size": 16_000_000, "ext": ".mp4"}]
    vimeo = [
        {"id": "1", "status": "ok", "title": "clarke",
         "duration": 343.0, "path": "/v/1 - clarke.mp4"},
        {"id": "2", "status": "ok", "title": "clarke",
         "duration": 344.0, "path": "/v/2 - clarke.mp4"},
    ]
    matches = reconcile.match_renditions(local, vimeo)
    assert len(matches) == 1
