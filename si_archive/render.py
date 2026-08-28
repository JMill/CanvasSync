"""Stage 7 -- emit the static site.

Section order and numbering come from the cartridge, not from Elucidat: the
cartridge's 16 sections are the course as actually taught, including the
surveys and the three-way split of Module 1.

One page per module item, grouped by kind under its section:

    sections/<dirname>/index.html                      depth 2
    sections/<dirname>/pages/<slug>.html                depth 3
    sections/<dirname>/assignments/<slug>.html          depth 3
    sections/<dirname>/discussions/<slug>.html          depth 3
    sections/<dirname>/quizzes/<slug>.html              depth 3
    sections/<dirname>/other/<slug>.html                depth 3 (external_tool, etc.)
    sections/<dirname>/elucidat/<slug>.html             depth 3 (mirrored Elucidat pages)

Elucidat placement is derived at runtime by scanning each item's HTML for an
`elucidat.com/course/<code>` reference and matching it against
constants.ELUCIDAT_PROJECTS, rather than trusting a hardcoded table that
would silently rot if the cartridge is ever re-exported.

Every file write, source read and JSON parse in this module is guarded: a
missing asset, an unreadable page or a malformed record is recorded as a gap
and rendering continues -- never abort the run over one bad item.
"""
import html as html_mod
import json
import re
import shutil
from pathlib import Path
from xml.etree import ElementTree as ET

from si_archive import constants
from si_archive.cartridge import slugify

FILEBASE_RE = re.compile(r"%24IMS-CC-FILEBASE%24(/[^\"'\s>]*)")
CANVAS_QS_RE = re.compile(r"\?(?:canvas_|amp;canvas_)[^\"'\s>]*")
ELUCIDAT_CODE_RE = re.compile(r"elucidat\.com/course/([a-f0-9-]+)")
ELUCIDAT_IFRAME_RE = re.compile(r"<iframe[^>]*elucidat\.com[^>]*>.*?</iframe>", re.I | re.S)

QTI = "{http://www.imsglobal.org/xsd/ims_qtiasiv1p2}"

KIND_SUBDIR = {"page": "pages", "assignment": "assignments",
               "discussion": "discussions", "quiz": "quizzes"}
KIND_LABEL = {"page": "Pages", "assignment": "Assignments", "discussion": "Discussions",
              "quiz": "Quizzes", "external_tool": "External tools",
              "unresolved": "Unresolved", "other": "Other"}

