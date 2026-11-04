# Course archive refresh — 2026-11-04

Refreshed the existing private AI574 and ENGR820 archives from the October 28
baseline using the repository's PSU session and browser archive tools. Course
content, submissions, credentials, signed download URLs and personal data remain
outside GitHub. This record contains only operational results.

## Result

- AI574: eight Lesson 11 pages became available, one announcement was added, and
  six course images were downloaded. The main manifest now records 135 pages,
  15 assignments, 11 announcements and 186 files. Fourteen pages remain locked;
  three previously captured page/assignment documents re-locked upstream were
  preserved.
- ENGR820: two Module 11 pages became available, one announcement was added, and
  four course files were downloaded. The main manifest now records 59 pages,
  38 assignments, 13 announcements and 56 files. Three pages remain locked.
- Saved three newly referenced submission attachments separately under
  `files/_submission_attachments/`: one for AI574 and two for ENGR820. These are
  additional to the main manifest's file counts. Each private course archive has
  a `_api/submission_attachments_2026-11-04.json` record with paths, byte sizes
  and SHA-256 hashes.
- Recovered a previously uncached 74-second AI574 Kaltura lecture and contact
  sheet. Staged it separately, verified its video stream and duration, and merged
  its state into the existing media index. No captions were available. Existing
  media entries were preserved; the AI574 media index now contains six entries.

## Validation and remaining limitations

- Preserved all 167 previously nonempty page bodies and all prior entity IDs.
  Raw HTML changes in 36 AI574 pages were escaping-only changes, with no content
  differences after decoding.
- Verified all ten new course downloads against their expected byte sizes.
  Verified the three supplemental submission attachments against their expected
  sizes and recorded hashes. Neither archive run reported a download failure.
- Validated local targets in both course indexes and media indexes. The media
  reference scan found no new embeds relative to the October 28 baseline; the
  recovered lecture filled an older gap.
- ENGR820's later modules remain gated by coursework. Only a dry-run prerequisite
  check was performed; the refresh did not submit coursework or mark requirements
  complete.
- The raw manifests retain 120 AI574 and 45 ENGR820 endpoint errors, versus 119
  and 43 in the baseline. All three newly reported errors were submission files
  queried through the wrong course-files route. Their direct submission download
  links recovered the files; the supplemental records document that recovery
  without rewriting the original diagnostics. The remaining baseline endpoint
  errors and locked content remain limitations of the archive.
- ENGR820's four existing Vimeo entries remain metadata/poster-only because
  their streams require a separate logged-in session.

## Follow-up for future refreshes

The browser archiver still discovers submission attachment IDs as generic file
references and queries the course-files endpoint, which returns 404 for these
files. A future implementation should enumerate `submission.attachments`, use
their download links, and preserve them in a dedicated attachment collection,
as the current discussion-attachment path already does. This refresh used a
targeted recovery; no runtime source code was changed.
