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
    transcript = _touch(build_dir / "transcripts" / "Talk.transcript.md", "Hi\n")
    media_records = [{"path": str(video), "status": "ok", "transcript": str(transcript)}]

    placed, captions = render.place_media(course, ledger, media_records, tmp_path / "out", build_dir)

    assert placed == 1
    out_srt = tmp_path / "out" / "orientation" / "media" / "Talk.srt"
    assert out_srt.exists()
    assert out_srt.read_text() == whisper_srt.read_text()
    assert captions == [{"video": "orientation/media/Talk.mp4", "caption_source": "whisper"}]


def test_place_media_does_not_surface_a_stray_whisper_srt_for_a_no_speech_video(tmp_path):
    # Regression: a video Whisper failed on (no real transcript, only a
    # marker) can still have a raw pre-degeneracy-screen SRT sitting in
    # build_dir/transcripts/ from the attempt. That SRT must never be
    # copied in as if it were a real caption track.
    course = {"sections": []}
    video = _mp4(tmp_path / "campus.mitpeonline.com" / "Module 1" / "Silent.mp4")
    build_dir = tmp_path / "_build"
    _touch(build_dir / "transcripts" / "Silent.srt", "1\n00:00:00,000 --> 00:00:01,000\nyou you you\n")
    ledger = {"files": [{"canonical": str(video), "aliases": []}], "renditions": [], "online_only": []}
    media_records = [{"path": str(video), "status": "no_speech",
                      "reason": "silent audio track", "marker": "/nonexistent/marker.md"}]

    placed, captions = render.place_media(course, ledger, media_records, tmp_path / "out", build_dir)

    assert placed == 1
    assert not (tmp_path / "out" / "sections" / "04-module-1" / "media" / "Silent.srt").exists()
    assert captions == []


def test_place_media_finds_a_whisper_srt_despite_mlx_whisper_stripping_an_extra_segment(tmp_path):
    # Regression for the mlx_whisper filename quirk (Ruling 27): it can
    # treat a dot-separated segment of the source name as an extension too,
    # writing a shorter .srt than the video's own stem.
    course = {"sections": []}
    video = _mp4(tmp_path / "campus.mitpeonline.com" / "pre" / "webinars" / "Talk.020322.mp4")
    build_dir = tmp_path / "_build"
    whisper_srt = _touch(build_dir / "transcripts" / "Talk.srt",
                         "1\n00:00:00,000 --> 00:00:01,000\nHi\n")
    ledger = {"files": [{"canonical": str(video), "aliases": []}], "renditions": [], "online_only": []}
    transcript = _touch(build_dir / "transcripts" / "Talk.020322.transcript.md", "Hi\n")
    media_records = [{"path": str(video), "status": "ok", "transcript": str(transcript)}]

    placed, captions = render.place_media(course, ledger, media_records, tmp_path / "out", build_dir)

    out_srt = tmp_path / "out" / "orientation" / "media" / "Talk.020322.srt"
    assert out_srt.exists()
    assert out_srt.read_text() == whisper_srt.read_text()
    assert captions == [{"video": "orientation/media/Talk.020322.mp4", "caption_source": "whisper"}]


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


