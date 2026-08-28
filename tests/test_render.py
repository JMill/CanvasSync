import json
from pathlib import Path

import pytest

from si_archive import constants, render

FIX_CARTRIDGE = Path(__file__).parent / "fixtures" / "cartridge"
REAL_CARTRIDGE = Path(constants.CARTRIDGE_DIR)
needs_cartridge = pytest.mark.skipif(
    not REAL_CARTRIDGE.exists(), reason="cartridge not mounted")


# -------------------------------------------------------------- brief's ---

def test_strip_canvas_query_removes_download_parameters():
    assert render.strip_canvas_query("Logo.PNG?canvas_download=1") == "Logo.PNG"
    assert render.strip_canvas_query(
        "a/b.png?canvas_download=1&canvas_qs_wrap=1") == "a/b.png"
    assert render.strip_canvas_query("plain.png") == "plain.png"


def test_rewrite_filebase_resolves_to_the_files_directory():
    html = '<img src="%24IMS-CC-FILEBASE%24/Dise%C3%B1o/iconos/Logo%20MIT.PNG?canvas_download=1">'
    out = render.rewrite_filebase(html, depth=2)
    assert "IMS-CC-FILEBASE" not in out
    assert "../../files/" in out
    assert "canvas_download" not in out


def test_rewrite_filebase_keeps_url_encoding_for_spaces():
    html = '<img src="%24IMS-CC-FILEBASE%24/a%20b/c%20d.png?canvas_download=1">'
    out = render.rewrite_filebase(html, depth=1)
    assert "a%20b/c%20d.png" in out


def test_page_shell_links_the_stylesheet_at_the_right_depth():
    out = render.page_shell("T", "<p>x</p>", depth=2)
    assert '<title>T</title>' in out
    assert '../../reveal.css' in out
    assert "<p>x</p>" in out


def test_page_shell_at_root_uses_a_bare_stylesheet_path():
    assert 'href="reveal.css"' in render.page_shell("T", "", depth=0)


def test_destination_for_maps_module_one_media_to_part_one():
    course = {"sections": [{"title": "Module 1 - Part 1",
                            "dirname": "04-module-1-part-1"}]}
    dest = render.destination_for(
        "/x/campus.mitpeonline.com/Module 1/MIT_INN_M1_V1.mp4", course)
    assert dest == "sections/04-module-1-part-1"


def test_destination_for_sends_pre_to_orientation():
    dest = render.destination_for(
        "/x/campus.mitpeonline.com/pre/webinars/a.mp4", {"sections": []})
    assert dest == "orientation"


def test_destination_for_falls_back_to_files_for_unknown_folders():
    dest = render.destination_for(
        "/x/campus.mitpeonline.com/mystery/a.mp4", {"sections": []})
    assert dest == "files"


# ------------------------------------------------------------ filenames ---

def test_unique_filename_suffixes_a_second_collision():
    seen = {}
    assert render.unique_filename(seen, "foo") == "foo"
    assert render.unique_filename(seen, "foo") == "foo-2"
    assert render.unique_filename(seen, "foo") == "foo-3"
    assert render.unique_filename(seen, "bar") == "bar"


def test_render_site_gives_two_items_with_identical_titles_distinct_files(tmp_path):
    # Two assignments in one section, same title -> same slug -> must not
    # clobber each other on disk.
    course = _course_with_items("06-module-1-part-4", [
        _assignment_item("Give your definitions"),
        _assignment_item("Give your definitions"),
    ])
    build_dir = _write_build(tmp_path, course)
    render.render_site(build_dir, tmp_path / "out")

    assign_dir = tmp_path / "out" / "sections" / "06-module-1-part-4" / "assignments"
    files = sorted(p.name for p in assign_dir.glob("*.html"))
    assert files == ["give-your-definitions-2.html", "give-your-definitions.html"]


# --------------------------------------------------------------- quizzes --

def test_render_quiz_omits_correct_answer_for_a_survey():
    quiz = {"title": "Entry Survey", "description_html": "<p>d</p>", "is_survey": True,
            "questions": [{"title": "Q1", "prompt_html": "<p>p</p>",
                           "options": ["a", "b"], "correct": "a"}]}
    out = render.render_quiz(quiz)
    assert "This is a survey" in out
    assert "Correct:" not in out


