#!/usr/bin/env python3
"""Archive CITI Program courses (module text + quiz questions) for offline reading.

CITI (citiprogram.org) is a server-rendered ColdFusion site with no learner
API. Every navigation is a POST form carrying `__ncforminfo`, a per-render
anti-tamper token, so replaying requests outside a browser is fragile. This
tool therefore drives a real Chrome window for page navigation and uses the
same cookies only for plain static GETs (module images, linked PDFs).

What it captures, per accessible module:
  - the "Classic" module text (div.module-classic), with images and linked
    CITI PDFs saved locally and the JavaScript show/hide toggles turned into
    <details> so tap-to-reveal works offline;
  - the quiz questions and answer options, read from the quiz form.

What it never does: submit a quiz. CITI shows correct answers and
explanations only after a submission, and a submission is real coursework
that counts toward the learner's record -- so the answer key is out of reach
by design. Opening a quiz form records nothing (verified: the gradebook still
reads "Incomplete -" afterwards); `click_form` refuses the submit target
outright rather than relying on the caller to remember.

Required modules in an incomplete course unlock one at a time as each quiz is
passed, so only unlocked modules can be archived. The run is incremental:
re-run after passing more quizzes and it fetches only what is new.

Login: CITI's session cookies (CFID/CFTOKEN/JSESSIONID) are non-persistent,
exactly like Canvas's `canvas_session`, so the Chrome profile alone cannot
carry a login forward. The cookie jar is saved (0600, 24h) the same way
canvas_login.py does and verified against the site before reuse.

Usage:
    citi_archive.py --out "<dir>"                  # all courses, institution 1463
    citi_archive.py --out "<dir>" --course IRB     # title substring filter
    citi_archive.py --out "<dir>" --render-only    # rebuild HTML from saved JSON
    citi_archive.py --forget                       # drop the saved session
"""

import argparse
import base64
import hashlib
import html as htmllib
import json
import mimetypes
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup, NavigableString

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bin.canvas_login import forget_session, load_session, save_session  # noqa: E402

BASE = "https://www.citiprogram.org"
DEFAULT_PROFILE = Path.home() / ".cache" / "citi-archive-profile"
DEFAULT_SESSION_STORE = Path.home() / ".cache" / "citi-archive-session.json"

# The quiz form posts here. Nothing in this tool may ever submit to it.
QUIZ_SUBMIT_RE = re.compile(r"pageID=177(?!\d)")
LOGIN_PAGE_RE = re.compile(r"pageID=14(?!\d)")
# The integrity / terms attestation shown before a course first opens. Agreeing
# is the learner's own statement, so the tool reports it and never submits it.
ATTESTATION_RE = re.compile(r"pageID=121(?!\d)")
ASSET_PATH_RE = re.compile(r"^/(citidocuments|members/images|images)/", re.I)


class RefusedSubmit(RuntimeError):
    """Raised when a click would submit a quiz or the integrity attestation."""


class SessionEnded(RuntimeError):
    """The CITI session is gone (login redirect / no logout link on a 200 page).

    Deliberately not the builtin PermissionError: that is also what a local
    EACCES raises, and an unwritable folder must not cost a valid session.
    """


# --------------------------------------------------------------------------
# Parsing (pure functions over HTML strings)
# --------------------------------------------------------------------------

def _text(node):
    return " ".join(node.get_text(" ").split()) if node else ""


def _form_fields(form):
    return {i.get("name"): i.get("value", "")
            for i in form.find_all("input")
            if i.get("type") == "hidden" and i.get("name")
            and i.get("name") != "__ncforminfo"}


def parse_courses(html):
    """Course cards on My Courses -> [{stage_id, title, status, action}].

    A card's entry form posts to pageID=122 (start/continue) or pageID=147
    (review a completed course). The title is the nearest <strong> in the
    card, found by walking up from the form.
    """
    soup = BeautifulSoup(html, "lxml")
    out, seen = [], set()
    for form in soup.find_all("form"):
        action = form.get("action") or ""
        if not re.search(r"pageID=(122|147)(?!\d)", action):
            continue
        fields = _form_fields(form)
        stage = fields.get("stageID")
        if not stage or stage in seen:
            continue
        # Walk up to the card, but never past it: an ancestor that holds
        # another course's entry form is the shared list, and its first
        # <strong> belongs to some other course.
        title, node = "", form
        while node is not None and node.name not in (None, "[document]") and not title:
            stages = {i.get("value") for i in node.find_all("input", attrs={"name": "stageID"})}
            if stages - {stage}:
                break
            title = _text(node.find(["strong", "h2", "h3", "h4"]))
            node = node.parent
        seen.add(stage)
        out.append({
            "stage_id": stage,
            "member_stage_id": fields.get("memberStageID"),
            "group_id": fields.get("groupID"),
            "title": title or f"Course {stage}",
            "status": "completed" if "pageID=147" in action else "open",
        })
    return out


