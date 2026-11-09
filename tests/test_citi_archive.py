"""citi_archive parses CITI's server-rendered pages and must never submit a quiz.

Fixtures are synthetic but mirror the markup observed on citiprogram.org
(November 2026): course cards with POST forms, footable gradebook rows,
div.module-classic content with JS show/hide toggles, and a quiz form whose
option order is shuffled per render.
"""
import json

import pytest

import bin.citi_archive as citi

HOME = """
<div class="card"><strong>Social and Behavioral Human Subjects Research (IRB) Course</strong>
  <form action="/members/index.cfm?pageID=122#view" method="post" name="course">
    <input type="hidden" name="institutionID" value="1463">
    <input type="hidden" name="memberStageID" value="111">
    <input type="hidden" name="stageID" value="103494">
    <input type="hidden" name="groupID" value="40767">
    <input type="submit" name="submit" value="Start Now">
    <input type="hidden" name="__ncforminfo" value="TOKEN"></form></div>
<div class="card"><strong>Responsible Conduct of Research (RCR) - Basic</strong>
  <form action="/members/index.cfm?pageID=810#view" method="post" name="course">
    <input type="hidden" name="stageID" value="177812"></form>
  <form action="/members/index.cfm?pageID=147#view" method="post" name="completed">
    <input type="hidden" name="memberStageID" value="222">
    <input type="hidden" name="stageID" value="177812">
    <input type="submit" name="submit" value="Review Course"></form></div>
"""

GRADEBOOK = """
<h2>Required Modules</h2>
<table><tr><th>Modules</th><th>Completed</th><th>Score</th><th></th></tr>
<tr><td>Belmont Report and Its Principles (ID 1127)</td><td>Incomplete</td><td>-</td>
 <td><form action="/members/index.cfm?pageID=125#view" name="module" method="post">
   <input type="hidden" name="moduleID" value="1127">
   <input name="submit" type="submit" value="Start"></form></td></tr>
<tr><td>Pennsylvania State University (ID 13323)</td><td>Incomplete</td><td>-</td>
 <td><input type="button" value="Start" title="Complete Required modules in order." disabled=""></td></tr>
</table>
<h2>Elective Modules</h2>
<table>
<tr><td>Plagiarism (RCR-Basic) (ID 15156)</td><td>Optional</td><td>-</td>
 <td><form action="x?pageID=665" name="module"><input type="hidden" name="moduleID" value="15156">
   <input name="submit" type="submit" value="Start"></form></td></tr>
<tr><td>Authorship (RCR-Basic) (ID 16597)</td><td>27-Aug-2026</td><td>100%</td>
 <td><form action="x?pageID=665" name="module"><input type="hidden" name="moduleID" value="16597">
   <input name="submit" type="submit" value="Review"></form></td></tr>
</table>
"""

MODULE = """
<div class="module-classic-or-modern">Choose Audio-Visual</div>
<div class="module-classic">
 <h2>Authorship</h2>
 <ul><li><button type="button" onclick="showonlyone('newboxes1');" aria-controls="newboxes1">Watch: Authorship</button></li>
  <div name="newboxes" id="newboxes1" style=" display: none;">
   <iframe src="https://player.vimeo.com/video/123?title=0"></iframe></div></ul>
 <p><img src="/citidocuments/_001pic/554.jpg" width="300" height="200" onclick="zoom()"></p>
 <div class="vf-show3"><p><strong>Case: The Thesis Project</strong></p></div>
 <div class="vf3" style="display: none"><p>Mr. Palant, a graduate student...</p>
   <p><button type="button" aria-controls="newboxes5"><strong>How should it be handled?</strong></button></p>
   <div id="newboxes5" style="display:none"><p>Discard the first paper.</p></div></div>
 <p><a href="/citidocuments/_001pic/1127_the_belmont_report.pdf">Belmont Report</a>
    <a href="https://www.hhs.gov/ohrp/">OHRP</a> <a href="javascript:void(0)">x</a></p>
 <script>alert(1)</script>
</div>
<form action="/members/index.cfm?pageID=176&amp;ce=1#view" method="post" name="course">
 <input type="hidden" name="module" value="16597"><input type="submit" value="Take the Quiz"></form>
"""