def test_render_quiz_shows_correct_answer_for_a_real_quiz():
    quiz = {"title": "Real Quiz", "description_html": "", "is_survey": False,
            "questions": [{"title": "Q1", "prompt_html": "<p>p</p>",
                           "options": ["a", "b"], "correct": "b"}]}
    out = render.render_quiz(quiz)
    assert "Correct:</strong> b" in out


# --------------------------------------------------------- item bodies ---

def test_render_item_body_dispatches_on_kind():
    page = {"kind": "page", "title": "P", "content": {"html": "<p>hi</p>"}}
    assert "<p>hi</p>" in render.render_item_body(page)

    assignment = {"kind": "assignment", "title": "A",
                  "content": {"html": "<p>do it</p>", "points_possible": 5.0,
                              "due_at": None, "submission_types": "online_upload"}}
    body = render.render_item_body(assignment)
    assert "<p>do it</p>" in body
    assert "Points:</strong> 5.0" in body

    discussion = {"kind": "discussion", "title": "D", "content": {"text_html": "<p>talk</p>"}}
    assert "<p>talk</p>" in render.render_item_body(discussion)

    tool = {"kind": "external_tool", "title": "Cert", "content": None}
    assert "known gap" in render.render_item_body(tool)


def test_render_item_body_handles_a_quiz_with_no_content():
    item = {"kind": "quiz", "title": "Broken Quiz", "content": None}
    out = render.render_item_body(item)
    assert "unavailable" in out


# ------------------------------------------------------------ Elucidat ---

def test_find_elucidat_embeds_matches_by_code_not_hardcoded_table(monkeypatch):
    code = "5fa00000abc12-5fa00000def34"
    monkeypatch.setattr(render.constants, "ELUCIDAT_PROJECTS", {"M1": code})
    item = {"title": "Module 1 Content", "kind": "page",
            "content": {"html": f'<iframe src="https://learning.elucidat.com/course/{code}"></iframe>'}}
    course = {"sections": [{"title": "S", "dirname": "01-s", "items": [item]}]}
    embeds = render.find_elucidat_embeds(course)
    assert set(embeds) == {"M1"}
    assert embeds["M1"]["item"] is item


def test_find_elucidat_embeds_skips_an_item_whose_content_is_not_a_dict():
    item = {"title": "Broken", "kind": "assignment", "content": "not-a-dict"}
    course = {"sections": [{"title": "S", "dirname": "01-s", "items": [item]}]}
    assert render.find_elucidat_embeds(course) == {}


def test_find_elucidat_embeds_warns_but_does_not_raise_for_a_missing_project(monkeypatch, capsys):
    monkeypatch.setattr(render.constants, "ELUCIDAT_PROJECTS", {"M1": "code-abc", "M2": "code-xyz"})
    course = {"sections": [{"title": "S", "dirname": "01-s", "items": []}]}
    embeds = render.find_elucidat_embeds(course)
    assert embeds == {}
    assert "WARNING" in capsys.readouterr().out


def test_embed_elucidat_links_replaces_the_dead_iframe():
    body = ('<p><iframe src="https://learning.elucidat.com/course/xyz" '
            'width="100%" height="800px"></iframe></p>')
    project = {"title": "Module 1.", "pages": [{"slug": "01-module-1", "name": "Module 1."}]}
    out = render.embed_elucidat_links(body, project, "04-module-1-part-1")
    assert "<iframe" not in out
    assert '../elucidat/01-module-1.html' in out
    assert "Module 1." in out


def test_embed_elucidat_links_appends_when_there_is_no_iframe_to_replace():
    project = {"title": "T", "pages": [{"slug": "x", "name": "X"}]}
    out = render.embed_elucidat_links("<p>no iframe here</p>", project, "01-s")
    assert "<p>no iframe here</p>" in out
    assert "../elucidat/x.html" in out


def test_copy_elucidat_project_records_a_gap_for_a_missing_page_file(tmp_path):
    build_dir = tmp_path / "_build"
    (tmp_path / "_source" / "elucidat" / "M1").mkdir(parents=True)
    project = {"pages": [{"slug": "01-missing", "name": "Missing"}]}
    written, gaps = render.copy_elucidat_project(project, "M1", "04-s", build_dir, tmp_path / "out")
    assert written == 0
    assert gaps and gaps[0]["page"] == "01-missing"


