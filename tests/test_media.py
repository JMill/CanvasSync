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