def quiz_page(order, rowid):
    opts = {"1": "The first author.", "2": "The last author.",
            "3": "The most significant contributor.", "4": "The corresponding author."}
    radios = "".join(
        f'<div><input type="radio" value="{v}" id="Response{v}{rowid}" name="QuizAnswer{rowid}">'
        f'<label for="Response{v}{rowid}"> {opts[v]} </label></div>' for v in order)
    return f"""
<p>Quiz Instructions : Please provide an answer for all questions. Each question is one point.</p>
<form action="/members/index.cfm?pageID=177&amp;ce=1#view" method="post" name="quiz" id="quiz">
  <h3 class="new-heading">Question 1</h3>
  <p class="quiz-question">Which author is normally responsible for sharing reprints?</p>
  <fieldset class="compact-form">{radios}</fieldset>
  <h3 class="new-heading">Question 2</h3>
  <p class="quiz-question">Select every responsibility of each author.</p>
  <fieldset><div><input type="checkbox" value="1" id="a{rowid}" name="QuizAnswer{rowid + 1}">
    <label for="a{rowid}">Confirming the data.</label></div></fieldset>
  <input type="hidden" name="intExamID" value="486216981">
  <input type="submit" name="submit" value="Submit">
</form>"""


def test_parse_courses_titles_status_and_skips_survey_form():
    courses = citi.parse_courses(HOME)
    assert [(c["stage_id"], c["status"]) for c in courses] == [
        ("103494", "open"), ("177812", "completed")]
    assert courses[0]["title"] == "Social and Behavioral Human Subjects Research (IRB) Course"
    assert courses[1]["title"] == "Responsible Conduct of Research (RCR) - Basic"


def test_parse_gradebook_sections_locks_and_completion():
    rows = {r["module_id"]: r for r in citi.parse_gradebook(GRADEBOOK)}
    assert rows["1127"]["section"] == "Required" and rows["1127"]["action"] == "Start"
    assert rows["13323"]["action"] is None
    assert rows["13323"]["locked_reason"] == "Complete Required modules in order."
    # "Optional" in the Completed column is not a completion date.
    assert rows["15156"]["section"] == "Elective" and rows["15156"]["completed"] is None
    assert rows["16597"]["completed"] == "27-Aug-2026" and rows["16597"]["score"] == "100%"
    assert rows["16597"]["title"] == "Authorship (RCR-Basic)"


def test_parse_module_and_assets():
    mod = citi.parse_module(MODULE)
    assert mod["title"] == "Authorship" and mod["has_quiz"]
    assert "Choose Audio-Visual" not in mod["content_html"]
    assert citi.asset_refs(mod["content_html"]) == [
        "/citidocuments/_001pic/554.jpg", "/citidocuments/_001pic/1127_the_belmont_report.pdf"]


def test_clean_content_reveals_toggles_and_neutralises_scripts():
    mod = citi.parse_module(MODULE)
    out = citi.clean_content(mod["content_html"], lambda p: "assets/" + p.rsplit("/", 1)[1])
    assert out.count("<details>") == 3
    assert "<summary>Watch: Authorship</summary>" in out
    assert "<summary><strong>How should it be handled?</strong></summary>" in out
    assert "Case: The Thesis Project" in out and "Discard the first paper." in out
    assert "display" not in out
    for bad in ("<script", "onclick", "<iframe", "<button", "<form", "javascript:"):
        assert bad not in out
    assert 'class="video-link"' in out and "vimeo.com/video/123" in out
    assert 'src="assets/554.jpg"' in out and 'width="300"' not in out
    assert 'href="assets/1127_the_belmont_report.pdf"' in out
    assert 'href="https://www.hhs.gov/ohrp/"' in out


def test_parse_quiz_sorts_shuffled_options_by_value():
    a = citi.parse_quiz(quiz_page(["2", "1", "4", "3"], 2126914069))
    b = citi.parse_quiz(quiz_page(["4", "3", "1", "2"], 2126914637))
    assert "Each question is one point" in a["instructions"]
    qa, qb = a["questions"][0], b["questions"][0]
    assert [o["value"] for o in qa["options"]] == ["1", "2", "3", "4"]
    assert qa["options"] == qb["options"]
    assert qa["text"] == "Which author is normally responsible for sharing reprints?"
    # Field names differ per attempt; the key must not.
    assert qa["key"] == qb["key"]
    assert a["questions"][1]["multi"] is True and not qa["multi"]


