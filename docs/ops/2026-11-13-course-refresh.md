# Course archive refresh — 2026-11-13

Refreshed the private AI574 and ENGR820 archives from the November 11 baseline.
Course content, submissions, credentials and personal data stay outside GitHub.
This record holds only operational results.

## Result

- AI574: unchanged. No new lesson (Friday run). Lesson 13 is still date-locked
  until 2026-11-16T05:00Z; Lesson 14 and the Course Design Survey until
  2026-11-30. Manifest identical apart from `archived_at`: 135 pages, 4 locked,
  12 announcements, 208 files (207 unchanged, 0 downloaded, 0 failed),
  `relocked_kept: 3` as expected.
- ENGR820: unchanged content. 59 pages, 0 locked, 89 files unchanged,
  13 announcements. One grading change in the merged assignments JSON: the
  Experimental Design peer review was graded 2026-11-12T02:18Z, replacing the
  stale missing-placeholder noted on November 9.
- Media sweep (`--video --max-height 1080 --sheets --youtube`): unchanged in
  both. AI574 7 embeds, all resolved, 5 with transcripts; ENGR820 5 embeds,
  Vimeo entries still metadata-only.

## Validation

- The unlock walker dry-run had nothing to mark viewed in either course.
- Neither archive run reported a failed download. Endpoint error counts are
  unchanged from November 11 (AI574 112, ENGR820 20): the usual course-files
  404s for student-hidden and submission files.
- The ENGR820 archive initially did not run: the wrapping shell loop aborted on
  a zsh `=word` expansion (`echo ====`) after AI574 finished. Re-run on its own;
  operator error, not a tool or Canvas fault.
- The cookie dump was deleted after use.

## Upcoming (from the merged assignments JSON)

- ENGR820, Tue Nov 17 08:00 ET: Statistical Analysis Exercise Part 3 and
  Literature Critique 7, both unsubmitted. Awaiting grades: Literature
  Critique 6, Statistical Analysis Part 2, Experimental Design second
  submission; Quiz 3 still `pending_review` at 6/20. Dec 8: Quiz 4 and the
  Final Research Paper.
- AI574: Assignment 3 resubmission still ungraded. Project Presentation video
  due Dec 6 (23:59 ET); SEEQ evaluation Dec 11; Final Project Deliverables and
  Individual Feedback Form Dec 11 (23:59 ET).
