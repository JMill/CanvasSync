# Systematic Innovation — Full Offline Archive

**Date:** 2026-08-27
**Status:** Approved design, ready for implementation planning

## Purpose

Build one self-contained, browsable offline archive of *Systematic Innovation:
Scaling Up from a Hunch* (MIT Professional Education, `SISH-ENG-001-FEB22`,
Feb–Oct 2022) by merging four partial sources into a single deconflicted whole.

The course is no longer reachable on its Canvas instance. Content survives only
as a Common Cartridge export, a live-but-unlinked set of Elucidat projects, a
local media dump, and loose documents. The goal is a reference archive: open
`index.html`, read every idea the course taught, watch every video, with no
network and no server.

Success means: every page of course content is readable offline; every video
plays locally with a transcript; nothing is silently dropped; and every surviving
file can be traced back to where it came from.

## Sources

| # | Source | Role | Inventory |
|---|---|---|---|
| 1 | `MIT Dropbox/…/Systematic Innovation/systematic-innovation-scaling-up-from-a-hunch-february-2022-export/` | **Canonical spine** — IMS Common Cartridge | 16 modules, 23 wiki pages, 24 assignments/discussions, 17 QTI quizzes, 81 web resources |
| 2 | 7 Elucidat projects on `learning.elucidat.com` | **Primary course content** | 70 pages, 2.3 MB HTML, 100 CDN assets, 36 Vimeo embeds |
| 3 | `MIT Dropbox/…/Systematic Innovation/campus.mitpeonline.com/` | Media + evidence layer | 49 MP4 (7.8 GB, 8.7 h), 27 SRT, 8 ScreenFlow (9.5 GB), screenshots |
| 4 | GDrive `…/systematic innovation/` + `Downloads/Learning Facilitator…pdf` | Assignment specs + provenance | 3 DOCX, 1 email thread PDF |

### Elucidat project registry

The user-supplied URL list had 5 entries. The cartridge's `module-N-content.html`
and `information.html` pages reveal **7**. The two additions are authoritative —
they are what the course actually iframed.

| Key | Project code | Pages | Vimeo | Title |
|---|---|---|---|---|
| `M1` | `5f7356442004e-5f7c8b919a261` | 13 | 9 | Module 1. Introduction to General Method and Structure of Problems |
| `M2` | `5f8966ad7f361-5f8ee6beacce6` | 10 | 6 | Module 2. On Hunches and Scoping Out Problems |
| `M3` | `5faa7fce0007f-5fae4255164d6` | 11 | 4 | Module 3. The Structure of an Opportunity Hypothesis |
| `M4` | `5fb68ea13b3de-5fbf667f2742b` | 10 | 5 | Module 4. Making the Problem and Opportunities Tangible |
| `M5` | `5fc61e2550add-5fd774d58f4ee` | 12 | 6 | Module 5. Advocating for What's Next – Scaling Up **(was missing)** |
| `M6` | `5fe0caa101abf-60783a3aa5ce5` | 12 | 5 | Module 6. Creating a Technology – Problem Report |
| `INFO` | `5f59f641d14f2-5f5a024ff039d` | 2 | 1 | Tour Virtual_ENG **(was missing)** |

All 7 return HTTP 200 with no authentication.

### Elucidat content format

Verified by reconnaissance on 2026-08-27:

1. `https://learning.elucidat.com/course/<code>` returns a ~7 KB SPA shell
   containing `var endpoint = {...}` with a `cdn` base URL and the filenames of
   the project's CSS and JS.
2. The project JS at `<cdn>/<endpoint.js>` contains
   `window.NAVIGATION_OBJECT = {url_format, pages}` — a complete page manifest
   mapping page id → `{n: name, p: parent id, sec: is_section}`.