def test_merge_quiz_unions_by_text_and_keeps_answer_keys():
    old = citi.parse_quiz(quiz_page(["1", "2", "3", "4"], 10))
    old["questions"][0]["correct"] = ["4"]
    new = citi.parse_quiz(quiz_page(["3", "1", "2", "4"], 99))
    new["questions"].append({"key": "zzz", "text": "A pool question", "options": []})
    merged = citi.merge_quiz(old, new)
    assert merged["questions"][-1]["text"] == "A pool question"
    assert len(merged["questions"]) == 3
    assert merged["questions"][0]["correct"] == ["4"]
    assert merged["questions"][0]["times_seen"] == 2


class FakeLocator:
    def __init__(self, attrs, clicks):
        self.attrs, self.clicks = attrs, clicks

    @property
    def first(self):
        return self

    def count(self):
        return 1

    def get_attribute(self, name):
        return self.attrs.get(name)

    def locator(self, _sel):
        return self

    def click(self):
        self.clicks.append(self.attrs)


class FakePage:
    url = "https://www.citiprogram.org/members/index.cfm?pageID=176"

    def __init__(self, attrs):
        self.clicks = []
        self.attrs = attrs

    def locator(self, _sel):
        return FakeLocator(self.attrs, self.clicks)


class NoWait:
    def wait(self, _url):
        pass


@pytest.mark.parametrize("attrs", [
    {"action": "/members/index.cfm?pageID=177&ce=1&intStageID=1#view", "name": "x"},
    {"action": "/members/index.cfm?pageID=999", "name": "quiz"},
])
def test_click_form_refuses_quiz_submission(attrs):
    page = FakePage(attrs)
    with pytest.raises(citi.RefusedSubmit):
        citi.click_form(page, "form", NoWait())
    assert page.clicks == []


def test_quiz_submit_pattern_does_not_catch_other_pages():
    assert not citi.QUIZ_SUBMIT_RE.search("index.cfm?pageID=1770")
    assert not citi.QUIZ_SUBMIT_RE.search("index.cfm?pageID=176&ce=1")
    assert citi.QUIZ_SUBMIT_RE.search("index.cfm?pageID=177#view")


def test_build_site_renders_self_contained_course(tmp_path):
    cdir = tmp_path / "IRB"
    (cdir / "modules").mkdir(parents=True)
    (cdir / "assets").mkdir()
    (cdir / "course.json").write_text(json.dumps({
        "title": "IRB", "updated_at": "2026-11-09T12:00:00+00:00",
        "gradebook": citi.parse_gradebook(GRADEBOOK)}))
    mod = citi.parse_module(MODULE)
    quiz = citi.parse_quiz(quiz_page(["2", "1", "4", "3"], 5))
    (cdir / "modules" / "1127.json").write_text(json.dumps({
        "module_id": "1127", "title": "Belmont", "section": "Required",
        "content_html": mod["content_html"], "has_quiz": True, "quiz": quiz,
        "fetched_at": "2026-11-09T12:00:00+00:00"}))
    img = "/citidocuments/_001pic/554.jpg"
    (cdir / "assets" / citi.asset_filename(img)).write_bytes(b"\xff\xd8jpeg")

    summary = citi.build_site(tmp_path)

    assert summary == [{"slug": "IRB", "title": "IRB", "archived": 1, "total": 4,
                        "needs_attestation": False}]
    page = (tmp_path / "IRB.html").read_text()
    assert "data:image/jpeg;base64," in page
    assert "Which author is normally responsible for sharing reprints?" in page
    assert "Complete Required modules in order." in page  # locked module listed, not hidden
    assert "Answers aren't included" in page
    assert (tmp_path / "index.html").is_file()


# --- Regressions for confirmed review findings -----------------------------

def test_parse_courses_does_not_borrow_a_neighbouring_cards_title():
    html = """<div class=list>
      <div><strong>Course A</strong><form action="x?pageID=122"><input type=hidden name=stageID value=1>
        <input type=submit></form></div>
      <div><h3>Course B</h3><form action="x?pageID=122"><input type=hidden name=stageID value=2>
        <input type=submit></form></div>
      <div><form action="x?pageID=147"><input type=hidden name=stageID value=3><input type=submit></form></div>
    </div>"""
    assert [c["title"] for c in citi.parse_courses(html)] == ["Course A", "Course B", "Course 3"]


def test_course_dirs_are_unique_per_stage_even_with_equal_titles():
    a = citi.course_dir_name({"title": "Same Course", "stage_id": "1"})
    b = citi.course_dir_name({"title": "Same Course", "stage_id": "2"})
    assert a != b and a.endswith("_1")


