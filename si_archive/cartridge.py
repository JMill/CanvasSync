"""Stage 1 -- parse the IMS Common Cartridge into the canonical course spine.

The cartridge is the authority on structure. Its 16 modules are the course as
actually taught, including the surveys and the three-way split of Module 1 that
the Elucidat project numbering does not show.
"""
import html
import json
import re
import unicodedata
from pathlib import Path
from xml.etree import ElementTree as ET

CC = "{http://canvas.instructure.com/xsd/cccv1p0}"
IMSCP = "{http://www.imsglobal.org/xsd/imsccv1p1/imscp_v1p1}"
IMSDT = "{http://www.imsglobal.org/xsd/imsccv1p1/imsdt_v1p1}"
QTI = "{http://www.imsglobal.org/xsd/ims_qtiasiv1p2}"


def slugify(text):
    """Kebab-case, ASCII-folded, filesystem- and URL-safe."""
    folded = unicodedata.normalize("NFKD", text)
    folded = folded.encode("ascii", "ignore").decode("ascii")
    folded = folded.replace("'", "").replace("’", "")   # possessives elide, not split
    folded = re.sub(r"[^\w\s-]", " ", folded)
    return re.sub(r"[-\s]+", "-", folded).strip("-").lower()


def _text(node, tag, default=""):
    if node is None:
        return default
    found = node.find(tag)
    return found.text if found is not None and found.text else default


def parse_modules(cartridge_dir):
    """Ordered sections from module_meta.xml -- the cartridge's own ordering."""
    path = Path(cartridge_dir) / "course_settings" / "module_meta.xml"
    root = ET.parse(path).getroot()
    modules = []
    for m in root.findall(f"{CC}module"):
        items = []
        for it in m.iter(f"{CC}item"):
            items.append({
                "title": _text(it, f"{CC}title"),
                "content_type": _text(it, f"{CC}content_type"),
                "identifierref": _text(it, f"{CC}identifierref") or None,
                "indent": int(_text(it, f"{CC}indent", "0") or 0),
            })
        title = _text(m, f"{CC}title")
        modules.append({
            "title": title,
            "slug": slugify(title),
            "position": int(_text(m, f"{CC}position", "0") or 0),
            "workflow_state": _text(m, f"{CC}workflow_state"),
            "items": items,
        })
    modules.sort(key=lambda m: m["position"])
    return modules


def parse_manifest(cartridge_dir):
    """Resource table: identifier -> type, href, and member files."""
    path = Path(cartridge_dir) / "imsmanifest.xml"
    root = ET.parse(path).getroot()
    title_node = root.find(f".//{{http://ltsc.ieee.org/xsd/imsccv1p1/LOM/manifest}}string")
    resources = {}
    for res in root.iter(f"{IMSCP}resource"):
        resources[res.get("identifier")] = {
            "type": res.get("type", ""),
            "href": res.get("href"),
            "files": [f.get("href") for f in res.findall(f"{IMSCP}file")],
        }
    return {
        "title": title_node.text if title_node is not None else "",
        "resources": resources,
    }


def parse_assignment(xml_path):
    root = ET.parse(xml_path).getroot()
    points = _text(root, f"{CC}points_possible", "0") or "0"
    return {
        "title": _text(root, f"{CC}title"),
        "due_at": _text(root, f"{CC}due_at") or None,
        "lock_at": _text(root, f"{CC}lock_at") or None,
        "points_possible": float(points),
        "submission_types": _text(root, f"{CC}submission_types"),
        "workflow_state": _text(root, f"{CC}workflow_state"),
    }


def parse_discussion(xml_path):
    root = ET.parse(xml_path).getroot()
    raw = _text(root, f"{IMSDT}text")
    return {"title": _text(root, f"{IMSDT}title"), "text_html": html.unescape(raw)}


def parse_quiz(meta_path, qti_path):
    """Render a QTI assessment as a readable document.

    Canvas emits a <varequal> "correct answer" even for surveys, where it is
    simply the first option and means nothing. Surveys must not present it as
    correct -- doing so would state something false.
    """
    meta = ET.parse(meta_path).getroot()
    quiz_type = _text(meta, f"{CC}quiz_type")
    is_survey = "survey" in quiz_type

    questions = []
    qti = ET.parse(qti_path).getroot()
    for item in qti.iter(f"{QTI}item"):
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
        correct = None
        if not is_survey:
            ve = item.find(f".//{QTI}varequal")
            if ve is not None and ve.text:
                ident_to_text = {}
                for label in item.iter(f"{QTI}response_label"):
                    mt = label.find(f"{QTI}material/{QTI}mattext")
                    ident_to_text[label.get("ident")] = (
                        mt.text if mt is not None and mt.text else "")
                correct = ident_to_text.get(ve.text)
        questions.append({
            "title": item.get("title", ""),
            "prompt_html": prompt,
            "options": options,
            "correct": correct,
        })

    return {
        "title": _text(meta, f"{CC}title"),
        "description_html": html.unescape(_text(meta, f"{CC}description")),
        "quiz_type": quiz_type,
        "is_survey": is_survey,
        "points_possible": float(_text(meta, f"{CC}points_possible", "0") or 0),
        "questions": questions,
    }


