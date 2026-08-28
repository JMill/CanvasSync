# Final whole-branch review — Systematic Innovation archive

**Verdict: mergeable with specific fixes.** The engineering is strong and the
delivered archive is genuinely good. But three things the spec promises were
never built, are not recorded as deviations anywhere, and are not listed as gaps
in `REPORT.md` — so the archive currently overstates its own completeness. Plus
one fifth instance of the recurring constraint, and one re-run hazard that can
silently gut the delivered site.

193 tests pass (`pytest tests -q`, verified). No network or media stage re-run.

## Deferred-minor triage

**Must fix before merge — 1 of 9:**

- **Task 8 `wiki_slug_to_path` (`render.py`).** The lead's read is right, and
  it is the only deferred minor whose failure mode is *silently wrong content*
  rather than a missing or cosmetically-imperfect artifact. It also closes the
  loop on deferred minor #2 (Task 2 slugs are not de-duplicated upstream), which
  was explicitly deferred *because* the robustness belongs where files are named
  — and this is the one place that names files by trusting slug uniqueness. Fix
  is small: on a second slug claiming the same key, record a gap and strip the
  link rather than resolving it to the first claimant.

**Acceptable to leave — the other 8.** #1 (pushback test name overclaims) is a
naming inaccuracy over correct behaviour. #2 (item slug dedup) is neutralised by
`unique_filename` once the fix above lands. #3, #4 (assignment without settings;
WikiPage with falsy href) are unreachable branches over a frozen local export.
#5 (no end-to-end asset-gap test) is coverage, not correctness — the path was
verified by re-review. #6 (`_asset_local_name` claims a basename pre-download)
produces a cosmetically unnecessary suffix, nothing more. #7 is a process gap.
#9 (link checker ignores `srcset`) hides nothing, since no template emits one.

## New findings

**Important — the fifth violation of "record a gap and continue": `media.py`.**
`contact_sheet` (line 450) calls `subprocess.run` bare, while every other
subprocess call in the same module — 133, 300, 369 — is wrapped. A missing
`ffmpeg` or a `TimeoutExpired` on a 2.2 GB webinar raises straight out.
`derive_all`'s non-Whisper branch (471-474) is likewise unguarded:
`srt.read_text` / `transcript.write_text` on a Dropbox online-only placeholder
or a permission error aborts identically. And `derive_all` has no per-video
`try` at all — it is the one stage-level loop on this branch with no gap-record
path — so a single bad asset kills the multi-hour stage, and since
`bin/si_archive.py:98` only writes `media.json` after the loop returns, the run
yields no manifest at all. Fix: guard `contact_sheet` like `probe_max_volume`,
and wrap the per-video body to append a gap record.

**Important — `si_archive all` can silently destroy the delivered archive.**
`run_stage("elucidat")` re-runs `mirror_all` unconditionally and overwrites
`_build/elucidat.json` with whatever it gets. On a bad network day a project
returns `_project_gap` with `pages: []`; `render` then calls
`clean_owned_output` (which deletes `sections/`) and rebuilds without the 70
Elucidat pages — the primary course content — reporting only gaps. The raw
mirror under `_source/` survives, so this is recoverable, but the delivered site
is gutted and `REPORT.md` would say so only in gap rows. Given the tooling is
built to be re-run, `--all` should skip a completed network stage unless forced,
or refuse to overwrite a good `elucidat.json` with a gap-bearing one.

**Important — `MANIFEST.json` does not implement its spec contract.** The spec
defines it as "every file: provenance, sha256, aliases, decisions", and depends
on it in four further places: student-work bundles recorded by Dropbox path,
ScreenFlow bundles by path and size, reference videos labelled third-party, and
"every file surviving into the archive carries provenance: originating source,
original path or URL, SHA-256, and the reason it was chosen over its aliases."
Delivered: 37 entries of `{video, caption_source}` — Ruling 22's addition,
which appears to have quietly become the whole file. This defeats the spec's
fourth success criterion outright. All the data exists in `_build/ledger.json`
and `_build/local.json`; the fix is a serialization step in `render.py`.

