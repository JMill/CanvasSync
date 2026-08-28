# Systematic Innovation Offline Archive — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Merge four partial sources into one self-contained, browsable offline archive of *Systematic Innovation: Scaling Up from a Hunch* (MIT Professional Education, `SISH-ENG-001-FEB22`).

**Architecture:** An eight-stage pipeline. Each stage is one module with one responsibility that reads and writes JSON, so any stage re-runs without forcing a full rebuild. The Canvas Common Cartridge supplies the canonical structure; Elucidat pages are baked to static HTML and force-revealed; local media and Vimeo downloads are deduplicated against each other by content hash and by duration/title rendition matching.

**Tech Stack:** Python 3.12, `requests`, `beautifulsoup4` + `lxml`, `yt-dlp`, `mlx-whisper` (Metal-accelerated on Apple Silicon), `ffmpeg`, `pytest`.

**Spec:** `docs/superpowers/specs/2026-08-27-systematic-innovation-archive-design.md`

## Global Constraints

- **Output root:** `/Volumes/Desk SSD/SystematicInnovation-Archive/`. Never the boot volume — it has 22 GB free of 1.8 TB and the archive needs ~20 GB.
- **Network pacing is mandatory.** All network access serial, via `si_archive.net.Throttle`. No concurrency, no thread pools, no `asyncio.gather` over requests. Randomised gaps, periodic longer rests, backoff that persists after any 429/503. (`CLAUDE.md`)
- **Student work is excluded.** Any path containing a directory matching `*_submissions`, and any file matching `*_text.html`, is skipped by every stage. Assignment and discussion *prompts* are kept.
- **Never fail the run on one bad asset.** Unresolvable items are recorded as gaps in `REPORT.md` and the pipeline continues.
- **Source data is read-only.** No stage writes to the Dropbox, GDrive, or Downloads source paths.
- **Interpreter:** `.venv/bin/python` (repo is `pip install -e`'d into it).
- **Elucidat page HTML is stored character-reversed** under the JSON key `lmth`. Decode with `s[::-1]`.
- **Vimeo must be requested as `https://player.vimeo.com/video/<id>`** with `--referer https://learning.elucidat.com/`. The `vimeo.com/<id>` form fails yt-dlp's OAuth path.

## Constants

These exact values are used across tasks. Defined once in `si_archive/constants.py` (Task 1).

```python
COURSE_TITLE = "Systematic Innovation: Scaling Up from a Hunch - February 2022"
COURSE_CODE = "SISH-ENG-001-FEB22"

DROPBOX_ROOT = "/Users/jmill/MIT Dropbox/Jonathan Miller/teaching/Systematic Innovation"
CARTRIDGE_DIR = f"{DROPBOX_ROOT}/systematic-innovation-scaling-up-from-a-hunch-february-2022-export"
CAMPUS_DIR = f"{DROPBOX_ROOT}/campus.mitpeonline.com"
GDRIVE_DIR = ("/Users/jmill/Library/CloudStorage/GoogleDrive-i.am.jonathanmiller@gmail.com"
              "/My Drive/Teaching/2021Q4/systematic innovation")
PROVENANCE_PDF = ("/Users/jmill/Downloads/Learning Facilitator for Systematic Innovation"
                  " • i.am.jonathanmiller@gmail.com.pdf")

OUTPUT_ROOT = "/Volumes/Desk SSD/SystematicInnovation-Archive"

# Discovered from the cartridge's iframe srcs. The user-supplied list had only 5;
# M5 and INFO were missing.
ELUCIDAT_PROJECTS = {
    "M1":   "5f7356442004e-5f7c8b919a261",
    "M2":   "5f8966ad7f361-5f8ee6beacce6",
    "M3":   "5faa7fce0007f-5fae4255164d6",
    "M4":   "5fb68ea13b3de-5fbf667f2742b",
    "M5":   "5fc61e2550add-5fd774d58f4ee",
    "M6":   "5fe0caa101abf-60783a3aa5ce5",
    "INFO": "5f59f641d14f2-5f5a024ff039d",
}

ELUCIDAT_REFERER = "https://learning.elucidat.com/"
STUDENT_WORK_DIR_GLOB = "*_submissions"
STUDENT_WORK_FILE_GLOB = "*_text.html"
CONTACTSHEET_MIN_SECONDS = 180

# Campus media folders map onto cartridge sections. "Module N" folders land in
# the first cartridge section whose title starts with that name -- Module 1 is
# split across three sections, and its media belongs with Part 1. `pre` and
# `post` have no cartridge section and get their own top-level directories.
CAMPUS_FOLDER_MAP = {
    "Module 1": "Module 1 - Part 1",
    "Module 2": "Module 2",
    "Module 3": "Module 3",
    "Module 4": "Module 4",
    "Module 5": "Module 5",
    "Module 6": "Module 6",
    "pre": "__orientation__",
    "post": "__closing__",
}
ORIENTATION_DIR = "orientation"
CLOSING_DIR = "closing"
```

## File Structure

| File | Responsibility |
|---|---|
| `si_archive/__init__.py` | Package marker |
| `si_archive/constants.py` | Paths, project registry, thresholds — no logic |
| `si_archive/net.py` | `Throttle` (moved from `canvas_media_archive.py`) + `get()` helper |
| `si_archive/cartridge.py` | Stage 1 — parse the Common Cartridge into `course.json` |
| `si_archive/elucidat.py` | Stage 2 — mirror the 7 Elucidat projects |
| `si_archive/vimeo.py` | Stage 3 — download Vimeo videos and captions |
| `si_archive/localsrc.py` | Stage 4 — hash-index local files (named to avoid shadowing `locals`) |
| `si_archive/reconcile.py` | Stage 5 — dedupe and rendition-match into `ledger.json` |
| `si_archive/media.py` | Stage 6 — transcripts and contact sheets |
| `si_archive/render.py` | Stage 7 — emit the static site |
| `si_archive/reveal.css` | Force-expand stylesheet for baked Elucidat pages |
| `si_archive/verify.py` | Stage 8 — coverage checks and `REPORT.md` |
| `bin/si_archive.py` | CLI driver with per-stage subcommands and `--all` |
| `tests/` | pytest suite with fixtures copied from real source data |

---

## Task 1: Package scaffolding, shared Throttle, test infrastructure

**Files:**
- Create: `si_archive/__init__.py`, `si_archive/constants.py`, `si_archive/net.py`
- Create: `bin/si_archive.py`
- Create: `tests/__init__.py`, `tests/test_net.py`
- Modify: `bin/canvas_media_archive.py` (remove `Throttle`, import from `si_archive.net`)
- Modify: `requirements.txt`
- Modify: `setup.py:packages` (include `si_archive`)

**Interfaces:**
- Consumes: nothing
- Produces:
  - `si_archive.net.Throttle(min_gap=1.5, jitter=1.5, rest_every=25, rest_secs=(8,20))` with methods `wait(url) -> None`, `pushback(resp) -> float`
  - `si_archive.net.get(url, throttle, headers=None, timeout=45, tries=3) -> requests.Response`
  - `si_archive.constants` module-level names as listed above

- [ ] **Step 1: Install dependencies**

```bash
cd /Users/jmill/coding/github/CanvasSync
.venv/bin/pip install pytest beautifulsoup4 lxml yt-dlp Pillow mlx-whisper curl-cffi
```

Then append to `requirements.txt`:

```
beautifulsoup4
lxml
yt-dlp
Pillow
mlx-whisper
curl-cffi
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_net.py`:

```python
import time
import pytest
from si_archive.net import Throttle


def test_throttle_spaces_requests_to_the_same_host():
    t = Throttle(min_gap=0.2, jitter=0.0, rest_every=0)
    t.wait("https://example.com/a")
    start = time.monotonic()
    t.wait("https://example.com/b")
    assert time.monotonic() - start >= 0.2


def test_throttle_does_not_delay_a_different_host():
    t = Throttle(min_gap=5.0, jitter=0.0, rest_every=0)
    t.wait("https://example.com/a")
    start = time.monotonic()
    t.wait("https://other.example.org/a")
    assert time.monotonic() - start < 0.5


def test_pushback_penalty_persists_after_a_429():
    class FakeResp:
        status_code = 429
        headers = {"Retry-After": "1"}

    t = Throttle(min_gap=0.0, jitter=0.0, rest_every=0)
    assert t.penalty == 0.0
    t.pushback(FakeResp())
    assert t.penalty > 0.0
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_net.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'si_archive'`

- [ ] **Step 4: Create the package and move Throttle**

Create `si_archive/__init__.py` (empty).

Create `si_archive/net.py`. Move the `Throttle` class verbatim from `bin/canvas_media_archive.py:51` — do not rewrite it, it is already correct and tested in production. Add at the top:

```python
"""Shared network pacing.

Throttle lived in bin/canvas_media_archive.py until a third tool needed it.
Behaviour is unchanged; only its home moved.
"""
import random
import time
from urllib.parse import urlsplit

import requests
```

Then append the `get` helper below the class:

```python
def get(url, throttle, headers=None, timeout=45, tries=3):
    """Serial, paced GET with backoff. Raises on final failure."""
    hdrs = {"User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/120.0 Safari/537.36")}
    if headers:
        hdrs.update(headers)
    last = None
    for attempt in range(tries):
        throttle.wait(url)
        try:
            resp = requests.get(url, headers=hdrs, timeout=timeout)
        except requests.RequestException as exc:
            last = exc
            time.sleep(5 * (attempt + 1))
            continue
        nap = throttle.pushback(resp)
        if nap:
            time.sleep(nap)
            last = RuntimeError(f"{resp.status_code} from {url}")
            continue
        resp.raise_for_status()
        return resp
    raise RuntimeError(f"GET failed after {tries} tries: {url}") from last
```

- [ ] **Step 5: Verify Throttle.pushback returns a float**

Read the tail of the moved `pushback` method. The test asserts `penalty > 0.0` after a 429 and `get()` treats the return as a sleep duration. If the original returns `None` on the clean path, that is correct — `if nap:` handles it. If it does not set `self.penalty` on 429, add:

```python
        self.penalty = min(self.penalty + 2.0, 30.0)
```

before returning the sleep duration.

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_net.py -v`
Expected: 3 passed

- [ ] **Step 7: Update canvas_media_archive.py to import the moved class**

Delete the `Throttle` class body from `bin/canvas_media_archive.py` and add near the other imports:

```python
from si_archive.net import Throttle
```

Verify the old tool still starts:

Run: `.venv/bin/python bin/canvas_media_archive.py --help`
Expected: usage text, no ImportError

- [ ] **Step 8: Write constants.py**

Create `si_archive/constants.py` with exactly the contents of the **Constants** section above.

- [ ] **Step 9: Write the CLI skeleton**

Create `bin/si_archive.py`:

```python
#!/usr/bin/env python
"""Build the Systematic Innovation offline archive.

Eight stages, each independently re-runnable. See
docs/superpowers/specs/2026-08-27-systematic-innovation-archive-design.md
"""
import argparse
import sys

STAGES = ["cartridge", "elucidat", "vimeo", "local",
          "reconcile", "media", "render", "verify"]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("stage", choices=STAGES + ["all"],
                    help="pipeline stage to run")
    ap.add_argument("--out", default=None,
                    help="archive root (default: constants.OUTPUT_ROOT)")
    ap.add_argument("--min-gap", type=float, default=1.5)
    ap.add_argument("--jitter", type=float, default=1.5)
    ap.add_argument("--rest-every", type=int, default=25)
    args = ap.parse_args(argv)

    stages = STAGES if args.stage == "all" else [args.stage]
    for name in stages:
        print(f"==> {name}")
        run_stage(name, args)
    return 0


def run_stage(name, args):
    raise NotImplementedError(f"stage {name!r} not yet implemented")


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 10: Verify the CLI parses**

Run: `.venv/bin/python bin/si_archive.py --help`
Expected: usage listing all eight stage names plus `all`

- [ ] **Step 11: Commit**

```bash
cd /Users/jmill/coding/github/CanvasSync
git add si_archive/ bin/si_archive.py tests/ requirements.txt setup.py bin/canvas_media_archive.py
git commit -m "Add si_archive package scaffolding and share Throttle

Throttle moves out of canvas_media_archive.py into si_archive/net.py now
that a third tool needs the same pacing discipline. Behaviour unchanged."
```

---

## Task 2: Cartridge ingest

**Files:**
- Create: `si_archive/cartridge.py`
- Create: `tests/test_cartridge.py`
- Create: `tests/fixtures/cartridge/` (small real XML files, copied in Step 1)

**Interfaces:**
- Consumes: `si_archive.constants.CARTRIDGE_DIR`
- Produces:
  - `parse_manifest(cartridge_dir: Path) -> dict` — `{"title": str, "resources": {ident: {"type": str, "href": str|None, "files": [str]}}}`
  - `parse_modules(cartridge_dir: Path) -> list[dict]` — ordered sections, each `{"title": str, "position": int, "items": [{"title", "content_type", "identifierref", "indent"}]}`
  - `parse_assignment(xml_path: Path) -> dict` — `{"title", "due_at", "points_possible", "submission_types", "workflow_state"}`
  - `parse_quiz(meta_path: Path, qti_path: Path) -> dict` — `{"title", "description_html", "quiz_type", "is_survey": bool, "questions": [{"title", "prompt_html", "options": [str], "correct": str|None}]}`
  - `parse_discussion(xml_path: Path) -> dict` — `{"title", "text_html"}`
  - `build_course(cartridge_dir: Path) -> dict` — the assembled `course.json` payload
- Later tasks rely on: `course.json` key `sections` (list, cartridge order) and each item's `slug` (kebab-case, unique).

- [ ] **Step 1: Copy test fixtures**

The cartridge lives on Dropbox and is read-only. Copy four small real files into the repo so tests do not depend on Dropbox being mounted. None contain student data — they are instructor-authored course structure.

```bash
cd /Users/jmill/coding/github/CanvasSync
E="/Users/jmill/MIT Dropbox/Jonathan Miller/teaching/Systematic Innovation/systematic-innovation-scaling-up-from-a-hunch-february-2022-export"
mkdir -p tests/fixtures/cartridge/course_settings tests/fixtures/cartridge/assignment
cp "$E/course_settings/module_meta.xml"      tests/fixtures/cartridge/course_settings/
cp "$E/course_settings/course_settings.xml"  tests/fixtures/cartridge/course_settings/
cp "$E/g0c9eda2afde951762cdd86a0f78979df/assignment_settings.xml" tests/fixtures/cartridge/assignment/
cp "$E/g0310b4bfcff4940c7e38472a5e6d8cc8.xml" tests/fixtures/cartridge/discussion.xml
ls -R tests/fixtures/cartridge
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_cartridge.py`:

```python
from pathlib import Path

import pytest

from si_archive import cartridge

FIX = Path(__file__).parent / "fixtures" / "cartridge"


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
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_cartridge.py -v`
Expected: FAIL with `ImportError: cannot import name 'cartridge'`

- [ ] **Step 4: Implement cartridge.py**

Create `si_archive/cartridge.py`:

```python
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


def build_course(cartridge_dir):
    """Assemble course.json -- the spine every later stage hangs content on."""
    cartridge_dir = Path(cartridge_dir)
    manifest = parse_manifest(cartridge_dir)
    settings = ET.parse(cartridge_dir / "course_settings" / "course_settings.xml").getroot()
    sections = parse_modules(cartridge_dir)

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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_cartridge.py -v`
Expected: 6 passed

If `test_parse_modules_returns_all_sixteen_in_cartridge_order` fails on count, print what was found before adjusting the parser — `module_meta.xml` is the source of truth and the expected count of 16 was verified during reconnaissance.

- [ ] **Step 6: Wire the stage into the CLI**

In `bin/si_archive.py`, replace the body of `run_stage` with a dispatch table and add the first entry:

```python
def run_stage(name, args):
    from pathlib import Path

    from si_archive import constants

    out = Path(args.out or constants.OUTPUT_ROOT)

    if name == "cartridge":
        from si_archive import cartridge
        course = cartridge.write_course_json(constants.CARTRIDGE_DIR,
                                             out / "_build" / "course.json")
        print(f"    {len(course['sections'])} sections")
        return

    raise NotImplementedError(f"stage {name!r} not yet implemented")
```

- [ ] **Step 7: Run the stage for real**

Run: `.venv/bin/python bin/si_archive.py cartridge --out /Volumes/Desk\ SSD/SystematicInnovation-Archive`
Expected: `16 sections`, and `_build/course.json` exists

- [ ] **Step 8: Commit**

```bash
git add si_archive/cartridge.py tests/test_cartridge.py tests/fixtures/ bin/si_archive.py
git commit -m "Add cartridge ingest stage

Parses module_meta.xml, imsmanifest.xml, assignments, discussions and QTI
into course.json -- the canonical 16-section spine. Surveys deliberately
omit the QTI varequal, which Canvas emits for surveys but which is just the
first option and means nothing."
```

---

## Task 3: Elucidat mirror

**Files:**
- Create: `si_archive/elucidat.py`
- Create: `tests/test_elucidat.py`
- Create: `tests/fixtures/elucidat/shell.html`, `tests/fixtures/elucidat/nav_snippet.js`, `tests/fixtures/elucidat/page.js`

**Interfaces:**
- Consumes: `si_archive.net.get`, `si_archive.net.Throttle`, `si_archive.constants.ELUCIDAT_PROJECTS`
- Produces:
  - `decode_lmth(reversed_html: str) -> str`
  - `parse_endpoint(shell_html: str) -> dict` — the `var endpoint = {...}` object, with keys `cdn`, `js`, `css`, `homepage`
  - `parse_navigation(project_js: str) -> dict` — `{"url_format": str, "pages": {page_id: {"n","p","sec",...}}}`
  - `page_order(nav: dict) -> list[str]` — page ids in reading order, sections before their children
  - `load_page_json(page_js: str) -> dict` — peels the `e._load_json(...)` wrapper
  - `rewrite_assets(page_html: str, asset_map: dict) -> str`
  - `mirror_project(key, code, out_dir, throttle) -> dict` — writes files, returns a project record
- Later tasks rely on: `elucidat.json` shape `{key: {"code","title","cdn","pages":[{"id","name","slug","file","vimeo":[...]}]}}`

- [ ] **Step 1: Create test fixtures**

Fetch one shell, one project JS navigation block, and one page. Paced, one time only.

```bash
cd /Users/jmill/coding/github/CanvasSync
mkdir -p tests/fixtures/elucidat
B="https://cdn.elucidat.com/5aaa306cbe9c3/projects/5f7356442004e/releases/5f7c8b919a261/50.5"
curl -sS --max-time 45 "https://learning.elucidat.com/course/5f7356442004e-5f7c8b919a261" \
  -o tests/fixtures/elucidat/shell.html
sleep 3
curl -sS --max-time 60 "$B/5f7c8b919a261.js" \
  | grep -o 'window.NAVIGATION_OBJECT=.*' | head -1 > tests/fixtures/elucidat/nav_snippet.js
sleep 3
curl -sS --max-time 45 "$B/5f735644979ac.js" -o tests/fixtures/elucidat/page.js
wc -c tests/fixtures/elucidat/*
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_elucidat.py`:

```python
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
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_elucidat.py -v`
Expected: FAIL with `ImportError: cannot import name 'elucidat'`

- [ ] **Step 4: Implement elucidat.py**

Create `si_archive/elucidat.py`:

```python
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_elucidat.py -v`
Expected: 8 passed

- [ ] **Step 6: Wire the stage into the CLI**

Add to `run_stage` in `bin/si_archive.py`, before the `raise`:

```python
    if name == "elucidat":
        import json

        from si_archive import elucidat
        from si_archive.net import Throttle
        throttle = Throttle(min_gap=args.min_gap, jitter=args.jitter,
                            rest_every=args.rest_every)
        projects = elucidat.mirror_all(out / "_source" / "elucidat", throttle)
        target = out / "_build" / "elucidat.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(projects, indent=2, ensure_ascii=False))
        total = sum(len(p["pages"]) for p in projects.values())
        print(f"    {len(projects)} projects, {total} pages")
        return
```

- [ ] **Step 7: Run the stage for real**

Run: `.venv/bin/python bin/si_archive.py elucidat --out /Volumes/Desk\ SSD/SystematicInnovation-Archive`
Expected: 7 projects, **70 pages** total (13/10/11/10/12/12/2). This takes several minutes — pacing is deliberate.

- [ ] **Step 8: Commit**

```bash
git add si_archive/elucidat.py tests/test_elucidat.py tests/fixtures/elucidat/ bin/si_archive.py
git commit -m "Add Elucidat mirror stage

Decodes the reversed-HTML 'lmth' payloads and bakes each page to static
HTML with CDN assets rewritten to local paths. Raw page JS is kept under
_source/ so a full-fidelity rebuild stays possible without re-fetching."
```

---

## Task 4: Vimeo download

**Files:**
- Create: `si_archive/vimeo.py`
- Create: `tests/test_vimeo.py`

**Interfaces:**
- Consumes: `elucidat.json` from Task 3
- Produces:
  - `collect_ids(elucidat_json: dict) -> list[dict]` — `[{"id","hash","projects":[key]}]`, deduplicated
  - `embed_url(vid: str, vhash: str|None) -> str`
  - `download(vid, vhash, out_dir) -> dict` — `{"id","status","path","title","duration","error"}` where `status` is `"ok"` or `"gap"`
  - `download_all(elucidat_json, out_dir, throttle) -> list[dict]`
- Later tasks rely on: `vimeo.json` — a list of those download records.

- [ ] **Step 1: Write the failing test**

Create `tests/test_vimeo.py`:

```python
from si_archive import vimeo


def test_embed_url_always_uses_the_player_form():
    # vimeo.com/<id> fails yt-dlp's OAuth path; player.vimeo.com works.
    assert vimeo.embed_url("464955563", None) == \
        "https://player.vimeo.com/video/464955563"


def test_embed_url_preserves_the_unlisted_hash():
    assert vimeo.embed_url("605462161", "50187719bc") == \
        "https://player.vimeo.com/video/605462161?h=50187719bc"


def test_collect_ids_deduplicates_across_projects_and_pages():
    doc = {
        "M1": {"pages": [
            {"vimeo": [{"id": "1", "hash": "a"}, {"id": "2", "hash": None}]},
            {"vimeo": [{"id": "1", "hash": "a"}]},
        ]},
        "M2": {"pages": [{"vimeo": [{"id": "1", "hash": "a"},
                                     {"id": "3", "hash": "c"}]}]},
    }
    ids = vimeo.collect_ids(doc)
    assert [v["id"] for v in ids] == ["1", "2", "3"]
    assert ids[0]["projects"] == ["M1", "M2"]
    assert ids[0]["hash"] == "a"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_vimeo.py -v`
Expected: FAIL with `ImportError: cannot import name 'vimeo'`

- [ ] **Step 3: Implement vimeo.py**

Create `si_archive/vimeo.py`:

```python
"""Stage 3 -- download the Vimeo videos the Elucidat pages embed.

Two access classes, both resolvable:
  * hashed  -- unlisted MIT PE recordings named MIT_INN_M<n>_V<n>; these are
               renditions of MP4s already on disk, reconciled in stage 5
  * bare id -- third-party reference material

Always request player.vimeo.com/video/<id>; the vimeo.com/<id> form fails
yt-dlp's OAuth token path. One id (777331374) returned a TLS-fingerprint block
during reconnaissance, so a --impersonate retry is built in.
"""
import json
import subprocess
from pathlib import Path

from si_archive import constants


def embed_url(vid, vhash):
    base = f"https://player.vimeo.com/video/{vid}"
    return f"{base}?h={vhash}" if vhash else base


def collect_ids(elucidat_json):
    """Deduplicate every embed across all projects, keeping first-seen order."""
    order, found = [], {}
    for key, project in elucidat_json.items():
        for page in project.get("pages", []):
            for ref in page.get("vimeo", []):
                vid = ref["id"]
                if vid not in found:
                    found[vid] = {"id": vid, "hash": ref.get("hash"), "projects": []}
                    order.append(vid)
                if ref.get("hash") and not found[vid]["hash"]:
                    found[vid]["hash"] = ref["hash"]
                if key not in found[vid]["projects"]:
                    found[vid]["projects"].append(key)
    return [found[v] for v in order]


def _run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=1800)


def download(vid, vhash, out_dir):
    """Fetch one video plus any native captions. Never raises -- returns a record."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    url = embed_url(vid, vhash)
    template = str(out_dir / f"{vid} - %(title)s.%(ext)s")

    base = ["yt-dlp", "--no-warnings", "--no-playlist",
            "--referer", constants.ELUCIDAT_REFERER,
            "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "--write-subs", "--sub-langs", "all", "--convert-subs", "srt",
            "--print", "after_move:%(filepath)s|%(title)s|%(duration)s",
            "-o", template, url]

    result = _run(base)
    if result.returncode != 0 and "TLS fingerprint" in (result.stderr or ""):
        # Anti-bot fingerprinting; curl-cffi lets yt-dlp present a real browser TLS profile.
        result = _run(base[:1] + ["--impersonate", "chrome"] + base[1:])

    if result.returncode != 0:
        return {"id": vid, "status": "gap", "path": None, "title": None,
                "duration": None, "error": (result.stderr or "").strip()[-500:]}

    line = (result.stdout or "").strip().splitlines()[-1]
    path, title, duration = (line.split("|", 2) + [None, None])[:3]
    try:
        duration = float(duration)
    except (TypeError, ValueError):
        duration = None
    return {"id": vid, "status": "ok", "path": path, "title": title,
            "duration": duration, "error": None}


def download_all(elucidat_json, out_dir, throttle):
    records = []
    targets = collect_ids(elucidat_json)
    for index, ref in enumerate(targets, start=1):
        throttle.wait("https://player.vimeo.com/")
        record = download(ref["id"], ref["hash"], out_dir)
        record["projects"] = ref["projects"]
        status = record["title"] if record["status"] == "ok" else "GAP"
        print(f"    [{index}/{len(targets)}] {ref['id']}: {status}")
        records.append(record)
    return records
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_vimeo.py -v`
Expected: 3 passed

- [ ] **Step 5: Wire the stage into the CLI**

Add to `run_stage`:

```python
    if name == "vimeo":
        import json

        from si_archive import vimeo
        from si_archive.net import Throttle
        doc = json.loads((out / "_build" / "elucidat.json").read_text())
        throttle = Throttle(min_gap=max(args.min_gap, 3.0), jitter=args.jitter,
                            rest_every=args.rest_every)
        records = vimeo.download_all(doc, out / "_build" / "vimeo", throttle)
        (out / "_build" / "vimeo.json").write_text(
            json.dumps(records, indent=2, ensure_ascii=False))
        gaps = [r for r in records if r["status"] == "gap"]
        print(f"    {len(records)} videos, {len(gaps)} gaps")
        return
```

- [ ] **Step 6: Run the stage for real**

Run: `.venv/bin/python bin/si_archive.py vimeo --out /Volumes/Desk\ SSD/SystematicInnovation-Archive`
Expected: 36 videos attempted. Any gaps are recorded, not fatal. Verify at least one title reads `MIT_INN_M1_V2` — that is the rendition match stage 5 depends on.

- [ ] **Step 7: Commit**

```bash
git add si_archive/vimeo.py tests/test_vimeo.py bin/si_archive.py
git commit -m "Add Vimeo download stage

Uses the player.vimeo.com form throughout -- the vimeo.com/<id> form fails
yt-dlp's OAuth path. Retries TLS-fingerprint blocks with --impersonate and
records unresolvable ids as gaps rather than failing the run."
```

---

## Task 5: Local source index

**Files:**
- Create: `si_archive/localsrc.py`
- Create: `tests/test_localsrc.py`

**Interfaces:**
- Consumes: `constants.CAMPUS_DIR`, `constants.GDRIVE_DIR`, `constants.PROVENANCE_PDF`
- Produces:
  - `is_student_work(path: Path) -> bool`
  - `sha256(path: Path) -> str`
  - `probe_duration(path: Path) -> float | None` — via ffprobe, `None` for non-media
  - `index_tree(root: Path, source: str) -> list[dict]` — `[{"source","path","relpath","size","sha256","duration","ext"}]`
  - `build_index() -> list[dict]`
- Later tasks rely on: every record having `sha256`, and `duration` populated for `.mp4`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_localsrc.py`:

```python
from pathlib import Path

from si_archive import localsrc


def test_is_student_work_matches_a_submissions_directory():
    p = Path("/x/Module 1/Assignment/1682350566_563__SISH_submissions/essay.docx")
    assert localsrc.is_student_work(p)


def test_is_student_work_matches_a_text_html_dump():
    assert localsrc.is_student_work(Path("/x/calmetricardo_6908_text.html"))


def test_is_student_work_allows_ordinary_course_media():
    assert not localsrc.is_student_work(Path("/x/Module 1/MIT_INN_M1_V1.mp4"))
    assert not localsrc.is_student_work(Path("/x/pre/Code of Conduct MIT - ENG.pdf"))


def test_sha256_matches_a_known_digest(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("hello")
    assert localsrc.sha256(f) == (
        "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824")


def test_index_tree_skips_student_work(tmp_path):
    (tmp_path / "ok.txt").write_text("keep")
    sub = tmp_path / "1682_x_submissions"
    sub.mkdir()
    (sub / "essay.docx").write_text("drop")
    (tmp_path / "someone_1234_text.html").write_text("drop")

    records = localsrc.index_tree(tmp_path, source="test")
    names = [Path(r["path"]).name for r in records]
    assert names == ["ok.txt"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_localsrc.py -v`
Expected: FAIL with `ImportError: cannot import name 'localsrc'`

- [ ] **Step 3: Implement localsrc.py**

Create `si_archive/localsrc.py`:

```python
"""Stage 4 -- index the local sources by content hash.

Student work is excluded here, at the index, so no later stage can copy or
link it by accident. What is kept is the instructor-authored course material:
prompts, rubrics, media, reference documents.
"""
import fnmatch
import hashlib
import json
import subprocess
from pathlib import Path

from si_archive import constants

MEDIA_EXTS = {".mp4", ".m4v", ".mov", ".mp3", ".m4a", ".wav"}
SKIP_NAMES = {".DS_Store"}


def is_student_work(path):
    path = Path(path)
    if fnmatch.fnmatch(path.name, constants.STUDENT_WORK_FILE_GLOB):
        return True
    return any(fnmatch.fnmatch(part, constants.STUDENT_WORK_DIR_GLOB)
               for part in path.parts)


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def probe_duration(path):
    if Path(path).suffix.lower() not in MEDIA_EXTS:
        return None
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, timeout=120)
        return float(result.stdout.strip())
    except (ValueError, subprocess.SubprocessError):
        return None


def index_tree(root, source):
    root = Path(root)
    records = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name in SKIP_NAMES:
            continue
        # ScreenFlow bundles are directories; never descend into one.
        if any(part.endswith(".screenflow") for part in path.parts):
            continue
        if is_student_work(path):
            continue
        records.append({
            "source": source,
            "path": str(path),
            "relpath": str(path.relative_to(root)),
            "size": path.stat().st_size,
            "sha256": sha256(path),
            "duration": probe_duration(path),
            "ext": path.suffix.lower(),
        })
    return records


def index_screenflow_bundles(root):
    """Referenced, not copied -- 9.5GB of editable production masters."""
    return [{"source": "screenflow", "path": str(p), "relpath": p.name,
             "size": sum(f.stat().st_size for f in p.rglob("*") if f.is_file()),
             "sha256": None, "duration": None, "ext": ".screenflow"}
            for p in sorted(Path(root).rglob("*.screenflow"))]


def build_index():
    records = []
    records += index_tree(constants.CAMPUS_DIR, "campus")
    records += index_tree(constants.GDRIVE_DIR, "gdrive")
    records += index_screenflow_bundles(constants.CAMPUS_DIR)
    pdf = Path(constants.PROVENANCE_PDF)
    if pdf.exists():
        records.append({
            "source": "provenance", "path": str(pdf), "relpath": pdf.name,
            "size": pdf.stat().st_size, "sha256": sha256(pdf),
            "duration": None, "ext": ".pdf",
        })
    return records
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_localsrc.py -v`
Expected: 5 passed

- [ ] **Step 5: Wire the stage into the CLI**

Add to `run_stage`:

```python
    if name == "local":
        import json

        from si_archive import localsrc
        records = localsrc.build_index()
        target = out / "_build" / "local.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(records, indent=2, ensure_ascii=False))
        mp4 = [r for r in records if r["ext"] == ".mp4"]
        print(f"    {len(records)} files, {len(mp4)} mp4")
        return
```

- [ ] **Step 6: Run the stage for real**

Run: `.venv/bin/python bin/si_archive.py local --out /Volumes/Desk\ SSD/SystematicInnovation-Archive`
Expected: **47 mp4** (49 on disk minus the 2 inside student submission bundles). Hashing 8 GB takes a few minutes.

If the mp4 count is 49, the student-work exclusion is not firing — check `is_student_work` against the real submission paths before continuing.

- [ ] **Step 7: Commit**

```bash
git add si_archive/localsrc.py tests/test_localsrc.py bin/si_archive.py
git commit -m "Add local source index stage

SHA-256 and ffprobe duration for every local file, with student submissions
excluded at the index so no later stage can link them. ScreenFlow bundles are
recorded by path and size only -- 9.5GB of editable masters, not deliverables."
```

---

## Task 6: Reconcile — dedupe and rendition matching

**Files:**
- Create: `si_archive/reconcile.py`
- Create: `tests/test_reconcile.py`

**Interfaces:**
- Consumes: `local.json` (Task 5), `vimeo.json` (Task 4)
- Produces:
  - `normalize_title(text: str) -> str`
  - `group_by_hash(records: list[dict]) -> list[dict]` — `[{"sha256","canonical","aliases":[str],"size"}]`
  - `match_renditions(local: list[dict], vimeo: list[dict], tolerance=1.0) -> list[dict]` — `[{"work","local_path","vimeo_id","local_duration","vimeo_duration","canonical","reason"}]`
  - `build_ledger(local, vimeo) -> dict` — `{"files":[...], "renditions":[...], "stats":{...}}`
- Later tasks rely on: `ledger.json` keys `files` and `renditions`.

**Design note.** Two relationships, handled separately. Byte-identical files collapse by SHA-256 — the cartridge alone ships three copies of the program outline. Different encodings of the same work cannot hash-match, so Vimeo downloads pair with local MP4s on normalized title and duration within ±1 s. The larger file wins as canonical; the loser is *recorded*, never deleted from the record.

- [ ] **Step 1: Write the failing test**

Create `tests/test_reconcile.py`:

```python
from si_archive import reconcile


def test_normalize_title_strips_extension_case_and_punctuation():
    assert reconcile.normalize_title("MIT_INN_M1_V2.mp4") == "mit inn m1 v2"
    assert reconcile.normalize_title("MIT_INN_M1_V2") == "mit inn m1 v2"
    assert reconcile.normalize_title("Grove Our Mission -  - 2023-04-24 13-04-00") == \
        "grove our mission 2023 04 24 13 04 00"


def test_group_by_hash_collapses_duplicates_and_keeps_aliases():
    records = [
        {"path": "/a/Outline.pdf", "sha256": "aa", "size": 10},
        {"path": "/b/Outline (2).pdf", "sha256": "aa", "size": 10},
        {"path": "/c/other.pdf", "sha256": "bb", "size": 20},
    ]
    groups = {g["sha256"]: g for g in reconcile.group_by_hash(records)}
    assert len(groups) == 2
    assert groups["aa"]["canonical"] == "/a/Outline.pdf"
    assert groups["aa"]["aliases"] == ["/b/Outline (2).pdf"]
    assert groups["bb"]["aliases"] == []


def test_match_renditions_pairs_vimeo_with_the_local_mp4():
    local = [{"path": "/x/Module 1/MIT_INN_M1_V2.mp4",
              "duration": 258.0, "size": 90_000_000, "ext": ".mp4"}]
    vimeo = [{"id": "605462161", "status": "ok", "title": "MIT_INN_M1_V2",
              "duration": 258.0, "path": "/v/605462161 - MIT_INN_M1_V2.mp4"}]
    matches = reconcile.match_renditions(local, vimeo)
    assert len(matches) == 1
    assert matches[0]["vimeo_id"] == "605462161"
    assert matches[0]["local_path"].endswith("MIT_INN_M1_V2.mp4")


def test_match_renditions_prefers_the_larger_file_as_canonical():
    local = [{"path": "/x/clarke.mp4", "duration": 343.0,
              "size": 16_000_000, "ext": ".mp4"}]
    vimeo = [{"id": "493369035", "status": "ok", "title": "clarke",
              "duration": 343.0, "path": "/v/493369035 - clarke.mp4",
              "size": 90_000_000}]
    match = reconcile.match_renditions(local, vimeo)[0]
    assert match["canonical"] == "/v/493369035 - clarke.mp4"


def test_match_renditions_ignores_a_duration_mismatch():
    local = [{"path": "/x/a.mp4", "duration": 100.0, "size": 1, "ext": ".mp4"}]
    vimeo = [{"id": "9", "status": "ok", "title": "a", "duration": 400.0,
              "path": "/v/9 - a.mp4"}]
    assert reconcile.match_renditions(local, vimeo) == []


def test_match_renditions_skips_failed_downloads():
    local = [{"path": "/x/a.mp4", "duration": 100.0, "size": 1, "ext": ".mp4"}]
    vimeo = [{"id": "9", "status": "gap", "title": None, "duration": None,
              "path": None}]
    assert reconcile.match_renditions(local, vimeo) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_reconcile.py -v`
Expected: FAIL with `ImportError: cannot import name 'reconcile'`

- [ ] **Step 3: Implement reconcile.py**

Create `si_archive/reconcile.py`:

```python
"""Stage 5 -- deduplicate and rendition-match into a single ledger.

Three relationships between copies of the same thing:

  1. byte-identical      -- collapse by SHA-256, keep aliases
  2. same work, different encoding -- cannot hash-match; pair on normalized
     title and duration, keep the better copy, record the other
  3. distinct works      -- keep separately

Nothing is deleted from the record. A file that loses to a better rendition is
still named in the ledger, so the archive can always say what it chose and why.
"""
import json
import re
import unicodedata
from pathlib import Path


def normalize_title(text):
    """Fold to lowercase words so 'MIT_INN_M1_V2.mp4' == 'MIT_INN_M1_V2'."""
    if not text:
        return ""
    stem = Path(text).stem if "." in Path(text).name else text
    folded = unicodedata.normalize("NFKD", stem)
    folded = folded.encode("ascii", "ignore").decode("ascii")
    folded = re.sub(r"[^\w\s]", " ", folded)
    return re.sub(r"\s+", " ", folded.replace("_", " ")).strip().lower()


def group_by_hash(records):
    """Collapse byte-identical files. First-seen path wins as canonical."""
    groups = {}
    for record in records:
        digest = record.get("sha256")
        if not digest:
            continue
        group = groups.setdefault(digest, {"sha256": digest, "canonical": record["path"],
                                           "aliases": [], "size": record.get("size")})
        if record["path"] != group["canonical"]:
            group["aliases"].append(record["path"])
    return list(groups.values())


def match_renditions(local, vimeo, tolerance=1.0):
    """Pair Vimeo downloads with local MP4s of the same work."""
    candidates = [r for r in local
                  if r.get("ext") == ".mp4" and r.get("duration")]
    matches = []
    for video in vimeo:
        if video.get("status") != "ok" or not video.get("duration"):
            continue
        vtitle = normalize_title(video.get("title") or "")
        for record in candidates:
            if abs(record["duration"] - video["duration"]) > tolerance:
                continue
            if normalize_title(Path(record["path"]).name) != vtitle:
                continue
            local_size = record.get("size") or 0
            vimeo_size = video.get("size") or 0
            if vimeo_size > local_size:
                canonical, reason = video["path"], "vimeo copy is larger"
            else:
                canonical, reason = record["path"], "local copy is at least as large"
            matches.append({
                "work": vtitle,
                "local_path": record["path"],
                "vimeo_id": video["id"],
                "vimeo_path": video.get("path"),
                "local_duration": record["duration"],
                "vimeo_duration": video["duration"],
                "canonical": canonical,
                "reason": reason,
            })
            break
    return matches


def build_ledger(local, vimeo):
    files = group_by_hash(local)
    renditions = match_renditions(local, vimeo)
    matched_ids = {m["vimeo_id"] for m in renditions}
    online_only = [v for v in vimeo
                   if v.get("status") == "ok" and v["id"] not in matched_ids]
    gaps = [v for v in vimeo if v.get("status") == "gap"]
    return {
        "files": files,
        "renditions": renditions,
        "online_only": online_only,
        "gaps": gaps,
        "stats": {
            "local_records": len(local),
            "unique_files": len(files),
            "duplicate_paths": sum(len(f["aliases"]) for f in files),
            "renditions": len(renditions),
            "online_only": len(online_only),
            "vimeo_gaps": len(gaps),
        },
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_reconcile.py -v`
Expected: 6 passed

- [ ] **Step 5: Wire the stage into the CLI**

Add to `run_stage`:

```python
    if name == "reconcile":
        import json

        from si_archive import reconcile
        local = json.loads((out / "_build" / "local.json").read_text())
        vimeo_records = json.loads((out / "_build" / "vimeo.json").read_text())
        ledger = reconcile.build_ledger(local, vimeo_records)
        (out / "_build" / "ledger.json").write_text(
            json.dumps(ledger, indent=2, ensure_ascii=False))
        for key, value in ledger["stats"].items():
            print(f"    {key}: {value}")
        return
```

- [ ] **Step 6: Run the stage for real**

Run: `.venv/bin/python bin/si_archive.py reconcile --out /Volumes/Desk\ SSD/SystematicInnovation-Archive`
Expected: non-zero `duplicate_paths` (the program outline ships three times) and non-zero `renditions` (the `MIT_INN_*` videos). If `renditions` is 0, print a few Vimeo titles next to local filenames and check `normalize_title` against them before continuing.

- [ ] **Step 7: Commit**

```bash
git add si_archive/reconcile.py tests/test_reconcile.py bin/si_archive.py
git commit -m "Add reconcile stage

Collapses byte-identical files by SHA-256 and pairs Vimeo downloads with the
local MP4s they duplicate on normalized title plus duration within 1s. The
losing rendition stays in the ledger so every choice is auditable."
```

---

## Task 7: Transcripts and contact sheets

**Files:**
- Create: `si_archive/media.py`
- Create: `tests/test_media.py`

**Interfaces:**
- Consumes: `ledger.json`, `local.json`
- Produces:
  - `srt_to_markdown(srt_text: str) -> str`
  - `needs_transcription(record: dict, srt_index: set) -> bool`
  - `transcribe(mp4_path: Path, out_path: Path) -> dict`
  - `contact_sheet(mp4_path: Path, out_path: Path, duration: float) -> Path | None`
  - `derive_all(ledger, local, out_dir) -> list[dict]`
- Later tasks rely on: every video having either a `.transcript.md` beside it or a logged reason.

**Design note.** 20 MP4s need transcription — 22 lack an SRT, of which 2 are student submissions already excluded at the index. `mlx-whisper` runs `large-v3` on Metal. Existing SRTs convert to the same `.transcript.md` shape so the site has one artifact type regardless of origin.

- [ ] **Step 1: Write the failing test**

Create `tests/test_media.py`:

```python
from si_archive import media

SRT = """1
00:00:01,000 --> 00:00:04,000
Innovation is not a bolt of lightning.

2
00:00:04,500 --> 00:00:07,000
It is a method you can practise.
"""


def test_srt_to_markdown_keeps_text_and_drops_cue_numbers():
    out = media.srt_to_markdown(SRT)
    assert "Innovation is not a bolt of lightning." in out
    assert "It is a method you can practise." in out
    assert "00:00:01,000" not in out
    assert "\n1\n" not in out


def test_srt_to_markdown_joins_cues_into_flowing_text():
    out = media.srt_to_markdown(SRT)
    assert "lightning. It is a method" in out


def test_needs_transcription_is_false_when_a_sibling_srt_exists():
    record = {"path": "/x/MIT_INN_M1_V1.mp4", "ext": ".mp4"}
    assert not media.needs_transcription(record, {"/x/MIT_INN_M1_V1.srt"})


def test_needs_transcription_is_true_without_an_srt():
    record = {"path": "/x/webinar.mp4", "ext": ".mp4"}
    assert media.needs_transcription(record, set())


def test_needs_transcription_ignores_non_video():
    record = {"path": "/x/notes.pdf", "ext": ".pdf"}
    assert not media.needs_transcription(record, set())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_media.py -v`
Expected: FAIL with `ImportError: cannot import name 'media'`

- [ ] **Step 3: Implement media.py**

Create `si_archive/media.py`:

```python
"""Stage 6 -- one transcript per video, contact sheets for the long ones.

27 of the 47 archived MP4s ship with an SRT. The other 20 are transcribed with
mlx-whisper (large-v3, Metal-accelerated on Apple Silicon). Existing SRTs are
converted to the same markdown shape so the site presents one artifact type
regardless of where the text came from.
"""
import re
import subprocess
from pathlib import Path

from si_archive import constants

TIMECODE_RE = re.compile(r"^\d{2}:\d{2}:\d{2}[,.]\d{3}\s*-->")


def srt_to_markdown(srt_text):
    """Strip cue numbers and timecodes; join the text into flowing paragraphs."""
    lines = []
    for raw in srt_text.splitlines():
        line = raw.strip()
        if not line or line.isdigit() or TIMECODE_RE.match(line):
            continue
        # Some exports leave a stray WEBVTT header on the first line.
        if line.upper().startswith("WEBVTT"):
            continue
        lines.append(line)
    return " ".join(lines).strip() + "\n"


def needs_transcription(record, srt_index):
    if record.get("ext") not in {".mp4", ".m4v", ".mov"}:
        return False
    return str(Path(record["path"]).with_suffix(".srt")) not in srt_index


def transcribe(mp4_path, out_path):
    """mlx-whisper large-v3. Returns a record; never raises."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        result = subprocess.run(
            ["mlx_whisper", "--model", "mlx-community/whisper-large-v3-mlx",
             "--output-format", "srt", "--output-dir", str(out_path.parent),
             str(mp4_path)],
            capture_output=True, text=True, timeout=7200)
    except subprocess.SubprocessError as exc:
        return {"path": str(mp4_path), "status": "gap", "error": str(exc)}
    if result.returncode != 0:
        return {"path": str(mp4_path), "status": "gap",
                "error": (result.stderr or "").strip()[-500:]}
    produced = out_path.parent / (Path(mp4_path).stem + ".srt")
    if not produced.exists():
        return {"path": str(mp4_path), "status": "gap",
                "error": "mlx_whisper produced no srt"}
    out_path.write_text(srt_to_markdown(produced.read_text()))
    return {"path": str(mp4_path), "status": "ok", "transcript": str(out_path),
            "source": "whisper"}


def contact_sheet(mp4_path, out_path, duration):
    """A 4x4 tile sheet for videos worth skimming. None if too short."""
    if not duration or duration < constants.CONTACTSHEET_MIN_SECONDS:
        return None
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    interval = max(duration / 16.0, 1.0)
    result = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(mp4_path),
         "-vf", f"fps=1/{interval:.3f},scale=320:-1,tile=4x4",
         "-frames:v", "1", str(out_path)],
        capture_output=True, text=True, timeout=1800)
    return out_path if result.returncode == 0 and out_path.exists() else None


def derive_all(local, out_dir):
    out_dir = Path(out_dir)
    srt_index = {r["path"] for r in local if r.get("ext") == ".srt"}
    records = []
    videos = [r for r in local if r.get("ext") in {".mp4", ".m4v", ".mov"}]
    for index, record in enumerate(videos, start=1):
        stem = Path(record["path"]).stem
        transcript = out_dir / "transcripts" / f"{stem}.transcript.md"
        if needs_transcription(record, srt_index):
            print(f"    [{index}/{len(videos)}] whisper: {stem}")
            result = transcribe(record["path"], transcript)
        else:
            srt = Path(record["path"]).with_suffix(".srt")
            transcript.parent.mkdir(parents=True, exist_ok=True)
            transcript.write_text(
                srt_to_markdown(srt.read_text(encoding="utf-8", errors="replace")))
            result = {"path": record["path"], "status": "ok",
                      "transcript": str(transcript), "source": "srt"}
        sheet = contact_sheet(record["path"],
                              out_dir / "contactsheets" / f"{stem}.jpg",
                              record.get("duration"))
        result["contactsheet"] = str(sheet) if sheet else None
        records.append(result)
    return records
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_media.py -v`
Expected: 5 passed

- [ ] **Step 5: Verify mlx-whisper works before committing to a long run**

```bash
cd /Users/jmill/coding/github/CanvasSync
.venv/bin/python -c "import mlx_whisper; print('mlx_whisper ok')"
which mlx_whisper || .venv/bin/python -m pip show mlx-whisper
```

If the `mlx_whisper` CLI is absent, invoke it as `.venv/bin/python -m mlx_whisper` in `transcribe` instead. Test on the shortest video first:

```bash
.venv/bin/python -c "
from si_archive import media
from pathlib import Path
r = media.transcribe(
    '/Users/jmill/MIT Dropbox/Jonathan Miller/teaching/Systematic Innovation/campus.mitpeonline.com/Module 1/references/Theodore Maiman Explains the First Ruby Laser.mp4',
    Path('/tmp/maiman.transcript.md'))
print(r)
print(Path('/tmp/maiman.transcript.md').read_text()[:300])
"
```

Expected: readable English prose about the ruby laser.

- [ ] **Step 6: Wire the stage into the CLI**

Add to `run_stage`:

```python
    if name == "media":
        import json

        from si_archive import media
        local = json.loads((out / "_build" / "local.json").read_text())
        records = media.derive_all(local, out / "_build")
        (out / "_build" / "media.json").write_text(
            json.dumps(records, indent=2, ensure_ascii=False))
        ok = [r for r in records if r["status"] == "ok"]
        sheets = [r for r in records if r.get("contactsheet")]
        print(f"    {len(ok)}/{len(records)} transcripts, {len(sheets)} contact sheets")
        return
```

- [ ] **Step 7: Run the stage for real**

Run: `.venv/bin/python bin/si_archive.py media --out /Volumes/Desk\ SSD/SystematicInnovation-Archive`
Expected: 47 transcripts (27 converted from SRT, 20 from Whisper). This is the slow stage — 8.7 hours of audio. Run it and let it finish.

- [ ] **Step 8: Commit**

```bash
git add si_archive/media.py tests/test_media.py bin/si_archive.py
git commit -m "Add transcript and contact sheet stage

Converts the 27 existing SRTs and Whisper-transcribes the other 20 videos
into one markdown shape, plus 4x4 contact sheets for anything over 3 minutes."
```

---

## Task 8: Render the site

**Files:**
- Create: `si_archive/render.py`
- Create: `si_archive/reveal.css`
- Create: `tests/test_render.py`

**Interfaces:**
- Consumes: `course.json`, `elucidat.json`, `ledger.json`, `media.json`
- Produces:
  - `rewrite_filebase(html: str, depth: int) -> str` — turns `%24IMS-CC-FILEBASE%24/...` into a relative path
  - `strip_canvas_query(url: str) -> str` — drops `?canvas_download=1` and friends
  - `page_shell(title: str, body: str, depth: int, nav_html: str = "") -> str`
  - `render_site(build_dir: Path, out_dir: Path) -> dict`
- Later tasks rely on: `index.html` at the archive root and one directory per section named by `course.json`'s `dirname`.

**Design note — reveal.** Elucidat hides most content behind accordions, modals and carousels: one sampled page was 66 KB of HTML yielding 9 KB of visible text, with 56 accordion and 48 modal references. `reveal.css` force-expands all of it into linear flow. Interactivity is lost; content is not.

- [ ] **Step 1: Write reveal.css**

Create `si_archive/reveal.css`:

```css
/* Force every deferred Elucidat component into linear document flow.
   Interactive e-learning hides content for pacing, not secrecy -- a modal is
   a paragraph with a delay. Expanding it costs the pedagogy and keeps the idea. */

.collapse, .collapsing, .accordion-body, .accordion-collapse,
.tab-pane, .carousel-item, .modal, .modal-dialog, .modal-content,
.e-hidden, .hidden, [aria-hidden="true"] {
    display: block !important;
    visibility: visible !important;
    opacity: 1 !important;
    height: auto !important;
    max-height: none !important;
    overflow: visible !important;
    position: static !important;
    transform: none !important;
}

/* Carousels stack instead of overlapping. */
.carousel-inner, .carousel { height: auto !important; }
.carousel-item { float: none !important; margin-bottom: 1.5rem; }

/* Modals become inline blocks, not overlays. */
.modal {
    background: transparent !important;
    z-index: auto !important;
    border: 1px solid #d8d8d8;
    margin: 1.5rem 0;
    padding: 1rem;
}
.modal-backdrop { display: none !important; }

/* Player chrome that means nothing offline. */
.project__header, .project__footer, .toolbar, .progress_bar,
.pager, .menu__body { display: none !important; }

/* Anything the reveal rules expanded gets a readable width. */
body { max-width: 60rem; margin: 0 auto; padding: 2rem 1.5rem; }
img, video { max-width: 100%; height: auto; }
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_render.py`:

```python
from si_archive import render


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
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_render.py -v`
Expected: FAIL with `ImportError: cannot import name 'render'`

- [ ] **Step 4: Implement render.py**

Create `si_archive/render.py`:

```python
"""Stage 7 -- emit the static site.

Section order and numbering come from the cartridge, not from Elucidat: the
cartridge's 16 sections are the course as taught, including the surveys and the
three-way split of Module 1.
"""
import html as html_mod
import json
import re
import shutil
from pathlib import Path

FILEBASE_RE = re.compile(r"%24IMS-CC-FILEBASE%24(/[^\"'\s>]*)")
CANVAS_QS_RE = re.compile(r"\?(?:canvas_|amp;canvas_)[^\"'\s>]*")

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


def render_quiz(quiz):
    """Surveys render as questionnaires -- no 'correct' answer is asserted."""
    parts = [f"<h1>{html_mod.escape(quiz['title'])}</h1>", quiz["description_html"]]
    if quiz["is_survey"]:
        parts.append("<p><em>This is a survey. No answer is scored as correct.</em></p>")
    for question in quiz["questions"]:
        parts.append(f"<h3>{html_mod.escape(question['title'])}</h3>")
        parts.append(question["prompt_html"])
        if question["options"]:
            items = "".join(
                f"<li>{html_mod.escape(o)}</li>" for o in question["options"])
            parts.append(f"<ol>{items}</ol>")
        if question.get("correct") and not quiz["is_survey"]:
            parts.append(
                f"<p><strong>Correct:</strong> "
                f"{html_mod.escape(question['correct'])}</p>")
    return "\n".join(parts)


def render_site(build_dir, out_dir):
    build_dir, out_dir = Path(build_dir), Path(out_dir)
    course = json.loads((build_dir / "course.json").read_text())
    elucidat = json.loads((build_dir / "elucidat.json").read_text())
    out_dir.mkdir(parents=True, exist_ok=True)

    shutil.copy(Path(__file__).parent / "reveal.css", out_dir / "reveal.css")

    written = 0
    rows = []
    for section in course["sections"]:
        directory = out_dir / "sections" / section["dirname"]
        directory.mkdir(parents=True, exist_ok=True)
        items = "".join(
            f"<li>{html_mod.escape(i['title'])} "
            f"<em>({html_mod.escape(i['content_type'])})</em></li>"
            for i in section["items"])
        body = (f"<h1>{html_mod.escape(section['title'])}</h1>"
                f"<ul>{items}</ul>")
        (directory / "index.html").write_text(
            page_shell(section["title"], rewrite_filebase(body, depth=2), depth=2))
        written += 1
        rows.append(f'<li><a href="sections/{section["dirname"]}/index.html">'
                    f'{html_mod.escape(section["title"])}</a></li>')

    # Elucidat pages, wrapped in the shell with the reveal stylesheet applied.
    for key, project in elucidat.items():
        directory = out_dir / "elucidat" / key
        directory.mkdir(parents=True, exist_ok=True)
        source_dir = build_dir.parent / "_source" / "elucidat" / key
        if (source_dir / "assets").exists():
            shutil.copytree(source_dir / "assets", directory / "assets",
                            dirs_exist_ok=True)
        for page in project["pages"]:
            raw = (source_dir / f"{page['slug']}.html")
            if not raw.exists():
                continue
            (directory / f"{page['slug']}.html").write_text(
                page_shell(page["name"], raw.read_text(), depth=2))
            written += 1

    index = (f"<h1>{html_mod.escape(course['title'])}</h1>"
             f"<p>{html_mod.escape(course['course_code'])}</p>"
             f"<ol>{''.join(rows)}</ol>")
    (out_dir / "index.html").write_text(page_shell(course["title"], index, depth=0))
    return {"pages_written": written + 1, "sections": len(course["sections"])}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_render.py -v`
Expected: 5 passed

- [ ] **Step 6: Copy files and media into the archive**

Add to `si_archive/render.py`, above `render_site`:

```python
def section_dir_for(course, section_title):
    """Cartridge section title -> its numbered output directory name."""
    for section in course["sections"]:
        if section["title"] == section_title:
            return f"sections/{section['dirname']}"
    return None


def destination_for(local_path, course):
    """Which output directory a campus media file belongs in.

    Campus media is organised by the folder it sits in, not by filename, so the
    mapping is folder-level and explicit. Anything outside the known folders
    goes to files/ rather than being dropped.
    """
    from si_archive import constants

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


def place_media(course, ledger, media_records, out_dir):
    """Copy each canonical video plus its transcript and contact sheet.

    Aliases and losing renditions are skipped -- the ledger already records
    that they existed and why they lost.
    """
    out_dir = Path(out_dir)
    skip = {alias for group in ledger["files"] for alias in group["aliases"]}
    for match in ledger["renditions"]:
        loser = (match["local_path"] if match["canonical"] != match["local_path"]
                 else match["vimeo_path"])
        if loser:
            skip.add(loser)

    derived = {record["path"]: record for record in media_records}
    placed = 0
    for group in ledger["files"]:
        source = Path(group["canonical"])
        if str(source) in skip or source.suffix.lower() != ".mp4":
            continue
        if not source.exists():
            continue
        target_dir = out_dir / destination_for(source, course) / "media"
        target_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target_dir / source.name)
        placed += 1

        srt = source.with_suffix(".srt")
        if srt.exists():
            shutil.copy2(srt, target_dir / srt.name)

        record = derived.get(str(source), {})
        for key, suffix in (("transcript", ".transcript.md"),
                            ("contactsheet", ".contactsheet.jpg")):
            value = record.get(key)
            if value and Path(value).exists():
                shutil.copy2(value, target_dir / (source.stem + suffix))
    return placed
```

Then call it from `render_site`, just before the `index` assignment, replacing
the `web_resources` snippet with:

```python
    from si_archive import constants
    resources = Path(constants.CARTRIDGE_DIR) / "web_resources"
    if resources.exists():
        shutil.copytree(resources, out_dir / "files", dirs_exist_ok=True)

    ledger_path = build_dir / "ledger.json"
    media_path = build_dir / "media.json"
    if ledger_path.exists() and media_path.exists():
        placed = place_media(course,
                             json.loads(ledger_path.read_text()),
                             json.loads(media_path.read_text()),
                             out_dir)
    else:
        placed = 0
```

and add `"media_placed": placed` to the dict `render_site` returns.

Add these tests to `tests/test_render.py`:

```python
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
```

Run: `.venv/bin/python -m pytest tests/test_render.py -v`
Expected: 8 passed

- [ ] **Step 7: Wire the stage into the CLI and run it**

Add to `run_stage`:

```python
    if name == "render":
        from si_archive import render
        stats = render.render_site(out / "_build", out)
        print(f"    {stats['pages_written']} pages, {stats['sections']} sections")
        return
```

Run: `.venv/bin/python bin/si_archive.py render --out /Volumes/Desk\ SSD/SystematicInnovation-Archive`
Then open it: `open "/Volumes/Desk SSD/SystematicInnovation-Archive/index.html"`
Expected: 16 sections listed; clicking through to an Elucidat page shows fully expanded content with images loading.

- [ ] **Step 8: Commit**

```bash
git add si_archive/render.py si_archive/reveal.css tests/test_render.py bin/si_archive.py
git commit -m "Add site render stage

Emits the static site in cartridge section order with reveal.css force-expanding
Elucidat's accordions, modals and carousels into linear flow. Surveys render as
questionnaires rather than asserting a correct answer."
```

---

## Task 9: Verify and report

**Files:**
- Create: `si_archive/verify.py`
- Create: `tests/test_verify.py`

**Interfaces:**
- Consumes: the built archive plus every `_build/*.json`
- Produces:
  - `find_broken_links(out_dir: Path) -> list[dict]`
  - `find_student_work(out_dir: Path) -> list[str]`
  - `check_reveal(out_dir: Path, min_ratio=0.05) -> list[dict]`
  - `build_report(out_dir: Path) -> str`
- Later tasks rely on: `REPORT.md` at the archive root.

- [ ] **Step 1: Write the failing test**

Create `tests/test_verify.py`:

```python
from si_archive import verify


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_verify.py -v`
Expected: FAIL with `ImportError: cannot import name 'verify'`

- [ ] **Step 3: Implement verify.py**

Create `si_archive/verify.py`:

```python
"""Stage 8 -- prove what the archive actually contains.

Failures become entries in REPORT.md, not exceptions. An archive that reports
its own gaps honestly is more useful than one that refuses to finish.
"""
import json
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

from si_archive import localsrc

HREF_RE = re.compile(r'(?:href|src)="([^"]+)"')
TAG_RE = re.compile(r"<[^>]+>")
EXTERNAL = ("http://", "https://", "mailto:", "data:", "#", "javascript:")


def find_broken_links(out_dir):
    out_dir = Path(out_dir)
    broken = []
    for page in sorted(out_dir.rglob("*.html")):
        for raw in HREF_RE.findall(page.read_text(errors="replace")):
            if raw.startswith(EXTERNAL) or not raw.strip():
                continue
            target = unquote(urlsplit(raw).path)
            if not target:
                continue
            if not (page.parent / target).exists():
                broken.append({"file": str(page.relative_to(out_dir)),
                               "target": target})
    return broken


def find_student_work(out_dir):
    out_dir = Path(out_dir)
    return [str(p.relative_to(out_dir)) for p in out_dir.rglob("*")
            if p.is_file() and localsrc.is_student_work(p)]


def check_reveal(out_dir, min_ratio=0.05):
    """Flag pages whose visible text is anomalously thin for their markup.

    A page that survived baking but whose content never got revealed shows up
    as a very low text-to-HTML ratio.
    """
    flagged = []
    for page in sorted(Path(out_dir).rglob("*.html")):
        raw = page.read_text(errors="replace")
        if len(raw) < 2000:
            continue
        text = re.sub(r"\s+", " ", TAG_RE.sub(" ", raw)).strip()
        ratio = len(text) / len(raw)
        if ratio < min_ratio:
            flagged.append({"file": str(page), "ratio": round(ratio, 4)})
    return flagged


def build_report(out_dir):
    out_dir = Path(out_dir)
    build = out_dir / "_build"
    lines = ["# Systematic Innovation Archive — Verification Report", ""]

    def load(name):
        path = build / name
        return json.loads(path.read_text()) if path.exists() else None

    course = load("course.json")
    elucidat = load("elucidat.json")
    ledger = load("ledger.json")
    media = load("media.json")

    lines.append("## Coverage")
    if course:
        lines.append(f"- Sections: {len(course['sections'])}")
    if elucidat:
        pages = sum(len(p["pages"]) for p in elucidat.values())
        lines.append(f"- Elucidat projects: {len(elucidat)} ({pages} pages)")
    if media:
        ok = [m for m in media if m["status"] == "ok"]
        lines.append(f"- Transcripts: {len(ok)}/{len(media)}")
        sheets = [m for m in media if m.get("contactsheet")]
        lines.append(f"- Contact sheets: {len(sheets)}")
    if ledger:
        for key, value in ledger["stats"].items():
            lines.append(f"- {key.replace('_', ' ').capitalize()}: {value}")

    lines += ["", "## Known gaps", ""]
    lines.append("- `Certificate of Completion` and `Continuous Education Units` "
                 "are LTI tool launches with no archivable content.")
    if ledger:
        for gap in ledger.get("gaps", []):
            lines.append(f"- Vimeo {gap['id']}: not retrieved")
    if media:
        for record in media:
            if record["status"] != "ok":
                lines.append(f"- No transcript: {Path(record['path']).name}")

    leaked = find_student_work(out_dir)
    broken = find_broken_links(out_dir)
    thin = check_reveal(out_dir)

    lines += ["", "## Integrity", ""]
    lines.append(f"- Student work present in archive: {len(leaked)} "
                 f"(must be 0)")
    for path in leaked[:20]:
        lines.append(f"  - {path}")
    lines.append(f"- Broken relative links: {len(broken)}")
    for item in broken[:20]:
        lines.append(f"  - {item['file']} -> {item['target']}")
    lines.append(f"- Pages flagged as possibly unrevealed: {len(thin)}")
    for item in thin[:20]:
        lines.append(f"  - {item['file']} (text ratio {item['ratio']})")

    return "\n".join(lines) + "\n"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_verify.py -v`
Expected: 6 passed

- [ ] **Step 5: Wire the stage into the CLI**

Add to `run_stage`:

```python
    if name == "verify":
        from si_archive import verify
        report = verify.build_report(out)
        (out / "REPORT.md").write_text(report)
        print(report)
        return
```

- [ ] **Step 6: Run the whole pipeline end to end**

Run: `.venv/bin/python bin/si_archive.py verify --out /Volumes/Desk\ SSD/SystematicInnovation-Archive`

Expected in `REPORT.md`:
- Sections: 16
- Elucidat projects: 7 (70 pages)
- **Student work present in archive: 0** — if this is not 0, stop and fix before anything else
- Broken relative links: 0, or each one explained

- [ ] **Step 7: Run the full suite**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: all tests pass (50 total across 9 test modules)

- [ ] **Step 8: Commit**

```bash
git add si_archive/verify.py tests/test_verify.py bin/si_archive.py
git commit -m "Add verification stage

Checks link integrity, asserts no student work reached the archive, and flags
pages whose text-to-markup ratio suggests reveal did not fire. Gaps are
reported in REPORT.md rather than raised."
```

---

## Self-Review

**Spec coverage.** Every spec section maps to a task: Sources and the Elucidat registry → Task 2 and Task 3; the bake-and-reveal decision → Task 8 (`reveal.css`); the three-level deconfliction model → Task 6; scope decisions (student work, ScreenFlow, prompts) → Task 5 index-level exclusion and Task 9 assertion; output layout → Task 8; the eight-stage pipeline → Tasks 2–9; code layout and the shared `Throttle` → Task 1; risks → the gap-recording behaviour in Tasks 4, 7 and 9.

**Type consistency.** `slugify` is defined once in `cartridge.py` and imported by `elucidat.py`. `is_student_work` is defined once in `localsrc.py` and imported by `verify.py`. Video records carry `path`/`duration`/`size` in both `local.json` and `vimeo.json`, which is what `match_renditions` compares. `page_order` and `mirror_project` agree that page slugs are `NN-name`.

**Placeholder scan.** One was found and fixed: Task 8 Step 6 originally described per-section media placement rather than supplying it. The campus-folder-to-section mapping is fixed and knowable, so it is now an explicit `CAMPUS_FOLDER_MAP` in `constants.py` with `destination_for` implemented and tested. The only intentional judgement left to the implementer is the fallback path — unknown campus folders land in `files/` rather than being dropped, which `test_destination_for_falls_back_to_files_for_unknown_folders` pins down.

**Test count.** 50 tests across 9 modules: net 3, cartridge 6, elucidat 8, vimeo 3, localsrc 5, reconcile 6, media 5, render 8, verify 6.
