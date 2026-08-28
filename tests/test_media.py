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


def _srt_from_sentences(text):
    """Build a minimal, well-formed SRT out of a period-separated paragraph."""
    sentences = [s.strip() for s in text.split(". ") if s.strip()]
    cues = []
    for i, sentence in enumerate(sentences, start=1):
        cues.append(f"{i}\n00:00:{i:02d},000 --> 00:00:{i + 1:02d},000\n{sentence}")
    return "\n\n".join(cues) + "\n"


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

    def fake_run(cmd, **kwargs):
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
