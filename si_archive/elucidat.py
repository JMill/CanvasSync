"""Stage 2 -- mirror the Elucidat projects to static, revealed HTML.

Elucidat serves a ~7KB SPA shell whose `var endpoint = {...}` points at a CDN
release directory. The project JS there carries window.NAVIGATION_OBJECT, a
complete page manifest. Each page is `e._load_json({... "lmth": ...})`, where
`lmth` is "html" backwards and its value is the page HTML with the character
order reversed -- light obfuscation, not encryption.

We bake each page to a standalone file rather than rehosting the player: the
player fetches page data by XHR, which is dead under file://, and reports to a
learning-record store that will not exist offline.
"""
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

from si_archive import constants
from si_archive.cartridge import slugify
from si_archive.net import get

ENDPOINT_RE = re.compile(r"var endpoint = (\{.*?\});", re.S)
NAV_RE = re.compile(r"window\.NAVIGATION_OBJECT\s*=\s*(\{.*?\})\s*;?\s*$", re.S | re.M)
CDN_ASSET_RE = re.compile(r"https://cdn\.elucidat\.com/[^\s\"'\\<>)]+")
VIMEO_RE = re.compile(r"https://(?:player\.)?vimeo\.com/(?:video/)?(\d+)(?:\?h=([0-9a-f]+))?")
TITLE_RE = re.compile(r"<title>(.*?)</title>", re.S)


def decode_lmth(reversed_html):
    """`lmth` is `html` backwards, and so is its value."""
    return reversed_html[::-1]


def parse_endpoint(shell_html):
    match = ENDPOINT_RE.search(shell_html)
    if not match:
        raise ValueError("no `var endpoint` block in shell HTML")
    return json.loads(match.group(1))


def parse_title(shell_html):
    match = TITLE_RE.search(shell_html)
    return match.group(1).strip() if match else ""


def parse_navigation(project_js):
    match = NAV_RE.search(project_js)
    if not match:
        raise ValueError("no window.NAVIGATION_OBJECT in project JS")
    return json.loads(match.group(1))


def page_order(nav):
    """Sections first, then their children, in manifest order.

    NAVIGATION_OBJECT preserves insertion order, and children carry a `p`
    pointing at their parent section. Reading order is: each section, then the
    children that name it, then any orphan.
    """
    pages = nav["pages"]
    sections = [pid for pid, meta in pages.items() if meta.get("sec")]
    order = []
    for section in sections:
        order.append(section)
        order.extend(pid for pid, meta in pages.items() if meta.get("p") == section)
    order.extend(pid for pid in pages if pid not in order)
    return order


def load_page_json(page_js):
    text = page_js.strip()
    return json.loads(text[text.index("(") + 1: text.rindex(")")])


def extract_vimeo(page_html):
    """Return [(id, hash_or_None)] preserving first-seen order."""
    seen, out = set(), []
    for vid, vhash in VIMEO_RE.findall(page_html):
        if vid not in seen:
            seen.add(vid)
            out.append((vid, vhash or None))
    return out


def rewrite_assets(page_html, asset_map):
    def swap(match):
        return asset_map.get(match.group(0), match.group(0))
    return CDN_ASSET_RE.sub(swap, page_html)


def mirror_project(key, code, out_dir, throttle):
    """Fetch one project: shell, project JS, every page, every CDN asset."""
    out_dir = Path(out_dir)
    pages_dir = out_dir / key
    assets_dir = pages_dir / "assets"
    raw_dir = out_dir / "_raw" / key
    for directory in (pages_dir, assets_dir, raw_dir):
        directory.mkdir(parents=True, exist_ok=True)

    shell = get(f"https://learning.elucidat.com/course/{code}", throttle).text
    (raw_dir / "shell.html").write_text(shell)
    endpoint = parse_endpoint(shell)
    title = parse_title(shell)
    cdn = endpoint["cdn"]

    project_js = get(f"{cdn}/{endpoint['js']}", throttle).text
    (raw_dir / "project.js").write_text(project_js)
    nav = parse_navigation(project_js)

    # Fetch every page first so raw data is safe on disk before any processing.
    raw_pages = {}
    for page_id in page_order(nav):
        page_js = get(f"{cdn}/{page_id}.js", throttle).text
        (raw_dir / f"{page_id}.js").write_text(page_js)
        raw_pages[page_id] = decode_lmth(load_page_json(page_js)["lmth"])

    # Collect and download assets once each, then rewrite every page against them.
    asset_map = {}
    for html in raw_pages.values():
        for url in CDN_ASSET_RE.findall(html):
            if url in asset_map:
                continue
            name = Path(urlsplit(url).path).name
            if not name:
                continue
            target = assets_dir / name
            if not target.exists():
                target.write_bytes(get(url, throttle).content)
            asset_map[url] = f"assets/{name}"

    records = []
    for position, page_id in enumerate(page_order(nav), start=1):
        meta = nav["pages"][page_id]
        name = meta.get("n") or page_id
        slug = f"{position:02d}-{slugify(name) or page_id}"
        html = rewrite_assets(raw_pages[page_id], asset_map)
        (pages_dir / f"{slug}.html").write_text(html)
        records.append({
            "id": page_id,
            "name": name,
            "slug": slug,
            "file": f"{key}/{slug}.html",
            "is_section": bool(meta.get("sec")),
            "vimeo": [{"id": v, "hash": h} for v, h in extract_vimeo(raw_pages[page_id])],
        })

    return {"key": key, "code": code, "title": title, "cdn": cdn,
            "assets": sorted(asset_map.values()), "pages": records}


def mirror_all(out_dir, throttle):
    projects = {}
    for key, code in constants.ELUCIDAT_PROJECTS.items():
        print(f"    {key}: {code}")
        projects[key] = mirror_project(key, code, out_dir, throttle)
        print(f"      {len(projects[key]['pages'])} pages, "
              f"{len(projects[key]['assets'])} assets")
    return projects
