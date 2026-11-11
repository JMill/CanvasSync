# Course archive refresh — 2026-11-11

Refreshed the private AI574 and ENGR820 archives from the November 9 baseline.
Course content, submissions, credentials and personal data stay outside GitHub.
This record holds only operational results.

## Result

- AI574: no new lesson. Lesson 13 (Advanced Topics in NLP) is date-locked until
  2026-11-16T05:00Z, Sunday night on the usual cadence. Lesson 14 and the Course
  Design Survey unlock 2026-11-30. Two submission attachments were downloaded,
  both from the Assignment 3 resubmission made 2026-11-09T15:25Z, ten minutes
  after the previous run. One announcement was added (the Lesson 12 notice,
  posted 18:00Z the same day). The manifest now records 135 pages, 4 locked,
  12 announcements and 208 files. `relocked_kept: 3` as expected.
- ENGR820: byte-identical. 59 pages, 0 locked, 89 files unchanged. Every module
  is `completed`.
- Media sweep (`--video --max-height 1080 --sheets --youtube`): unchanged in
  both. AI574 has 7 embeds, all resolved, 5 with transcripts. ENGR820 has
  5 embeds, and the 4 Vimeo entries are still metadata-only.

## Validation

- The unlock walker dry-run had nothing to mark viewed in either course.
- Neither archive run reported a failed download.
- AI574 endpoint errors went from 111 to 112. The new one is file 197856828,
  the PDF from the *first* Assignment 3 submission. The resubmission replaced it
  in `submission.attachments`, so the archiver now reaches it only through the
  merged `_api/files.json` and the course-files route, which 404s for
  submission files. The copy saved on 2026-11-04 is still on disk under
  `files/_submission_attachments/`. This is noise, not a loss.
- The session saved on 2026-11-09 was over 24h old, so login needed Duo.
  The cookie dump was deleted after use.

## Upcoming (from the merged assignments JSON)

- ENGR820, Tue Nov 17 08:00 ET: Statistical Analysis Exercise Part 3 and
  Literature Critique 7, both unsubmitted. Dec 8: Quiz 4 and the Final
  Research Paper. Quiz 3 is still `pending_review` at 6/20.
- AI574: Assignment 3 resubmitted, not yet graded. Project Presentation video
  is due Dec 6 (23:59 ET). Final Project Deliverables and the Individual
  Feedback Form are due Dec 11 (23:59 ET).