def parse_gradebook(html):
    """Gradebook rows -> [{module_id, title, section, completed, score, action, locked_reason}].

    `action` is the submit value ("Start"/"Review") when the module has an
    entry form, else None; a locked row carries a disabled button whose title
    says why (e.g. "Complete Required modules in order.").
    """
    soup = BeautifulSoup(html, "lxml")
    rows = []
    for table in soup.find_all("table"):
        section = ""
        for prev in table.find_all_previous(string=re.compile(
                r"(Required|Elective|Supplemental|Optional) Modules")):
            section = " ".join(prev.split()).split(" Modules")[0]
            break
        for tr in table.find_all("tr"):
            tds = tr.find_all("td")
            if len(tds) < 4:
                continue
            title = _text(tds[0])
            m = re.search(r"\(ID (\d+)\)\s*$", title)
            if not m:
                continue
            form = tds[3].find("form")
            submit = form.find("input", {"type": "submit"}) if form else None
            disabled = tds[3].find("input", disabled=True)
            completed = _text(tds[1])
            rows.append({
                "module_id": m.group(1),
                "title": title[:m.start()].strip(),
                "section": section,
                # Not a date: "Incomplete" (not done) or "Optional" (untaken elective).
                "completed": None if re.match(r"(incomplete|optional)\b", completed, re.I)
                else completed or None,
                "score": None if _text(tds[2]) in ("", "-") else _text(tds[2]),
                "action": submit.get("value") if submit else None,
                "locked_reason": (disabled.get("title") or "locked") if (disabled and not form) else None,
            })
    return rows


def parse_module(html):
    """Module page -> {title, content_html, has_quiz}. content_html is raw (uncleaned)."""
    soup = BeautifulSoup(html, "lxml")
    body = soup.select_one("div.module-classic")
    if body is None:
        return None
    heading = body.find(["h1", "h2"])
    has_quiz = bool(soup.select('form[action*="pageID=176"]'))
    return {"title": _text(heading), "content_html": str(body), "has_quiz": has_quiz}


def question_key(text, options=()):
    """Stable identity for a question across attempts.

    The QuizAnswer<n> field names are per-attempt response-row ids (they
    increment across unrelated quizzes), so they cannot identify a question;
    its normalized text plus its option texts can. Options are part of the key
    because pool questions can share a generic stem ("Which of the following
    is true?") and differ only in their choices.
    """
    def norm(s):
        return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()
    sig = norm(text) + "\x1f" + "\x1e".join(sorted(norm(o) for o in options))
    return hashlib.sha1(sig.encode()).hexdigest()[:16]


def parse_quiz(html):
    """Quiz form -> {instructions, questions:[{key, text, text_html, multi, options:[{value,text}]}]}.

    Option order is shuffled per render, so options are stored sorted by their
    `value`, which is CITI's stable per-question option id.
    """
    soup = BeautifulSoup(html, "lxml")
    form = soup.find("form", {"name": "quiz"}) or soup.find("form", id="quiz")
    if form is None:
        return None
    instr = ""
    for p in form.find_all_previous("p"):
        if "Quiz Instructions" in p.get_text() or "Each question is" in p.get_text():
            instr = _text(p)
            break
    questions = []
    for fs in form.find_all("fieldset"):
        inputs = fs.find_all("input", {"type": ["radio", "checkbox"]})
        if not inputs:
            continue
        # Question text: everything between the preceding "Question N" heading and this fieldset.
        parts, node = [], fs.previous_sibling
        while node is not None:
            if getattr(node, "name", None) in ("h3", "h2", "fieldset"):
                break
            if getattr(node, "name", None):
                parts.insert(0, node)
            node = node.previous_sibling
        text_html = "".join(str(p) for p in parts).strip()
        text = " ".join(BeautifulSoup(text_html, "lxml").get_text(" ").split())
        opts = []
        for inp in inputs:
            lab = fs.find("label", attrs={"for": inp.get("id")}) if inp.get("id") else None
            opts.append({"value": inp.get("value"), "text": _text(lab)})
        try:
            opts.sort(key=lambda o: int(o["value"]))
        except (TypeError, ValueError):
            opts.sort(key=lambda o: str(o["value"]))
        questions.append({
            "key": question_key(text or text_html, [o["text"] for o in opts]),
            "text": text,
            "text_html": text_html,
            "multi": any(i.get("type") == "checkbox" for i in inputs),
            "options": opts,
        })
    return {"instructions": instr, "questions": questions}


def stored_key(q):
    return question_key(q.get("text") or q.get("text_html", ""),
                        [o.get("text", "") for o in q.get("options", [])])


def merge_quiz(old, new):
    """Union of old and new questions by key, keeping first-seen order.

    Deduplication is only *between* the two lists, never within one: entries
    already stored are kept as they are, so a key collision can never shrink
    an archive that was already saved.
    """
    if not old:
        return new
    if not new:
        return old
    # Keys are recomputed rather than trusted: records saved under an older
    # key formula would otherwise never match and every question would double.
    merged = [dict(q, key=stored_key(q)) for q in old.get("questions", [])]
    index = {}
    for i, q in enumerate(merged):
        index.setdefault(q["key"], i)
    for q in new.get("questions", []):
        q = dict(q, key=stored_key(q))
        if q["key"] in index:
            prev = merged[index[q["key"]]]
            prev["times_seen"] = prev.get("times_seen", 1) + 1
            # Answer keys (if ever captured) survive a re-fetch that lacks them.
            for k in ("correct", "explanation"):
                if q.get(k) and not prev.get(k):
                    prev[k] = q[k]
            continue
        merged.append(dict(q))
    return {"instructions": new.get("instructions") or old.get("instructions", ""),
            "questions": merged}


def merge_gradebook(old_rows, new_rows):
    """Keep every module ever seen: new rows win on status, old-only rows stay.

    A partial or failed gradebook parse must not make archived modules vanish
    from the rendered site, which is driven by these rows.
    """
    new_ids = {r["module_id"] for r in new_rows}
    return list(new_rows) + [dict(r, stale=True) for r in (old_rows or [])
                             if r["module_id"] not in new_ids]


