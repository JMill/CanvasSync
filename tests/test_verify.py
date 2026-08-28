import json
from pathlib import Path

import pytest

from si_archive import constants, verify

REAL_OUT = Path(constants.OUTPUT_ROOT)
needs_archive = pytest.mark.skipif(not REAL_OUT.exists(), reason="archive not built")

QTI_NS = "http://www.imsglobal.org/xsd/ims_qtiasiv1p2"


# --------------------------------------------------------------- brief's --

def test_find_broken_links_reports_a_missing_target(tmp_path):
    (tmp_path / "a.html").write_text('<a href="missing.html">x</a>')
    broken = verify.find_broken_links(tmp_path)
    assert len(broken) == 1
    assert broken[0]["target"] == "missing.html"


def test_find_broken_links_accepts_a_present_target(tmp_path):
    (tmp_path / "a.html").write_text('<a href="b.html">x</a>')
    (tmp_path / "b.html").write_text("ok")
    assert verify.find_broken_links(tmp_path) == []


def test_find_broken_links_ignores_external_and_anchor_urls(tmp_path):
    (tmp_path / "a.html").write_text(
        '<a href="https://x.test/y">e</a><a href="#top">t</a>'
        '<a href="mailto:a@b.test">m</a>')
    assert verify.find_broken_links(tmp_path) == []


def test_find_student_work_flags_a_leaked_submission(tmp_path):
    d = tmp_path / "sections" / "x" / "1682_y_submissions"
    d.mkdir(parents=True)
    (d / "essay.docx").write_text("leak")
    assert verify.find_student_work(tmp_path)


def test_find_student_work_is_empty_for_a_clean_archive(tmp_path):
    (tmp_path / "index.html").write_text("ok")
    assert verify.find_student_work(tmp_path) == []


def test_check_reveal_flags_a_page_that_is_mostly_markup(tmp_path):
    page = tmp_path / "thin.html"
    page.write_text("<div>" + ("<span class='x'></span>" * 500) + "</div>")
    flagged = verify.check_reveal(tmp_path)
    assert any(f["file"].endswith("thin.html") for f in flagged)


# -------------------------------------------------- audit: never crash ---
# The plan's binding constraint ("never fail the run on one bad asset") has
# been violated three times elsewhere in this build, each caught in review.
# These pin down the same fix here: a file that can't be read as text (e.g.
# a directory that happens to match *.html) must be skipped, not raised on.

def test_find_broken_links_skips_a_path_that_is_not_actually_a_file(tmp_path):
    (tmp_path / "trap.html").mkdir()
    assert verify.find_broken_links(tmp_path) == []


def test_check_reveal_skips_a_path_that_is_not_actually_a_file(tmp_path):
    (tmp_path / "trap.html").mkdir()
    assert verify.check_reveal(tmp_path) == []


# `_source/` is the raw, pre-substitution Elucidat mirror -- its
# "{{next.url}}"-style template tokens are not real links and were never
# meant to resolve on disk (they're stripped/replaced only in the copy
# under sections/*/elucidat/). A blind rglob over the whole archive found
# 303 of these as "broken links" against the real build; both checks must
# be scoped to the delivered site, not the read-only stage-input mirrors.

def test_find_broken_links_ignores_the_unsubstituted_source_mirror(tmp_path):
    source = tmp_path / "_source" / "elucidat" / "M1"
    source.mkdir(parents=True)
    (source / "01-page.html").write_text('<a href="{{next.url}}">next</a>')
    assert verify.find_broken_links(tmp_path) == []


def test_check_reveal_ignores_the_source_mirror(tmp_path):
    source = tmp_path / "_source" / "elucidat" / "M1"
    source.mkdir(parents=True)
    (source / "01-page.html").write_text(
        "<div>" + ("<span class='x'></span>" * 500) + "</div>")
    assert verify.check_reveal(tmp_path) == []


# --------------------------------------------------------- check_coverage -

def _write_assessment(directory, ident, title):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{ident}.xml.qti").write_text(f"""<?xml version="1.0"?>
<questestinterop xmlns="{QTI_NS}">
  <assessment ident="{ident}" title="{title}">
    <section ident="root_section"><item ident="i1" title="Q1">
      <presentation><material><mattext>x</mattext></material></presentation>
    </item></section>
  </assessment>