def test_copy_elucidat_project_writes_pages_and_assets(tmp_path):
    build_dir = tmp_path / "_build"
    source = tmp_path / "_source" / "elucidat" / "M1"
    (source / "assets").mkdir(parents=True)
    (source / "assets" / "img.png").write_bytes(b"\x89PNG")
    (source / "01-page.html").write_text("<div>content</div>")
    project = {"pages": [{"slug": "01-page", "name": "Page One"}]}

    written, gaps = render.copy_elucidat_project(project, "M1", "04-s", build_dir, tmp_path / "out")

    assert written == 1
    assert gaps == []
    out_page = tmp_path / "out" / "sections" / "04-s" / "elucidat" / "01-page.html"
    assert out_page.exists()
    assert "content" in out_page.read_text()
    assert (tmp_path / "out" / "sections" / "04-s" / "elucidat" / "assets" / "img.png").exists()


# ------------------------------------------------ non-cartridge QTI docs -

QTI_NS = "http://www.imsglobal.org/xsd/ims_qtiasiv1p2"


def _write_assessment(directory, ident, title):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{ident}.xml.qti").write_text(f"""<?xml version="1.0"?>
<questestinterop xmlns="{QTI_NS}">
  <assessment ident="{ident}" title="{title}">
    <section ident="root_section">
      <item ident="i1" title="Question 1">
        <presentation>
          <material><mattext texttype="text/html">&lt;p&gt;How was it?&lt;/p&gt;</mattext></material>
          <response_lid ident="response1">
            <render_choice>
              <response_label ident="a"><material><mattext>Good</mattext></material></response_label>
            </render_choice>
          </response_lid>
        </presentation>
      </item>
    </section>
  </assessment>
</questestinterop>""")


def _write_bank(directory, ident, n_items=2):
    directory.mkdir(parents=True, exist_ok=True)
    items = "".join(f"""
      <item ident="i{n}" title="Bank Question {n}">
        <presentation>
          <material><mattext texttype="text/html">&lt;p&gt;Q{n}&lt;/p&gt;</mattext></material>
        </presentation>
      </item>""" for n in range(1, n_items + 1))
    (directory / f"{ident}.xml.qti").write_text(f"""<?xml version="1.0"?>
<questestinterop xmlns="{QTI_NS}">
  <objectbank ident="{ident}">{items}</objectbank>
