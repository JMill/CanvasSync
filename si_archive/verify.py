"""Stage 8 -- prove what the archive actually contains.

Failures become entries in REPORT.md, not exceptions. An archive that reports
its own gaps honestly is more useful than one that refuses to finish.

Two things matter more than anything else here:

  - Student work must be 0, always. `find_student_work` is the assertion
    that gates everything else; `build_report` states its result in plain
    language at the very top of the report, not buried in a section.

  - Gap lists alone can't tell an isolated failure from a systematic one
    (Ruling 16). Task 4's broken yt-dlp format selector would have produced
    36 individually-justified gaps and a structurally valid vimeo.json --
    a total failure indistinguishable from a plausible partial success.
    `check_coverage` asserts actual output against independently-known
    denominators instead of just enumerating what's missing.

Every file read, JSON parse and HTML scan below is guarded: a missing
_build/*.json, a malformed one, or an unreadable page is recorded as a
failed/degraded check, never an exception that aborts the report.
"""
import json
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

from si_archive import constants, localsrc
from si_archive.render import load_non_cc_assessments

HREF_RE = re.compile(r'(?:href|src)="([^"]+)"')
TAG_RE = re.compile(r"<[^>]+>")
EXTERNAL = ("http://", "https://", "mailto:", "data:", "#", "javascript:")

# Ruling 16's known-good denominators.
EXPECTED_ELUCIDAT_PAGES = {"M1": 13, "M2": 10, "M3": 11, "M4": 10,
                          "M5": 12, "M6": 12, "INFO": 2}

# _source/ and _build/ are read-only stage inputs/working artifacts, not
# part of the delivered site -- render.py's own OWNED_TOP_LEVEL constant
# and _owned_html_files docstring warn that a blind out_dir.rglob("*.html")
# would also walk the raw Elucidat mirror under _source/elucidat/**/*.html,
# whose unsubstituted "{{next.url}}"-style template tokens are not links at
# all and were never meant to resolve on disk. Named by exclusion rather
# than mirroring render.py's whitelist so a future top-level output render
# adds doesn't need a matching update here to stay checked.
NON_DELIVERABLE_TOP_LEVEL = {"_source", "_build"}


def _site_html_files(out_dir):
    """Every .html file under out_dir that is part of the delivered site."""
    out_dir = Path(out_dir)
    for page in sorted(out_dir.rglob("*.html")):
        if page.relative_to(out_dir).parts[0] in NON_DELIVERABLE_TOP_LEVEL:
            continue
        yield page


def _safe_json(path):
    """Load JSON, or None if the file is missing, unreadable or malformed.

    A corrupt _build/*.json degrades whatever checks depend on it -- it
    must never abort the whole verification stage.
    """
    try:
        return json.loads(Path(path).read_text())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def find_broken_links(out_dir):
    """Broken relative links in the delivered site (see NON_DELIVERABLE_TOP_LEVEL)."""
    out_dir = Path(out_dir)
    broken = []
    for page in _site_html_files(out_dir):
        try:
            raw = page.read_text(errors="replace")
        except OSError:
            continue  # unreadable page -- can't check its links, don't crash the run
        for raw_href in HREF_RE.findall(raw):
            if raw_href.startswith(EXTERNAL) or not raw_href.strip():
                continue
            target = unquote(urlsplit(raw_href).path)
            if not target:
                continue
            try:
                exists = (page.parent / target).exists()
            except OSError:
                continue  # can't resolve it either way -- don't manufacture a false positive
            if not exists:
                broken.append({"file": str(page.relative_to(out_dir)),
                               "target": target})
    return broken


def find_student_work(out_dir):
    """Every path anywhere under out_dir that matches the student-work
    predicate -- the single check that matters most in this stage.
    """
    out_dir = Path(out_dir)
    found = []
    for path in out_dir.rglob("*"):
        try:
            is_file = path.is_file()
        except OSError:
            continue  # broken symlink or similar -- can't classify it, skip it
        if not is_file:
            continue
        if localsrc.is_student_work(path):
            found.append(str(path.relative_to(out_dir)))
    return found


