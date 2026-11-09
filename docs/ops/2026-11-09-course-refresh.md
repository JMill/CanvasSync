# Course archive refresh — 2026-11-09

Refreshed the private AI574 and ENGR820 archives from the November 4 baseline
using the repository's PSU session and browser archive tools. Course content,
submissions, credentials, signed download URLs and personal data remain outside
GitHub. This record contains only operational results.

## Result

- AI574: Lesson 12 (Speech Recognition) opened. Twelve course files were
  downloaded (Lesson 12 figures). The main manifest now records 135 pages,
  15 assignments, 11 announcements and 197 files. Locked pages fell from 14 to 4
  (Lessons 13–14 and the Course Design Survey remain date-locked). The three
  previously preserved re-locked documents are still kept (`relocked_kept: 3`).
- ENGR820: Module 10 is now `completed` and Module 11 `started`, after the
  Statistical Analysis Part 1 submission. The next wall is
  "Statistical Analysis Exercise Part 2" (`must_submit`), so Modules 12–13 stay
  locked. Three course files were downloaded or refreshed. The manifest still
  records 59 pages, 38 assignments, 13 announcements and 56 files, with three
  pages locked.
- Recovered one new ENGR820 submission attachment (the Experimental Design peer
  review, 67,415 bytes) through its submission download link. It was saved under
  `files/_submission_attachments/` with a `_api/submission_attachments_2026-11-09.json`
  record holding its path, byte size and SHA-256.
- Media sweep (`--video --max-height 1080 --sheets --youtube`): AI574 gained one
  new YouTube embed (a short LipNet demo). The video and YouTube's own captions were
  fetched, and the 40-word transcript was checked as genuine. AI574 now has
  7 embeds, all resolved, 5 with transcripts. ENGR820 is unchanged: 5 embeds, the
  4 Vimeo entries still metadata-only.

## Validation and remaining limitations

- The unlock walker dry-run found nothing to mark viewed in either course. No
  coursework was submitted and no requirements were marked complete.
- Neither archive run reported a download failure. The recovered attachment
  matched its expected byte size and is a valid 4-page PDF.
- Endpoint errors are 120 for AI574 (unchanged) and 46 for ENGR820 (45 before).
  The one new error is the submission attachment above, queried through the
  course-files route. It was recovered as described.
- The login session saved earlier in the day was reused for the media and
  attachment steps without a second Duo prompt.

## Follow-up (done same day)

The submission-attachment gap noted on 2026-11-04 recurred, so the archiver now
enumerates `submission.attachments` from the merged assignments JSON and downloads
each one from its signed URL into `files/_submission_attachments/<id>_<name>`.
A verification re-run picked up 26 ENGR820 and 9 AI574 submission files that had
never been archived. The four previously hand-recovered files kept identical
SHA-256 hashes. Endpoint errors fell to 20 (ENGR820) and 111 (AI574), because
these ids are no longer tried through the course-files route.