# --------------------------------------------------------------------------
# Cleaning module HTML for offline reading
# --------------------------------------------------------------------------

_HIDDEN_RE = re.compile(r"display\s*:\s*none", re.I)


def _strip_hidden_style(tag):
    style = tag.get("style")
    if style and _HIDDEN_RE.search(style):
        rest = ";".join(s for s in style.split(";") if s.strip() and not _HIDDEN_RE.search(s))
        if rest.strip():
            tag["style"] = rest
        else:
            del tag["style"]


def _to_details(soup, summary_html, panel):
    det = soup.new_tag("details")
    summ = soup.new_tag("summary")
    summ.append(BeautifulSoup(summary_html, "html.parser"))
    det.append(summ)
    _strip_hidden_style(panel)
    panel.wrap(det)
    det.insert(0, summ)
    return det


def asset_refs(content_html):
    """CITI-hosted asset paths referenced by module content (images, linked PDFs)."""
    soup = BeautifulSoup(content_html, "lxml")
    refs = []
    for tag, attr in (("img", "src"), ("a", "href")):
        for t in soup.find_all(tag):
            v = (t.get(attr) or "").strip()
            path = urlsplit(urljoin(BASE + "/", v))
            if path.netloc.endswith("citiprogram.org") and ASSET_PATH_RE.match(path.path):
                if tag == "img" or path.path.lower().endswith(".pdf"):
                    refs.append(path.path)
    return list(dict.fromkeys(refs))


def asset_filename(path):
    """Flatten a site path to a collision-safe local name."""
    name = Path(path).name or "asset"
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", name)[:120]
    return f"{hashlib.sha1(path.encode()).hexdigest()[:8]}_{stem}"


_URL_ATTRS = ("href", "src", "xlink:href", "data", "action", "formaction",
              "poster", "background", "srcset", "cite", "longdesc")
_CTRL_RE = re.compile(r"[\x00-\x20\x7f]+")


def safe_url(value, allow_data_image=False):
    """Return the URL if its scheme is harmless offline, else None.

    Browsers ignore ASCII whitespace/control characters and case inside a
    scheme ("Java\\tScript:"), so the check runs on a normalised copy.
    """
    v = (value or "").strip()
    probe = _CTRL_RE.sub("", v).lower()
    m = re.match(r"^([a-z][a-z0-9+.-]*):", probe)
    if not m:
        return v  # relative or fragment
    scheme = m.group(1)
    if scheme in ("http", "https", "mailto", "tel"):
        return v
    if scheme == "data" and allow_data_image and probe.startswith("data:image/") \
            and not probe.startswith("data:image/svg"):
        return v
    return None


def clean_content(content_html, resolve_asset):
    """Make module (or quiz-question) HTML safe and readable offline.

    resolve_asset(path) -> replacement URL (data: URI or relative path) or None.
    """
    soup = BeautifulSoup(content_html, "html.parser")
    root = soup.select_one("div.module-classic") or soup

    # button[aria-controls=X] + #X{display:none}  ->  <details><summary>button</summary>X</details>
    for btn in root.find_all("button", attrs={"aria-controls": True}):
        panel = root.find(id=btn["aria-controls"])
        if panel is None:
            continue
        label = btn.decode_contents()
        holder = btn.parent if btn.parent and btn.parent.name in ("p", "li") and \
            len([c for c in btn.parent.contents if str(c).strip()]) == 1 else None
        _to_details(soup, label, panel)
        if holder is not None and holder.name == "p":
            holder.decompose()
        else:
            btn.decompose()

    # div.vf-showN (header) + div.vfN (hidden body)
    for show in root.find_all("div", class_=re.compile(r"^vf-show\d+$")):
        n = re.search(r"\d+", " ".join(show["class"])).group()
        panel = show.find_next_sibling("div", class_=f"vf{n}")
        if panel is None:
            continue
        label = show.decode_contents()
        _to_details(soup, label, panel)
        show.decompose()

    for t in root.find_all(["script", "style", "noscript", "form", "input", "link", "meta",
                            "object", "embed", "applet", "base", "frame", "frameset",
                            "animate", "set", "animatemotion", "animatetransform"]):
        t.decompose()
    for t in root.find_all(True):
        _strip_hidden_style(t)
        for a in list(t.attrs):
            low = a.lower()
            if low.startswith("on") or low == "srcdoc":
                del t[a]
            elif low == "style" and re.search(r"javascript:|expression\s*\(|url\s*\(",
                                              _CTRL_RE.sub("", str(t[a])).lower()):
                del t[a]
            elif low in _URL_ATTRS:
                ok = safe_url(t[a] if isinstance(t[a], str) else " ".join(t[a]),
                              allow_data_image=(t.name == "img" and low == "src"))
                if ok is None:
                    del t[a]

    for img in root.find_all("img"):
        src = (img.get("src") or "").strip()
        path = urlsplit(urljoin(BASE + "/", src)).path
        local = resolve_asset(path) if ASSET_PATH_RE.match(path) else None
        img["src"] = local or urljoin(BASE + "/", src)
        img["loading"] = "lazy"
        for a in ("width", "height"):
            img.attrs.pop(a, None)

    for a in root.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith("#"):
            continue
        absu = urljoin(BASE + "/", href)
        sp = urlsplit(absu)
        local = resolve_asset(sp.path) if (sp.netloc.endswith("citiprogram.org")
                                          and ASSET_PATH_RE.match(sp.path)
                                          and sp.path.lower().endswith(".pdf")) else None
        a["href"] = local or absu
        if not local:
            a["target"] = "_blank"
            a["rel"] = "noopener"

    for fr in root.find_all("iframe"):
        src = urljoin(BASE + "/", fr.get("src") or "")
        if urlsplit(src).scheme not in ("http", "https"):
            fr.decompose()
            continue
        link = soup.new_tag("a", href=src, target="_blank", rel="noopener")
        link["class"] = "video-link"
        host = urlsplit(src).netloc.replace("player.", "").replace("www.", "")
        link.string = f"▶ Video on {host} (needs internet)"
        fr.replace_with(link)

    return root.decode_contents() if root is not soup else str(soup)


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------