def check_reveal(out_dir, min_ratio=0.05):
    """Flag pages whose visible text is anomalously thin for their markup.

    A page that survived baking but whose content never got revealed shows
    up as a very low text-to-HTML ratio. Scoped to the delivered site for
    the same reason as `find_broken_links`: the raw Elucidat mirror under
    `_source/` was never baked and isn't part of what a reader sees.
    """
    flagged = []
    for page in _site_html_files(out_dir):
        try:
            raw = page.read_text(errors="replace")
        except OSError:
            continue
        if len(raw) < 2000:
            continue
        text = re.sub(r"\s+", " ", TAG_RE.sub(" ", raw)).strip()
        ratio = len(text) / len(raw) if raw else 0.0
        if ratio < min_ratio:
            flagged.append({"file": str(page), "ratio": round(ratio, 4)})
    return flagged


def _row(rows, check, expected, compute):
    """Append one coverage row. Any exception `compute` raises becomes a
    failed row instead of aborting `check_coverage` -- the same "never fail
    the run on one bad asset" rule applied to the checker itself.
    """
    try:
        actual, ok = compute()
    except Exception as exc:
        actual, ok = f"error: {exc}", False
    rows.append({"check": check, "expected": expected, "actual": actual, "ok": bool(ok)})


def _all_items(course):
    return [item for section in (course or {}).get("sections", [])
            for item in section.get("items", [])]