def test_question_key_separates_generic_stems_with_different_options():
    assert citi.question_key("Which of the following is true?", ["a", "b"]) != \
        citi.question_key("Which of the following is true?", ["c", "d"])
    assert citi.question_key("Q?", ["b", "a"]) == citi.question_key("q", ["A", "B"])


def test_merge_quiz_never_shrinks_stored_questions():
    dup = {"key": "k", "text": "same", "options": []}
    old = {"questions": [dict(dup), dict(dup, text="other but colliding")]}
    merged = citi.merge_quiz(old, {"questions": [dict(dup)]})
    assert len(merged["questions"]) == 2


def test_merge_gradebook_keeps_rows_a_partial_parse_dropped():
    old = [{"module_id": "1", "title": "A"}, {"module_id": "2", "title": "B"}]
    new = [{"module_id": "1", "title": "A2"}]
    rows = citi.merge_gradebook(old, new)
    assert [r["module_id"] for r in rows] == ["1", "2"]
    assert rows[0]["title"] == "A2" and rows[1]["stale"] is True


def test_render_course_shows_archived_modules_missing_from_gradebook():
    course = {"title": "C", "gradebook": []}
    mods = [{"module_id": "9", "title": "Orphan", "content_html":
             "<div class='module-classic'><p>kept text</p></div>", "fetched_at": ""}]
    page = citi.render_course(course, mods, lambda p: None)
    assert "kept text" in page and "Other archived modules" in page


@pytest.mark.parametrize("bad", [
    '<a href="JaVaScRiPt:alert(1)">x</a>',
    '<a href="java\tscript:alert(1)">x</a>',
    '<img src="javascript:alert(1)">',
    '<iframe src="javascript:alert(1)"></iframe>',
    '<iframe srcdoc="<script>alert(1)</script>"></iframe>',
    '<object data="javascript:alert(1)"></object>',
    '<embed src="x.swf">',
    '<svg><a xlink:href="javascript:alert(1)">x</a></svg>',
    '<base href="javascript:alert(1)//">',
    '<p style="background:url(javascript:alert(1))">x</p>',
    '<a href="data:text/html,<script>alert(1)</script>">x</a>',
])
def test_clean_content_drops_active_urls(bad):
    out = citi.clean_content(f"<div class='module-classic'>{bad}</div>", lambda p: None).lower()
    for needle in ("javascript", "<script", "srcdoc", "<object", "<embed", "<base", "data:text"):
        assert needle not in out


def test_safe_url_allows_ordinary_links_and_inline_images():
    assert citi.safe_url("https://x.org/a") == "https://x.org/a"
    assert citi.safe_url("/citidocuments/a.pdf") == "/citidocuments/a.pdf"
    assert citi.safe_url("data:image/png;base64,AAAA", allow_data_image=True)
    assert citi.safe_url("data:image/svg+xml,<svg onload=1>", allow_data_image=True) is None


def test_quiz_question_html_is_cleaned_and_its_images_resolved():
    quiz = {"questions": [{"key": "k", "text": "Which image?", "options": [],
                           "text_html": '<p onclick="x()">Which image?</p>'
                                        '<img src="/citidocuments/_001pic/q1.jpg"><script>bad()</script>'}]}
    out = citi.render_quiz(quiz, lambda p: "data:image/jpeg;base64,QQ==" if p.endswith("q1.jpg") else None)
    assert "onclick" not in out and "<script" not in out
    assert 'src="data:image/jpeg;base64,QQ=="' in out
    assert citi.CitiArchiver.record_assets({"content_html": "", "quiz": quiz}) == \
        ["/citidocuments/_001pic/q1.jpg"]


def test_click_form_refuses_form_identified_as_quiz_by_id():
    page = FakePage({"action": "/members/index.cfm?pageID=999", "name": "x", "id": "quiz"})
    with pytest.raises(citi.RefusedSubmit):
        citi.click_form(page, "form", NoWait())
    assert page.clicks == []


class FakeResp:
    def __init__(self, status=200, url="https://www.citiprogram.org/citidocuments/a.jpg",
                 ctype="image/jpeg", body=b"img"):
        self.status, self.url, self._body = status, url, body
        self.headers = {"content-type": ctype}

    def body(self):
        return self._body


class FakeCtx:
    def __init__(self, resp):
        self.request = self
        self.resp = resp

    def get(self, _url, timeout=None):
        return self.resp