def _read_body(path):
    """Return the <body> inner HTML of a cartridge HTML file, or the whole file."""
    raw = Path(path).read_text(encoding="utf-8", errors="replace")
    match = re.search(r"<body[^>]*>(.*)</body>", raw, re.S | re.I)
    return match.group(1).strip() if match else raw


def attach_item_content(item, resources, cartridge_dir):
    """Resolve one module item's identifierref to its parsed body.

    Sets item["kind"] and item["content"]. Items whose ref is absent from the
    manifest -- the two ContextExternalTool launches -- get kind "external_tool"
    and content None; they are known, recorded gaps, not failures.
    """
    cartridge_dir = Path(cartridge_dir)
    ref = item.get("identifierref")
    resource = resources.get(ref) if ref else None
    ctype = item.get("content_type", "")

    if resource is None:
        item["kind"] = "external_tool" if ctype == "ContextExternalTool" else "unresolved"
        item["content"] = None
        return item

    href = resource.get("href")
    files = resource.get("files") or []

    if ctype == "WikiPage" and href:
        item["kind"] = "page"
        item["content"] = {"html": _read_body(cartridge_dir / href)}

    elif ctype == "Assignment":
        settings = next((f for f in files if f.endswith("assignment_settings.xml")), None)
        body = href or next((f for f in files if f.endswith(".html")), None)
        content = parse_assignment(cartridge_dir / settings) if settings else {}
        content["html"] = _read_body(cartridge_dir / body) if body else ""
        item["kind"] = "assignment"
        item["content"] = content

    elif ctype == "DiscussionTopic":
        topic = href or next((f for f in files if f.endswith(".xml")), None)
        item["kind"] = "discussion"
        item["content"] = parse_discussion(cartridge_dir / topic) if topic else None

    elif ctype == "Quizzes::Quiz":
        qti = next((f for f in files if f.endswith("assessment_qti.xml")), None)
        meta = Path(qti).parent / "assessment_meta.xml" if qti else None
        # Canvas's own export is a superset of the CC-standard one: the CC file
        # drops question types it cannot model (Entry Survey loses 6, Exit Survey 1).
        canvas_qti = cartridge_dir / "non_cc_assessments" / f"{ref}.xml.qti"
        source = canvas_qti if canvas_qti.exists() else (cartridge_dir / qti if qti else None)
        item["kind"] = "quiz"
        item["content"] = (parse_quiz(cartridge_dir / meta, source)
                           if source and meta and (cartridge_dir / meta).exists() else None)
    else:
        item["kind"] = "other"
        item["content"] = None

    return item


def build_course(cartridge_dir):
    """Assemble course.json -- the spine every later stage hangs content on."""
    cartridge_dir = Path(cartridge_dir)
    manifest = parse_manifest(cartridge_dir)
    settings = ET.parse(cartridge_dir / "course_settings" / "course_settings.xml").getroot()
    sections = parse_modules(cartridge_dir)

    for section in sections:
        for item in section["items"]:
            attach_item_content(item, manifest["resources"], cartridge_dir)
            item["slug"] = slugify(item["title"]) or (item.get("identifierref") or "item")

    seen = {}
    for index, section in enumerate(sections, start=1):
        base = section["slug"]
        seen[base] = seen.get(base, 0) + 1
        suffix = "" if seen[base] == 1 else f"-{seen[base]}"
        section["dirname"] = f"{index:02d}-{base}{suffix}"

    return {
        "title": _text(settings, f"{CC}title") or manifest["title"],
        "course_code": _text(settings, f"{CC}course_code"),
        "start_at": _text(settings, f"{CC}start_at"),
        "conclude_at": _text(settings, f"{CC}conclude_at"),
        "sections": sections,
        "resources": manifest["resources"],
    }


def write_course_json(cartridge_dir, out_path):
    payload = build_course(cartridge_dir)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    return payload