**Important — `documents/` was never built.** The spec's output tree lists
`documents/  3 GDrive DOCX + converted readable form`, and Scope decisions
include them as course content to be "archived and linked". They are indexed in
`local.json` (3 `.docx` under `learning_facilitator_for_systematic_innovation_2/`)
and then dropped: `grep gdrive si_archive/render.py` returns nothing, no `.docx`
exists anywhere under the archive root, and `REPORT.md` does not mention them.
This is the exact failure mode the spec forbids — a silent drop.

**Minor — `_source/cartridge/` and `_source/provenance/` are absent**; only
`_source/elucidat/` was built. The archive therefore depends on Dropbox and
`~/Downloads` for the canonical export and its own provenance PDF. Either copy
them or record the deviation explicitly in `REPORT.md`.

**Minor — verify's 24 checks assert nothing about the deliverable tree.** That
is precisely why 24/24 passes while three spec deliverables are missing. One row
each for `documents/`, `_source/*` and MANIFEST shape would have caught all of
them; add them with the fixes so the report stops overstating coverage.

**Minor — `cartridge.py` guards nothing.** Seven `ET.parse`/`read_text` sites
(39, 65, 81, 94, 106, 111, 215) plus `attach_item_content`'s four parser calls
are unwrapped, where `render.py` guards every equivalent touch point. One
malformed item aborts stage 1. Not blocking — the input is a frozen local export
and the stage is seconds to re-run — but it is the same defect class, and the
inconsistency between the two modules is the clearest cross-cutting seam left.
Same shape at `elucidat.py:210` (`write_text` after all the network work).

## Cross-cutting consistency

Better than expected for nine agents. `cartridge.py`'s boundary is clean — later
modules import `slugify` and the parsers, never reach around them. Gap records
are near-uniform (`{reason, ...context}`); `elucidat.py`'s `_project_gap` /
`_page_gap` and `media.py`'s status strings are different shapes but each is
internally consistent and consumed by exactly one reader. `unique_filename` and
`build_course`'s `dirname` counter duplicate the same idiom in two modules — the
docstring acknowledges it, and factoring it out now would be churn. No dead code
of consequence, no import cycles. `RETIRED_OWNED_TOP_LEVEL` is a genuinely good
piece of engineering.

## Nothing dangerous found

`clean_owned_output` deletes only an explicit name list and can never touch
`_build/` or `_source/`. `slugify` cannot emit a path separator, so no write can
escape the archive root. Every reference to `CARTRIDGE_DIR` / `CAMPUS_DIR` /
`GDRIVE_DIR` is a read. No student data: my independent sweep
(`find` for `*_submissions*` and `*_text.html` across the whole 8.4 GB root,
including `_build/` and `_source/`) returns zero paths, matching the report's
claim. `REPORT.md`'s own caveat about five media rows being self-consistency
checks rather than disk checks is honest and correct.

## Does it satisfy the spec's purpose?

Two of four promises are fully met, two are not.

- *Every idea readable offline* — **yes**, and beyond the plan. 70 Elucidat
  pages baked and revealed, 16 sections in cartridge order, all 45 items, plus
  42 orphaned pages/discussions/assignments rescued into `unlinked/` and the 11
  question banks rendered as source pools rather than dropped.
- *Every video plays with a transcript* — **yes**. 47/47 accounted for, 38
  transcripts, 9 honest `no_speech` markers, 0 failures, caption provenance
  labelled.
- *Nothing silently dropped* — **no**. The 3 GDrive DOCX are dropped and
  unmentioned.
- *Every file's provenance traceable* — **no**. `MANIFEST.json` carries captions
  only.

Fix the DOCX, the manifest, the `--all` overwrite, `contact_sheet`/`derive_all`,
and `wiki_slug_to_path`, and this is a genuinely excellent archive.