</questestinterop>""")


def _write_bank(directory, ident):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{ident}.xml.qti").write_text(f"""<?xml version="1.0"?>
<questestinterop xmlns="{QTI_NS}">
  <objectbank ident="{ident}"><item ident="i1" title="Q1">
    <presentation><material><mattext>x</mattext></material></presentation>
  </item></objectbank>
</questestinterop>""")


def _good_build(tmp_path):
    """A minimal build where every Ruling-16 coverage check should pass."""
    out_dir = tmp_path / "archive"
    build = out_dir / "_build"
    build.mkdir(parents=True)

    quiz_items = [
        {"kind": "quiz", "title": "Entry Survey",
         "content": {"questions": [{}] * 23}},
        {"kind": "quiz", "title": "Exit Survey",
         "content": {"questions": [{}] * 23}},
        {"kind": "quiz", "title": "Code of Conduct",
         "content": {"questions": [{}] * 2}},
        {"kind": "quiz", "title": "Module Poll",
         "content": {"questions": [{}] * 1}},
        {"kind": "quiz", "title": "CEUs Survey",
         "content": {"questions": [{}] * 7}},
    ]
    items = (quiz_items
             + [{"kind": "page", "title": f"Page {i}"} for i in range(15)]
             + [{"kind": "discussion", "title": f"Disc {i}"} for i in range(9)]
             + [{"kind": "assignment", "title": f"Assign {i}"} for i in range(14)]
             + [{"kind": "external_tool", "title": f"LTI {i}"} for i in range(2)])
    sections = [{"title": "S1", "items": items}]
    sections += [{"title": f"S{i}", "items": []} for i in range(2, 17)]
    (build / "course.json").write_text(json.dumps({"sections": sections}))

    elucidat = {key: {"pages": [{}] * n}
               for key, n in verify.EXPECTED_ELUCIDAT_PAGES.items()}
    (build / "elucidat.json").write_text(json.dumps(elucidat))

    vimeo = [{"id": str(i), "status": "ok"} for i in range(36)]
    (build / "vimeo.json").write_text(json.dumps(vimeo))

    local = ([{"ext": ".mp4", "path": f"v{i}.mp4"} for i in range(47)]
             + [{"ext": ".pdf", "path": f"d{i}.pdf"} for i in range(87)])
    (build / "local.json").write_text(json.dumps(local))

    media = ([{"path": f"v{i}.mp4", "status": "ok"} for i in range(38)]
             + [{"path": f"v{i}.mp4", "status": "no_speech"} for i in range(38, 47)])
    (build / "media.json").write_text(json.dumps(media))

    cartridge_dir = tmp_path / "cartridge"
    assessments_dir = cartridge_dir / "non_cc_assessments"
    for i in range(6):
        _write_assessment(assessments_dir, f"assess-{i}", f"Assessment {i}")
    for i in range(11):
        _write_bank(assessments_dir, f"bank-{i}")

    return out_dir, cartridge_dir


def test_check_coverage_all_pass_for_a_known_good_build(tmp_path):
    out_dir, cartridge_dir = _good_build(tmp_path)
    rows = verify.check_coverage(out_dir, cartridge_dir=cartridge_dir)
    failed = [row for row in rows if not row["ok"]]
    assert failed == []
    assert len(rows) >= 18
    for row in rows:
        assert set(row) == {"check", "expected", "actual", "ok"}


def test_check_coverage_flags_a_systematic_vimeo_failure(tmp_path):
    """The exact regression Ruling 16 exists for: every vimeo id gapping
    out must show up as a failed rate check, not a quietly-accepted 36
    individually-justified gaps.
    """
    out_dir, cartridge_dir = _good_build(tmp_path)
    build = out_dir / "_build"
    all_gaps = [{"id": str(i), "status": "gap"} for i in range(36)]
    (build / "vimeo.json").write_text(json.dumps(all_gaps))

    rows = verify.check_coverage(out_dir, cartridge_dir=cartridge_dir)
    gap_row = next(row for row in rows if row["check"] == "Vimeo gap rate")
    assert gap_row["ok"] is False
    assert "100" in gap_row["actual"]


def test_check_coverage_flags_leaked_student_work(tmp_path):
    out_dir, cartridge_dir = _good_build(tmp_path)
    leak_dir = out_dir / "sections" / "x" / "1682_y_submissions"
    leak_dir.mkdir(parents=True)
    (leak_dir / "essay.docx").write_text("leak")

    rows = verify.check_coverage(out_dir, cartridge_dir=cartridge_dir)
    row = next(row for row in rows
              if row["check"] == "Student-work paths anywhere in the archive")
    assert row["ok"] is False
    assert row["actual"] == 1


def test_check_coverage_is_robust_to_a_missing_build_directory(tmp_path):
    out_dir = tmp_path / "empty_archive"
    out_dir.mkdir()
    rows = verify.check_coverage(out_dir, cartridge_dir=tmp_path / "no-such-cartridge")
    assert rows  # returns rows, doesn't raise
    by_check = {row["check"]: row for row in rows}
    # These have a non-zero expected count, so an empty build must fail them --
    # they can't pass by accident the way a "must be 0" check vacuously can.
    for name in ("Elucidat projects", "Cartridge sections", "Cartridge module items",
                "Vimeo ids attempted", "Local index records", "In-scope MP4s",
                "Assessments on disk", "Question banks on disk"):
        assert by_check[name]["ok"] is False, name


def test_check_coverage_is_robust_to_malformed_json(tmp_path):
    out_dir, cartridge_dir = _good_build(tmp_path)
    (out_dir / "_build" / "course.json").write_text("{not valid json")
    (out_dir / "_build" / "vimeo.json").write_text("")

    rows = verify.check_coverage(out_dir, cartridge_dir=cartridge_dir)  # must not raise
    sections_row = next(row for row in rows if row["check"] == "Cartridge sections")
    assert sections_row["ok"] is False


# ------------------------------------------------------------ build_report -

def test_build_report_headline_states_zero_student_work_first(tmp_path):
    out_dir, cartridge_dir = _good_build(tmp_path)
    report = verify.build_report(out_dir)
    assert report.startswith("# Systematic Innovation Archive")
    assert "NONE FOUND (0 paths)" in report.splitlines()[2]
    assert "COVERAGE:" in report


def test_build_report_headline_flags_leaked_student_work_first(tmp_path):
    out_dir, cartridge_dir = _good_build(tmp_path)
    leak_dir = out_dir / "sections" / "x" / "1682_y_submissions"
    leak_dir.mkdir(parents=True)
    (leak_dir / "essay.docx").write_text("leak")

    report = verify.build_report(out_dir)
    assert "STUDENT WORK FOUND IN ARCHIVE" in report.splitlines()[2]
    assert "sections/x/1682_y_submissions/essay.docx" in report


def test_build_report_flags_a_thin_non_elucidat_page_as_not_a_reveal_regression(tmp_path):
    """check_reveal exists to catch reveal.css failing to expand Elucidat's
    hidden interactive content. A thin *non*-Elucidat page (a Canvas wiki
    page that's mostly icon links) is real data the check should still
    surface, but the report must not let a reader mistake it for that
    regression -- see the real archive's homepage and FAQ pages, which are
    exactly this shape.
    """
    out_dir, cartridge_dir = _good_build(tmp_path)
    page = out_dir / "sections" / "01-homepage" / "pages" / "thin.html"
    page.parent.mkdir(parents=True)
    page.write_text("<div>" + ("<span class='x'></span>" * 500) + "</div>")

    report = verify.build_report(out_dir)
    assert "not an Elucidat mirror page" in report
    assert "not that regression" in report


def test_build_report_names_transcription_failed_files_individually(tmp_path):
    out_dir, cartridge_dir = _good_build(tmp_path)
    media = json.loads((out_dir / "_build" / "media.json").read_text())
    media[0] = {"path": "webinar.mp4", "status": "transcription_failed",
               "reason": "repetition loop"}
    (out_dir / "_build" / "media.json").write_text(json.dumps(media))

    report = verify.build_report(out_dir)
    assert "webinar.mp4: repetition loop" in report


# --------------------------------------------------- against the real build -

@needs_archive
def test_check_coverage_against_the_real_archive_does_not_raise():
    rows = verify.check_coverage(REAL_OUT)
    assert len(rows) >= 18
    student_row = next(row for row in rows
                       if row["check"] == "Student-work paths anywhere in the archive")
    assert student_row["actual"] == 0
    assert student_row["ok"] is True


@needs_archive
def test_find_student_work_is_empty_for_the_real_archive():
    assert verify.find_student_work(REAL_OUT) == []


@needs_archive
def test_build_report_runs_against_the_real_archive_without_writing_anything():
    before = sorted(p.name for p in REAL_OUT.iterdir())
    report = verify.build_report(REAL_OUT)
    after = sorted(p.name for p in REAL_OUT.iterdir())
    assert before == after  # build_report only returns text; it never writes
    assert "COVERAGE:" in report
