from pathlib import Path

from si_archive import elucidat

FIX = Path(__file__).parent / "fixtures" / "elucidat"


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