def test_place_media_places_the_no_speech_marker_alongside_its_video(tmp_path):
    course = {"sections": []}
    video = _mp4(tmp_path / "campus.mitpeonline.com" / "Module 2" / "Silent.mp4")
    marker = _touch(tmp_path / "_build" / "transcripts" / "Silent.no_speech.md",
                    "No speech detected in this video's audio track: silent audio track.\n")
    ledger = {"files": [{"canonical": str(video), "aliases": []}], "renditions": [], "online_only": []}
    media_records = [{"path": str(video), "status": "no_speech",
                      "reason": "silent audio track", "marker": str(marker)}]

    placed, captions = render.place_media(course, ledger, media_records, tmp_path / "out", tmp_path / "_build")

    assert placed == 1
    out_marker = tmp_path / "out" / "files" / "media" / "Silent.no_speech.md"
    assert out_marker.exists()
    assert out_marker.read_text() == marker.read_text()
    assert captions == []  # a marker is not a caption track


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
    return {"title": "Test Course", "course_code": "TEST-001", "resources": {},
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


# ------------------------------------------------- Elucidat template vars -

def test_strip_template_placeholders_drops_unsubstituted_href_and_src():
    html = ('<a href="{{next.url}}">Next</a> '
            '<a href="{{navigation.first.url}}">First</a> '
            '<img src="{{some.var}}">')
    out = render.strip_template_placeholders(html)
    assert "{{" not in out
    assert "<a>Next</a>" in out
    assert "<a>First</a>" in out
    assert "<img>" in out


def test_strip_template_placeholders_keeps_a_real_link_untouched():
    html = '<a href="../elucidat/02-page.html">Real</a>'
    assert render.strip_template_placeholders(html) == html


def test_copy_elucidat_project_strips_template_placeholders_from_the_copy(tmp_path):
    build_dir = tmp_path / "_build"
    source = tmp_path / "_source" / "elucidat" / "M1"
    source.mkdir(parents=True)
    raw = '<a href="{{previous.url}}">Prev</a><div>content</div>'
    (source / "01-page.html").write_text(raw)
    project = {"pages": [{"slug": "01-page", "name": "Page One"}]}

    render.copy_elucidat_project(project, "M1", "04-s", build_dir, tmp_path / "out")

    # The raw mirror under _source/ must never be touched.
    assert (source / "01-page.html").read_text() == raw
    out_page = (tmp_path / "out" / "sections" / "04-s" / "elucidat" / "01-page.html").read_text()
    assert "{{" not in out_page
    assert "content" in out_page


# ---------------------------------------------------- cross-reference: --
# $WIKI_REFERENCE$, $CANVAS_OBJECT_REFERENCE$, $CANVAS_COURSE_REFERENCE$

def test_relative_href_computes_a_correct_relative_path(tmp_path):
    a = tmp_path / "sections" / "01-s" / "pages" / "a.html"
    b = tmp_path / "sections" / "02-t" / "quizzes" / "b.html"
    assert render.relative_href(a, b) == "../../02-t/quizzes/b.html"


def test_load_wiki_pages_indexes_by_canvas_identifier(tmp_path):
    wc = tmp_path / "wiki_content"
    wc.mkdir()
    (wc / "captains-log.html").write_text(
        '<html><head><title>Captains Log</title>'
        '<meta name="identifier" content="g-cl"/></head>'
        '<body><p>Ahoy</p></body></html>')

    pages, gaps = render.load_wiki_pages(tmp_path)

    assert gaps == []
    assert set(pages) == {"g-cl"}
    assert pages["g-cl"]["title"] == "Captains Log"
    assert "<p>Ahoy</p>" in pages["g-cl"]["html"]


def test_load_wiki_pages_records_a_gap_for_a_page_with_no_identifier(tmp_path):
    wc = tmp_path / "wiki_content"
    wc.mkdir()
    (wc / "no-id.html").write_text("<html><head><title>X</title></head><body>x</body></html>")

    pages, gaps = render.load_wiki_pages(tmp_path)

    assert pages == {}
    assert len(gaps) == 1 and gaps[0]["file"] == "no-id.html"


def test_load_wiki_pages_returns_empty_when_wiki_content_is_absent(tmp_path):
    assert render.load_wiki_pages(tmp_path) == ({}, [])


def test_find_unlinked_wiki_pages_returns_only_pages_no_item_reaches():
    course = {"sections": [{"items": [{"identifierref": "g-linked"}]}]}
    pages = {"g-linked": {"ident": "g-linked", "title": "Linked"},
             "g-orphan": {"ident": "g-orphan", "title": "Orphan"}}
    unlinked = render.find_unlinked_wiki_pages(course, pages)
    assert [p["title"] for p in unlinked] == ["Orphan"]


def test_render_unlinked_wiki_pages_writes_a_page_and_rewrites_filebase(tmp_path):
    pages = [{"ident": "g1", "title": "Help",
              "html": '<img src="%24IMS-CC-FILEBASE%24/h.png?canvas_download=1">',
              "file": "help.html"}]
    gaps = []

    entries = render.render_unlinked_wiki_pages(pages, tmp_path, gaps)

    assert gaps == []
    assert len(entries) == 1
    entry = entries[0]
    assert entry["slug"] == "help"
    assert entry["path"] == tmp_path / "unlinked" / "pages" / "help.html"
    out = entry["path"].read_text()
    assert "IMS-CC-FILEBASE" not in out
    assert "../../files/h.png" in out


def test_render_unlinked_wiki_pages_deduplicates_a_slug_collision(tmp_path):
    pages = [{"ident": "g1", "title": "Info", "html": "<p>a</p>", "file": "a.html"},
             {"ident": "g2", "title": "Info", "html": "<p>b</p>", "file": "b.html"}]
    entries = render.render_unlinked_wiki_pages(pages, tmp_path, [])
    assert sorted(e["path"].name for e in entries) == ["info-2.html", "info.html"]


def test_render_unlinked_assessments_writes_a_survey_with_no_correct_answer(tmp_path):
    assessments = [{"ident": "g1", "title": "Survey: Webinar 1",
                    "questions": [{"title": "Q1", "prompt_html": "<p>p</p>",
                                   "options": ["a"], "correct": "a"}]}]
    gaps = []
    entries = render.render_unlinked_assessments(assessments, tmp_path, gaps)
    assert gaps == []
    assert len(entries) == 1
    entry = entries[0]
    assert entry["path"] == tmp_path / "unlinked" / "assessments" / "survey-webinar-1.html"
    out = entry["path"].read_text()
    assert "This is a survey" in out
    assert "Correct:" not in out


IMSCP_NS = "http://www.imsglobal.org/xsd/imsccv1p1/imscp_v1p1"
CC_NS = "http://canvas.instructure.com/xsd/cccv1p0"


def _write_manifest_with_dependency(cartridge_dir, resource_id, dependency_id):
    cartridge_dir.mkdir(parents=True, exist_ok=True)
    (cartridge_dir / "imsmanifest.xml").write_text(f"""<?xml version="1.0"?>
<manifest xmlns="{IMSCP_NS}">
  <resources>
    <resource identifier="{resource_id}" type="imsdt_xmlv1p1">
      <file href="{resource_id}.xml"/>
      <dependency identifierref="{dependency_id}"/>
    </resource>
  </resources>
</manifest>""")


def test_load_manifest_dependencies_reads_a_resources_dependency(tmp_path):
    _write_manifest_with_dependency(tmp_path, "g-disc", "g-meta")
    deps = render.load_manifest_dependencies(tmp_path)
    assert deps == {"g-disc": "g-meta"}


def test_load_manifest_dependencies_tolerates_a_missing_manifest(tmp_path):
    assert render.load_manifest_dependencies(tmp_path) == {}


def test_load_topic_meta_reads_position_and_type(tmp_path):
    (tmp_path / "g-meta.xml").write_text(f"""<?xml version="1.0"?>
<topicMeta xmlns="{CC_NS}">
  <position>7</position>
  <type>announcement</type>
</topicMeta>""")
    meta = render.load_topic_meta(tmp_path, "g-meta")
    assert meta == {"position": 7, "type": "announcement"}


def test_load_topic_meta_tolerates_a_missing_companion(tmp_path):
    assert render.load_topic_meta(tmp_path, "g-ghost") == {"position": None, "type": ""}


def _write_discussion(cartridge_dir, ident, title, text="<p>hi</p>"):
    IMSDT = "http://www.imsglobal.org/xsd/imsccv1p1/imsdt_v1p1"
    (cartridge_dir / f"{ident}.xml").write_text(f"""<?xml version="1.0"?>
<topic xmlns="{IMSDT}"><title>{title}</title><text texttype="text/html">{text}</text></topic>""")


def test_load_unlinked_discussions_finds_orphans_and_sorts_by_position(tmp_path):
    cart = tmp_path / "cart"
    cart.mkdir()
    _write_discussion(cart, "g-later", "Later Announcement")
    _write_discussion(cart, "g-earlier", "Earlier Announcement")
    (cart / "imsmanifest.xml").write_text(f"""<?xml version="1.0"?>
<manifest xmlns="{IMSCP_NS}">
  <resources>
    <resource identifier="g-later" type="imsdt_xmlv1p1">
      <file href="g-later.xml"/>
      <dependency identifierref="g-later-meta"/>
    </resource>
    <resource identifier="g-earlier" type="imsdt_xmlv1p1">
      <file href="g-earlier.xml"/>
      <dependency identifierref="g-earlier-meta"/>
    </resource>
    <resource identifier="g-linked" type="imsdt_xmlv1p1">
      <file href="g-linked.xml"/>
    </resource>
  </resources>
</manifest>""")
    (cart / "g-later-meta.xml").write_text(
        f'<topicMeta xmlns="{CC_NS}"><position>5</position><type>announcement</type></topicMeta>')
    (cart / "g-earlier-meta.xml").write_text(
        f'<topicMeta xmlns="{CC_NS}"><position>1</position><type>announcement</type></topicMeta>')
    course = {"sections": [{"items": [{"identifierref": "g-linked"}]}],
             "resources": {
                 "g-later": {"type": "imsdt_xmlv1p1", "href": "g-later.xml", "files": []},
                 "g-earlier": {"type": "imsdt_xmlv1p1", "href": "g-earlier.xml", "files": []},
                 "g-linked": {"type": "imsdt_xmlv1p1", "href": "g-linked.xml", "files": []},
             }}

    entries, gaps = render.load_unlinked_discussions(course, cart)

    assert gaps == []
    assert [e["title"] for e in entries] == ["Earlier Announcement", "Later Announcement"]


def test_load_unlinked_discussions_puts_undated_topics_after_positioned_ones(tmp_path):
    cart = tmp_path / "cart"
    cart.mkdir()
    _write_discussion(cart, "g-forum", "Standing Forum")
    _write_discussion(cart, "g-ann", "Dated Announcement")
    (cart / "imsmanifest.xml").write_text(f"""<?xml version="1.0"?>
<manifest xmlns="{IMSCP_NS}">
  <resources>
    <resource identifier="g-forum" type="imsdt_xmlv1p1"><file href="g-forum.xml"/></resource>
    <resource identifier="g-ann" type="imsdt_xmlv1p1">
      <file href="g-ann.xml"/><dependency identifierref="g-ann-meta"/>
    </resource>
  </resources>
</manifest>""")
    (cart / "g-ann-meta.xml").write_text(
        f'<topicMeta xmlns="{CC_NS}"><position>3</position><type>announcement</type></topicMeta>')
    course = {"sections": [], "resources": {
        "g-forum": {"type": "imsdt_xmlv1p1", "href": "g-forum.xml", "files": []},
        "g-ann": {"type": "imsdt_xmlv1p1", "href": "g-ann.xml", "files": []},
    }}

    entries, gaps = render.load_unlinked_discussions(course, cart)

    assert gaps == []
    assert [e["title"] for e in entries] == ["Dated Announcement", "Standing Forum"]


def test_render_unlinked_discussions_deduplicates_a_shared_title(tmp_path):
    entries = [{"ident": "g1", "title": "Reminder", "text_html": "<p>a</p>"},
              {"ident": "g2", "title": "Reminder", "text_html": "<p>b</p>"}]
    written = render.render_unlinked_discussions(entries, tmp_path, [])
    assert sorted(e["path"].name for e in written) == ["reminder-2.html", "reminder.html"]
    assert (tmp_path / "unlinked" / "discussions" / "reminder.html").read_text().count("<p>a</p>") == 1


def _write_assignment_resource(cartridge_dir, ident, title, html="<p>content</p>"):
    resdir = cartridge_dir / ident
    resdir.mkdir(parents=True)
    (resdir / "assignment_settings.xml").write_text(
        f'<assignment xmlns="{CC_NS}"><title>{title}</title>'
        "<points_possible>0</points_possible>"
        "<submission_types>online_text_entry</submission_types></assignment>")
    (resdir / f"{ident}.html").write_text(f"<html><body>{html}</body></html>")
    return {"type": "associatedcontent/imscc_xmlv1p1/learning-application-resource",
            "href": f"{ident}/{ident}.html",
            "files": [f"{ident}/{ident}.html", f"{ident}/assignment_settings.xml"]}


def test_find_unlinked_assignments_finds_a_real_assignment_and_skips_companions(tmp_path):
    cart = tmp_path / "cart"
    cart.mkdir()
    assignment_resource = _write_assignment_resource(cart, "g-real", "Mud Cards", "<p>Ask away</p>")
    (cart / "g-companion.xml").write_text(f'<topicMeta xmlns="{CC_NS}"><title>x</title></topicMeta>')
    course = {"sections": [], "resources": {
        "g-real": assignment_resource,
        "g-companion": {"type": "associatedcontent/imscc_xmlv1p1/learning-application-resource",
                        "href": None, "files": ["g-companion.xml"]},
        "g-txt": {"type": "associatedcontent/imscc_xmlv1p1/learning-application-resource",
                  "href": None, "files": ["course_settings/canvas_export.txt"]},
    }}

    entries = render.find_unlinked_assignments(course, cart)

    assert len(entries) == 1
    assert entries[0]["ident"] == "g-real"
    assert entries[0]["title"] == "Mud Cards"
    assert "Ask away" in entries[0]["content"]["html"]


def test_find_unlinked_assignments_skips_a_linked_assignment(tmp_path):
    cart = tmp_path / "cart"
    cart.mkdir()
    resource = _write_assignment_resource(cart, "g-linked", "Linked One")
    course = {"sections": [{"items": [{"identifierref": "g-linked"}]}],
             "resources": {"g-linked": resource}}
    assert render.find_unlinked_assignments(course, cart) == []


def test_render_unlinked_assignments_writes_via_render_assignment(tmp_path):
    entries = [{"ident": "g1", "title": "Mud Cards",
               "content": {"html": "<p>Ask a question</p>", "points_possible": 0.0,
                           "due_at": None, "submission_types": "online_text_entry"}}]
    gaps = []
    written = render.render_unlinked_assignments(entries, tmp_path, gaps)
    assert gaps == []
    out = written[0]["path"].read_text()
    assert "Ask a question" in out
    assert "Points:</strong> 0.0" in out


def test_render_unlinked_index_groups_by_category_and_skips_empty_ones():
    categories = [("Pages", "", [("pages/a.html", "A")]),
                  ("Assignments", "blurb here", [])]
    out = render.render_unlinked_index(categories, Path("/out"))
    assert "Pages (1)" in out
    assert "pages/a.html" in out
    assert "Assignments" not in out  # empty category skipped entirely


def test_clean_owned_output_removes_a_previous_run_but_not_build_or_source(tmp_path):
    (tmp_path / "sections" / "01-s").mkdir(parents=True)
    (tmp_path / "sections" / "01-s" / "index.html").write_text("stale")
    (tmp_path / "unlinked" / "pages").mkdir(parents=True)
    (tmp_path / "unlinked" / "pages" / "old.html").write_text("stale")
    (tmp_path / "index.html").write_text("stale")
    (tmp_path / "_build").mkdir()
    (tmp_path / "_build" / "course.json").write_text("{}")
    (tmp_path / "_source").mkdir()
    (tmp_path / "_source" / "keep.txt").write_text("keep")

    render.clean_owned_output(tmp_path)

    assert not (tmp_path / "sections").exists()
    assert not (tmp_path / "unlinked").exists()
    assert not (tmp_path / "index.html").exists()
    assert (tmp_path / "_build" / "course.json").exists()
    assert (tmp_path / "_source" / "keep.txt").exists()


def test_clean_owned_output_removes_directories_a_superseded_version_wrote(tmp_path):
    # Regression: an archive rendered by the version of this module that
    # wrote unlinked-pages/unlinked-assessments/unlinked-assignments/
    # unlinked-discussions/ as four separate top-level dirs (before they
    # were folded into one unlinked/ tree) must not leave that content
    # stranded once a newer version only owns "unlinked". Reads the retired
    # list itself, not a hardcoded copy of it -- so this test keeps proving
    # the guarantee even as more names are retired in the future.
    assert render.RETIRED_OWNED_TOP_LEVEL, "nothing to test -- add a retired name first"
    for legacy in render.RETIRED_OWNED_TOP_LEVEL:
        (tmp_path / legacy).mkdir()
        (tmp_path / legacy / "old.html").write_text("stale")

    render.clean_owned_output(tmp_path)

    for legacy in render.RETIRED_OWNED_TOP_LEVEL:
        assert not (tmp_path / legacy).exists()


def test_retired_top_level_names_are_folded_into_owned_top_level():
    # A name can only ever move from CURRENT_OWNED_TOP_LEVEL into
    # RETIRED_OWNED_TOP_LEVEL, never disappear from OWNED_TOP_LEVEL
    # entirely -- that's what makes the clean step immune to its own
    # renames. Also guards against ever *removing* a retired name outright,
    # which would silently reopen this exact bug.
    assert set(render.RETIRED_OWNED_TOP_LEVEL) <= set(render.OWNED_TOP_LEVEL)
    assert set(render.CURRENT_OWNED_TOP_LEVEL) <= set(render.OWNED_TOP_LEVEL)
    assert set(render.RETIRED_OWNED_TOP_LEVEL).isdisjoint(render.CURRENT_OWNED_TOP_LEVEL)


def test_clean_owned_output_is_a_no_op_on_a_directory_that_does_not_exist_yet(tmp_path):
    render.clean_owned_output(tmp_path / "does-not-exist")  # must not raise


def test_resolve_cross_reference_tokens_rewrites_a_resolved_wiki_reference(tmp_path):
    (tmp_path / "sections" / "01-s" / "pages").mkdir(parents=True)
    (tmp_path / "sections" / "02-t" / "pages").mkdir(parents=True)
    source = tmp_path / "sections" / "01-s" / "pages" / "a.html"
    target = tmp_path / "sections" / "02-t" / "pages" / "b.html"
    source.write_text('<a href="%24WIKI_REFERENCE%24/pages/b">B</a>')
    target.write_text("<h1>B</h1>")
    gaps = []

    fixed = render.resolve_cross_reference_tokens(
        tmp_path, {"identifierrefs": {}, "wiki_slugs": {"b": target}}, gaps)

    assert fixed == 1
    assert gaps == []
    out = source.read_text()
    assert "WIKI_REFERENCE" not in out
    assert 'href="../../02-t/pages/b.html"' in out


def test_resolve_cross_reference_tokens_strips_an_unresolvable_wiki_reference(tmp_path):
    (tmp_path / "sections" / "01-s" / "pages").mkdir(parents=True)
    source = tmp_path / "sections" / "01-s" / "pages" / "a.html"
    source.write_text('<a href="%24WIKI_REFERENCE%24/pages/ghost">Ghost</a>')
    gaps = []

    fixed = render.resolve_cross_reference_tokens(
        tmp_path, {"identifierrefs": {}, "wiki_slugs": {}}, gaps)

    assert fixed == 1
    out = source.read_text()
    assert "WIKI_REFERENCE" not in out
    assert "<a>Ghost</a>" in out
    assert gaps == [{"page": "sections/01-s/pages/a.html",
                     "token": "WIKI_REFERENCE", "target": "ghost"}]


def test_resolve_cross_reference_tokens_rewrites_an_object_reference(tmp_path):
    (tmp_path / "sections" / "01-s" / "pages").mkdir(parents=True)
    (tmp_path / "unlinked" / "assignments").mkdir(parents=True)
    source = tmp_path / "sections" / "01-s" / "pages" / "a.html"
    target = tmp_path / "unlinked" / "assignments" / "mud-cards.html"
    source.write_text('<a href="%24CANVAS_OBJECT_REFERENCE%24/assignments/g1">M</a>')
    target.write_text("<h1>M</h1>")
    gaps = []

    fixed = render.resolve_cross_reference_tokens(
        tmp_path, {"identifierrefs": {"g1": target}, "wiki_slugs": {}}, gaps)

    assert fixed == 1
    assert gaps == []
    assert 'href="../../../unlinked/assignments/mud-cards.html"' in source.read_text()


def test_resolve_cross_reference_tokens_strips_an_unresolvable_object_reference(tmp_path):
    (tmp_path / "sections" / "01-s" / "pages").mkdir(parents=True)
    source = tmp_path / "sections" / "01-s" / "pages" / "a.html"
    source.write_text('<a href="%24CANVAS_OBJECT_REFERENCE%24/quizzes/g-ghost">Q</a>')
    gaps = []

    fixed = render.resolve_cross_reference_tokens(
        tmp_path, {"identifierrefs": {}, "wiki_slugs": {}}, gaps)

    assert fixed == 1
    assert "CANVAS_OBJECT_REFERENCE" not in source.read_text()
    assert gaps[0]["target"] == "g-ghost"


def test_resolve_cross_reference_tokens_points_course_assignments_at_the_index(tmp_path):
    (tmp_path / "sections" / "01-s" / "pages").mkdir(parents=True)
    source = tmp_path / "sections" / "01-s" / "pages" / "a.html"
    source.write_text('<a href="%24CANVAS_COURSE_REFERENCE%24/assignments">A</a> '
                       '<a href="%24CANVAS_COURSE_REFERENCE%24/assignments/syllabus">S</a>')
    gaps = []

    fixed = render.resolve_cross_reference_tokens(
        tmp_path, {"identifierrefs": {}, "wiki_slugs": {}}, gaps)

    assert fixed == 1
    out = source.read_text()
    assert out.count('href="../../../index.html"') == 2
    assert gaps == []


def test_resolve_cross_reference_tokens_strips_an_unsupported_course_reference(tmp_path):
    (tmp_path / "sections" / "01-s" / "pages").mkdir(parents=True)
    source = tmp_path / "sections" / "01-s" / "pages" / "a.html"
    source.write_text('<a href="%24CANVAS_COURSE_REFERENCE%24/grades">G</a>')
    gaps = []

    fixed = render.resolve_cross_reference_tokens(
        tmp_path, {"identifierrefs": {}, "wiki_slugs": {}}, gaps)

    assert fixed == 1
    assert "CANVAS_COURSE_REFERENCE" not in source.read_text()
    assert gaps[0]["target"] == "grades"


def test_resolve_cross_reference_tokens_never_touches_source_or_build(tmp_path):
    (tmp_path / "_source" / "elucidat" / "M1").mkdir(parents=True)
    stale = tmp_path / "_source" / "elucidat" / "M1" / "01.html"
    original = '<a href="%24WIKI_REFERENCE%24/pages/ghost">G</a>'
    stale.write_text(original)
    (tmp_path / "_build").mkdir(parents=True)
    build_stale = tmp_path / "_build" / "course.json"
    build_stale.write_text(original)

    render.resolve_cross_reference_tokens(
        tmp_path, {"identifierrefs": {}, "wiki_slugs": {}}, [])

    assert stale.read_text() == original
    assert build_stale.read_text() == original


# ------------------------------------------------- full render_site (v2) --

def test_render_site_archives_every_kind_of_unlinked_content(tmp_path, monkeypatch):
    # A linked page and an unlinked ("orphan") wiki page, an orphan
    # assignment, and an orphan discussion, cross-referencing each other
    # (plus a self-reference that can't be resolved) -- exercising Findings
    # 1 and 2 end to end across all four unlinked content kinds.
    cart = tmp_path / "cart"
    (cart / "wiki_content").mkdir(parents=True)
    (cart / "wiki_content" / "help.html").write_text(
        '<html><head><title>Help</title>'
        '<meta name="identifier" content="g-help"/></head>'
        '<body><p>See <a href="%24WIKI_REFERENCE%24/pages/landing">Landing</a> and '
        '<a href="%24WIKI_REFERENCE%24/pages/ghost">Ghost</a>.</p></body></html>')
    resdir = cart / "g-assign"
    resdir.mkdir(parents=True)
    (resdir / "assignment_settings.xml").write_text(
        '<assignment xmlns="http://canvas.instructure.com/xsd/cccv1p0">'
        '<title>Orphan Task</title><points_possible>0</points_possible>'
        '<submission_types>none</submission_types></assignment>')
    (resdir / "orphan-task.html").write_text("<html><body><p>Do it</p></body></html>")
    IMSDT = "http://www.imsglobal.org/xsd/imsccv1p1/imsdt_v1p1"
    (cart / "g-disc.xml").write_text(
        f'<topic xmlns="{IMSDT}"><title>Orphan Announcement</title>'
        '<text texttype="text/html">&lt;p&gt;News&lt;/p&gt;</text></topic>')
    monkeypatch.setattr(render.constants, "CARTRIDGE_DIR", str(cart))

    item = {"title": "Landing", "content_type": "WikiPage", "kind": "page",
            "slug": "landing", "identifierref": "g-landing",
            "content": {"html": '<a href="%24CANVAS_OBJECT_REFERENCE%24/assignments/g-assign">'
                                'Orphan Task</a>'}}
    course = _course_with_items("01-homepage", [item])
    course["resources"] = {
        "g-assign": {"type": "associatedcontent/imscc_xmlv1p1/learning-application-resource",
                    "href": "g-assign/orphan-task.html",
                    "files": ["g-assign/orphan-task.html", "g-assign/assignment_settings.xml"]},
        "g-disc": {"type": "imsdt_xmlv1p1", "href": "g-disc.xml", "files": ["g-disc.xml"]},
    }
    build_dir = _write_build(tmp_path, course)
    out_dir = tmp_path / "out"

    stats = render.render_site(build_dir, out_dir)

    # Every kind of orphan got archived under unlinked/<kind>/.
    help_page = (out_dir / "unlinked" / "pages" / "help.html").read_text()
    assert 'href="../../sections/01-homepage/pages/landing.html"' in help_page
    assert "WIKI_REFERENCE" not in help_page
    assert any("ghost" in str(g) for g in stats["gap_details"])

    orphan_task = (out_dir / "unlinked" / "assignments" / "orphan-task.html").read_text()
    assert "Do it" in orphan_task
    orphan_disc = (out_dir / "unlinked" / "discussions" / "orphan-announcement.html").read_text()
    assert "News" in orphan_disc

    # The linked page's reference to the orphan assignment now resolves.
    landing_page = (out_dir / "sections" / "01-homepage" / "pages" / "landing.html").read_text()
    assert 'href="../../../unlinked/assignments/orphan-task.html"' in landing_page

    # Everything is reachable from the dedicated unlinked/index.html hub,
    # which the main index.html points at.
    unlinked_index = (out_dir / "unlinked" / "index.html").read_text()
    assert "pages/help.html" in unlinked_index
    assert "assignments/orphan-task.html" in unlinked_index
    assert "discussions/orphan-announcement.html" in unlinked_index
    index_html = (out_dir / "index.html").read_text()
    assert 'href="unlinked/index.html"' in index_html


def test_render_site_cleans_a_stale_file_from_a_previous_run(tmp_path):
    course = _course_with_items("01-homepage", [_assignment_item("Only Item")])
    build_dir = _write_build(tmp_path, course)
    out_dir = tmp_path / "out"
    (out_dir / "unlinked" / "pages").mkdir(parents=True)
    (out_dir / "unlinked" / "pages" / "leftover.html").write_text("stale from a since-fixed bug")

    render.render_site(build_dir, out_dir)

    assert not (out_dir / "unlinked" / "pages" / "leftover.html").exists()


@needs_cartridge
def test_load_wiki_pages_finds_twenty_three_real_pages_with_no_gaps():
    pages, gaps = render.load_wiki_pages(REAL_CARTRIDGE)
    assert len(pages) == 23
    assert gaps == []


def _real_course_json():
    path = Path(constants.OUTPUT_ROOT) / "_build" / "course.json"
    if not path.exists():
        pytest.skip("real _build/course.json not present")
    return json.loads(path.read_text())


@needs_cartridge
def test_load_unlinked_discussions_finds_thirty_one_real_orphans():
    entries, gaps = render.load_unlinked_discussions(_real_course_json(), REAL_CARTRIDGE)
    assert len(entries) == 31
    assert gaps == []
    # module-start announcements sort near the front by their real position
    titles = [e["title"] for e in entries]
    assert titles.index("Start of Module 1") < titles.index("Start of Module 6")
    assert titles.count("Reminder: Faculty Webinar - Professor Luis Perez Breva") == 4


@needs_cartridge
def test_find_unlinked_assignments_finds_two_real_orphans():
    entries = render.find_unlinked_assignments(_real_course_json(), REAL_CARTRIDGE)
    assert {e["title"] for e in entries} == {"Mud Cards", "Final Video Testimonial"}


@needs_cartridge
def test_render_site_real_render_has_zero_broken_relative_links(tmp_path, monkeypatch):
    monkeypatch.setattr(render.constants, "CARTRIDGE_DIR", str(REAL_CARTRIDGE))
    build_dir = Path(constants.OUTPUT_ROOT) / "_build"
    if not build_dir.exists():
        pytest.skip("real _build/ not present")
    out_dir = tmp_path / "out"

    stats = render.render_site(build_dir, out_dir)

    broken = 0
    href_re = __import__("re").compile(r'\b(?:href|src)="([^"]*)"')
    # _source/ and _build/ are archived raw material, not the delivered
    # site -- their HTML (the unmodified cartridge export under
    # _source/cartridge/, in particular) uses Canvas's own unresolved
    # $TOKEN$-style hrefs and was never meant to resolve as flat relative
    # links. Scoped the same way verify.find_broken_links scopes itself.
    for html_file in out_dir.rglob("*.html"):
        if html_file.relative_to(out_dir).parts[0] in ("_source", "_build"):
            continue
        text = html_file.read_text(encoding="utf-8", errors="replace")
        for match in href_re.finditer(text):
            value = match.group(1)
            if not value or value.startswith(("http://", "https://", "mailto:", "data:", "#")):
                continue
            target = value.split("#")[0].split("?")[0]
            if not target:
                continue
            import urllib.parse
            target = urllib.parse.unquote(target)
            if not (html_file.parent / target).resolve().exists():
                broken += 1
    assert broken == 0
    # Every unresolved cross-reference token is a recorded gap, not a dead link.
    assert stats["gaps"] == 12


# ------------------------------------------------- Finding 5: wiki slugs --

def test_register_wiki_slug_claims_a_fresh_slug():
    registry, gaps = {}, []
    render.register_wiki_slug(registry, "intro", Path("/out/a.html"), gaps, context="a")
    assert registry == {"intro": Path("/out/a.html")}
    assert gaps == []


def test_register_wiki_slug_poisons_a_second_claimant_and_records_a_gap():
    """Finding 5: a slug claimed by two different page-kind items must not
    silently resolve $WIKI_REFERENCE$ to whichever registered first -- the
    second claimant poisons the slug to None so the cross-reference
    resolver treats it as unresolved (strips the link, logs a gap) instead
    of serving the wrong page's content.
    """
    registry, gaps = {}, []
    render.register_wiki_slug(registry, "intro", Path("/out/a.html"), gaps, context="a")
    render.register_wiki_slug(registry, "intro", Path("/out/b.html"), gaps, context="b")

    assert registry["intro"] is None
    assert len(gaps) == 1
    assert gaps[0]["slug"] == "intro"
    assert gaps[0]["context"] == "b"


def test_register_wiki_slug_a_third_claimant_records_another_gap_not_a_crash():
    registry, gaps = {}, []
    render.register_wiki_slug(registry, "intro", Path("/out/a.html"), gaps, context="a")
    render.register_wiki_slug(registry, "intro", Path("/out/b.html"), gaps, context="b")
    render.register_wiki_slug(registry, "intro", Path("/out/c.html"), gaps, context="c")

    assert registry["intro"] is None
    assert len(gaps) == 2


def test_resolve_cross_reference_tokens_strips_a_link_to_a_poisoned_slug(tmp_path):
    (tmp_path / "sections" / "01-s" / "pages").mkdir(parents=True)
    page = tmp_path / "sections" / "01-s" / "pages" / "a.html"
    page.write_text('<a href="%24WIKI_REFERENCE%24/pages/intro">Intro</a>')
    gaps = []

    fixed = render.resolve_cross_reference_tokens(
        tmp_path, {"identifierrefs": {}, "wiki_slugs": {"intro": None}}, gaps)

    assert fixed == 1
    assert "WIKI_REFERENCE" not in page.read_text()
    assert any(g.get("token") == "WIKI_REFERENCE" for g in gaps)


# ------------------------------------------------ Finding 1: documents/ ---

DOCX_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _make_docx(path, paragraphs):
    import zipfile
    paras_xml = "".join(f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>" for text in paragraphs)
    document_xml = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                    f'<w:document xmlns:w="{DOCX_NS}"><w:body>{paras_xml}'
                    f"</w:body></w:document>")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", document_xml)
    return path


def test_extract_docx_text_reads_paragraphs_from_document_xml(tmp_path):
    docx = _make_docx(tmp_path / "spec.docx", ["Program Outline", "Course Title: X"])
    text = render.extract_docx_text(docx)
    assert "Program Outline" in text
    assert "Course Title: X" in text


def test_extract_docx_text_returns_none_for_a_corrupt_file(tmp_path):
    bad = tmp_path / "bad.docx"
    bad.write_text("not a zip at all")
    assert render.extract_docx_text(bad) is None


def test_extract_docx_text_returns_none_when_document_xml_is_missing(tmp_path):
    import zipfile
    empty = tmp_path / "empty.docx"
    with zipfile.ZipFile(empty, "w") as archive:
        archive.writestr("word/other.xml", "<x/>")
    assert render.extract_docx_text(empty) is None


def test_place_documents_copies_docx_and_writes_a_text_sibling(tmp_path):
    source = tmp_path / "gdrive" / "Program Outline.docx"
    _make_docx(source, ["Hello from the outline."])
    local = [{"path": str(source), "relpath": "Program Outline.docx", "ext": ".docx"}]
    out_dir = tmp_path / "out"

    entries = render.place_documents(local, out_dir)

    assert len(entries) == 1
    entry = entries[0]
    assert (out_dir / entry["docx"]).exists()
    assert (out_dir / entry["docx"]).suffix == ".docx"
    assert entry["text"] is not None
    assert "Hello from the outline." in (out_dir / entry["text"]).read_text()
    index = (out_dir / "documents" / "index.html").read_text()
    assert "Program Outline" in index
    assert ".docx" in index


def test_place_documents_still_links_the_docx_when_extraction_fails(tmp_path):
    source = tmp_path / "gdrive" / "Corrupt.docx"
    source.parent.mkdir(parents=True)
    source.write_text("not a real docx")
    local = [{"path": str(source), "relpath": "Corrupt.docx", "ext": ".docx"}]
    out_dir = tmp_path / "out"

    entries = render.place_documents(local, out_dir)

    assert len(entries) == 1
    assert entries[0]["text"] is None
    assert (out_dir / entries[0]["docx"]).exists()


def test_place_documents_returns_empty_when_local_has_no_docx(tmp_path):
    local = [{"path": "/x/a.pdf", "ext": ".pdf"}]
    assert render.place_documents(local, tmp_path / "out") == []
    assert not (tmp_path / "out" / "documents").exists()


def test_place_documents_deduplicates_a_title_collision(tmp_path):
    a = _make_docx(tmp_path / "a" / "Program Outline.docx", ["A"])
    b = _make_docx(tmp_path / "b" / "Program Outline.docx", ["B"])
    local = [{"path": str(a), "relpath": "a/Program Outline.docx", "ext": ".docx"},
             {"path": str(b), "relpath": "b/Program Outline.docx", "ext": ".docx"}]
    entries = render.place_documents(local, tmp_path / "out")
    names = sorted(Path(e["docx"]).name for e in entries)
    assert names == ["program-outline-2.docx", "program-outline.docx"]


# ------------------------------------------- Finding 2: MANIFEST.json -----

def test_build_manifest_has_every_top_level_section():
    ledger = {"files": [], "renditions": [], "online_only": []}
    manifest = render.build_manifest(ledger, [], captions=[], document_entries=[],
                                     campus_dir="/nonexistent")
    assert set(manifest) == {"files", "student_work", "screenflow_bundles",
                             "reference_note", "captions", "documents"}


def test_build_manifest_file_entry_carries_full_provenance():
    ledger = {"files": [{"canonical": "/x/a.mp4", "aliases": ["/x/a-copy.mp4"],
                        "sha256": "deadbeef", "size": 100}],
              "renditions": [], "online_only": []}
    local = [{"path": "/x/a.mp4", "source": "campus"}]

    manifest = render.build_manifest(ledger, local, captions=[], document_entries=[],
                                     campus_dir="/nonexistent")

    entry = manifest["files"][0]
    assert entry["canonical_path"] == "/x/a.mp4"
    assert entry["source"] == "campus"
    assert entry["sha256"] == "deadbeef"
    assert entry["size"] == 100
    assert entry["aliases"] == ["/x/a-copy.mp4"]
    assert "duplicate" in entry["reason"]
    assert entry["third_party"] is False


def test_build_manifest_tags_a_references_folder_video_as_third_party():
    ledger = {"files": [{"canonical": "/x/Module 1/references/Clip.mp4", "aliases": [],
                        "sha256": "abc", "size": 1}],
              "renditions": [], "online_only": []}
    manifest = render.build_manifest(ledger, [], captions=[], document_entries=[],
                                     campus_dir="/nonexistent")
    assert manifest["files"][0]["third_party"] is True


def test_build_manifest_records_a_rendition_match_reason():
    ledger = {"files": [{"canonical": "/x/a.mp4", "aliases": [], "sha256": "abc", "size": 1}],
              "renditions": [{"local_path": "/x/a.mp4", "canonical": "/vimeo/1 - a.mp4",
                             "vimeo_id": "1", "vimeo_path": "/vimeo/1 - a.mp4",
                             "vimeo_duration": 10.0, "local_duration": 10.0,
                             "reason": "vimeo copy is larger"}],
              "online_only": []}
    manifest = render.build_manifest(ledger, [], captions=[], document_entries=[],
                                     campus_dir="/nonexistent")
    match = manifest["files"][0]["rendition_match"]
    assert match["chosen"] == "/vimeo/1 - a.mp4"
    assert match["reason"] == "vimeo copy is larger"


def test_build_manifest_includes_an_online_only_vimeo_asset(tmp_path):
    video = tmp_path / "1 - solo.mp4"
    video.write_bytes(b"fake video bytes")
    ledger = {"files": [], "renditions": [],
              "online_only": [{"id": "1", "path": str(video), "size": 17}]}

    manifest = render.build_manifest(ledger, [], captions=[], document_entries=[],
                                     campus_dir="/nonexistent")

    entry = manifest["files"][0]
    assert entry["source"] == "vimeo"
    assert entry["original_url"] == "https://player.vimeo.com/video/1"
    assert entry["sha256"] is not None
    assert entry["third_party"] is True


def test_build_manifest_screenflow_bundles_are_path_and_size_only():
    local = [{"path": "/x/a.screenflow", "ext": ".screenflow", "size": 12345}]
    ledger = {"files": [], "renditions": [], "online_only": []}
    manifest = render.build_manifest(ledger, local, captions=[], document_entries=[],
                                     campus_dir="/nonexistent")
    assert manifest["screenflow_bundles"] == [{"path": "/x/a.screenflow", "size": 12345}]


def test_build_manifest_student_work_is_path_and_kind_only(tmp_path):
    bundle = tmp_path / "1682_x_submissions"
    bundle.mkdir()
    (bundle / "student_essay_text.html").write_text("SECRET STUDENT CONTENT")

    ledger = {"files": [], "renditions": [], "online_only": []}
    manifest = render.build_manifest(ledger, [], captions=[], document_entries=[],
                                     campus_dir=tmp_path)

    assert manifest["student_work"]
    for entry in manifest["student_work"]:
        assert set(entry) == {"path", "kind"}
        assert "SECRET" not in json.dumps(entry)


def test_build_manifest_keeps_captions_as_one_field_among_the_rest():
    ledger = {"files": [], "renditions": [], "online_only": []}
    captions = [{"video": "orientation/media/Talk.mp4", "caption_source": "whisper"}]
    manifest = render.build_manifest(ledger, [], captions=captions, document_entries=[],
                                     campus_dir="/nonexistent")
    assert manifest["captions"] == captions
    assert manifest["files"] == []  # captions must not have become the whole file


# ------------------------------------------------- _source/ copy-in ------

def test_archive_source_copies_copies_cartridge_and_provenance(tmp_path):
    cartridge = tmp_path / "cartridge"
    (cartridge / "web_resources").mkdir(parents=True)
    (cartridge / "imsmanifest.xml").write_text("<manifest/>")
    pdf = tmp_path / "provenance.pdf"
    pdf.write_bytes(b"%PDF-fake")
    out_dir = tmp_path / "out"
    gaps = []

    render.archive_source_copies(out_dir, gaps, cartridge_dir=cartridge, provenance_pdf=pdf)

    assert (out_dir / "_source" / "cartridge" / "imsmanifest.xml").exists()
    assert (out_dir / "_source" / "provenance" / "provenance.pdf").exists()
    assert gaps == []


def test_archive_source_copies_records_a_gap_for_a_missing_source(tmp_path):
    out_dir = tmp_path / "out"
    gaps = []
    render.archive_source_copies(out_dir, gaps,
                                 cartridge_dir=tmp_path / "no-such-cartridge",
                                 provenance_pdf=tmp_path / "no-such.pdf")
    assert len(gaps) == 2
    assert not (out_dir / "_source" / "cartridge").exists()