3. Each page at `<cdn>/<page_id>.js` is a call
   `e._load_json({page_id, content_id, completed_by, lmth})`.
   **`lmth` is `html` spelled backwards, and its value is the page HTML with the
   character order reversed** — light obfuscation, defeated by `s[::-1]`.
   `String.prototype.reverse` is defined in the project JS immediately above
   `NAVIGATION_OBJECT`, confirming intent.

There is no DRM and no encryption. Content is fully archivable.

## Rendering decision: bake and reveal

Elucidat pages are fragments assembled by a JS player. A representative page
(M1 §1) is 66 KB of HTML yielding 9 KB of flat text, with 56 accordion, 48
modal, 48 carousel, and 9 collapse references. **Most content is behind a click.**

Options considered:

- **A. Rehost the player.** Mirror the player JS/CSS and rewrite `endpoint` to
  local paths. Highest fidelity, but the player fetches page data by XHR (blocked
  under `file://` CORS) and reports to an LRS at `api.elucidat.com`. Rejected: it
  makes the archive depend on the semantics of a third party's JS, which is the
  fragility the archive exists to escape.
- **B. Bake flat HTML.** Decode `lmth` into a static shell. Durable, but loses
  the ~85% of content inside collapsed panels. Rejected as lossy.
- **C. Bake and reveal — CHOSEN.** Decode to standalone HTML, retain Elucidat's
  own stylesheet for visual fidelity, then apply a *reveal* stylesheet that
  force-expands every accordion, tab, modal, and carousel slide into linear
  document flow. Generate prev/next navigation from `NAVIGATION_OBJECT`. Nothing
  requires JS to read; nothing stays hidden.

The trade is explicit: **interactivity is lost, content is not.** Interactive
e-learning hides content for pacing, not secrecy. To keep the decision
reversible, unmodified player assets and raw page JS are archived under
`_source/elucidat/`, so a full-fidelity reconstruction remains possible later
without re-fetching.

## Deconfliction model

The same work appears across sources in three distinct relationships, each
handled differently.

**1. Byte-identical duplicates.** Detected by SHA-256 over file contents.
Collapse to one canonical copy; every other path is recorded as an alias.
Example: the cartridge ships `Program Outline Systematic Innovation ENG.pdf`,
`Program Outline Systematic Innovation ENG (2).pdf`, and an `Information/`
copy of the same document.

**2. Renditions — same work, different encoding.** Cannot hash-match. Paired on
`(duration within ±1 s, normalized title)`. The highest-quality rendition
becomes canonical; the other is recorded in the ledger and **never silently
discarded**. This is the dominant Vimeo case: Vimeo `605462161` is titled
`MIT_INN_M1_V2` and is the same work as local `Module 1/MIT_INN_M1_V2.mp4`.

**3. Distinct works.** Kept separately, each with provenance.

Vimeo embeds fall into two access classes, both resolvable:

- **Hashed** (`605462161?h=50187719bc`) — unlisted MIT PE recordings, named
  `MIT_INN_M<n>_V<n>`, corresponding to local MP4s. Resolve at 1920×1080.
- **Bare id** (`464955563`) — third-party reference material. Must be requested
  via `player.vimeo.com/video/<id>`; the `vimeo.com/<id>` form fails yt-dlp's
  OAuth path. Most are also present locally, e.g. *Tracking fingers with the Wii
  Remote* and *Interview with Arthur C. Clarke, AT&T-MIT Conference, 1976*
  (local copy 16 MB; Vimeo copy 343 s and likely higher quality — a rendition
  match, not an online-only asset).

One id, `777331374` (INFO), returned a TLS-fingerprint block on first attempt.
Implementation must retry it with `--impersonate` (via `curl-cffi`) and, if it
still fails, record it as a known gap in `REPORT.md` rather than failing the run.

Every file surviving into the archive carries provenance: originating source,
original path or URL, SHA-256, and the reason it was chosen over its aliases.

## Scope decisions

