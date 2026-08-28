from pathlib import Path

from si_archive import localsrc


def test_is_student_work_matches_a_submissions_directory():
    p = Path("/x/Module 1/Assignment/1682350566_563__SISH_submissions/essay.docx")
    assert localsrc.is_student_work(p)


def test_is_student_work_matches_a_text_html_dump():
    assert localsrc.is_student_work(Path("/x/calmetricardo_6908_text.html"))


def test_is_student_work_allows_ordinary_course_media():
    assert not localsrc.is_student_work(Path("/x/Module 1/MIT_INN_M1_V1.mp4"))
    assert not localsrc.is_student_work(Path("/x/pre/Code of Conduct MIT - ENG.pdf"))


def test_sha256_matches_a_known_digest(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("hello")
    assert localsrc.sha256(f) == (
        "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824")


def test_index_tree_skips_student_work(tmp_path):
    (tmp_path / "ok.txt").write_text("keep")
    sub = tmp_path / "1682_x_submissions"
    sub.mkdir()
    (sub / "essay.docx").write_text("drop")
    (tmp_path / "someone_1234_text.html").write_text("drop")

    records = localsrc.index_tree(tmp_path, source="test")
    names = [Path(r["path"]).name for r in records]
    assert names == ["ok.txt"]


def test_is_student_work_matches_case_variants():
    assert localsrc.is_student_work(Path("/x/calmetricardo_6908_TEXT.HTML"))
    assert localsrc.is_student_work(
        Path("/x/Module 1/Assignment/1682350566_563__SISH_SUBMISSIONS/essay.docx"))


def test_index_screenflow_bundles_skips_a_bundle_under_submissions(tmp_path):
    kept = tmp_path / "Module 1" / "Project.screenflow"
    kept.mkdir(parents=True)
    (kept / "document.iwa").write_text("kept bundle contents")

    dropped = tmp_path / "1682_x_submissions" / "StudentProject.screenflow"
    dropped.mkdir(parents=True)
    (dropped / "document.iwa").write_text("dropped bundle contents")

    records = localsrc.index_screenflow_bundles(tmp_path)
    names = [Path(r["path"]).name for r in records]
    assert names == ["Project.screenflow"]


def test_probe_duration_returns_none_when_ffprobe_missing(tmp_path, monkeypatch):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"not a real video")

    def fake_run(*args, **kwargs):
        raise FileNotFoundError("ffprobe not found")

    monkeypatch.setattr(localsrc.subprocess, "run", fake_run)
    assert localsrc.probe_duration(video) is None