CSS = """
:root{--bg:#fbfaf7;--fg:#1d1d1f;--muted:#6b6b70;--card:#fff;--line:#e4e2dc;--accent:#2563a8;--soft:#eef3f9}
@media (prefers-color-scheme:dark){:root{--bg:#141416;--fg:#e8e8ea;--muted:#9a9aa2;--card:#1d1d21;--line:#2f2f35;--accent:#7cb0ea;--soft:#1f2a37}}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--fg);font:17px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
main{max-width:46rem;margin:0 auto;padding:0 16px 4rem}
header.top{position:sticky;top:0;z-index:5;background:var(--bg);border-bottom:1px solid var(--line);padding:.6rem 16px}
header.top a{color:var(--accent);text-decoration:none;font-weight:600}
h1{font-size:1.5rem;line-height:1.25;margin:1.2rem 0 .3rem}
h2{font-size:1.25rem;line-height:1.3}
.meta{color:var(--muted);font-size:.85rem}
nav.toc ol{padding-left:1.2rem}
nav.toc li{margin:.35rem 0}
nav.toc a{color:var(--accent);text-decoration:none}
.tag{display:inline-block;font-size:.72rem;padding:.05rem .45rem;border-radius:99px;background:var(--soft);color:var(--muted);margin-left:.3rem;vertical-align:middle}
section.module{border-top:2px solid var(--line);margin-top:2.5rem;padding-top:.5rem}
.content img{max-width:100%;height:auto;border-radius:4px}
.content img[align]{float:none!important;display:block;margin:.5rem 0}
.content table{width:100%!important;max-width:100%;border-collapse:collapse;display:block;overflow-x:auto}
.content td,.content th{padding:.3rem;vertical-align:top}
.content blockquote{margin:.5rem 0;padding:0}
.content a{color:var(--accent);word-break:break-word}
details{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:.4rem .8rem;margin:.6rem 0}
summary{cursor:pointer;font-weight:600;color:var(--accent)}
details[open]>summary{margin-bottom:.4rem}
.video-link{display:inline-block;padding:.4rem .7rem;border:1px solid var(--line);border-radius:6px;background:var(--card);text-decoration:none}
.quiz{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:.8rem 1rem;margin-top:1.5rem}
.quiz h3{margin:.2rem 0 .4rem}
.q{border-top:1px solid var(--line);padding:.7rem 0}
.q:first-of-type{border-top:0}
.q .qn{font-weight:700;color:var(--muted);font-size:.85rem}
.q ol{list-style:upper-alpha;padding-left:1.6rem;margin:.4rem 0}
.q li{margin:.3rem 0}
.q li.correct{font-weight:700}
.q li.correct::after{content:" ✓";color:#2e8b57}
.explain{font-size:.92rem;color:var(--muted)}
.locked{color:var(--muted)}
.note{background:var(--soft);border-radius:8px;padding:.6rem .8rem}
"""


def _page(title, body):
    return ("<!doctype html><html lang=en><head><meta charset=utf-8>"
            "<meta name=viewport content='width=device-width,initial-scale=1'>"
            f"<title>{htmllib.escape(title)}</title><style>{CSS}</style></head>"
            f"<body>{body}</body></html>")


def render_quiz(quiz, resolve_asset=lambda _p: None):
    if not quiz or not quiz.get("questions"):
        return ""
    has_key = any(q.get("correct") for q in quiz["questions"])
    note = ("" if has_key else
            "<p class=meta>Answers aren't included: CITI reveals them only after a quiz "
            "is submitted on the site.</p>")
    parts = [f"<div class=quiz><h3>Quiz · {len(quiz['questions'])} questions</h3>{note}"]
    for i, q in enumerate(quiz["questions"], 1):
        correct = set(q.get("correct") or [])
        opts = "".join(
            f"<li{' class=correct' if o['value'] in correct else ''}>{htmllib.escape(o['text'])}</li>"
            for o in q["options"])
        multi = " <span class=tag>select all that apply</span>" if q.get("multi") else ""
        # Question HTML is site content like module text: same cleaning, same assets.
        stem = (clean_content(q["text_html"], resolve_asset) if q.get("text_html")
                else htmllib.escape(q.get("text", "")))
        expl = (f"<div class=explain>{clean_content(q['explanation'], resolve_asset)}</div>"
                if q.get("explanation") else "")
        parts.append(f"<div class=q><div class=qn>Question {i}{multi}</div>"
                     f"<div>{stem}</div><ol>{opts}</ol>{expl}</div>")
    parts.append("</div>")
    return "".join(parts)


ATTEST_NOTE = ("<p class=note>CITI asks you to accept its integrity statement before this "
               "course opens. Open it once on citiprogram.org, agree, then re-run the archiver.</p>")


