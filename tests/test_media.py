from collections import Counter
from pathlib import Path
from unittest.mock import MagicMock, patch

from si_archive import media

SRT = """1
00:00:01,000 --> 00:00:04,000
Innovation is not a bolt of lightning.

2
00:00:04,500 --> 00:00:07,000
It is a method you can practise.
"""

# Realistic prose, not two sentences -- exercises the degeneracy screen's
# unique-word and top-word-share thresholds against real-shaped text.
REALISTIC_TRANSCRIPT = (
    "Innovation rarely arrives as a single flash of insight. It is built from "
    "a disciplined sequence of observation, abstraction, and testing that a "
    "team can repeat on purpose rather than wait to stumble into by accident. "
    "In this module we trace how a founder moves from a vague hunch about a "
    "market gap toward a validated concept that investors and engineers can "
    "both act on. We look at interviews, prototypes, competitive landscapes, "
    "and the messy iteration between them, and we ask what separates teams "
    "that converge quickly from teams that circle the same idea for months "
    "without ever committing to a direction worth testing in the real world. "
    "Along the way we introduce a handful of frameworks for structuring "
    "ambiguous problems, weigh their tradeoffs against each other, and close "
    "with a short case study drawn from a hardware startup that pivoted twice "
    "before finding a market that actually wanted what it was building."
)


# A phrase-loop hallucination: unlike a single repeated word, this keeps
# unique-word count and top-word share inside the first two degeneracy
# thresholds while the type-token ratio (unique/total) collapses -- the
# shape of the real MITPE-Onboarding failure (110 unique words / 48,933
# total = 0.22%).
PHRASE_LOOP = [
    "I am a graduate student at MIT.",
    "I'm a graduate student here at MIT.",
    "I study bioengineering at MIT.",
    "Thanks so much for having me today.",
    "This has been a great program so far.",
    "Welcome everyone to the onboarding session.",
]


def _srt_from_sentences(text, start_seconds=1):
    """Build a minimal, well-formed SRT out of a period-separated paragraph,
    one cue per sentence, one second apart, starting at `start_seconds`.
    """
    sentences = [s.strip() for s in text.split(". ") if s.strip()]
    cues = []
    for i, sentence in enumerate(sentences, start=0):
        t0, t1 = start_seconds + i, start_seconds + i + 1
        cues.append(f"{i + 1}\n{_ts(t0)} --> {_ts(t1)}\n{sentence}")
    return "\n\n".join(cues) + "\n"


def _srt_phrase_loop(repeats, start_seconds, cue_seconds=3):
    """One cue per phrase repetition, `cue_seconds` apart, starting at
    `start_seconds`, cycling through several short phrases -- keeps unique-
    word count and top-word share healthy-looking while the type-token
    ratio collapses (see PHRASE_LOOP above).
    """
    cues = []
    for i in range(repeats):
        t0 = start_seconds + i * cue_seconds
        t1 = t0 + cue_seconds
        cues.append(f"{i + 1}\n{_ts(t0)} --> {_ts(t1)}\n{PHRASE_LOOP[i % len(PHRASE_LOOP)]}")
    return "\n\n".join(cues) + "\n"


def _srt_single_phrase_loop(phrase, repeats, start_seconds, cue_seconds=3):
    """One short phrase repeated verbatim, `cue_seconds` apart -- the
    classic Whisper repetition-loop signature ("OK. OK. OK...."), as
    opposed to `_srt_phrase_loop`'s cycling variant used to stress the
    type-token ratio rule specifically.
    """
    cues = []
    for i in range(repeats):
        t0 = start_seconds + i * cue_seconds
        t1 = t0 + cue_seconds
        cues.append(f"{i + 1}\n{_ts(t0)} --> {_ts(t1)}\n{phrase}")
    return "\n\n".join(cues) + "\n"