class PacedThrottle(NoWait):
    def __init__(self):
        self.fed = []

    def pushback(self, resp):
        self.fed.append(resp.status_code)
        return 0


def archiver_with(resp, tmp_path):
    th = PacedThrottle()
    return citi.CitiArchiver(None, FakeCtx(resp), tmp_path, "1463", th), th


def test_fetch_asset_treats_login_redirect_as_dead_session(tmp_path):
    arch, _ = archiver_with(FakeResp(url="https://www.citiprogram.org/index.cfm?pageID=14",
                                     ctype="text/html"), tmp_path)
    dest = tmp_path / "a.jpg"
    with pytest.raises(citi.SessionEnded):
        arch.fetch_asset("/citidocuments/a.jpg", dest)
    assert not dest.exists()


def test_fetch_asset_refuses_html_in_place_of_an_image(tmp_path):
    arch, th = archiver_with(FakeResp(ctype="text/html; charset=utf-8"), tmp_path)
    dest = tmp_path / "a.jpg"
    assert arch.fetch_asset("/citidocuments/a.jpg", dest) is False
    assert not dest.exists() and th.fed == [200]


def test_fetch_asset_saves_and_feeds_pushback(tmp_path):
    arch, th = archiver_with(FakeResp(), tmp_path)
    dest = tmp_path / "x" / "a.jpg"
    assert arch.fetch_asset("/citidocuments/a.jpg", dest) is True
    assert dest.read_bytes() == b"img" and th.fed == [200]


def test_click_form_refuses_the_integrity_attestation():
    page = FakePage({"action": "/members/index.cfm?pageID=121&intStageID=120968#view", "name": "CFForm_1"})
    with pytest.raises(citi.RefusedSubmit):
        citi.click_form(page, "form", NoWait())
    assert page.clicks == []


def test_inline_image_downscales_wide_photos_and_caches(tmp_path):
    from PIL import Image
    import base64 as b64
    import io
    src = tmp_path / "big.jpg"
    Image.effect_noise((3000, 2000), 80).convert("RGB").save(src, "JPEG", quality=95)
    uri = citi.inline_image(src, tmp_path / "_inline")
    assert uri.startswith("data:image/jpeg;base64,")
    im = Image.open(io.BytesIO(b64.b64decode(uri.split(",", 1)[1])))
    assert im.width == citi.INLINE_MAX_WIDTH and len(uri) < src.stat().st_size
    assert citi.inline_image(src, tmp_path / "_inline") == uri  # cache hit, identical


def test_inline_image_leaves_small_images_alone(tmp_path):
    from PIL import Image
    src = tmp_path / "icon.png"
    Image.new("RGBA", (40, 40), (255, 0, 0, 128)).save(src, "PNG")
    uri = citi.inline_image(src, tmp_path / "_inline")
    import base64 as b64
    assert b64.b64decode(uri.split(",", 1)[1]) == src.read_bytes()


def test_asset_refs_cover_every_citi_image_root():
    html = ("<div class='module-classic'><img src='/images/Module2/a.jpg'>"
            "<img src='https://www.citiprogram.org/members/images/case-study.png'>"
            "<img src='/citidocuments/_001pic/1.jpg'><img src='https://other.org/x.jpg'></div>")
    assert citi.asset_refs(html) == ["/images/Module2/a.jpg", "/members/images/case-study.png",
                                     "/citidocuments/_001pic/1.jpg"]


def test_merge_quiz_rekeys_records_saved_under_an_old_key_formula():
    fresh = citi.parse_quiz(quiz_page(["1", "2", "3", "4"], 1))
    legacy = {"questions": [dict(q, key="old-format-" + str(i))
                            for i, q in enumerate(fresh["questions"])]}
    merged = citi.merge_quiz(legacy, citi.parse_quiz(quiz_page(["4", "2", "1", "3"], 2)))
    assert len(merged["questions"]) == len(fresh["questions"])


def test_session_ended_is_not_a_local_permission_error():
    assert not issubclass(citi.SessionEnded, PermissionError)
    assert not issubclass(PermissionError, citi.SessionEnded)


class RateLimitedPage:
    url = "https://www.citiprogram.org/members/index.cfm?pageID=50"

    def goto(self, *_a, **_k):
        class R:
            status, headers = 429, {}
        return R()


class NapFreeThrottle(NoWait):
    def pushback(self, resp):
        return 0  # status still 429, so obey_pushback reports pushback without sleeping