SHELL = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<link rel="stylesheet" href="{prefix}reveal.css">
</head>
<body>
{nav}
<main>
{body}
</main>
</body>
</html>
"""


# ---------------------------------------------------------------- helpers --

def strip_canvas_query(url):
    return CANVAS_QS_RE.sub("", url)


def rewrite_filebase(page_html, depth):
    """`$IMS-CC-FILEBASE$/x.png?canvas_download=1` -> `../../files/x.png`."""
    prefix = "../" * depth

    def swap(match):
        return f"{prefix}files{strip_canvas_query(match.group(1))}"
    return FILEBASE_RE.sub(swap, page_html)


def page_shell(title, body, depth, nav_html=""):
    return SHELL.format(title=html_mod.escape(title), body=body,
                         nav=nav_html, prefix="../" * depth)


def unique_filename(seen, base):
    """Per-directory de-dup counter, exactly as `build_course` suffixes
    `dirname` -- slugs are not guaranteed unique, and a silent collision
    would clobber one item's page with another's.
    """
    base = base or "item"
    seen[base] = seen.get(base, 0) + 1
    n = seen[base]
    return base if n == 1 else f"{base}-{n}"


def _load_json_safe(path, default):
    """Read and parse a JSON file that may not exist or may be mid-write by
    another stage; never raises."""
    try:
        return json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError):
        return default


# --------------------------------------------------------- item rendering --

def render_quiz(quiz):
    """Surveys render as questionnaires -- no 'correct' answer is asserted."""
    parts = [f"<h1>{html_mod.escape(quiz.get('title', ''))}</h1>",
             quiz.get("description_html") or ""]
    if quiz.get("is_survey"):
        parts.append("<p><em>This is a survey. No answer is scored as correct.</em></p>")
    for question in quiz.get("questions") or []:
        parts.append(f"<h3>{html_mod.escape(question.get('title', ''))}</h3>")
        parts.append(question.get("prompt_html") or "")
        if question.get("options"):
            items = "".join(
                f"<li>{html_mod.escape(o)}</li>" for o in question["options"])
            parts.append(f"<ol>{items}</ol>")
        if question.get("correct") and not quiz.get("is_survey"):
            parts.append(
                f"<p><strong>Correct:</strong> "
                f"{html_mod.escape(question['correct'])}</p>")
    return "\n".join(parts)


def render_wiki_page(item):
    content = item.get("content") or {}
    return (f"<h1>{html_mod.escape(item.get('title', ''))}</h1>\n"
            f"{content.get('html') or ''}")


def render_assignment(item):
    content = item.get("content") or {}
    parts = [f"<h1>{html_mod.escape(item.get('title', ''))}</h1>"]
    meta = []
    if content.get("points_possible") is not None:
        meta.append(f"<li><strong>Points:</strong> {content['points_possible']}</li>")
    if content.get("due_at"):
        meta.append(f"<li><strong>Due:</strong> {html_mod.escape(content['due_at'])}</li>")
    if content.get("submission_types"):
        meta.append("<li><strong>Submission type:</strong> "
                     f"{html_mod.escape(content['submission_types'])}</li>")
    if meta:
        parts.append(f"<ul class=\"assignment-meta\">{''.join(meta)}</ul>")
    parts.append(content.get("html") or "")
    return "\n".join(parts)


def render_discussion(item):
    content = item.get("content") or {}
    return (f"<h1>{html_mod.escape(item.get('title', ''))}</h1>\n"
            f"{content.get('text_html') or ''}")


def render_external_tool(item):
    return (f"<h1>{html_mod.escape(item.get('title', ''))}</h1>"
            "<p><em>This item launches an external tool (LTI) and holds no "
            "archivable content of its own. It is a known gap, not an "
            "omission.</em></p>")


def render_item_body(item):
    """Kind-dispatch: the inner HTML body for one module item.

    A missing/malformed content dict raises inside the specific renderer,
    not here -- the caller (`render_site`) catches it, so one bad item
    becomes a short gap notice instead of aborting the whole render.
    """
    kind = item.get("kind")
    if kind == "page":
        return render_wiki_page(item)
    if kind == "assignment":
        return render_assignment(item)
    if kind == "discussion":
        return render_discussion(item)
    if kind == "quiz":
        content = item.get("content")
        if not content:
            return (f"<h1>{html_mod.escape(item.get('title', ''))}</h1>"
                     "<p><em>Quiz content unavailable.</em></p>")
        return render_quiz(content)
    if kind == "external_tool":
        return render_external_tool(item)
    return (f"<h1>{html_mod.escape(item.get('title', '') or 'Untitled')}</h1>"
            f"<p><em>Unrecognized item kind {html_mod.escape(str(kind))}; "
            "no content extracted.</em></p>")


def render_section_index(section, item_links):
    """`item_links` is [(kind, href, title), ...] in cartridge order,
    grouped by kind (first-seen order), each group in cartridge order.
    """
    groups, order = {}, []
    for kind, href, title in item_links:
        if kind not in groups:
            groups[kind] = []
            order.append(kind)
        groups[kind].append((href, title))
    parts = [f"<h1>{html_mod.escape(section['title'])}</h1>"]
    for kind in order:
        label = KIND_LABEL.get(kind, kind.replace("_", " ").title())
        parts.append(f"<h2>{html_mod.escape(label)}</h2>")
        links = "".join(f'<li><a href="{href}">{html_mod.escape(title)}</a></li>'
                         for href, title in groups[kind])
        parts.append(f"<ul>{links}</ul>")
    return "\n".join(parts)


# ------------------------------------------------------------- Elucidat ---

def find_elucidat_embeds(course):
    """Map each Elucidat project key to the section/item that embeds it.

    Derived at runtime by scanning item HTML for `elucidat.com/course/<code>`
    and matching against constants.ELUCIDAT_PROJECTS, rather than trusting a
    hardcoded table that would silently rot if the cartridge is re-exported.
    Logs (does not raise) if a known project can't be placed.
    """
    code_to_key = {code: key for key, code in constants.ELUCIDAT_PROJECTS.items()}
    embeds = {}
    for section in course["sections"]:
        for item in section["items"]:
            content = item.get("content")
            if not isinstance(content, dict):
                continue  # malformed record -- no embed here, not a crash
            body = (content.get("html") or content.get("text_html")
                    or content.get("description_html") or "")
            if not isinstance(body, str):
                continue
            for match in ELUCIDAT_CODE_RE.finditer(body):
                key = code_to_key.get(match.group(1))
                if key and key not in embeds:
                    embeds[key] = {"section": section, "item": item}
    missing = sorted(set(constants.ELUCIDAT_PROJECTS) - set(embeds))
    if missing:
        print(f"    WARNING: could not place Elucidat project(s) {missing} "
              "in any course item")
    return embeds


def embed_elucidat_links(body_html, project, section_dirname):
    """Replace the dead `<iframe>` with a link into the project's mirrored
    pages (sections/<dirname>/elucidat/), and list them.
    """
    pages = [p for p in (project.get("pages") or []) if p.get("slug")]
    if not pages:
        return body_html
    items = "".join(
        f'<li><a href="../elucidat/{p["slug"]}.html">'
        f'{html_mod.escape(p.get("name") or p["slug"])}</a></li>'
        for p in pages)
    title = html_mod.escape(project.get("title") or "")
    listing = (
        '<div class="elucidat-mirror">'
        f"<p>This section's original interactive module"
        f"{f' (<em>{title}</em>)' if title else ''} is mirrored below, with its "
        "accordions, modals and carousels expanded into a linear read:</p>"
        f"<ol>{items}</ol></div>")
    if ELUCIDAT_IFRAME_RE.search(body_html):
        return ELUCIDAT_IFRAME_RE.sub(listing, body_html, count=1)
    return body_html + listing


def copy_elucidat_project(project, key, section_dirname, build_dir, out_dir):
    """Mirror one Elucidat project's baked pages into its embedding section,
    each wrapped in the site shell with reveal.css applied.

    Never raises: a missing source page, an unreadable file or a failed copy
    is recorded as a gap and the rest of the project still mirrors.
    """
    out_section = Path(out_dir) / "sections" / section_dirname / "elucidat"
    source_dir = Path(build_dir).parent / "_source" / "elucidat" / key
    gaps = []
    try:
        out_section.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return 0, [{"project": key, "reason": f"could not create output dir: {exc}"}]

    assets_src = source_dir / "assets"
    if assets_src.exists():
        try:
            shutil.copytree(assets_src, out_section / "assets", dirs_exist_ok=True)
        except OSError as exc:
            gaps.append({"project": key, "reason": f"assets copy failed: {exc}"})

    written = 0
    for page in project.get("pages") or []:
        slug = page.get("slug")
        if not slug:
            gaps.append({"project": key, "page": page.get("id"),
                         "reason": "no slug (a gap page from the mirror stage)"})
            continue
        raw = source_dir / f"{slug}.html"
        try:
            body = raw.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            gaps.append({"project": key, "page": slug, "reason": str(exc)})
            continue
        try:
            (out_section / f"{slug}.html").write_text(
                page_shell(page.get("name") or slug, body, depth=3))
        except OSError as exc:
            gaps.append({"project": key, "page": slug, "reason": str(exc)})
            continue
        written += 1
    return written, gaps


# ------------------------------------------- non-cartridge assessments ----

def parse_qti_items(root):
    """Extract questions the same way `cartridge.parse_quiz` does, for QTI
    documents that have no separate assessment_meta.xml -- the orphaned
    assessment and the question banks under non_cc_assessments/.
    """
    questions = []
    for item in root.iter(f"{QTI}item"):
        prompt = ""
        presentation = item.find(f"{QTI}presentation")
        if presentation is not None:
            mt = presentation.find(f"{QTI}material/{QTI}mattext")
            if mt is not None and mt.text:
                prompt = mt.text
        options = []
        for label in item.iter(f"{QTI}response_label"):
            mt = label.find(f"{QTI}material/{QTI}mattext")
            options.append(mt.text if mt is not None and mt.text else "")
        questions.append({"title": item.get("title", ""), "prompt_html": prompt,
                           "options": options, "correct": None})
    return questions


def load_non_cc_assessments(cartridge_dir):
    """Every non_cc_assessments/*.xml.qti file, classified by its actual
    child element: <assessment> (6, including the orphaned "Survey: Webinar
    1") or Canvas <objectbank> (11, the question pools quizzes draw from).

    A file that fails to parse, or matches neither shape, is a gap -- never
    a crash.
    """
    directory = Path(cartridge_dir) / "non_cc_assessments"
    assessments, banks, gaps = [], [], []
    if not directory.exists():
        return assessments, banks, gaps
    for path in sorted(directory.glob("*.xml.qti")):
        try:
            root = ET.parse(path).getroot()
        except (ET.ParseError, OSError) as exc:
            gaps.append({"file": path.name, "reason": str(exc)})
            continue
        node = root.find(f"{QTI}assessment")
        if node is not None:
            assessments.append({"ident": node.get("ident"), "title": node.get("title") or "",
                                 "questions": parse_qti_items(node)})
            continue
        node = root.find(f"{QTI}objectbank")
        if node is not None:
            banks.append({"ident": node.get("ident"), "questions": parse_qti_items(node)})
            continue
        gaps.append({"file": path.name, "reason": "neither <assessment> nor <objectbank>"})
    return assessments, banks, gaps


def find_unlinked_assessments(course, assessments):
    """Assessments in the manifest but reachable from no module item -- the
    Task 2 cartridge stage never renders these into course.json at all.
    """
    linked = {item.get("identifierref") for section in course["sections"]
              for item in section["items"] if item.get("identifierref")}
    return [a for a in assessments if a["ident"] not in linked]


def render_question_banks(banks):
    parts = ["<h1>Question Banks</h1>",
             "<p><em>These are Canvas question banks: source pools that quizzes "
             "draw questions from, not quizzes presented to learners. They were "
             "never shown to students as a set.</em></p>"]
    for index, bank in enumerate(banks, start=1):
        parts.append(f"<h2>Bank {index} ({html_mod.escape(bank['ident'] or '')}, "
                      f"{len(bank['questions'])} questions)</h2>")
        for question in bank["questions"]:
            parts.append(f"<h3>{html_mod.escape(question.get('title', ''))}</h3>")
            parts.append(question.get("prompt_html") or "")
            if question.get("options"):
                items = "".join(
                    f"<li>{html_mod.escape(o)}</li>" for o in question["options"])
                parts.append(f"<ol>{items}</ol>")
    return "\n".join(parts)


# ------------------------------------------------------- media placement --

def section_dir_for(course, section_title):
    """Cartridge section title -> its numbered output directory name."""
    for section in course["sections"]:
        if section["title"] == section_title:
            return f"sections/{section['dirname']}"
    return None


def destination_for(local_path, course):
    """Which output directory a campus media file belongs in.

    Campus media is organised by the folder it sits in, not by filename, so
    the mapping is folder-level and explicit. Anything outside the known
    folders -- including a Vimeo-only download with no campus path at all --
    goes to files/ rather than being dropped.
    """
    parts = Path(local_path).parts
    try:
        index = parts.index("campus.mitpeonline.com")
    except ValueError:
        return "files"
    if index + 1 >= len(parts):
        return "files"
    folder = parts[index + 1]
    mapped = constants.CAMPUS_FOLDER_MAP.get(folder)
    if mapped == "__orientation__":
        return constants.ORIENTATION_DIR
    if mapped == "__closing__":
        return constants.CLOSING_DIR
    if mapped:
        return section_dir_for(course, mapped) or "files"
    return "files"


def collect_canonical_videos(ledger):
    """Every video this archive should carry, as `{"copy_from", "identity"}`.

    `ledger["files"]` groups are built only from local-disk records (see
    `reconcile.group_by_hash`), so a rendition whose Vimeo copy outranks the
    local one -- true for 33 of this course's 35 matched renditions -- would
    otherwise vanish entirely: excluded from copying as the alias/loser, and
    never present as its own file group since it isn't a local record. The
    override below copies the *bytes* from whichever side the ledger judged
    better, while `identity` keeps the original local path so the video's
    human-readable filename and its media.json transcript/contactsheet
    lookup (both keyed on the local path) still resolve.

    `ledger["online_only"]` videos (a Vimeo id with no local counterpart at
    all -- present in this course) have no such identity and are copied
    under their own name.
    """
    path_to_group = {}
    for group in ledger.get("files", []):
        canonical = group.get("canonical")
        if not canonical:
            continue
        path_to_group[canonical] = group
        for alias in group.get("aliases", []):
            path_to_group[alias] = group

    overrides = {}
    for match in ledger.get("renditions", []):
        group = path_to_group.get(match.get("local_path"))
        if group is not None and match.get("canonical"):
            overrides[group["canonical"]] = match["canonical"]

    videos = []
    for group in ledger.get("files", []):
        identity = group.get("canonical")
        if not identity or Path(identity).suffix.lower() != ".mp4":
            continue
        videos.append({"copy_from": overrides.get(identity, identity), "identity": identity})

    for video in ledger.get("online_only", []):
        path = video.get("path")
        if path:
            videos.append({"copy_from": path, "identity": None})
    return videos


def place_media(course, ledger, media_records, out_dir, build_dir=None):
    """Copy each canonical video plus its transcript, contact sheet and
    caption track (an original sibling .srt, or -- Ruling 22 -- a
    Whisper-generated one from `<build_dir>/transcripts/` for the videos
    that shipped with no captions of their own).

    Tolerant of any `status` value media_records may carry: only the
    presence of a `transcript`/`contactsheet` path that actually exists on
    disk is ever consulted, never the status string itself. A missing
    source file or a failed copy is skipped, not fatal.

    Returns (count placed, caption manifest entries for MANIFEST.json).
    """
    out_dir = Path(out_dir)
    derived = {record["path"]: record for record in media_records if record.get("path")}
    placed = 0
    captions = []

    for video in collect_canonical_videos(ledger):
        copy_from = Path(video["copy_from"])
        if not copy_from.exists():
            continue
        identity = Path(video["identity"]) if video["identity"] else copy_from
        dest_dir_name = destination_for(identity, course)
        target_dir = out_dir / dest_dir_name / "media"
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            continue
        target_name = identity.name
        try:
            shutil.copy2(copy_from, target_dir / target_name)
        except OSError:
            continue
        placed += 1
        stem = identity.stem

        caption_source = None
        original_srt = identity.with_suffix(".srt")
        if original_srt.exists():
            try:
                shutil.copy2(original_srt, target_dir / f"{stem}.srt")
                caption_source = "original"
            except OSError:
                pass
        elif build_dir is not None:
            whisper_srt = Path(build_dir) / "transcripts" / f"{stem}.srt"
            if whisper_srt.exists():
                try:
                    shutil.copy2(whisper_srt, target_dir / f"{stem}.srt")
                    caption_source = "whisper"
                except OSError:
                    pass
        if caption_source:
            rel_video = str((target_dir / target_name).relative_to(out_dir))
            captions.append({"video": rel_video, "caption_source": caption_source})

        record = derived.get(str(identity), {})
        for key, suffix in (("transcript", ".transcript.md"),
                             ("contactsheet", ".contactsheet.jpg")):
            value = record.get(key)
            if value and Path(value).exists():
                try:
                    shutil.copy2(value, target_dir / f"{stem}{suffix}")
                except OSError:
                    continue
    return placed, captions


# ------------------------------------------------------------ site build --

def render_site(build_dir, out_dir):
    build_dir, out_dir = Path(build_dir), Path(out_dir)
    course = json.loads((build_dir / "course.json").read_text())
    elucidat_projects = _load_json_safe(build_dir / "elucidat.json", default={})
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        shutil.copy(Path(__file__).parent / "reveal.css", out_dir / "reveal.css")
    except OSError as exc:
        raise RuntimeError(f"could not write reveal.css: {exc}") from exc

    embeds = find_elucidat_embeds(course)
    embed_by_item_id = {id(e["item"]): key for key, e in embeds.items()}

    written = 0
    gaps = []
    section_rows = []

    for section in course["sections"]:
        dirname = section["dirname"]
        section_dir = out_dir / "sections" / dirname
        section_dir.mkdir(parents=True, exist_ok=True)

        seen_per_dir = {}
        item_links = []
        for item in section["items"]:
            kind = item.get("kind", "other")
            subdir_name = KIND_SUBDIR.get(kind, "other")
            subdir = section_dir / subdir_name
            try:
                subdir.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                gaps.append({"section": dirname, "item": item.get("slug"), "reason": str(exc)})
                continue

            filename = f"{unique_filename(seen_per_dir.setdefault(subdir_name, {}), item.get('slug'))}.html"

            try:
                body = render_item_body(item)
            except Exception as exc:  # a malformed content dict must not abort the run
                body = (f"<h1>{html_mod.escape(item.get('title') or 'Untitled')}</h1>"
                        f"<p><em>This item could not be rendered "
                        f"({html_mod.escape(str(exc))}).</em></p>")
                gaps.append({"section": dirname, "item": item.get("slug"), "reason": str(exc)})

            project_key = embed_by_item_id.get(id(item))
            if project_key and project_key in elucidat_projects:
                project = elucidat_projects[project_key]
                try:
                    p_written, p_gaps = copy_elucidat_project(
                        project, project_key, dirname, build_dir, out_dir)
                    written += p_written
                    gaps.extend(p_gaps)
                    body = embed_elucidat_links(body, project, dirname)
                except Exception as exc:  # malformed elucidat.json entry -- not a crash
                    gaps.append({"section": dirname, "project": project_key, "reason": str(exc)})

            body = rewrite_filebase(body, depth=3)
            try:
                (subdir / filename).write_text(page_shell(item.get("title", ""), body, depth=3))
            except OSError as exc:
                gaps.append({"section": dirname, "item": item.get("slug"), "reason": str(exc)})
                continue
            written += 1
            item_links.append((kind, f"{subdir_name}/{filename}", item.get("title", "")))

        index_body = render_section_index(section, item_links)
        try:
            (section_dir / "index.html").write_text(
                page_shell(section["title"], index_body, depth=2))
            written += 1
        except OSError as exc:
            gaps.append({"section": dirname, "reason": str(exc)})
        section_rows.append(f'<li><a href="sections/{dirname}/index.html">'
                             f'{html_mod.escape(section["title"])}</a></li>')

    # Files bundled inside the cartridge export itself ($IMS-CC-FILEBASE$ targets).
    resources = Path(constants.CARTRIDGE_DIR) / "web_resources"
    if resources.exists():
        try:
            shutil.copytree(resources, out_dir / "files", dirs_exist_ok=True)
        except OSError as exc:
            gaps.append({"reason": f"web_resources copy failed: {exc}"})

    # Campus media -- only once Tasks 6/7 have produced a ledger and media.json.
    placed = 0
    ledger = _load_json_safe(build_dir / "ledger.json", default=None)
    media_records = _load_json_safe(build_dir / "media.json", default=None)
    if isinstance(ledger, dict) and isinstance(media_records, list):
        try:
            placed, captions = place_media(course, ledger, media_records, out_dir, build_dir)
        except Exception as exc:  # a structurally malformed ledger/media.json -- not a crash
            captions = []
            gaps.append({"reason": f"media placement failed: {exc}"})
        if captions:
            try:
                (out_dir / "MANIFEST.json").write_text(
                    json.dumps(captions, indent=2, ensure_ascii=False))
            except OSError as exc:
                gaps.append({"reason": f"MANIFEST.json write failed: {exc}"})
    elif ledger is not None or media_records is not None:
        gaps.append({"reason": "ledger.json/media.json present but not in the expected shape"})

    # Question banks and the one assessment reachable from no module.
    assessments, banks, qti_gaps = load_non_cc_assessments(constants.CARTRIDGE_DIR)
    gaps.extend({"reason": g["reason"], "file": g.get("file")} for g in qti_gaps)
    unlinked_rows = []
    unlinked_seen = {}
    for assessment in find_unlinked_assessments(course, assessments):
        unlinked_dir = out_dir / "unlinked-assessments"
        try:
            unlinked_dir.mkdir(parents=True, exist_ok=True)
            base = slugify(assessment["title"]) or "assessment"
            name = unique_filename(unlinked_seen, base)
            body = render_quiz({"title": assessment["title"], "description_html": "",
                                 "is_survey": True, "questions": assessment["questions"]})
            (unlinked_dir / f"{name}.html").write_text(
                page_shell(assessment["title"], body, depth=1))
            written += 1
            unlinked_rows.append(
                f'<li><a href="unlinked-assessments/{name}.html">'
                f'{html_mod.escape(assessment["title"])}</a></li>')
        except OSError as exc:
            gaps.append({"reason": f"unlinked assessment write failed: {exc}"})

    if banks:
        try:
            (out_dir / "question-banks.html").write_text(
                page_shell("Question Banks", render_question_banks(banks), depth=0))
            written += 1
        except OSError as exc:
            gaps.append({"reason": f"question-banks.html write failed: {exc}"})

    index_parts = [f"<h1>{html_mod.escape(course.get('title', ''))}</h1>",
                   f"<p>{html_mod.escape(course.get('course_code', ''))}</p>",
                   f"<ol>{''.join(section_rows)}</ol>"]
    if unlinked_rows:
        index_parts.append("<h2>Not part of any module</h2>")
        index_parts.append("<p>In the export manifest but never linked into a "
                            "module in Canvas:</p>")
        index_parts.append(f"<ul>{''.join(unlinked_rows)}</ul>")
    if banks:
        index_parts.append(
            f'<p><a href="question-banks.html">Question banks</a> '
            f'({len(banks)} source pools quizzes draw from -- not shown to '
            f'learners as such)</p>')
    try:
        (out_dir / "index.html").write_text(
            page_shell(course.get("title", ""), "\n".join(index_parts), depth=0))
        written += 1
    except OSError as exc:
        gaps.append({"reason": f"index.html write failed: {exc}"})

    return {"pages_written": written, "sections": len(course["sections"]),
            "media_placed": placed, "gaps": len(gaps), "gap_details": gaps}