def render_course(course, modules, resolve_asset):
    """One self-contained page per course: TOC, then every archived module.

    Rows come from the gradebook, but any saved module the gradebook no longer
    lists is still rendered (under "Other archived modules") -- the archive
    never loses content because one page load parsed badly.
    """
    title = course["title"]
    by_id = {m["module_id"]: m for m in modules}
    rows = list(course.get("gradebook", []))
    listed = {r["module_id"] for r in rows}
    rows += [{"module_id": m["module_id"], "title": m.get("title") or m["module_id"],
              "section": "Other archived modules", "score": None}
             for m in modules if m["module_id"] not in listed]
    toc, sections = [], []
    for row in rows:
        mid = row["module_id"]
        mod = by_id.get(mid)
        tags = f"<span class=tag>{htmllib.escape(row.get('section') or 'Module')}</span>"
        if row.get("score"):
            tags += f"<span class=tag>{htmllib.escape(row['score'])}</span>"
        if mod and (mod.get("quiz") or {}).get("questions"):
            tags += f"<span class=tag>{len(mod['quiz']['questions'])} Q</span>"
        if mod:
            toc.append(f"<li><a href='#m{htmllib.escape(mid)}'>{htmllib.escape(row['title'])}</a>{tags}</li>")
        else:
            why = row.get("locked_reason") or "not archived yet"
            toc.append(f"<li class=locked>{htmllib.escape(row['title'])}{tags}"
                       f" <span class=meta>— {htmllib.escape(why)}</span></li>")
        if mod:
            body = clean_content(mod.get("content_html", ""), resolve_asset)
            sections.append(
                f"<section class=module id='m{htmllib.escape(mid)}'>"
                f"<p class=meta>{htmllib.escape(row.get('section') or '')} · ID {htmllib.escape(mid)}"
                f" · fetched {htmllib.escape(mod.get('fetched_at', '')[:10])} · <a href='#top'>top</a></p>"
                f"<div class=content>{body}</div>{render_quiz(mod.get('quiz'), resolve_asset)}</section>")
    got = sum(1 for r in rows if r["module_id"] in by_id)
    body = (f"<header class=top id=top><a href='index.html'>‹ CITI archive</a></header><main>"
            f"<h1>{htmllib.escape(title)}</h1>"
            f"<p class=meta>{got} of {len(rows)} modules archived · "
            f"updated {htmllib.escape(course.get('updated_at', '')[:16].replace('T', ' '))} UTC</p>"
            f"{ATTEST_NOTE if course.get('needs_attestation') else ''}"
            f"<nav class=toc><ol>{''.join(toc)}</ol></nav>{''.join(sections)}</main>")
    return _page(title, body)


def render_index(courses):
    items = "".join(
        f"<li><a href='{htmllib.escape(c['slug'])}.html'>{htmllib.escape(c['title'])}</a>"
        f" <span class=meta>{c['archived']}/{c['total']} modules"
        f"{' · accept integrity statement on CITI first' if c.get('needs_attestation') else ''}</span></li>"
        for c in courses)
    return _page("CITI archive", f"<main><h1>CITI archive</h1><nav class=toc><ol>{items}</ol></nav>"
                                 "<p class=meta>Each course page is self-contained (images inlined); "
                                 "linked PDFs sit in each course's assets/ folder.</p></main>")


def slugify(text, maxlen=60):
    s = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_")
    return s[:maxlen] or "course"


INLINE_MAX_WIDTH = 1200


def inline_image(f, cache_dir):
    """data: URI for an image, downscaled for a phone.

    CITI serves photos up to ~1 MB; inlined at full size a course page reaches
    30 MB. Images wider than INLINE_MAX_WIDTH are resized (JPEG q75, or PNG
    when there is transparency) into cache_dir; originals stay untouched in
    assets/. Anything Pillow cannot read is inlined as-is.
    """
    mime = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
    data = f.read_bytes()
    if mime in ("image/jpeg", "image/png", "image/webp"):
        meta, blob = cache_dir / (f.name + ".mime"), cache_dir / (f.name + ".bin")
        try:
            if blob.is_file() and meta.is_file() and blob.stat().st_mtime >= f.stat().st_mtime:
                mime, data = meta.read_text().strip(), blob.read_bytes()
            else:
                mime, data = _shrink(data, mime)
                cache_dir.mkdir(parents=True, exist_ok=True)
                blob.write_bytes(data)
                meta.write_text(mime)
        except Exception:
            mime = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
            data = f.read_bytes()
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"


def _shrink(data, mime):
    import io
    from PIL import Image
    from PIL import ImageOps
    im = Image.open(io.BytesIO(data))
    # Leave alone anything re-encoding would damage: animations (one frame
    # survives) and high-bit-depth modes (16-bit grey saturates to white).
    if getattr(im, "is_animated", False) or \
            im.mode not in ("RGB", "RGBA", "L", "LA", "P", "PA", "CMYK", "1"):
        return mime, data
    alpha = im.mode in ("RGBA", "LA", "PA") or "transparency" in im.info
    if im.width <= INLINE_MAX_WIDTH and len(data) < 250_000:
        return mime, data
    im = ImageOps.exif_transpose(im)  # JPEG re-encode drops EXIF orientation
    if im.width > INLINE_MAX_WIDTH:
        im = im.resize((INLINE_MAX_WIDTH, round(im.height * INLINE_MAX_WIDTH / im.width)),
                       Image.LANCZOS)
    buf = io.BytesIO()
    if alpha:
        im.save(buf, "PNG", optimize=True)
        out = ("image/png", buf.getvalue())
    else:
        im.convert("RGB").save(buf, "JPEG", quality=75, optimize=True, progressive=True)
        out = ("image/jpeg", buf.getvalue())
    return out if len(out[1]) < len(data) else (mime, data)


