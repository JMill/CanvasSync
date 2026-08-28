from pathlib import Path

import pytest

from si_archive import cartridge, constants

FIX = Path(__file__).parent / "fixtures" / "cartridge"
REAL = Path(constants.CARTRIDGE_DIR)
needs_cartridge = pytest.mark.skipif(
    not REAL.exists(), reason="cartridge not mounted")


def test_parse_modules_returns_all_sixteen_in_cartridge_order():
    mods = cartridge.parse_modules(FIX)
    assert len(mods) == 16
    assert mods[0]["title"] == "Homepage"
    assert mods[1]["title"] == "Requirements and Information"
    assert mods[-1]["title"] == "Continuous Education Units"


def test_parse_modules_splits_module_one_across_three_sections():
    titles = [m["title"] for m in cartridge.parse_modules(FIX)]
    assert "Module 1 - Part 1" in titles
    assert "Module 1 - Part 2 and 3" in titles
    assert "Module 1 - Part 4" in titles


def test_parse_modules_records_item_content_types():
    mods = {m["title"]: m for m in cartridge.parse_modules(FIX)}
    kinds = [i["content_type"] for i in mods["Module 3"]["items"]]
    assert kinds.count("Assignment") == 4
    assert kinds.count("WikiPage") == 2


def test_parse_assignment_reads_title_and_points():
    a = cartridge.parse_assignment(FIX / "assignment" / "assignment_settings.xml")
    assert a["title"] == "Module 3 Assignment: Your Assumptions Log"
    assert a["points_possible"] == 1.0
    assert "online_upload" in a["submission_types"]


def test_parse_discussion_unescapes_embedded_html():
    d = cartridge.parse_discussion(FIX / "discussion.xml")
    assert d["title"] == "Extension of the program"
    # The XML stores HTML entity-escaped; the parser must unescape it.
    assert "<p>" in d["text_html"]
    assert "&lt;p&gt;" not in d["text_html"]


def test_slugify_is_stable_and_url_safe():
    assert cartridge.slugify("Module 1 - Part 2 and 3") == "module-1-part-2-and-3"
    assert cartridge.slugify("Where's Company X") == "wheres-company-x"
    assert cartridge.slugify("Diseño / iconos") == "diseno-iconos"


@needs_cartridge
def test_build_course_attaches_bodies_to_every_resolvable_item():
    course = cartridge.build_course(REAL)
    items = [i for s in course["sections"] for i in s["items"]]
    assert len(items) == 45
    unresolved = [i for i in items if i["kind"] == "unresolved"]
    assert unresolved == []


@needs_cartridge
def test_build_course_marks_the_two_lti_launches_as_external_tools():
    course = cartridge.build_course(REAL)
    items = [i for s in course["sections"] for i in s["items"]]
    external = [i for i in items if i["kind"] == "external_tool"]
    assert len(external) == 2


@needs_cartridge
def test_build_course_parses_all_five_quizzes_with_questions():
    course = cartridge.build_course(REAL)
    quizzes = [i for s in course["sections"] for i in s["items"]
               if i["kind"] == "quiz"]
    assert len(quizzes) == 5
    assert all(q["content"]["questions"] for q in quizzes)


@needs_cartridge
def test_build_course_gives_assignments_both_settings_and_body():
    course = cartridge.build_course(REAL)
    assignments = [i for s in course["sections"] for i in s["items"]
                   if i["kind"] == "assignment"]
    assert len(assignments) == 14
    assert all(a["content"].get("html") for a in assignments)
    assert all(a["content"].get("title") for a in assignments)


@needs_cartridge
def test_build_course_uses_the_unabridged_quiz_export():
    """The CC-standard file drops questions; the Canvas export keeps them."""
    course = cartridge.build_course(REAL)
    quizzes = {i["content"]["title"]: i["content"]
               for s in course["sections"] for i in s["items"]
               if i["kind"] == "quiz" and i["content"]}
    assert len(quizzes["Entry Survey"]["questions"]) == 23
    assert len(quizzes["Exit Survey"]["questions"]) == 23
