import json
from pathlib import Path

from si_archive import elucidat

FIX = Path(__file__).parent / "fixtures" / "elucidat"


class FakeResponse:
    """Stand-in for requests.Response -- only .text/.content are used."""
    def __init__(self, text=None, content=None):
        self.text = text
        self.content = content if content is not None else (text or "").encode()


def _make_page_js(page_id, html):
    """Build `e._load_json({...})` text the way the real CDN serves a page."""
    payload = json.dumps({"page_id": page_id, "lmth": html[::-1]})
    return f"e._load_json({payload})"


def test_decode_lmth_reverses_the_string():
    assert elucidat.decode_lmth(">p/<olleh>p<") == "<p>hello</p>"


def test_parse_endpoint_finds_the_cdn_base():
    ep = elucidat.parse_endpoint(FIX.joinpath("shell.html").read_text())
    assert ep["cdn"].startswith("https://cdn.elucidat.com/")
    assert ep["js"].endswith(".js")


def test_parse_navigation_lists_every_page_with_names():
    nav = elucidat.parse_navigation(FIX.joinpath("nav_snippet.js").read_text())
    assert len(nav["pages"]) == 13
    assert nav["pages"]["5f73564484798"]["n"] == "Module 1."
    assert nav["url_format"].endswith("%s.js")


def test_page_order_puts_the_section_first_then_its_children():
    nav = elucidat.parse_navigation(FIX.joinpath("nav_snippet.js").read_text())
    order = elucidat.page_order(nav)
    assert order[0] == "5f73564484798"          # the section page
    assert len(order) == len(nav["pages"])
    assert len(set(order)) == len(order)        # no duplicates


def test_load_page_json_peels_the_wrapper_and_decodes():
    data = elucidat.load_page_json(FIX.joinpath("page.js").read_text())
    assert data["page_id"] == "5f735644979ac"
    html = elucidat.decode_lmth(data["lmth"])
    assert html.lstrip().startswith("<div")
    assert "How to Get Started Innovating" in html


def test_rewrite_assets_points_cdn_urls_at_local_files():
    html = '<img src="https://cdn.elucidat.com/x/media/abc.png">'
    out = elucidat.rewrite_assets(
        html, {"https://cdn.elucidat.com/x/media/abc.png": "assets/abc.png"})
    assert 'src="assets/abc.png"' in out
    assert "cdn.elucidat.com" not in out


def test_extract_vimeo_keeps_the_unlisted_hash():
    html = '<iframe src="https://player.vimeo.com/video/605462161?h=50187719bc"></iframe>'
    assert elucidat.extract_vimeo(html) == [("605462161", "50187719bc")]


def test_extract_vimeo_handles_a_bare_id():
    html = '<iframe src="https://player.vimeo.com/video/464955563"></iframe>'
    assert elucidat.extract_vimeo(html) == [("464955563", None)]


def test_page_order_matches_the_real_fixtures_flat_order_exactly():
    # Regression guard for the page_order rewrite: every child in the real
    # M1 nav points at the one (non-nested) section, in manifest order, so
    # the fixed function must still return exactly that order, unchanged.
    nav = elucidat.parse_navigation(FIX.joinpath("nav_snippet.js").read_text())
    assert elucidat.page_order(nav) == list(nav["pages"].keys())


def test_page_order_has_no_duplicate_when_a_section_is_nested_under_another():
    # B is itself a section (sec: true) but also names A as its parent (p) --
    # the dormant case the brief's "no duplicates" requirement covers.
    nav = {"pages": {
        "A": {"n": "Top", "sec": True},
        "B": {"n": "Nested", "sec": True, "p": "A"},
        "C": {"n": "Child of B", "p": "B"},
    }}
    order = elucidat.page_order(nav)
    assert order == ["A", "B", "C"]
    assert len(order) == len(set(order)) == 3