**Excluded — student work.** The 9 `*_submissions` bundles and 14 `*_text.html`
dumps contain named student submissions (FERPA-adjacent). They are **not copied
into the archive** and **not linked from any page**. `MANIFEST.json` records that
they exist and their Dropbox paths, nothing more. Two MP4s inside those bundles
are consequently excluded from all media processing.

**Included — assignment prompts.** Assignment and discussion instructions,
rubrics, and the 3 GDrive DOCX assignment specifications are course content and
are archived and linked.

**Referenced, not copied — ScreenFlow bundles.** 8 bundles totalling 9.5 GB are
editable production masters, not viewable deliverables. Recorded in
`MANIFEST.json` with their Dropbox paths and sizes.

**Copied — MP4s and SRTs.** 47 MP4s (49 minus 2 student submissions) and 27 SRTs.

## Output

**Location: `/Volumes/Desk SSD/SystematicInnovation-Archive/`.**

This is a hard constraint, not a preference. The boot volume has 22 GB free of
1.8 TB (99% full); the archive needs roughly 20 GB. `Desk SSD` has 7.3 TB free.

```
SystematicInnovation-Archive/
  index.html                  course home; all 16 sections in cartridge order
  sections/
    01-homepage/
    02-requirements-and-information/
    03-initial-survey/
      quiz.html               QTI rendered as a readable document
    04-module-1-part-1/
      index.html              Canvas wiki page content
      elucidat/
        00-index.html         Elucidat TOC for this project
        01-introduction.html  one file per page, revealed
        assets/               CDN media, URLs rewritten to local paths
      media/
        MIT_INN_M1_V1.mp4
        MIT_INN_M1_V1.srt
        MIT_INN_M1_V1.transcript.md
        MIT_INN_M1_V1.contactsheet.jpg
      assignments/            prompts and rubrics only
      discussions/            prompts only
    …                         through 16-continuous-education-units/
  orientation/                campus `pre/` — onboarding, webinars, Mud Cards
  closing/                    campus `post/` — CEU survey, exit survey, certificate
  files/                      81 web resources, cartridge subfolders preserved
  documents/                  3 GDrive DOCX + converted readable form
  _source/
    cartridge/                unmodified export
    elucidat/                 raw page JS, player assets, NAVIGATION_OBJECT
    provenance/               the originating email PDF
  MANIFEST.json               every file: provenance, sha256, aliases, decisions
  REPORT.md                   coverage, gaps, unresolved items
```

**Section numbering follows the cartridge**, not the Elucidat module numbers. The
cartridge's 16 modules include non-numbered ones (`Homepage`, `Requirements and
Information`, `Initial Survey`, `Final Survey`, `Final assessment`, `Certificate
of Completion`, `MIT CEUs Survey`, `Continuous Education Units`) and split
Module 1 across three (`Module 1 - Part 1`, `- Part 2 and 3`, `- Part 4`). The
site preserves that order because it is the course as actually taught; the
Elucidat project for a section is inlined wherever the cartridge iframed it.

**Quizzes.** All 17 QTI assessments render as readable documents — questions,
options, and correct answers where the QTI records them. Several are surveys
(`Initial Survey`, `Final Survey`, `MIT CEUs Survey`) with no correct answers;
these render as questionnaires.

**Media placement.** Campus media maps to sections by its parent folder:
`Module N/` → the corresponding section(s), `pre/` → `orientation/`, `post/` →
`closing/`. `pre/webinars/` (2 recordings, 2.2 GB) and `pre/Mud Cards/` land in
`orientation/`. Reference videos under `Module N/references/` stay with their
section and are labelled as third-party material in `MANIFEST.json`.

**Files.** The cartridge's `web_resources/` subfolder structure (`Information/`,
`FAQs/`, `unfiled/`, `Diseño/`) is preserved under `files/` so cartridge-relative
`$IMS-CC-FILEBASE$` links rewrite mechanically. Deduplication replaces duplicate
*files*, not the folder layout: an alias path becomes a record in `MANIFEST.json`,
and any page linking it is rewritten to the canonical copy.

## Pipeline

Eight stages. Each is a module with one responsibility that reads and writes JSON,
so any stage re-runs independently — necessary because transcription is the slow
step and should not force a full rebuild.

| # | Module | Input | Output |
|---|---|---|---|
| 1 | `ingest_cartridge` | Source 1 | `course.json` — canonical module/item spine |
| 2 | `fetch_elucidat` | 7 project codes | `elucidat/`, `elucidat.json` |
| 3 | `fetch_vimeo` | 36 ids from stage 2 | `vimeo/`, `vimeo.json` |
| 4 | `ingest_local` | Sources 3, 4 | `local.json` — SHA-256 file ledger |
| 5 | `reconcile` | stages 1–4 | `ledger.json` — canonical/alias/rendition decisions |
| 6 | `media_derive` | `ledger.json` | `transcripts/`, `contactsheets/` |
| 7 | `render_site` | `ledger.json`, `course.json` | static HTML |
| 8 | `verify` | the built archive | `REPORT.md` |

### Stage notes

**2 — `fetch_elucidat`.** Fetch shell → parse `endpoint` → fetch project JS →
parse `NAVIGATION_OBJECT` → fetch each page JS → reverse `lmth` → rewrite
`cdn.elucidat.com` asset URLs to local relative paths → download those assets.

**3 — `fetch_vimeo`.** `yt-dlp` with `--referer https://learning.elucidat.com/`,
best MP4, plus any native captions. Always the `player.vimeo.com/video/<id>` form.
Retry TLS-blocked ids with `--impersonate`.