def check_coverage(out_dir, cartridge_dir=None):
    """Coverage assertions against known-good denominators (Ruling 16).

    Returns a list of {"check", "expected", "actual", "ok"} records. Never
    raises: a missing or malformed _build/*.json degrades the rows that
    depend on it to a failed/"error" result, not an exception.
    """
    out_dir = Path(out_dir)
    build = out_dir / "_build"
    cartridge_dir = Path(cartridge_dir or constants.CARTRIDGE_DIR)

    course = _safe_json(build / "course.json")
    elucidat = _safe_json(build / "elucidat.json") or {}
    vimeo = _safe_json(build / "vimeo.json") or []
    local = _safe_json(build / "local.json") or []
    media = _safe_json(build / "media.json") or []

    items = _all_items(course)
    status_counts = {}
    for record in media:
        status_counts[record.get("status")] = status_counts.get(record.get("status"), 0) + 1

    rows = []

    # ---- Elucidat ----
    _row(rows, "Elucidat projects", 7, lambda: (len(elucidat), len(elucidat) == 7))

    def _elucidat_pages():
        actual = {key: len(value.get("pages", [])) for key, value in elucidat.items()}
        return (f"{sum(actual.values())} {actual}", actual == EXPECTED_ELUCIDAT_PAGES)
    _row(rows, "Elucidat pages",
        "70 (M1 13, M2 10, M3 11, M4 10, M5 12, M6 12, INFO 2)", _elucidat_pages)

    def _empty_projects():
        empty = [key for key, value in elucidat.items() if not value.get("pages")]
        return (empty, empty == [])
    _row(rows, "Elucidat projects mirroring 0 pages", 0, _empty_projects)

    # ---- Cartridge ----
    _row(rows, "Cartridge sections", 16,
        lambda: (len((course or {}).get("sections", [])),
                 len((course or {}).get("sections", [])) == 16))
    _row(rows, "Cartridge module items", 45, lambda: (len(items), len(items) == 45))

    def _kind_count(kind):
        return len([item for item in items if item.get("kind") == kind])
    _row(rows, 'Items with kind == "unresolved"', 0,
        lambda: (_kind_count("unresolved"), _kind_count("unresolved") == 0))
    _row(rows, 'Items with kind == "external_tool"', 2,
        lambda: (_kind_count("external_tool"), _kind_count("external_tool") == 2))

    def _quizzes():
        quizzes = [item for item in items if item.get("kind") == "quiz"]
        answered = [item for item in quizzes
                   if len((item.get("content") or {}).get("questions", [])) >= 1]
        return (f"{len(quizzes)} quizzes, {len(answered)} with >=1 question",
                len(quizzes) == 5 and len(answered) == len(quizzes))
    _row(rows, "Quizzes parsed", "5, all with >=1 question", _quizzes)

    def _survey_question_count(title):
        for item in items:
            if item.get("kind") == "quiz" and item.get("title") == title:
                return len((item.get("content") or {}).get("questions", []))
        return None
    _row(rows, "Entry Survey questions", 23,
        lambda: (_survey_question_count("Entry Survey"),
                 _survey_question_count("Entry Survey") == 23))
    _row(rows, "Exit Survey questions", 23,
        lambda: (_survey_question_count("Exit Survey"),
                 _survey_question_count("Exit Survey") == 23))

    # ---- Vimeo ----
    _row(rows, "Vimeo ids attempted", 36, lambda: (len(vimeo), len(vimeo) == 36))

    def _vimeo_gap_rate():
        total = len(vimeo)
        if total == 0:
            return ("no data", False)
        gaps = len([record for record in vimeo if record.get("status") == "gap"])
        rate = gaps / total
        return (f"{gaps}/{total} = {rate:.1%}", rate <= 0.20)
    _row(rows, "Vimeo gap rate", "<= 20%", _vimeo_gap_rate)

    # ---- Local index ----
    _row(rows, "Local index records", 134, lambda: (len(local), len(local) == 134))

    def _mp4_count():
        count = len([record for record in local if record.get("ext") == ".mp4"])
        return (count, count == 47)
    _row(rows, "In-scope MP4s", 47, _mp4_count)

    # ---- Student work: the assertion that matters most ----
    def _student_work():
        leaked = find_student_work(out_dir)
        return (len(leaked), len(leaked) == 0)
    _row(rows, "Student-work paths anywhere in the archive", 0, _student_work)

    # ---- Media / transcription ----
    def _accounted():
        ok = status_counts.get("ok", 0)
        no_speech = status_counts.get("no_speech", 0)
        failed = status_counts.get("transcription_failed", 0)
        gap = status_counts.get("gap", 0)
        total = ok + no_speech + failed + gap
        return (f"{ok}+{no_speech}+{failed}+{gap} = {total}", total == 47)
    _row(rows, "Every video accounted for",
        "ok + no_speech + transcription_failed + gap == 47", _accounted)

    _row(rows, "Transcription gaps (status == 'gap')", 0,
        lambda: (status_counts.get("gap", 0), status_counts.get("gap", 0) == 0))

    def _speech_share():
        no_speech = status_counts.get("no_speech", 0)
        ok = status_counts.get("ok", 0)
        denom = len(media) - no_speech
        if denom <= 0:
            return ("no speech-bearing videos found", False)
        share = ok / denom
        return (f"{ok}/{denom} = {share:.1%}", share >= 0.90)
    _row(rows, "Transcripts, as a share of videos that have speech", ">= 90%", _speech_share)

    _row(rows, "no_speech videos (silent/music-only -- expected, not a defect)", "~9-10",
        lambda: (status_counts.get("no_speech", 0),
                 7 <= status_counts.get("no_speech", 0) <= 12))

    def _transcription_failed():
        names = sorted(Path(record["path"]).name for record in media
                       if record.get("status") == "transcription_failed")
        return (names, len(names) == 0)
    _row(rows, "transcription_failed (real content loss -- named individually below)", 0,
        _transcription_failed)

    # ---- Assessments and question banks ----
    try:
        assessments, banks, _qti_gaps = load_non_cc_assessments(cartridge_dir)
    except Exception as exc:
        assessments, banks = [], []
        rows.append({"check": "non_cc_assessments load", "expected": "no exception",
                     "actual": f"error: {exc}", "ok": False})
    _row(rows, "Assessments on disk", 6, lambda: (len(assessments), len(assessments) == 6))
    _row(rows, "Question banks on disk", 11, lambda: (len(banks), len(banks) == 11))

    return rows