def test_persistent_rate_limit_is_not_reported_as_logged_out(tmp_path):
    arch = citi.CitiArchiver(RateLimitedPage(), None, tmp_path, "1463", NapFreeThrottle())
    with pytest.raises(RuntimeError) as e:
        arch.go_home()
    assert not isinstance(e.value, citi.SessionEnded) and "rate limit" in str(e.value)


def test_course_dir_reuses_existing_folder_for_the_stage(tmp_path):
    old = tmp_path / "Old_Title_42"
    old.mkdir()
    (old / "course.json").write_text("{}")
    arch = citi.CitiArchiver(None, None, tmp_path, "1463", NoWait())
    assert arch.course_dir({"title": "Renamed Course", "stage_id": "42"}) == old
    assert arch.course_dir({"title": "Other", "stage_id": "7"}).name == "Other_7"


def test_clean_content_drops_svg_animation_that_rewrites_href():
    bad = ('<svg><a><animate attributeName="href" values="javascript:alert(1)"/>'
           '<set attributeName="xlink:href" to="javascript:alert(1)"/><text>x</text></a></svg>')
    out = citi.clean_content(f"<div class='module-classic'>{bad}</div>", lambda p: None).lower()
    assert "javascript" not in out and "<animate" not in out and "<set" not in out


def _shrunk(tmp_path, im, name, **save):
    from PIL import Image  # noqa: F401
    import base64 as b64
    import io
    from PIL import Image as I
    src = tmp_path / name
    im.save(src, **save)
    uri = citi.inline_image(src, tmp_path / "_inline")
    return src, I.open(io.BytesIO(b64.b64decode(uri.split(",", 1)[1]))), uri


def test_shrink_respects_exif_orientation(tmp_path):
    from PIL import Image
    im = Image.effect_noise((3000, 1500), 80).convert("RGB")
    exif = Image.Exif()
    exif[0x0112] = 6  # rotate 90 CW on display
    _, out, _ = _shrunk(tmp_path, im, "rot.jpg", format="JPEG", quality=95, exif=exif)
    assert out.height > out.width  # displayed portrait, as the viewer would see it


def test_shrink_keeps_colour_keyed_transparency_as_png(tmp_path):
    from PIL import Image
    im = Image.effect_noise((2000, 1000), 80).convert("RGB")
    _, out, uri = _shrunk(tmp_path, im, "key.png", format="PNG", transparency=(0, 0, 0))
    assert uri.startswith("data:image/png")


def test_shrink_leaves_16bit_grey_untouched(tmp_path):
    from PIL import Image
    im = Image.linear_gradient("L").resize((2000, 2000)).convert("I;16")
    src, out, _ = _shrunk(tmp_path, im, "g16.png", format="PNG")
    import base64 as b64
    assert out.mode.startswith("I")  # original bytes, not a saturated JPEG


@pytest.mark.parametrize("payload", [
    "<p>a<!-- x --!><img src=x onerror=alert(1)> --></p>",
    "<p><!--><img src=x onerror=alert(1)>--></p>",
    "<p><!---><img src=x onerror=alert(1)>--></p>",
    '<xmp><p title="</xmp><img src=x onerror=alert(1)>"></xmp>',
    '<noembed><p title="</noembed><img src=x onerror=alert(1)>"></noembed>',
    '<textarea><p title="</textarea><img src=x onerror=alert(1)>"></textarea>',
    '<noframes><p title="</noframes><img src=x onerror=alert(1)>"></noframes>',
    '<svg><![CDATA[><img src=x onerror=alert(1)>]]></svg>',
    '<![CDATA[><img src=x onerror=alert(1)>]]>',
    '<?xml ><img src=x onerror=alert(1)>?>',
    '<!DOCTYPE x><template><img src=x onerror=alert(1)></template>',
])
def test_clean_content_survives_parser_differentials(payload):
    # Judge the output the way a browser-like parser builds it, not by string
    # search: no element may carry an event handler, and no script may exist.
    import lxml.html
    out = citi.clean_content(f"<div class='module-classic'>{payload}<p>keep</p></div>",
                             lambda p: None)
    tree = lxml.html.fromstring(f"<div>{out}</div>")
    for el in tree.iter():
        if not isinstance(el.tag, str):
            continue
        assert el.tag not in ("script", "iframe", "object", "embed")
        assert not [a for a in el.attrib if a.lower().startswith("on")], out
    assert "<!--" not in out and "CDATA" not in out and "keep" in out