def build_site(out):
    """Render every course directory under `out` from its saved JSON."""
    out = Path(out)
    summary = []
    for cdir in sorted(p for p in out.iterdir() if (p / "course.json").is_file()):
        course = json.loads((cdir / "course.json").read_text())
        modules = [json.loads(p.read_text()) for p in sorted((cdir / "modules").glob("*.json"))]

        def resolve(path, cdir=cdir):
            f = cdir / "assets" / asset_filename(path)
            if not f.is_file():
                return None
            if path.lower().endswith(".pdf"):
                return f"{cdir.name}/assets/{f.name}"
            return inline_image(f, cdir / "assets" / "_inline")

        page = render_course(course, modules, resolve)
        (out / f"{cdir.name}.html").write_text(page)
        ids = {r["module_id"] for r in course.get("gradebook", [])} | {m["module_id"] for m in modules}
        summary.append({"slug": cdir.name, "title": course["title"],
                        "archived": len(modules), "total": len(ids),
                        "needs_attestation": bool(course.get("needs_attestation"))})
    (out / "index.html").write_text(render_index(summary))
    return summary


# --------------------------------------------------------------------------
# Browser driver
# --------------------------------------------------------------------------

def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def is_logged_in(page):
    if LOGIN_PAGE_RE.search(page.url) or "citiprogram.org" not in page.url:
        return False
    try:
        return page.locator('a[href*="/lms/home/logout"]').count() > 0
    except Exception:
        return False


class _Resp:
    """Adapt a Playwright response to what si_archive.net.Throttle.pushback reads."""

    def __init__(self, r):
        self.status_code = r.status if r is not None else 200
        self.headers = (r.headers if r is not None else {}) or {}


def obey_pushback(throttle, response):
    """Feed every response to the shared Throttle; sleep if the server pushed back.

    Returns True when the response was a 429/503, so the caller can retry or
    give up. Clean responses are fed too, which lets an earlier penalty decay.
    """
    nap = throttle.pushback(_Resp(response))
    if nap:
        print(f"    (server pushback {response.status}; sleeping {nap:.0f}s, pace slowed)", flush=True)
        time.sleep(nap)
        return True
    return response is not None and response.status in (429, 503)


def write_json(path, data):
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_text(json.dumps(data, indent=1))
    tmp.replace(path)


def prev_course(cfile):
    return json.loads(cfile.read_text()) if cfile.is_file() else {}


def course_dir_name(c):
    """Directory per course: readable title plus the stage id, so two courses
    with the same (or misparsed) title can never share a folder."""
    return f"{slugify(c['title'], 50)}_{c['stage_id']}"


def click_form(page, form_selector, throttle):
    """Submit a navigation form by clicking its real submit button.

    Refuses anything that would submit a quiz -- the one irreversible action
    on this site. Clicking (rather than form.submit()) keeps the button's own
    name/value in the POST, which CITI uses (submit=Start/Review).
    """
    form = page.locator(form_selector).first
    if form.count() == 0:
        raise LookupError(f"no form matches {form_selector!r} on {page.url}")
    button = form.locator('input[type="submit"]').first
    action = form.get_attribute("action") or ""
    target = button.get_attribute("formaction") or "" if button.count() else ""
    ident = {(form.get_attribute("name") or "").lower(), (form.get_attribute("id") or "").lower()}
    if QUIZ_SUBMIT_RE.search(action) or QUIZ_SUBMIT_RE.search(target) or "quiz" in ident:
        raise RefusedSubmit(f"refusing to submit quiz form ({action})")
    if ATTESTATION_RE.search(action) or ATTESTATION_RE.search(target):
        raise RefusedSubmit(f"refusing to answer the integrity attestation ({action})")
    throttle.wait(BASE + "/")
    with page.expect_navigation(wait_until="domcontentloaded", timeout=60000) as nav:
        button.click()
    page.wait_for_timeout(600)
    if LOGIN_PAGE_RE.search(page.url):
        raise SessionEnded("session ended (redirected to the CITI login page)")
    if obey_pushback(throttle, nav.value):
        raise RuntimeError(f"server pushback on {form_selector}")