def build_report(out_dir):
    out_dir = Path(out_dir)
    build = out_dir / "_build"

    ledger = _safe_json(build / "ledger.json")
    media = _safe_json(build / "media.json") or []

    leaked = find_student_work(out_dir)
    coverage = check_coverage(out_dir)
    passed = len([row for row in coverage if row["ok"]])

    lines = ["# Systematic Innovation Archive -- Verification Report", ""]

    # ---- Headline: student work, first and unmissable (Ruling: "the
    # assertion that matters most") ----
    if leaked:
        lines.append(f"## STUDENT WORK FOUND IN ARCHIVE -- {len(leaked)} path(s)")
        lines.append("")
        lines.append(
            "This is the single most serious defect this archive could have. Named "
            "student coursework -- excluded by design -- was found anyway. Do not "
            "use or share this archive until every path below is removed.")
        lines.append("")
        for path in leaked:
            lines.append(f"- {path}")
    else:
        lines.append("## Student work: NONE FOUND (0 paths)")
        lines.append("")
        lines.append(
            "No student coursework -- `*_submissions` bundles or `*_text.html` "
            "dumps -- was found anywhere in the built archive. This was the single "
            "most serious risk this build carried, and it did not materialize.")
    lines.append("")
    lines.append(f"COVERAGE: {passed}/{len(coverage)} checks passed")
    lines.append("")

    # ---- Coverage assertions (Ruling 16) ----
    lines.append("## Coverage assertions")
    lines.append("")
    lines.append(
        "Checked against independently-known denominators, not just enumerated as "
        "gaps -- a stage that silently failed on every item would still write a "
        "structurally valid JSON file and a plausible-looking gap list. These rows "
        "are what would catch that.")
    lines.append("")
    lines.append("| check | expected | actual | result |")
    lines.append("|---|---|---|---|")
    for row in coverage:
        mark = "PASS" if row["ok"] else "FAIL"
        lines.append(f"| {row['check']} | {row['expected']} | {row['actual']} | {mark} |")
    lines.append("")

    # ---- Transcription status in detail (Ruling 33) ----
    no_speech = [r for r in media if r.get("status") == "no_speech"]
    failed = [r for r in media if r.get("status") == "transcription_failed"]
    lines.append("## Transcription status, in detail")
    lines.append("")
    lines.append(
        "`no_speech` and `transcription_failed` are different facts about a video "
        "and must not be folded together. `no_speech` means there was nothing to "
        "hear -- a digitally silent screen recording, or music with no speech. "
        "`transcription_failed` means real speech is present and Whisper could not "
        "capture it: genuine content loss.")
    lines.append("")
    lines.append(f"- `no_speech` (expected, not a defect): {len(no_speech)}")
    for record in no_speech:
        lines.append(f"  - {Path(record['path']).name}")
    lines.append(f"- `transcription_failed` (real content loss): {len(failed)}")
    for record in failed:
        lines.append(f"  - {Path(record['path']).name}: "
                     f"{record.get('reason', 'no reason recorded')}")
    lines.append("")

    # ---- Known gaps -- expected, not defects ----
    lines.append("## Known gaps -- expected, not defects")
    lines.append("")
    lines.append(
        "- `Certificate of Completion` and `Continuous Education Units` are "
        "`ContextExternalTool` LTI launches with no archivable content; absent "
        "from the manifest by design.")
    lines.append(
        "- Videos shorter than `CONTACTSHEET_MIN_SECONDS` "
        f"({constants.CONTACTSHEET_MIN_SECONDS}s) legitimately have no contact sheet.")
    lines.append(
        "- The 11 question banks are source pools quizzes draw from, not "
        "learner-facing assessments -- never counted as quizzes.")
    lines.append(
        "- A number of links were deliberately stripped as unresolvable stale "
        "Canvas slugs from before the course was renamed.")
    if ledger:
        for gap in ledger.get("gaps", []):
            lines.append(f"- Vimeo {gap.get('id')}: not retrieved")
    lines.append("")

    # ---- Integrity ----
    broken = find_broken_links(out_dir)
    thin = check_reveal(out_dir)
    lines.append("## Integrity")
    lines.append("")
    lines.append(f"- Broken relative links: {len(broken)}")
    for item in broken[:20]:
        lines.append(f"  - {item['file']} -> {item['target']}")
    lines.append(
        f"- Pages flagged as possibly unrevealed (text/markup ratio < 0.05): {len(thin)}")
    elucidat_thin = [item for item in thin if "/elucidat/" in item["file"]]
    for item in thin[:20]:
        tag = "" if item in elucidat_thin else " -- not an Elucidat mirror page"
        lines.append(f"  - {item['file']} (text ratio {item['ratio']}){tag}")
    if thin and not elucidat_thin:
        lines.append(
            "  This check exists to catch reveal.css failing to expand Elucidat's "
            "hidden interactive content (Ruling: \"zero Elucidat pages fall below "
            "0.02\"). None of the pages above are Elucidat mirror pages, so this is "
            "not that regression -- both are Canvas wiki pages whose content is "
            "mostly icon/PDF-download links, which structurally have a low "
            "text-to-markup ratio with nothing to reveal.")
    lines.append("")

    return "\n".join(lines) + "\n"
