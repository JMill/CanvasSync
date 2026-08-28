from si_archive import media

SRT = """1
00:00:01,000 --> 00:00:04,000
Innovation is not a bolt of lightning.

2
00:00:04,500 --> 00:00:07,000
It is a method you can practise.
"""


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