class CitiArchiver:
    def __init__(self, page, ctx, out, institution, throttle, refresh=False):
        self.page, self.ctx, self.out = page, ctx, Path(out)
        self.institution, self.throttle, self.refresh = institution, throttle, refresh
        self.home = f"{BASE}/members/index.cfm?pageID=50&showInstitution={institution}"

    def go_home(self):
        for _ in range(3):
            self.throttle.wait(BASE + "/")
            resp = self.page.goto(self.home, wait_until="domcontentloaded")
            if not obey_pushback(self.throttle, resp):
                break
        else:
            # Still pushed back after the retries: rate limited, not logged out.
            raise RuntimeError("CITI is rate limiting My Courses; try again later")
        if not is_logged_in(self.page):
            raise SessionEnded("not logged in on My Courses")

    def open_course(self, stage_id):
        self.go_home()
        click_form(self.page,
                   f'form[action*="pageID=122"]:has(input[name="stageID"][value="{stage_id}"]), '
                   f'form[action*="pageID=147"]:has(input[name="stageID"][value="{stage_id}"])',
                   self.throttle)

    def fetch_asset(self, path, dest):
        """GET a CITI-hosted image/PDF with the session cookies. True if on disk.

        A followed redirect to the login page (or any HTML where an image or
        PDF belongs) is a dead session, not an asset; saving it would poison
        the cache, since an existing file is never fetched again.
        """
        if dest.is_file() and dest.stat().st_size > 0:
            return True
        url = BASE + path
        for attempt in range(3):
            self.throttle.wait(url)
            try:
                r = self.ctx.request.get(url, timeout=60000)
            except Exception as e:
                print(f"      asset error {path}: {e}")
                time.sleep(5 * (attempt + 1))
                continue
            if obey_pushback(self.throttle, r):
                continue
            if LOGIN_PAGE_RE.search(r.url):
                raise SessionEnded(f"session ended (asset {path} redirected to login)")
            if r.status != 200:
                print(f"      asset {r.status}: {path}")
                return False
            ctype = (r.headers.get("content-type") or "").lower()
            if "text/html" in ctype:
                print(f"      asset {path}: got an HTML page instead; not saved")
                return False
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_suffix(dest.suffix + ".part")
            tmp.write_bytes(r.body())
            tmp.replace(dest)
            return True
        return False

    def fetch_assets(self, refs, cdir):
        got = sum(self.fetch_asset(p, cdir / "assets" / asset_filename(p)) for p in refs)
        if refs:
            print(f"     assets {got}/{len(refs)}")
        return got == len(refs)

    def run(self, course_filter=None, on_home=False):
        """Archive every (matching) course. Returns the number of courses that failed.

        A failure in one course does not stop the others -- except a dead
        session (nothing further can work) or a refused submit (a bug that
        must stop the run).
        """
        if not on_home:
            self.go_home()
        courses = parse_courses(self.page.content())
        if course_filter:
            courses = [c for c in courses if course_filter.lower() in c["title"].lower()]
        print(f"{len(courses)} course(s): " + "; ".join(c["title"] for c in courses), flush=True)
        failed = 0
        for c in courses:
            try:
                self.archive_course(c)
            except (SessionEnded, RefusedSubmit):
                raise
            except Exception as e:
                failed += 1
                print(f"   !! course {c['title']} failed: {e}", flush=True)
        return failed

    def course_dir(self, c):
        """Existing folder for this stage id if there is one (titles can change
        or misparse), else a new slug_stageid folder."""
        for d in sorted(self.out.glob(f"*_{c['stage_id']}")):
            if d.is_dir() and (d / "course.json").is_file():
                return d
        return self.out / course_dir_name(c)

    def archive_course(self, c):
        cdir = self.course_dir(c)
        (cdir / "modules").mkdir(parents=True, exist_ok=True)
        print(f"\n== {c['title']} (stage {c['stage_id']})", flush=True)
        self.open_course(c["stage_id"])
        html = self.page.content()
        rows = parse_gradebook(html)
        cfile = cdir / "course.json"
        if not rows and (ATTESTATION_RE.search(self.page.url) or 'name="strResponse"' in html):
            print("   CITI wants you to accept its integrity statement before this course opens."
                  "\n   Open the course on citiprogram.org, agree, then re-run.", flush=True)
            prev = prev_course(cfile)
            write_json(cfile, {**prev, **c, "needs_attestation": True,
                               "gradebook": prev.get("gradebook", []),
                               "updated_at": now_iso(), "institution": self.institution})
            return
        prev = prev_course(cfile)
        if not rows:
            print(f"   no gradebook rows parsed at {self.page.url}; keeping the previous "
                  "course record and skipping this course", flush=True)
            return
        prev.pop("needs_attestation", None)
        course = {**prev, **c, "gradebook": merge_gradebook(prev.get("gradebook"), rows),
                  "updated_at": now_iso(), "institution": self.institution}
        write_json(cfile, course)
        todo = [r for r in rows if r["action"]]
        print(f"   {len(rows)} modules: {len(todo)} open, {len(rows) - len(todo)} locked", flush=True)
        for r in todo:
            mfile = cdir / "modules" / f"{r['module_id']}.json"
            old = json.loads(mfile.read_text()) if mfile.is_file() else None
            if old and not self.refresh and old.get("content_html") and \
                    (not old.get("has_quiz") or (old.get("quiz") or {}).get("questions")):
                # Retry any asset that failed last time; no page navigation needed.
                missing = [p for p in self.record_assets(old)
                           if not (cdir / "assets" / asset_filename(p)).is_file()]
                print(f"   = {r['title']} (have it{f'; retrying {len(missing)} assets' if missing else ''})")
                if missing:
                    self.fetch_assets(missing, cdir)
                continue
            try:
                self.archive_module(c, r, cdir, mfile, old)
            except (SessionEnded, RefusedSubmit):
                raise
            except Exception as e:
                print(f"   ! {r['title']}: {e}", flush=True)

    @staticmethod
    def record_assets(record):
        refs = asset_refs(record.get("content_html", ""))
        for q in (record.get("quiz") or {}).get("questions", []):
            refs += asset_refs(q.get("text_html", "") + (q.get("explanation") or ""))
        return list(dict.fromkeys(refs))

    def archive_module(self, c, r, cdir, mfile, old):
        print(f"   + {r['title']} ({r['module_id']})", flush=True)
        self.open_course(c["stage_id"])
        click_form(self.page,
                   f'form[name="module"]:has(input[name="moduleID"][value="{r["module_id"]}"])',
                   self.throttle)
        mod = parse_module(self.page.content())
        if mod is None:
            print(f"     no classic content at {self.page.url}")
            return
        record = {"module_id": r["module_id"], "title": r["title"], "section": r["section"],
                  "content_html": mod["content_html"], "has_quiz": mod["has_quiz"],
                  "fetched_at": now_iso(), "quiz": (old or {}).get("quiz")}
        # Persist the text before anything else can fail: a quiz-step error
        # must not cost the content already in hand.
        write_json(mfile, record)
        self.fetch_assets(asset_refs(mod["content_html"]), cdir)
        if not mod["has_quiz"]:
            return
        click_form(self.page, 'form[action*="pageID=176"]', self.throttle)
        quiz = parse_quiz(self.page.content())
        if not (quiz and quiz["questions"]):
            print(f"     quiz form not found at {self.page.url}")
            return
        record["quiz"] = merge_quiz(record["quiz"], quiz)
        write_json(mfile, record)
        print(f"     quiz {len(quiz['questions'])} questions"
              f" ({len(record['quiz']['questions'])} known)")
        qrefs = [p for p in self.record_assets(record) if p not in asset_refs(mod["content_html"])]
        if qrefs:
            self.fetch_assets(qrefs, cdir)


