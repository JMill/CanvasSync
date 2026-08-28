# Rulings made during execution

45 decisions taken on the user's behalf, in order, each with what it costs if wrong.

**1.** `bin/si_archive.py` must insert its repo root at `sys.path[0]` before importing `si_archive` — `sys.path.insert(0, str(Path(__file__).resolve().parent.parent))`.
   _Cost if wrong: two lines of defensive path setup in one script; no behavioural risk._

**2.** `media.derive_all` takes `(local, out_dir)`.
   _Cost if wrong: a later stage wanting ledger-aware transcription needs the parameter added._

**3.** `vimeo.download()` must record the downloaded file's size (`Path(path).stat().st_size` when the file exists), added to its returned record.
   _Cost if wrong: one extra stat call per download._

**4.** the cartridge content path must be completed end to end.
   _Cost if wrong: rework in Tasks 2 and 8; carried into both dispatches rather than discovered at final review._

**5.** `slugify` strips apostrophes before the punctuation pass — add `folded = folded.replace("'", "").replace("’", "")` before the `[^\w\s-]` substitution.
   _Cost if wrong: slugs for possessive titles differ by one hyphen; no cross-task reference depends on the exact form since `dirname` is generated once and consumed from course._

**6.** the spec's "17 QTI quizzes" is wrong — it counted files in `non_cc_assessments/`.
   _Cost if wrong: banks are archived that the reader may not care about — additive, not lossy._

**7.** **(deferred minor, not blocking)** a plugin hook flags `xml.etree.ElementTree` as XXE/billion-laughs vulnerable and recommends `defusedxml`.
   _Cost if wrong: negligible — the input is not attacker-controlled._

**8.** correct the spec's inventory line from "17 QTI quizzes" to "6 assessments + 11 question banks" so REPORT.md's coverage claims derive from a true denominator.
   _Cost if wrong: none — this is a factual correction verified by parsing every file._

**9.** `scripts/task-brief` extracts only the `## Task N` section, so no brief carries the plan's Global Constraints or Constants block — Task 1's implementer hit this at Step 8 ("the Constants section above" did not exist in its brief) and recovered it from the full plan itself.
   _Cost if wrong: one extra file per dispatch._

**10.** ratify the Task 1 implementer's extension of Ruling 1 to `bin/canvas_media_archive.py`.
   _Cost if wrong: none — a sys._

**11.** quizzes must be parsed from `non_cc_assessments/<identifierref>.xml.qti` when that file exists, falling back to the manifest's `<id>/assessment_qti.xml` only when it does not.
   _Cost if wrong: none — the fallback preserves the manifest path, and the non-CC file is a strict superset wherever they differ._

**12.** widen `match_renditions`' duration tolerance from 1.0s to 2.0s, and update the brief's `test_match_renditions_ignores_a_duration_mismatch` fixture (100.0 vs 400.0) — it still fails at 2.0s, so the test stays valid unchanged.
   _Cost if wrong: two distinct works within 2s that also share a normalized title would be wrongly paired — implausible for this corpus._

**13.** fix the unguarded network calls in `mirror_project`.
   _Cost if wrong: a little more error-handling code in one function._

**14.** fix `page_order`'s duplicate risk.
   _Cost if wrong: a redundant guard on a function that already behaves._

**15.** bundle the Minor asset-basename-collision guard into this same fix round rather than deferring it.
   _Cost if wrong: one extra dict lookup per asset._

**16.** **(for Task 9, verify)** REPORT.md must flag an implausible gap RATE, not merely list gaps.
   _Cost if wrong: a threshold occasionally trips on a legitimately bad day and a human looks at it._

**17.** start Task 7 (transcripts) now, in parallel with Task 4's download run, rather than waiting for the pipeline order.
   _Cost if wrong: a lost update on bin/si_archive._

**18.** fix `index_screenflow_bundles` to apply `is_student_work`.
   _Cost if wrong: one redundant check per bundle._

**19.** bundle the case-sensitivity Minor into the same fix.
   _Cost if wrong: negligible._

**20.** bundle the `ffprobe` FileNotFoundError Minor.
   _Cost if wrong: one extra exception class in an except clause._

**21.** fix `download()` so it genuinely cannot raise.
   _Cost if wrong: one try/except folding into the existing `_gap_record`._

**22.** Task 8 must also carry Whisper-generated SRTs into the archive, not only the prose transcripts.
   _Cost if wrong: 20 extra small files in the archive._