def test_asset_local_name_gives_distinct_names_to_distinct_urls_sharing_a_basename():
    claimed = {}
    first = elucidat._asset_local_name(
        "https://cdn.elucidat.com/proj/media/img.png", "img.png", claimed)
    second = elucidat._asset_local_name(
        "https://cdn.elucidat.com/proj/other/img.png", "img.png", claimed)
    assert first == "img.png"
    assert second != first
    assert second.endswith(".png")


def test_asset_local_name_is_stable_for_the_same_url_seen_twice():
    claimed = {}
    url = "https://cdn.elucidat.com/proj/media/img.png"
    first = elucidat._asset_local_name(url, "img.png", claimed)
    again = elucidat._asset_local_name(url, "img.png", claimed)
    assert first == again == "img.png"


def test_mirror_project_records_a_page_gap_and_still_mirrors_the_rest(tmp_path, monkeypatch):
    shell_text = FIX.joinpath("shell.html").read_text()
    endpoint = elucidat.parse_endpoint(shell_text)
    cdn, js = endpoint["cdn"], endpoint["js"]
    code = "test-code-123"
    shell_url = f"https://learning.elucidat.com/course/{code}"
    project_js_url = f"{cdn}/{js}"
    project_js_text = ('window.NAVIGATION_OBJECT={"pages":{'
                        '"p1":{"n":"Page One"},'
                        '"p2":{"n":"Page Two"},'
                        '"p3":{"n":"Page Three"}}};')
    pages_html = {"p1": "<p>one</p>", "p2": "<p>two</p>", "p3": "<p>three</p>"}

    def fake_get(url, throttle):
        if url == shell_url:
            return FakeResponse(text=shell_text)
        if url == project_js_url:
            return FakeResponse(text=project_js_text)
        if url == f"{cdn}/p2.js":
            raise RuntimeError("GET failed after 3 tries: " + url)
        for pid, html in pages_html.items():
            if url == f"{cdn}/{pid}.js":
                return FakeResponse(text=_make_page_js(pid, html))
        raise AssertionError(f"unexpected URL in test: {url}")

    monkeypatch.setattr(elucidat, "get", fake_get)

    result = elucidat.mirror_project("TEST", code, tmp_path, throttle=None)

    assert result["status"] == "ok"
    by_id = {p["id"]: p for p in result["pages"]}
    assert len(by_id) == 3
    assert by_id["p1"]["status"] == "ok"
    assert by_id["p3"]["status"] == "ok"
    assert by_id["p2"]["status"] == "gap"
    assert by_id["p2"]["error"]
    assert by_id["p2"]["file"] is None

    # The two good pages actually made it to disk; the bad one did not.
    assert (tmp_path / "TEST" / by_id["p1"]["slug"]).with_suffix(".html").exists()
    assert (tmp_path / "TEST" / by_id["p3"]["slug"]).with_suffix(".html").exists()
    assert not list((tmp_path / "TEST").glob("*p2*"))


def test_mirror_project_records_a_project_gap_when_the_shell_fetch_fails(tmp_path, monkeypatch):
    def fake_get(url, throttle):
        raise RuntimeError("GET failed after 3 tries: " + url)

    monkeypatch.setattr(elucidat, "get", fake_get)

    result = elucidat.mirror_project("TEST", "bad-code", tmp_path, throttle=None)

    assert result["status"] == "gap"
    assert result["error"]
    assert result["pages"] == []


def test_mirror_all_continues_past_a_project_level_gap(tmp_path, monkeypatch):
    monkeypatch.setattr(elucidat.constants, "ELUCIDAT_PROJECTS",
                         {"BAD": "bad-code", "GOOD": "good-code"})

    def fake_mirror_project(key, code, out_dir, throttle):
        if key == "BAD":
            return elucidat._project_gap(key, code, "boom")
        return {"key": key, "code": code, "status": "ok", "error": None,
                "title": "t", "cdn": "https://cdn.elucidat.com/x",
                "assets": [], "asset_gaps": [], "pages": []}

    monkeypatch.setattr(elucidat, "mirror_project", fake_mirror_project)

    result = elucidat.mirror_all(tmp_path, throttle=None)

    assert result["BAD"]["status"] == "gap"
    assert result["GOOD"]["status"] == "ok"