def _ts(seconds):
    hours, rem = divmod(int(seconds), 3600)
    minutes, secs = divmod(rem, 60)
    millis = round((seconds - int(seconds)) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def test_srt_to_markdown_keeps_text_and_drops_cue_numbers():
    out = media.srt_to_markdown(SRT)
    assert "Innovation is not a bolt of lightning." in out
    assert "It is a method you can practise." in out
    assert "00:00:01,000" not in out
    assert "\n1\n" not in out


def test_srt_to_markdown_joins_cues_into_flowing_text():
    out = media.srt_to_markdown(SRT)
    assert "lightning. It is a method" in out


def test_needs_transcription_is_false_when_a_sibling_srt_exists():
    record = {"path": "/x/MIT_INN_M1_V1.mp4", "ext": ".mp4"}
    assert not media.needs_transcription(record, {"/x/MIT_INN_M1_V1.srt"})


def test_needs_transcription_is_true_without_an_srt():
    record = {"path": "/x/webinar.mp4", "ext": ".mp4"}
    assert media.needs_transcription(record, set())


def test_needs_transcription_ignores_non_video():
    record = {"path": "/x/notes.pdf", "ext": ".pdf"}
    assert not media.needs_transcription(record, set())


# --- Defect 1: silence probe and degeneracy screen -------------------------


def test_is_silent_classifies_a_silent_reading_and_a_normal_reading():
    assert media.is_silent(-91.0)       # silent screen recording
    assert not media.is_silent(-23.4)   # normal speech audio


def test_probe_max_volume_parses_ffmpeg_volumedetect_output():
    silent = MagicMock(stderr="[Parsed_volumedetect_0] mean_volume: -91.0 dB\n"
                               "[Parsed_volumedetect_0] max_volume: -91.0 dB\n")
    normal = MagicMock(stderr="[Parsed_volumedetect_0] mean_volume: -23.2 dB\n"
                               "[Parsed_volumedetect_0] max_volume: -0.5 dB\n")
    with patch.object(media.subprocess, "run", return_value=silent):
        assert media.probe_max_volume("/x/silent.mp4") == -91.0
    with patch.object(media.subprocess, "run", return_value=normal):
        assert media.probe_max_volume("/x/lecture.mp4") == -0.5


def test_is_degenerate_transcript_flags_a_repeated_single_word():
    text = media.srt_to_markdown(
        "\n\n".join(f"{i}\n00:00:{i:02d},000 --> 00:00:{i + 1:02d},000\nyou"
                    for i in range(1, 60)))
    assert media.is_degenerate_transcript(text)


def test_is_degenerate_transcript_accepts_realistic_prose():
    text = media.srt_to_markdown(_srt_from_sentences(REALISTIC_TRANSCRIPT))
    assert not media.is_degenerate_transcript(text)


def test_transcribe_skips_whisper_and_records_no_speech_for_silent_audio(tmp_path):
    mp4 = tmp_path / "Systematic Innovation Module 1.mp4"
    out = tmp_path / "Systematic Innovation Module 1.transcript.md"
    probe = MagicMock(stderr="max_volume: -91.0 dB\n")

    with patch.object(media.subprocess, "run", return_value=probe) as run:
        result = media.transcribe(str(mp4), out)

    run.assert_called_once()  # only the volumedetect probe -- never whisper
    assert result["status"] == "no_speech"
    assert result["reason"] == "silent audio track"
    assert not out.exists()
    marker = tmp_path / "Systematic Innovation Module 1.no_speech.md"
    assert marker.exists()
    assert "silent audio track" in marker.read_text()


def test_transcribe_rejects_a_degenerate_whisper_transcript(tmp_path):
    mp4 = tmp_path / "Uses of Virtual Singapore.mp4"
    out = tmp_path / "Uses of Virtual Singapore.transcript.md"
    degenerate_srt = "\n\n".join(
        f"{i}\n00:00:{i:02d},000 --> 00:00:{i + 1:02d},000\nWe'll be right back."
        for i in range(1, 40))
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if "volumedetect" in cmd:
            return MagicMock(stderr="max_volume: -3.6 dB\n")
        (tmp_path / "Uses of Virtual Singapore.srt").write_text(degenerate_srt)
        return MagicMock(returncode=0, stderr="", stdout="")

    with patch.object(media.subprocess, "run", side_effect=fake_run):
        result = media.transcribe(str(mp4), out)

    assert result["status"] == "no_speech"
    assert result["reason"] == "no speech detected in audio"
    assert not out.exists()
    # The raw whisper output is never destroyed, even when it's discarded.
    assert (tmp_path / "Uses of Virtual Singapore.srt").exists()
    # Genuinely no speech (degenerate from the very first cue) does not
    # deserve a recovery retry -- there's nothing to recover.
    assert not any("--condition-on-previous-text" in cmd for cmd in calls)


def test_transcribe_accepts_a_normal_whisper_transcript(tmp_path):
    mp4 = tmp_path / "webinar.mp4"
    out = tmp_path / "webinar.transcript.md"

    def fake_run(cmd, **kwargs):
        if "volumedetect" in cmd:
            return MagicMock(stderr="max_volume: -0.5 dB\n")
        (tmp_path / "webinar.srt").write_text(_srt_from_sentences(REALISTIC_TRANSCRIPT))
        return MagicMock(returncode=0, stderr="", stdout="")

    with patch.object(media.subprocess, "run", side_effect=fake_run):
        result = media.transcribe(str(mp4), out)

    assert result["status"] == "ok"
    assert result["source"] == "whisper"
    assert out.exists()
    assert "Innovation" in out.read_text()


# --- Defect 2: produced-file discovery by directory diff -------------------


def test_transcribe_finds_a_produced_srt_whose_name_the_stem_guess_misses(tmp_path):
    """mlx_whisper strips more of the filename than Path.stem does: for
    'MITPE.FW.SISH.ENG.090322.mp4' it wrote 'MITPE.FW.SISH.ENG.srt', not
    'MITPE.FW.SISH.ENG.090322.srt'. transcribe() must find it by diffing the
    output directory rather than guessing the name, or it silently discards
    a completed hour-long transcription as a "gap".
    """
    mp4 = tmp_path / "MITPE.FW.SISH.ENG.090322.mp4"
    out = tmp_path / "MITPE.FW.SISH.ENG.090322.transcript.md"

    def fake_run(cmd, **kwargs):
        if "volumedetect" in cmd:
            return MagicMock(stderr="max_volume: -18.0 dB\n")
        # mlx_whisper's mis-stemmed output name -- NOT MITPE.FW.SISH.ENG.090322.srt
        (tmp_path / "MITPE.FW.SISH.ENG.srt").write_text(
            _srt_from_sentences(REALISTIC_TRANSCRIPT))
        return MagicMock(returncode=0, stderr="", stdout="")

    with patch.object(media.subprocess, "run", side_effect=fake_run):
        result = media.transcribe(str(mp4), out)

    assert result["status"] == "ok"
    assert out.exists()
    assert "Innovation" in out.read_text()


def test_transcribe_reuses_an_existing_srt_without_invoking_whisper_again(tmp_path):
    """A raw SRT left behind by an earlier run -- even under mlx_whisper's
    mis-stemmed name -- is reused rather than re-transcribed. A re-run must
    not re-pay an hour of compute for a file already done.
    """
    mp4 = tmp_path / "MITPE.FW.SISH.ENG.090322.mp4"
    out = tmp_path / "MITPE.FW.SISH.ENG.090322.transcript.md"
    (tmp_path / "MITPE.FW.SISH.ENG.srt").write_text(
        _srt_from_sentences(REALISTIC_TRANSCRIPT))

    def fake_run(cmd, **kwargs):
        assert "volumedetect" in cmd, "whisper must not run when an SRT can be reused"
        return MagicMock(stderr="max_volume: -18.0 dB\n")

    with patch.object(media.subprocess, "run", side_effect=fake_run) as run:
        result = media.transcribe(str(mp4), out)

    assert result["status"] == "ok"
    assert run.call_count == 1  # only the silence probe
    assert out.exists()


def test_find_existing_srt_does_not_match_an_unrelated_short_stem(tmp_path):
    (tmp_path / "MIT.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nhi\n")
    assert media.find_existing_srt(tmp_path, "MIT_INN_M1_V1") is None


def test_transcribe_clears_a_stale_marker_left_by_a_previous_run_with_a_different_verdict(tmp_path):
    """A rerun that now succeeds must not leave a contradictory "no speech
    detected" marker from a previous run's different (wrong) verdict sitting
    next to the fresh transcript.
    """
    mp4 = tmp_path / "webinar.mp4"
    out = tmp_path / "webinar.transcript.md"
    stale_marker = tmp_path / "webinar.no_speech.md"
    stale_marker.write_text("No speech detected in this video's audio track: silent audio track.\n")

    def fake_run(cmd, **kwargs):
        if "volumedetect" in cmd:
            return MagicMock(stderr="max_volume: -0.5 dB\n")
        (tmp_path / "webinar.srt").write_text(_srt_from_sentences(REALISTIC_TRANSCRIPT))
        return MagicMock(returncode=0, stderr="", stdout="")

    with patch.object(media.subprocess, "run", side_effect=fake_run):
        result = media.transcribe(str(mp4), out)

    assert result["status"] == "ok"
    assert out.exists()
    assert not stale_marker.exists()


def test_transcribe_clears_a_stale_transcript_left_by_a_previous_run_with_a_different_verdict(tmp_path):
    """The inverse: a rerun that now fails must not leave a stale "ok"
    transcript.md (from a previous, less careful run) looking legitimate
    next to the fresh failure marker.
    """
    mp4 = tmp_path / "webinar.mp4"
    out = tmp_path / "webinar.transcript.md"
    out.write_text("This looks like a legitimate transcript but isn't anymore.\n")

    def fake_run(cmd, **kwargs):
        return MagicMock(stderr="max_volume: -91.0 dB\n")  # silent

    with patch.object(media.subprocess, "run", side_effect=fake_run):
        result = media.transcribe(str(mp4), out)

    assert result["status"] == "no_speech"
    assert not out.exists()


# --- Third degeneracy rule: type-token ratio (phrase-loop hallucination) ---


def test_is_degenerate_transcript_flags_a_phrase_loop_via_type_token_ratio():
    """A repeated PHRASE (not a single word) stays inside the top-word-share
    and min-unique-words thresholds while the type-token ratio collapses --
    the shape of the real MITPE-Onboarding failure. Rules 1 and 2 alone
    would miss this; rule 3 must catch it.
    """
    text = media.srt_to_markdown(_srt_phrase_loop(repeats=400, start_seconds=0))
    words = media.WORD_RE.findall(text.lower())
    unique = len(set(words))
    # Sanity-check the fixture actually exercises rule 3 specifically, not
    # rules 1/2 by coincidence.
    assert unique >= media.DEGENERATE_MIN_UNIQUE_WORDS
    assert len(words) > media.DEGENERATE_TYPE_TOKEN_RATIO_MIN_WORDS
    assert media.is_degenerate_transcript(text)


# --- Splitting "no speech" from "speech Whisper failed to transcribe" ------


def test_healthy_prefix_seconds_is_zero_when_degenerate_from_the_start():
    srt = _srt_single_phrase_loop("We'll be right back.", repeats=40,
                                  start_seconds=0, cue_seconds=3)
    assert media.healthy_prefix_seconds(srt) == 0.0


def test_healthy_prefix_seconds_is_positive_after_a_genuine_prefix():
    prefix = _srt_from_sentences(REALISTIC_TRANSCRIPT, start_seconds=1)  # real speech, ~1-6s
    loop = _srt_single_phrase_loop("I'm a graduate student at MIT.", repeats=40,
                                   start_seconds=20, cue_seconds=3)  # loop from 20s on
    result = media.healthy_prefix_seconds(prefix + loop)
    assert 0 < result < 20 + 40 * 3


# --- Recovery attempt for real speech that Whisper failed to transcribe ----


def test_transcribe_recovers_a_repetition_loop_with_condition_on_previous_text(tmp_path):
    """A file with real speech followed by a repetition loop gets one retry
    with --condition-on-previous-text False; a clean result from that retry
    is recorded as ok, and the failed first attempt is preserved rather
    than silently overwritten.
    """
    mp4 = tmp_path / "webinar.mp4"
    out = tmp_path / "webinar.transcript.md"
    prefix = _srt_from_sentences(REALISTIC_TRANSCRIPT, start_seconds=1)
    degenerate_srt = prefix + _srt_single_phrase_loop(
        "OK.", repeats=200, start_seconds=20, cue_seconds=1)
    recovered_srt = _srt_from_sentences(REALISTIC_TRANSCRIPT, start_seconds=1)
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if "volumedetect" in cmd:
            return MagicMock(stderr="max_volume: -18.0 dB\n")
        if "--condition-on-previous-text" in cmd:
            (tmp_path / "webinar.srt").write_text(recovered_srt)
        else:
            (tmp_path / "webinar.srt").write_text(degenerate_srt)
        return MagicMock(returncode=0, stderr="", stdout="")

    with patch.object(media.subprocess, "run", side_effect=fake_run):
        result = media.transcribe(str(mp4), out)

    assert result["status"] == "ok"
    assert out.exists()
    assert "Innovation" in out.read_text()
    assert len(calls) == 3  # silence probe, first attempt, recovery attempt
    # The failed first attempt is preserved, not silently overwritten.
    assert (tmp_path / "webinar.failed-attempt.srt").exists()
    assert "OK." in (tmp_path / "webinar.failed-attempt.srt").read_text()


def test_transcribe_records_transcription_failed_when_recovery_does_not_help(tmp_path):
    """Real speech present, transcription degenerated, and the recovery
    retry ALSO degenerates -- status is "transcription_failed" (not
    "no_speech": there was real speech), no third attempt is made, and no
    degenerate .transcript.md is ever written.
    """
    mp4 = tmp_path / "webinar.mp4"
    out = tmp_path / "webinar.transcript.md"
    prefix = _srt_from_sentences(REALISTIC_TRANSCRIPT, start_seconds=1)
    degenerate_srt = prefix + _srt_single_phrase_loop(
        "OK.", repeats=200, start_seconds=20, cue_seconds=1)
    still_degenerate_srt = _srt_single_phrase_loop(
        "Right.", repeats=40, start_seconds=0, cue_seconds=1)
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if "volumedetect" in cmd:
            return MagicMock(stderr="max_volume: -18.0 dB\n")
        if "--condition-on-previous-text" in cmd:
            (tmp_path / "webinar.srt").write_text(still_degenerate_srt)
        else:
            (tmp_path / "webinar.srt").write_text(degenerate_srt)
        return MagicMock(returncode=0, stderr="", stdout="")

    with patch.object(media.subprocess, "run", side_effect=fake_run):
        result = media.transcribe(str(mp4), out)

    assert result["status"] == "transcription_failed"
    assert "valid speech" in result["reason"]
    assert "did not recover" in result["reason"]
    assert not out.exists()
    assert len(calls) == 3  # no third attempt
    marker = tmp_path / "webinar.transcription_failed.md"
    assert marker.exists()
    assert "Transcription failed" in marker.read_text()
    # The original failed attempt is preserved alongside the still-bad retry.
    assert (tmp_path / "webinar.failed-attempt.srt").exists()


# --- Review fix 1: a failed re-attempt must not destroy a correct prior
# --- artifact (mirror of the stale-clearing tests above) -------------------


def test_transcribe_leaves_a_valid_prior_marker_untouched_when_a_reattempt_fails(tmp_path):
    """A re-run that then FAILS must not destroy a correct artifact a
    previous run left behind. This is the mirror bug of the stale-clearing
    tests above: those clear a *superseded* artifact once a new verdict is
    confirmed; this reproduces clearing happening unconditionally before
    any new work is attempted, which destroys a *correct* artifact when
    the new attempt goes on to fail. Reproduces the reviewer's repro:
    seed a valid no_speech.md marker, mock the volume probe to fail open
    (no parseable max_volume -> None -> not silent), then mock whisper
    raising SubprocessError.
    """
    mp4 = tmp_path / "webinar.mp4"
    out = tmp_path / "webinar.transcript.md"
    marker = tmp_path / "webinar.no_speech.md"
    marker.write_text(
        "No speech detected in this video's audio track: silent audio track.\n"
        "No transcript was produced. See media.json for details.\n")

    def fake_run(cmd, **kwargs):
        if "volumedetect" in cmd:
            return MagicMock(stderr="")  # unparseable -- probe fails open (None)
        raise media.subprocess.SubprocessError("whisper crashed")

    with patch.object(media.subprocess, "run", side_effect=fake_run):
        result = media.transcribe(str(mp4), out)

    assert result["status"] == "gap"
    assert not out.exists()
    # The pre-existing marker must survive a failed attempt untouched.
    assert marker.exists()
    assert "silent audio track" in marker.read_text()
    assert [p.name for p in tmp_path.glob("webinar.*")] == [marker.name]


# --- Review fix 2: compression ratio as the primary degeneracy rule -------

# 40 distinct, unrelated words -- the reviewer's construction for a loop
# that evades all three of the older rules (unique-word count, top-word
# share, type-token ratio) regardless of how many times it cycles.
CYCLE_WORDS = [
    "orbit", "velvet", "granite", "whisper", "cactus", "harbor", "lantern",
    "meadow", "quartz", "ribbon", "silver", "timber", "umbrella", "violet",
    "walnut", "yonder", "zephyr", "amber", "brook", "cedar", "delta",
    "ember", "frost", "glacier", "honey", "ivory", "jasper", "kelp",
    "lunar", "marble", "nectar", "opal", "pebble", "quiver", "raven",
    "sable", "thistle", "urchin", "vapor", "willow",
]
assert len(CYCLE_WORDS) == 40


def _srt_word_cycle(vocab, cycles, cue_seconds=1, start_seconds=0):
    """One distinct word per cue, cycling through `vocab` in the same fixed
    order `cycles` times -- a longer-period loop than `_srt_phrase_loop`'s
    6 phrases, used to stress the compression-ratio rule specifically.
    """
    cues = []
    i = 0
    for _ in range(cycles):
        for word in vocab:
            t0 = start_seconds + i * cue_seconds
            t1 = t0 + cue_seconds
            cues.append(f"{i + 1}\n{_ts(t0)} --> {_ts(t1)}\n{word}")
            i += 1
    return "\n\n".join(cues) + "\n"


def test_is_degenerate_transcript_flags_a_sustained_word_cycle_via_compression_ratio():
    """40 distinct words cycled 25 times (1000 words) -- the reviewer's
    evading shape, sustained for a realistic number of repeats (a real
    Whisper repetition loop, once triggered, continues for the rest of the
    audio rather than stopping after a handful of repeats). Rules 1-3
    alone would miss this, exactly as the reviewer demonstrated; the
    compression-ratio rule must catch it.
    """
    text = media.srt_to_markdown(_srt_word_cycle(CYCLE_WORDS, cycles=25))
    words = media.WORD_RE.findall(text.lower())
    counts = Counter(words)
    unique = len(counts)
    top_share = counts.most_common(1)[0][1] / len(words)
    # Sanity-check the fixture evades rules 1-3, the same shape the
    # reviewer's minimal case did -- rule 4 (compression) must be what
    # catches it, not a coincidence with the older rules.
    assert unique >= media.DEGENERATE_MIN_UNIQUE_WORDS
    assert top_share < media.DEGENERATE_TOP_WORD_SHARE
    assert len(words) > media.DEGENERATE_TYPE_TOKEN_RATIO_MIN_WORDS
    assert (unique / len(words)) >= media.DEGENERATE_MIN_TYPE_TOKEN_RATIO
    assert media.is_degenerate_transcript(text)


def test_is_degenerate_transcript_does_not_flag_a_minimal_six_cycle_probe():
    """Documents a known, deliberately accepted boundary: the reviewer's
    literal minimal construction -- 40 distinct words cycled exactly 6
    times, 240 words, just past the 200-word compression floor -- is NOT
    flagged.

    This is calibrated against this archive's real data, not an oversight:
    at 6 cycles this probe compresses to ~10-12% of its raw size, which is
    indistinguishable from two of the archive's real, legitimate
    technical-explainer transcripts (Wii Remote and Henry Ford measure
    10.1-10.7%; see DEGENERATE_COMPRESSION_RATIO_MAX's docstring in
    media.py for the full calibration). Catching this exact minimal probe
    would require a threshold that misclassifies those two real,
    already-shipped transcripts -- so it isn't caught. Once a loop sustains
    for more repeats (any vocabulary size), it drops well clear of the
    healthy range -- see the test above.
    """
    text = media.srt_to_markdown(_srt_word_cycle(CYCLE_WORDS, cycles=6))
    words = media.WORD_RE.findall(text.lower())
    assert len(words) == 240
    assert len(set(words)) == 40  # still evades rules 1-3, same as the reviewer found
    assert not media.is_degenerate_transcript(text)


def test_is_degenerate_transcript_still_flags_the_older_loop_shapes():
    """The compression rule is additive -- the two loop shapes this corpus
    actually exhibited must still be caught."""
    single_word = media.srt_to_markdown(
        "\n\n".join(f"{i}\n00:00:{i:02d},000 --> 00:00:{i + 1:02d},000\nyou"
                    for i in range(1, 60)))
    assert media.is_degenerate_transcript(single_word)

    phrase_loop = media.srt_to_markdown(_srt_phrase_loop(repeats=400, start_seconds=0))
    assert media.is_degenerate_transcript(phrase_loop)


def test_is_degenerate_transcript_still_accepts_realistic_prose():
    """The compression rule must not false-positive on real, non-repetitive
    prose -- re-asserts the existing acceptance test still holds with the
    new rule in place."""
    text = media.srt_to_markdown(_srt_from_sentences(REALISTIC_TRANSCRIPT))
    assert not media.is_degenerate_transcript(text)


# --- Finding 3 (final review): "record a gap and continue" in media.py -----


def test_contact_sheet_returns_none_on_a_subprocess_error_instead_of_raising(tmp_path):
    """Guarded exactly like probe_max_volume: a missing ffmpeg binary or a
    TimeoutExpired on a huge webinar must fail open, not raise out of
    derive_all's per-video loop."""
    mp4 = tmp_path / "webinar.mp4"
    out = tmp_path / "webinar.contactsheet.jpg"

    with patch.object(media.subprocess, "run", side_effect=FileNotFoundError("no ffmpeg")):
        result = media.contact_sheet(str(mp4), out, duration=600)

    assert result is None


def test_contact_sheet_returns_none_on_ffmpeg_timeout(tmp_path):
    mp4 = tmp_path / "webinar.mp4"
    out = tmp_path / "webinar.contactsheet.jpg"
    timeout = media.subprocess.TimeoutExpired(cmd=["ffmpeg"], timeout=1800)

    with patch.object(media.subprocess, "run", side_effect=timeout):
        result = media.contact_sheet(str(mp4), out, duration=600)

    assert result is None


def test_derive_all_records_a_gap_for_one_bad_video_and_keeps_processing_the_rest(tmp_path):
    """derive_all used to have no per-video try at all -- the one
    stage-level loop on this branch with no gap-record path. A video whose
    processing raises (here: an unreadable sibling .srt) must become a
    `status: "gap"` record, and the loop must still process every other
    video rather than aborting the whole stage.
    """
    good = tmp_path / "good.mp4"
    good.write_text("x")
    good_srt = tmp_path / "good.srt"
    good_srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nHello\n")

    bad = tmp_path / "bad.mp4"
    bad.write_text("x")
    bad_srt = tmp_path / "bad.srt"
    bad_srt.write_text("placeholder")

    local = [
        {"path": str(good), "ext": ".mp4", "duration": 1.0},
        {"path": str(bad), "ext": ".mp4", "duration": 1.0},
        {"path": str(good_srt), "ext": ".srt"},
        {"path": str(bad_srt), "ext": ".srt"},
    ]

    real_read_text = Path.read_text

    def flaky_read_text(self, *args, **kwargs):
        if self == bad_srt:
            raise OSError("simulated Dropbox online-only placeholder")
        return real_read_text(self, *args, **kwargs)

    with patch.object(Path, "read_text", flaky_read_text):
        records = media.derive_all(local, tmp_path / "_build")

    by_path = {r["path"]: r for r in records}
    assert len(records) == 2
    assert by_path[str(good)]["status"] == "ok"
    assert (tmp_path / "_build" / "transcripts" / "good.transcript.md").exists()
    assert by_path[str(bad)]["status"] == "gap"
    assert "simulated Dropbox" in by_path[str(bad)]["error"]
    assert by_path[str(bad)]["contactsheet"] is None