**23.** **(IMPORTANT — found by spot-checking transcript CONTENT, not counts)** 9 of 45 transcripts are Whisper hallucinations on non-speech audio and must not ship as-is..

**24.** **(for Task 9)** REPORT.md must count and list no-speech videos as a named category, distinct from both successful transcripts and failures.

**25.** fix `match_renditions` so one local file cannot be claimed by two different Vimeo videos.
   _Cost if wrong: a claimed-set adds one line and cannot change today's output._

**26.** **(MY ERROR)** the addendum test I wrote to pin Ruling 12 is vacuous.
   _Cost if wrong: none; this strictly strengthens a test._

**27.** **(IMPORTANT)** `transcribe()` must not guess the filename mlx_whisper produced.

**28.** Whisper has a THIRD hallucination mode beyond silence and music — a repetition loop partway through a long, genuinely speech-bearing recording.

**29.** split the failure status.
   _Cost if wrong: one extra status value in the schema and in REPORT._

**30.** attempt one recovery pass on the two webinars only, with `--condition-on-previous-text False` (the standard mitigation for mlx-whisper repetition loops on long audio).
   _Cost if wrong: roughly 30 minutes of GPU time._

**31.** **(ratifying the fixer's own find)** `transcribe()` must clear any prior-run `.transcript.md` or marker carrying a different verdict before writing this run's result.
   _Cost if wrong: a delete of a file that was about to be overwritten anyway._

**32.** **(MY ERROR — the most serious defect found this session)** the brief's `place_media` would have copied only 14 of 47 videos into the archive, and my task-8 addendum explicitly blessed it with "Brief Step 6's place_media and destination_for stand as written.".

**33.** **(MY ERROR, found by applying Ruling 32's lesson immediately rather than waiting for review)** the Task 9 addendum asserted "Transcripts >= 90% of in-scope videos".

**34.** rewrite the Canvas cross-reference tokens I never specified.
   _Cost if wrong: a rewrite that mis-targets a link, visible immediately as a 404 in the link checker._

**35.** **(REAL CONTENT LOSS, same class as the orphaned assessment I did catch)** 8 wiki pages exist in the cartridge but are absent from the archive because they are not reachable from any module — captains-log, continue-your-journey (14.5KB), faculty-bio, faq (12.7KB), fire-hydrant-award, help, recorded-webinars, wiki.
   _Cost if wrong: 8 extra pages in the archive, which is the correct direction of error._

**36.** fix `transcribe()` to clear the prior artifact only AFTER the new one is written.
   _Cost if wrong: a stale artifact survives a failed run, which is the lesser error and still visible in media._

**37.** replace the three ad-hoc degeneracy heuristics with a compression-ratio check as the primary rule, keeping the existing three as secondary.
   _Cost if wrong: a genuinely repetitive but real transcript is flagged, which is visible and recoverable since the raw srt is retained._

**38.** **(CRITICAL)** `_elucidat_pages()` counts `len(value["pages"])` without filtering on status, but `mirror_project` appends `_page_gap` records (status "gap", file None, no HTML written) into that same list and continues by design.

**39.** **(Important)** the media/transcription rows are pure manifest self-agreement — the exact circularity my own brief warned about.
   _Cost if wrong: one more directory listing._

**40.** **(MY MISS — a silent drop, the exact thing the spec forbids)** `documents/` was never built.
   _Cost if wrong: none; this is restoring a promised deliverable._

**41.** **(MY RULING DISPLACED THE SPEC)** MANIFEST.json does not implement its contract.
   _Cost if wrong: none._

**42.** **(the predicted FIFTH instance)** `media.py` violates "record a gap and continue" in two places — `contact_sheet` calls subprocess.run bare while every other subprocess call in the same module is wrapped, and `derive_all` has no per-video try at all, making it the only stage-level loop on the branch with no gap-record path.

**43.** **(RE-RUN HAZARD, matters because this is backup tooling)** `si_archive all` can silently gut the delivered archive.
   _Cost if wrong: a forced re-mirror needs an explicit flag._

**44.** fix `wiki_slug_to_path` — the reviewer confirms it is the one deferred minor to block on, being the only one whose failure mode is silently WRONG content rather than missing content, and it closes the loop on the Task 2 slug-dedup minor that was deferred precisely because the robustness belongs where files are named.

**45.** **(the sharpest structural finding)** verify's 24 checks assert nothing about the deliverable TREE, which is exactly why 24/24 passed while three spec deliverables were missing.