**6 — `media_derive`.** Transcribe the **20** MP4s that lack an SRT and are not
student submissions, using `mlx-whisper` (`large-v3`) — Metal-accelerated on this
M2 Max. Convert existing SRTs to the same `.transcript.md` format so every video
has one artifact type. Generate ffmpeg contact sheets for videos over 3 minutes.

**7 — `render_site`.** Two cartridge items are `ContextExternalTool` launches
(`Certificate of Completion`, `Continuous Education Units`) which point at a
third-party LTI provider and hold no archivable content. They render as
placeholder pages naming the tool and are listed as known gaps in `REPORT.md`.

**8 — `verify`.** Assert: every cartridge item resolves to a page or a recorded
gap; no broken relative links; no orphaned files; no student-work path present;
every video has a transcript or a logged reason. Failures become entries in
`REPORT.md`, not exceptions.

## Code layout

New `si_archive/` package in the CanvasSync repo, driven by `bin/si_archive.py`
with per-stage subcommands and a `--all` driver.

`Throttle` currently lives inside `bin/canvas_media_archive.py`. It is lifted
into a shared module and imported by both, since a third tool now needs it.
This is the only change to existing code.

**Network pacing is mandatory** (per `CLAUDE.md`): all access serial, randomised
gaps, periodic longer rests, and backoff that persists after any 429/503.
Reconnaissance already followed this and drew no pushback.

**Dependencies to install into `.venv`:** `beautifulsoup4`, `lxml`, `yt-dlp`,
`Pillow`, `mlx-whisper`, `curl-cffi`. `ffmpeg` 8.1.1 and `yt-dlp` 2026.02.04 are
already present on the system.

## Risks

| Risk | Mitigation |
|---|---|
| Elucidat CDN withdraws content mid-build | Stage 2 runs first and archives raw JS to `_source/` before any processing |
| Reveal CSS fails to expand an unforeseen widget type | Stage 8 flags pages whose revealed text is anomalously short relative to raw HTML |
| Vimeo rate-limits or TLS-blocks | Paced serial requests; `--impersonate` retry; unresolved ids logged as gaps, run continues |
| Whisper output quality on 8.7 h of audio | `large-v3`; existing 27 SRTs act as a spot-check baseline |
| Disk exhaustion | Output on `Desk SSD` (7.3 TB free); stage 8 reports final size |