def session_cookies(ctx):
    return [{"name": c["name"], "value": c["value"], "domain": c["domain"],
             "path": c.get("path", "/")}
            for c in ctx.cookies() if c["domain"].lstrip(".").endswith("citiprogram.org")]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", help="archive directory (required unless --forget)")
    ap.add_argument("--institution", default="1463", help="CITI institution id (PSU = 1463)")
    ap.add_argument("--course", help="only courses whose title contains this text")
    ap.add_argument("--refresh", action="store_true", help="re-fetch modules already archived")
    ap.add_argument("--render-only", action="store_true", help="rebuild HTML from saved JSON, no network")
    ap.add_argument("--profile", default=str(DEFAULT_PROFILE))
    ap.add_argument("--session-store", default=str(DEFAULT_SESSION_STORE))
    ap.add_argument("--max-session-age", type=float, default=24.0)
    ap.add_argument("--timeout", type=int, default=600, help="seconds to wait for an interactive login")
    ap.add_argument("--forget", action="store_true", help="delete the saved session and exit")
    args = ap.parse_args()

    if args.forget:
        forget_session(args.session_store)
        print(f"saved session removed: {args.session_store}")
        return 0
    if not args.out:
        ap.error("--out is required unless --forget is given")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    if args.render_only:
        for s in build_site(out):
            print(f"{s['title']}: {s['archived']}/{s['total']} modules")
        print(f"-> {out / 'index.html'}")
        return 0

    from playwright.sync_api import sync_playwright
    from si_archive.net import Throttle

    profile = Path(args.profile)
    profile.mkdir(parents=True, exist_ok=True, mode=0o700)
    profile.chmod(0o700)
    throttle = Throttle(min_gap=2.5, jitter=2.5, rest_every=20, rest_secs=(8, 20))
    home = f"{BASE}/members/index.cfm?pageID=50&showInstitution={args.institution}"

    status = 1
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            str(profile), channel="chrome", headless=False,
            viewport={"width": 1280, "height": 900},
            args=["--disable-blink-features=AutomationControlled"])
        try:
            saved = load_session(args.session_store, args.max_session_age)
            if saved:
                try:
                    ctx.add_cookies(saved)
                except Exception as e:
                    print(f"saved session unusable ({e})", file=sys.stderr)
                    forget_session(args.session_store)
                    saved = None
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(home, wait_until="domcontentloaded")
            if is_logged_in(page):
                print(f"logged in{' (reused saved session)' if saved else ''}", flush=True)
            else:
                if saved:
                    print("saved session is no longer valid; logging in again", flush=True)
                    forget_session(args.session_store)
                print(f"waiting up to {args.timeout}s -- log in to CITI in the browser window "
                      "(Log In Through My Organization -> your institution)...", flush=True)
                deadline = time.time() + args.timeout
                while not is_logged_in(page):
                    if time.time() > deadline:
                        print("timed out with no session", file=sys.stderr)
                        return 1
                    page.wait_for_timeout(3000)
                print("logged in", flush=True)
                throttle.wait(BASE + "/")
                page.goto(home, wait_until="domcontentloaded")
            save_session(args.session_store, session_cookies(ctx))

            archiver = CitiArchiver(page, ctx, out, args.institution, throttle, refresh=args.refresh)
            try:
                failed = archiver.run(args.course, on_home=True)
                save_session(args.session_store, session_cookies(ctx))
            except SessionEnded as e:
                print(f"stopped: {e}. The saved session was dropped; re-run to log in again "
                      "-- everything archived so far is kept.", file=sys.stderr)
                forget_session(args.session_store)
                status = 2
            else:
                status = 1 if failed else 0
        finally:
            try:
                ctx.close()
            except Exception as e:
                print(f"browser close failed: {e}", file=sys.stderr)
            # Whatever happened above, rebuild the offline pages from what is
            # on disk -- without letting a render error mask the original one.
            try:
                for s in build_site(out):
                    print(f"{s['title']}: {s['archived']}/{s['total']} modules")
                print(f"-> {out / 'index.html'}")
            except Exception as e:
                print(f"rendering failed: {e!r}", file=sys.stderr)
                status = status or 1
    return status


if __name__ == "__main__":
    sys.exit(main())
