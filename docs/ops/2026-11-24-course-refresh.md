# Course archive refresh — 2026-11-24

Refreshed the private AI574 and ENGR820 archives from the November 13 baseline.
Course content, submissions, credentials and personal data stay outside GitHub.
This record holds only operational results.

## Result

- AI574: **Lessons 13 and 14 are both open.** Lesson 14 opened ahead of its
  earlier 2026-11-30 `unlock_at`. Only the Course Design Survey is still
  locked. pages_locked 4 -> 0. `relocked_kept` has dropped out of the
  manifest: the three Lesson 14 items held since October 21 now archive live
  content, and the two Lesson 14 pages contain no lock stub. Announcements
  12 -> 13 ("Lesson 13", posted 2026-11-18). Files 208 -> 210: 5 downloaded
  (the Templates folder's project write-up / slides / code templates plus two
  images), 204 unchanged, 0 failed.
- ENGR820: content unchanged, still 59 pages with 0 locked. Announcements
  13 -> 14 ("Module 12", 2026-11-18). Files 89 -> 91: 6 downloaded, made up of
  2 new submission attachments (Statistical Analysis Part 3, Literature
  Critique 7) and 4 earlier attachments fetched again after their metadata
  changed at grading.
- Media sweep (`--video --max-height 1080 --sheets --youtube`): AI574 went
  from 7 to 8 embeds, all resolved, 6 with transcripts. The new embed is a
  YouTube how-to for recording a presentation video in PowerPoint (Lesson 14),
  with YouTube captions. ENGR820 is unchanged at 5 embeds, and its Vimeo
  entries are still metadata-only.

## Validation

- The unlock walker dry-run had nothing to mark viewed in either course.
  Every AI574 lesson module reports `completed`, and so does every ENGR820
  module.
- Neither archive run reported a failed download. Endpoint error counts are
  the same as on November 13 (AI574 112, ENGR820 20): the usual course-files
  404s for student-hidden and submission files.
- Each course ran as a separate command, with no shell loop (see the
  November 13 note).
- The saved session was 11 days old, so the login needed Duo. The cookie
  dump was deleted after use.

## Grading changes (merged assignments JSON)

- ENGR820: graded since November 13 are Quiz 3 (20/20, no longer
  `pending_review`), Literature Critique 6 and 7, Statistical Analysis
  Parts 2 and 3 (20 each), and Experimental Design second submission (50).
- AI574: the Assignment 3 resubmission is still ungraded.

## Upcoming

- AI574: the **Final Project Deliverables and Individual Feedback Form moved
  earlier**, from Dec 11 to **Dec 9, 23:59 ET** (`2026-12-10T04:59:59Z`).
  Project Presentation video is due Dec 6, 23:59 ET, and the SEEQ evaluation
  Dec 11. All three Lesson 14 assignments are now unlocked.
- ENGR820, Tue Dec 8 08:00 ET: Quiz 4 and the Final Research Paper/Proposal.
  Nothing else is outstanding.