</questestinterop>""")


def test_load_non_cc_assessments_classifies_assessments_and_banks(tmp_path):
    directory = tmp_path / "non_cc_assessments"
    _write_assessment(directory, "g-linked", "Entry Survey")
    _write_assessment(directory, "g-orphan", "Survey: Webinar 1")
    _write_bank(directory, "g-bank-1", n_items=3)

    assessments, banks, gaps = render.load_non_cc_assessments(tmp_path)

    assert gaps == []
    assert {a["title"] for a in assessments} == {"Entry Survey", "Survey: Webinar 1"}
    assert len(banks) == 1
    assert len(banks[0]["questions"]) == 3
    entry = next(a for a in assessments if a["title"] == "Entry Survey")
    assert entry["questions"][0]["title"] == "Question 1"
    assert "How was it?" in entry["questions"][0]["prompt_html"]


def test_load_non_cc_assessments_records_a_gap_for_unparseable_xml(tmp_path):
    directory = tmp_path / "non_cc_assessments"
    directory.mkdir(parents=True)
    (directory / "bad.xml.qti").write_text("<not-xml")

    assessments, banks, gaps = render.load_non_cc_assessments(tmp_path)

    assert assessments == [] and banks == []
    assert len(gaps) == 1 and gaps[0]["file"] == "bad.xml.qti"


def test_find_unlinked_assessments_returns_only_the_one_no_module_reaches():
    course = {"sections": [{"items": [{"identifierref": "g-linked"}]}]}
    assessments = [{"ident": "g-linked", "title": "Linked"},
                   {"ident": "g-orphan", "title": "Survey: Webinar 1"}]
    unlinked = render.find_unlinked_assessments(course, assessments)
    assert [a["title"] for a in unlinked] == ["Survey: Webinar 1"]


def test_render_question_banks_labels_them_as_pools_not_quizzes():
    banks = [{"ident": "g1", "questions": [{"title": "Q", "prompt_html": "<p>x</p>", "options": []}]}]
    out = render.render_question_banks(banks)
    assert "not quizzes presented to learners" in out
    assert "Q" in out


@needs_cartridge
def test_load_non_cc_assessments_finds_six_assessments_and_eleven_banks_for_real():
    assessments, banks, gaps = render.load_non_cc_assessments(REAL_CARTRIDGE)
    assert len(assessments) == 6
    assert len(banks) == 11
    assert gaps == []


# ------------------------------------------------------- media placement -

def _mp4(path, content=b"fake-mp4-bytes"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def test_collect_canonical_videos_prefers_the_vimeo_copy_when_it_won(tmp_path):
    local = _mp4(tmp_path / "campus.mitpeonline.com" / "Module 1" / "V1.mp4")
    vimeo = _mp4(tmp_path / "vimeo" / "123 - V1.mp4")
    ledger = {
        "files": [{"canonical": str(local), "aliases": []}],
        "renditions": [{"local_path": str(local), "canonical": str(vimeo)}],
        "online_only": [],
    }
    videos = render.collect_canonical_videos(ledger)
    assert len(videos) == 1
    assert videos[0]["copy_from"] == str(vimeo)
    assert videos[0]["identity"] == str(local)


def test_collect_canonical_videos_includes_vimeo_only_entries(tmp_path):
    ledger = {"files": [], "renditions": [],
             "online_only": [{"path": "/x/online-only.mp4"}]}
    videos = render.collect_canonical_videos(ledger)
    assert videos == [{"copy_from": "/x/online-only.mp4", "identity": None}]


def test_collect_canonical_videos_resolves_a_rendition_keyed_by_an_alias_path(tmp_path):
    canonical_local = _mp4(tmp_path / "campus.mitpeonline.com" / "Module 2" / "canonical.mp4")
    alias_local = str(tmp_path / "campus.mitpeonline.com" / "Module 2" / "alias.mp4")
    vimeo = _mp4(tmp_path / "vimeo" / "9 - x.mp4")
    ledger = {
        "files": [{"canonical": str(canonical_local), "aliases": [alias_local]}],
        "renditions": [{"local_path": alias_local, "canonical": str(vimeo)}],
        "online_only": [],
    }
    videos = render.collect_canonical_videos(ledger)
    assert videos == [{"copy_from": str(vimeo), "identity": str(canonical_local)}]


def test_place_media_places_every_video_local_vimeo_and_online_only(tmp_path):
    course = {"sections": [{"title": "Module 1 - Part 1", "dirname": "04-module-1"}]}
    local_only = _mp4(tmp_path / "campus.mitpeonline.com" / "Module 1" / "Plain.mp4")
    local_losing = _mp4(tmp_path / "campus.mitpeonline.com" / "Module 1" / "Better.mp4")
    vimeo_winning = _mp4(tmp_path / "vimeo" / "1 - Better.mp4")
    online_only = _mp4(tmp_path / "vimeo" / "2 - OnlineOnly.mp4")

    ledger = {
        "files": [
            {"canonical": str(local_only), "aliases": []},
            {"canonical": str(local_losing), "aliases": []},
        ],
        "renditions": [
            {"local_path": str(local_losing), "canonical": str(vimeo_winning)},
        ],
        "online_only": [{"path": str(online_only)}],
    }
    media_records = [
        {"path": str(local_only), "status": "ok",
         "transcript": str(_touch(tmp_path / "t" / "Plain.transcript.md")),
         "contactsheet": None},
    ]
    out_dir = tmp_path / "out"
    placed, captions = render.place_media(course, ledger, media_records, out_dir, tmp_path / "_build")

    assert placed == 3
    media_dir = out_dir / "sections" / "04-module-1" / "media"
    assert (media_dir / "Plain.mp4").exists()
    assert (media_dir / "Better.mp4").read_bytes() == vimeo_winning.read_bytes()
    assert (media_dir / "Plain.transcript.md").exists()
    # Online-only video has no campus.mitpeonline.com path -> falls back to
    # files/, keeping its Vimeo-download filename since there's no local name.
    assert (out_dir / "files" / "media" / "2 - OnlineOnly.mp4").exists()


def test_place_media_falls_back_to_a_whisper_srt_when_no_original_caption_exists(tmp_path):
    course = {"sections": []}
    video = _mp4(tmp_path / "campus.mitpeonline.com" / "pre" / "webinars" / "Talk.mp4")
    build_dir = tmp_path / "_build"
    whisper_srt = _touch(build_dir / "transcripts" / "Talk.srt", "1\n00:00:00,000 --> 00:00:01,000\nHi\n")
    ledger = {"files": [{"canonical": str(video), "aliases": []}], "renditions": [], "online_only": []}

    placed, captions = render.place_media(course, ledger, [], tmp_path / "out", build_dir)

    assert placed == 1
    out_srt = tmp_path / "out" / "orientation" / "media" / "Talk.srt"
    assert out_srt.exists()
    assert out_srt.read_text() == whisper_srt.read_text()
    assert captions == [{"video": "orientation/media/Talk.mp4", "caption_source": "whisper"}]


def test_place_media_prefers_an_original_srt_over_a_whisper_one(tmp_path):
    course = {"sections": []}
    video = _mp4(tmp_path / "campus.mitpeonline.com" / "post" / "Closing.mp4")
    _touch(video.with_suffix(".srt"), "original captions")
    build_dir = tmp_path / "_build"
    _touch(build_dir / "transcripts" / "Closing.srt", "whisper captions")
    ledger = {"files": [{"canonical": str(video), "aliases": []}], "renditions": [], "online_only": []}

    placed, captions = render.place_media(course, ledger, [], tmp_path / "out", build_dir)

    out_srt = tmp_path / "out" / "closing" / "media" / "Closing.srt"
    assert out_srt.read_text() == "original captions"
    assert captions == [{"video": "closing/media/Closing.mp4", "caption_source": "original"}]


def test_place_media_tolerates_any_status_value_and_skips_missing_derived_files(tmp_path):
    course = {"sections": []}
    video = _mp4(tmp_path / "campus.mitpeonline.com" / "Module 2" / "X.mp4")
    ledger = {"files": [{"canonical": str(video), "aliases": []}], "renditions": [], "online_only": []}
    media_records = [{"path": str(video), "status": "transcription_failed",
                      "reason": "unrecognized future status", "marker": "/nonexistent/marker.md"}]

    placed, captions = render.place_media(course, ledger, media_records, tmp_path / "out", tmp_path / "_build")

    assert placed == 1  # the video itself is still placed
    assert captions == []  # no caption artifact -- nothing crashed on the unknown status


def test_place_media_skips_a_video_whose_source_file_is_missing(tmp_path):
    course = {"sections": []}
    ledger = {"files": [{"canonical": str(tmp_path / "gone.mp4"), "aliases": []}],
             "renditions": [], "online_only": []}
    placed, captions = render.place_media(course, ledger, [], tmp_path / "out", tmp_path / "_build")
    assert placed == 0
    assert captions == []


def _touch(path, content="x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


# ------------------------------------------------------- full render_site -

def _assignment_item(title):
    return {"title": title, "content_type": "Assignment", "kind": "assignment",
            "slug": None, "identifierref": None,
            "content": {"html": f"<p>{title}</p>", "points_possible": 1.0,
                        "due_at": None, "submission_types": "online_upload"}}


def _course_with_items(dirname, items):
    from si_archive.cartridge import slugify
    for item in items:
        item["slug"] = slugify(item["title"])
    return {"title": "Test Course", "course_code": "TEST-001",
            "sections": [{"title": "Test Section", "dirname": dirname, "items": items}]}


def _write_build(tmp_path, course):
    build_dir = tmp_path / "_build"
    build_dir.mkdir(parents=True, exist_ok=True)
    (build_dir / "course.json").write_text(json.dumps(course))
    return build_dir


def test_render_site_writes_an_index_and_a_section_page_at_the_right_depth(tmp_path):
    course = _course_with_items("01-homepage", [_assignment_item("Say Hi")])
    build_dir = _write_build(tmp_path, course)
    out_dir = tmp_path / "out"

    stats = render.render_site(build_dir, out_dir)

    assert stats["sections"] == 1
    assert (out_dir / "index.html").exists()
    assert (out_dir / "reveal.css").exists()
    section_index = (out_dir / "sections" / "01-homepage" / "index.html").read_text()
    assert "../../reveal.css" in section_index
    item_page = (out_dir / "sections" / "01-homepage" / "assignments" / "say-hi.html").read_text()
    assert "../../../reveal.css" in item_page
    assert "<p>Say Hi</p>" in item_page


def test_render_site_rewrites_filebase_references_in_item_bodies(tmp_path):
    item = {"title": "Logo Page", "content_type": "WikiPage", "kind": "page",
            "slug": None, "identifierref": None,
            "content": {"html": '<img src="%24IMS-CC-FILEBASE%24/logo.png?canvas_download=1">'}}
    course = _course_with_items("01-homepage", [item])
    build_dir = _write_build(tmp_path, course)
    out_dir = tmp_path / "out"

    render.render_site(build_dir, out_dir)

    page = (out_dir / "sections" / "01-homepage" / "pages" / "logo-page.html").read_text()
    assert "IMS-CC-FILEBASE" not in page
    assert "../../../files/logo.png" in page


def test_render_site_survives_an_item_whose_content_dict_is_malformed(tmp_path):
    item = {"title": "Broken", "content_type": "Assignment", "kind": "assignment",
            "slug": None, "identifierref": None, "content": "not-a-dict"}
    course = _course_with_items("01-homepage", [item])
    build_dir = _write_build(tmp_path, course)
    out_dir = tmp_path / "out"

    stats = render.render_site(build_dir, out_dir)

    assert stats["gaps"] >= 1
    page = out_dir / "sections" / "01-homepage" / "assignments" / "broken.html"
    assert page.exists()
    assert "could not be rendered" in page.read_text()


def test_render_site_runs_with_no_ledger_or_media_json(tmp_path):
    course = _course_with_items("01-homepage", [_assignment_item("Only Item")])
    build_dir = _write_build(tmp_path, course)
    stats = render.render_site(build_dir, tmp_path / "out")
    assert stats["media_placed"] == 0
    assert not (tmp_path / "out" / "MANIFEST.json").exists()


def test_render_site_survives_a_corrupt_elucidat_json(tmp_path):
    course = _course_with_items("01-homepage", [_assignment_item("Only Item")])
    build_dir = _write_build(tmp_path, course)
    (build_dir / "elucidat.json").write_text("{not valid json")
    stats = render.render_site(build_dir, tmp_path / "out")
    assert (tmp_path / "out" / "index.html").exists()
    assert stats["pages_written"] > 0


def test_render_site_survives_an_elucidat_project_that_is_the_wrong_shape(tmp_path, monkeypatch):
    code = "5fa00000abc12-5fa00000def34"
    item = {"title": "Module 1 Content", "content_type": "WikiPage", "kind": "page",
            "slug": None, "identifierref": None,
            "content": {"html": f'<iframe src="https://learning.elucidat.com/course/{code}"></iframe>'}}
    course = _course_with_items("01-homepage", [item])
    build_dir = _write_build(tmp_path, course)
    # elucidat.json parses fine as JSON but the project value is a list, not
    # a dict -- .get("pages") would raise if any call site were unguarded.
    (build_dir / "elucidat.json").write_text(
        json.dumps({"M1": ["not", "a", "project", "dict"]}))
    monkeypatch.setattr(render.constants, "ELUCIDAT_PROJECTS", {"M1": code})

    stats = render.render_site(build_dir, tmp_path / "out")

    assert (tmp_path / "out" / "index.html").exists()
    assert stats["gaps"] >= 1
    item_page = (tmp_path / "out" / "sections" / "01-homepage" / "pages" / "module-1-content.html")
    assert item_page.exists()


def test_render_site_survives_ledger_json_with_the_wrong_top_level_type(tmp_path):
    course = _course_with_items("01-homepage", [_assignment_item("Only Item")])
    build_dir = _write_build(tmp_path, course)
    (build_dir / "ledger.json").write_text(json.dumps(["not", "a", "dict"]))
    (build_dir / "media.json").write_text(json.dumps([]))

    stats = render.render_site(build_dir, tmp_path / "out")

    assert (tmp_path / "out" / "index.html").exists()
    assert stats["media_placed"] == 0
    assert stats["gaps"] >= 1


def test_collect_canonical_videos_skips_a_file_group_missing_its_canonical_key():
    ledger = {"files": [{"aliases": ["/x/a.mp4"]}], "renditions": [], "online_only": []}
    assert render.collect_canonical_videos(ledger) == []
