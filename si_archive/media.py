"""Stage 6 -- one transcript per video, contact sheets for the long ones.

27 of the 47 archived MP4s ship with an SRT. The other 20 are transcribed with
mlx-whisper (large-v3, Metal-accelerated on Apple Silicon). Existing SRTs are
converted to the same markdown shape so the site presents one artifact type
regardless of where the text came from.

Whisper has no failure mode for "nothing to transcribe" -- given silence or
music it emits a fluent, plausible, entirely fabricated continuation, and on
long audio it can also drop into a repetition-loop bug partway through a
real recording. Two guards catch this before a hallucination reaches the
archive as a transcript: a pre-transcription silence probe (`probe_max_volume`
/ `is_silent`), and a post-transcription degeneracy screen
(`is_degenerate_transcript`) for everything else -- music-only audio, and
long-audio repetition loops.

A degenerate transcript still needs to say something different depending on
*why* it's degenerate:

  - `status: "no_speech"` -- the audio genuinely has nothing to transcribe
    (silence, or music with no speech in it).
  - `status: "transcription_failed"` -- real speech is present
    (`healthy_prefix_seconds` finds a genuine, non-degenerate prefix) but
    Whisper's transcription of it broke down partway through. One recovery
    attempt is made with `--condition-on-previous-text False`, the standard
    mitigation for this failure mode; if that also degenerates, the failure
    is recorded rather than retried further.

Either non-`"ok"` status gets an honest marker file in place of a
`.transcript.md` -- never silence, never a fabricated transcript.
"""
import re
import subprocess
import zlib
from collections import Counter
from pathlib import Path

from si_archive import constants

TIMECODE_RE = re.compile(r"^\d{2}:\d{2}:\d{2}[,.]\d{3}\s*-->")

WHISPER_BIN = "/Users/jmill/coding/github/CanvasSync/.venv/bin/mlx_whisper"
WHISPER_MODEL = "mlx-community/whisper-large-v3-mlx"

# ffmpeg's volumedetect filter reports this to stderr, e.g. "max_volume: -91.0 dB".
VOLUME_RE = re.compile(r"max_volume:\s*(-?\d+(?:\.\d+)?)\s*dB")
# Silent screen recordings measure ~-91 dB; real speech measures -23 to -0.5 dB.
# The margin is huge, so this threshold has a lot of room either side of it.
SILENCE_MAX_VOLUME_DB = -50.0

# Real transcripts here have a top-word share of 4.0-5.5% and 124-1524 unique
# words. Whisper hallucination on non-speech audio loops a handful of words
# ("you you you...", "We'll be right back.") -- both thresholds have wide
# margin against the real data.
DEGENERATE_TOP_WORD_SHARE = 0.30
DEGENERATE_MIN_UNIQUE_WORDS = 25
# A repetition loop can also cycle through a short *phrase* rather than a
# single word ("I'm a graduate student at MIT." over and over) -- that keeps
# unique-word count and top-word share inside the two thresholds above while
# the type-token ratio collapses (one real webinar measured 110 unique words
# across 48,933 total: 0.22%, against 5.7-36% on healthy transcripts). Only
# meaningful past a couple hundred words, where the ratio stops being noisy.
DEGENERATE_MIN_TYPE_TOKEN_RATIO = 0.02
DEGENERATE_TYPE_TOKEN_RATIO_MIN_WORDS = 200

# The three rules above only cover the two loop shapes this corpus actually
# exhibited (a single repeated token, and a short repeated phrase) -- a
# loop cycling through dozens of distinct invented words takes many more
# words before its type-token ratio collapses below the 2% floor above,
# and would ship as "ok". Compression ratio catches repetition at ANY
# period, because that's what compression measures, so it's the primary
# guard; the three rules above stay on as secondary coverage.
#
# Calibrated against this archive's real data, not guessed: the two known
# real hallucination loops -- MITPE-Onboarding-ENG-020322 and
# MITPE.FW.SISH.ENG's first whisper attempts, both "I'm a graduate student
# at MIT."-style phrase loops before the condition_on_previous_text=False
# recovery fixed them -- compress to 0.5% and 0.9% of their raw size. The
# least compressible of the 38 shipped healthy transcripts (a dense,
# narrow-topic explainer video) compresses to 8.5%. That's a ~10x gap, and
# 6% sits with real margin on both sides of it (2.5 points below the
# healthy floor, 5.1 points above the worst real failure).
#
# What this does NOT catch: an artificially minimal loop of only a
# handful of repeats. Compression needs enough total repeats to show a
# real gain -- 40 distinct words cycled just 6 times (240 words, the
# minimum to clear DEGENERATE_COMPRESSION_MIN_WORDS below) compresses to
# only ~10-12%, indistinguishable from two of this archive's real, legit
# technical/narrow-topic videos (10.1% and 10.7%) -- so it is not flagged,
# by design: catching it would require a threshold that misclassifies
# those two real transcripts. Once a loop sustains for ~15+ repeats
# (regardless of vocabulary size), its ratio drops under 5.5% and clears
# the healthy floor with real margin -- see test_media.py.
DEGENERATE_COMPRESSION_RATIO_MAX = 0.06
DEGENERATE_COMPRESSION_MIN_WORDS = 200

# For splitting "no speech" from "speech Whisper failed to transcribe":
# chunk the transcript into windows this wide and screen each on its own.
HEALTHY_PREFIX_CHUNK_SECONDS = 15.0

WORD_RE = re.compile(r"[a-z']+")
CUE_TIME_RE = re.compile(r"^(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->")


def srt_to_markdown(srt_text):
    """Strip cue numbers and timecodes; join the text into flowing paragraphs."""
    lines = []
    for raw in srt_text.splitlines():
        line = raw.strip()
        if not line or line.isdigit() or TIMECODE_RE.match(line):
            continue
        # Some exports leave a stray WEBVTT header on the first line.
        if line.upper().startswith("WEBVTT"):
            continue
        lines.append(line)
    return " ".join(lines).strip() + "\n"


def needs_transcription(record, srt_index):
    if record.get("ext") not in {".mp4", ".m4v", ".mov"}:
        return False
    return str(Path(record["path"]).with_suffix(".srt")) not in srt_index


def probe_max_volume(mp4_path):
    """ffmpeg volumedetect's max_volume in dB, or None if it can't be read.

    A probe failure fails open (None, not silent) rather than skipping a
    video that might have real speech -- the degeneracy screen after
    transcription is the backstop for anything this misses.
    """
    try:
        result = subprocess.run(
            ["ffmpeg", "-i", str(mp4_path), "-af", "volumedetect", "-f", "null", "-"],
            capture_output=True, text=True, timeout=300)
    except (subprocess.SubprocessError, OSError):
        return None
    match = VOLUME_RE.search(result.stderr or "")
    return float(match.group(1)) if match else None


def is_silent(max_volume_db):
    return max_volume_db is not None and max_volume_db <= SILENCE_MAX_VOLUME_DB


def is_degenerate_transcript(text):
    """Flag Whisper hallucination: a repetition loop of any period (single
    word, short phrase, or a longer cycle of distinct words) rather than
    real prose.
    """
    words = WORD_RE.findall(text.lower())
    if not words:
        return True
    total = len(words)
    if total > DEGENERATE_COMPRESSION_MIN_WORDS:
        raw = text.encode("utf-8")
        if len(zlib.compress(raw)) / len(raw) < DEGENERATE_COMPRESSION_RATIO_MAX:
            return True
    counts = Counter(words)
    unique = len(counts)
    top_share = counts.most_common(1)[0][1] / total
    if top_share > DEGENERATE_TOP_WORD_SHARE or unique < DEGENERATE_MIN_UNIQUE_WORDS:
        return True
    if (total > DEGENERATE_TYPE_TOKEN_RATIO_MIN_WORDS
            and (unique / total) < DEGENERATE_MIN_TYPE_TOKEN_RATIO):
        return True
    return False


def _parse_srt_cues(srt_text):
    """(start_seconds, text) per cue, in chronological order. Only used by
    `healthy_prefix_seconds` below -- `srt_to_markdown` has its own simpler
    pass since it doesn't need timing.
    """
    cues = []
    start = None
    buf = []
    for raw in srt_text.splitlines():
        line = raw.strip()
        match = CUE_TIME_RE.match(line)
        if match:
            if start is not None:
                cues.append((start, " ".join(buf)))
            hours, minutes, seconds, millis = (int(g) for g in match.groups())
            start = hours * 3600 + minutes * 60 + seconds + millis / 1000
            buf = []
        elif line and not line.isdigit():
            buf.append(line)
    if start is not None:
        cues.append((start, " ".join(buf)))
    return cues


def healthy_prefix_seconds(srt_text, chunk_seconds=HEALTHY_PREFIX_CHUNK_SECONDS):
    """How much of the transcript, from the start, precedes a sustained
    degenerate loop -- the signal that separates a real recording whose
    transcription broke down partway through from audio that never had any
    speech to transcribe in the first place.

    Chunks the transcript into fixed time windows and scans backward from
    the end for the last window that is not degenerate on its own; every
    window after it was already found degenerate on the way there. Returns
    0.0 if even the first chunk looks degenerate -- i.e. the transcript
    never has a moment of real content (music-only audio, for example).
    """
    cues = _parse_srt_cues(srt_text)
    if not cues:
        return 0.0
    chunks = []
    current = []
    boundary = chunk_seconds
    for start, text in cues:
        while start >= boundary:
            chunks.append(current)
            current = []
            boundary += chunk_seconds
        current.append(text)
    if current:
        chunks.append(current)
    for index in range(len(chunks) - 1, -1, -1):
        if not is_degenerate_transcript(" ".join(chunks[index])):
            return (index + 1) * chunk_seconds
    return 0.0


def write_status_marker(out_dir, stem, status, reason):
    """A short, honest marker in place of a transcript for anything that
    isn't a clean "ok" -- never a degenerate `.transcript.md`, and never
    silence or a fabricated transcript passed off as nothing either.
    """
    headline = {
        "no_speech": "No speech detected in this video's audio track",
        "transcription_failed": "Transcription failed for this video",
    }[status]
    marker = Path(out_dir) / f"{stem}.{status}.md"
    marker.write_text(
        f"{headline}: {reason}.\n"
        "No transcript was produced. See media.json for details.\n")
    return marker


def find_existing_srt(out_dir, stem):
    """Reuse a whisper-produced SRT already on disk from an earlier run, so a
    re-run of this stage doesn't re-pay an hour of transcription for a file
    already done.

    mlx_whisper's own filename guess can strip more of the source name than
    `Path.stem` does -- it treated ".090322" in "MITPE.FW.SISH.ENG.090322.mp4"
    as an extension too, and wrote "MITPE.FW.SISH.ENG.srt". Match by prefix at
    a dot boundary, not just equality, so that mismatch is still found; but
    don't match "MIT" against "MIT_INN_M1_V1" -- the observed stripping only
    ever eats whole dot-separated segments, so only a dot counts as a
    boundary, not every word separator.
    """
    exact = Path(out_dir) / f"{stem}.srt"
    if exact.exists():
        return exact
    boundary = {"."}
    best = None
    for candidate in Path(out_dir).glob("*.srt"):
        cand_stem = candidate.stem
        if not cand_stem or not stem.startswith(cand_stem):
            continue
        if stem[len(cand_stem):len(cand_stem) + 1] not in boundary:
            continue
        if best is None or len(cand_stem) > len(best.stem):
            best = candidate
    return best


def find_produced_srt(out_dir, stem, before):
    """Whatever `*.srt` newly appeared in `out_dir` during the mlx_whisper
    call, found by directory diff rather than guessed from the stem -- see
    `find_existing_srt` for why guessing the name is unsafe. Falls back to
    the stem-based guess only if the diff finds nothing.
    """
    after = set(Path(out_dir).glob("*.srt"))
    new_files = after - before
    if new_files:
        return max(new_files, key=lambda p: p.stat().st_mtime)
    guess = Path(out_dir) / f"{stem}.srt"
    return guess if guess.exists() else None


def _attempt_recovery(mp4_path, out_dir, stem, produced):
    """One retry with `--condition-on-previous-text False` -- the standard
    mitigation for mlx-whisper's known repetition-loop failure on long
    audio. Never raises; returns the new SRT's Path on a clean subprocess
    run, else None.

    The failed first attempt is preserved under a distinguishing name
    rather than overwritten, so a second failure doesn't erase the
    evidence of the first -- destroy nothing, even a failed transcript.
    """
    preserved = produced.with_name(produced.stem + ".failed-attempt.srt")
    if produced.exists() and not preserved.exists():
        produced.replace(preserved)
    before = set(Path(out_dir).glob("*.srt"))
    try:
        result = subprocess.run(
            [WHISPER_BIN, "--model", WHISPER_MODEL,
             "--output-format", "srt", "--output-dir", str(out_dir),
             "--condition-on-previous-text", "False", str(mp4_path)],
            capture_output=True, text=True, timeout=7200)
    except subprocess.SubprocessError:
        return None
    if result.returncode != 0:
        return None
    return find_produced_srt(out_dir, stem, before)


def _clear_superseded_artifacts(out_dir, stem, out_path, status):
    """Remove whatever a previous run for this stem left behind, other than
    the artifact `status` is about to become -- a re-run can reach a
    different verdict than a previous run did (that's the point of the
    guards in `transcribe`), and the archive must never show two
    contradictory outcomes side by side.

    Called only once the new result is confirmed, immediately before it's
    written -- never at the top of `transcribe`, before any new work has
    even been attempted. That ordering matters: if it ran unconditionally
    up front and the new attempt then failed (probe fails open, whisper
    errors or times out, no srt produced), a correct prior artifact would
    be destroyed and nothing would replace it. A failed attempt must never
    reduce what's on disk -- only a confirmed new result may remove what
    it's superseding.
    """
    if status != "ok" and out_path.exists():
        out_path.unlink()
    for other_status in ("no_speech", "transcription_failed"):
        if other_status == status:
            continue
        stale = out_dir / f"{stem}.{other_status}.md"
        if stale.exists():
            stale.unlink()


def transcribe(mp4_path, out_path):
    """mlx-whisper large-v3. Returns a record; never raises.

    Guards against Whisper hallucination: a silence probe before
    transcribing (skips Whisper entirely for digitally silent audio), and a
    degeneracy screen on the resulting text after. A degenerate result with
    no genuine prefix (`healthy_prefix_seconds` == 0) means the audio never
    had speech to transcribe -- `status: "no_speech"`. A degenerate result
    with a genuine prefix means real speech broke Whisper partway through;
    one recovery attempt is made before giving up with
    `status: "transcription_failed"`.
    """
    out_path = Path(out_path)
    out_dir = out_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(mp4_path).stem

    try:
        silent = is_silent(probe_max_volume(mp4_path))
    except Exception:
        silent = False
    if silent:
        _clear_superseded_artifacts(out_dir, stem, out_path, "no_speech")
        marker = write_status_marker(out_dir, stem, "no_speech", "silent audio track")
        return {"path": str(mp4_path), "status": "no_speech",
                "reason": "silent audio track", "marker": str(marker)}

    produced = find_existing_srt(out_dir, stem)
    if produced is None:
        before = set(out_dir.glob("*.srt"))
        try:
            result = subprocess.run(
                [WHISPER_BIN, "--model", WHISPER_MODEL,
                 "--output-format", "srt", "--output-dir", str(out_dir),
                 str(mp4_path)],
                capture_output=True, text=True, timeout=7200)
        except subprocess.SubprocessError as exc:
            return {"path": str(mp4_path), "status": "gap", "error": str(exc)}
        if result.returncode != 0:
            return {"path": str(mp4_path), "status": "gap",
                    "error": (result.stderr or "").strip()[-500:]}
        produced = find_produced_srt(out_dir, stem, before)
        if produced is None:
            return {"path": str(mp4_path), "status": "gap",
                    "error": "mlx_whisper produced no srt"}

    try:
        raw = produced.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return {"path": str(mp4_path), "status": "gap", "error": str(exc)}
    text = srt_to_markdown(raw)

    try:
        degenerate = is_degenerate_transcript(text)
    except Exception:
        degenerate = False
    if not degenerate:
        _clear_superseded_artifacts(out_dir, stem, out_path, "ok")
        out_path.write_text(text)
        return {"path": str(mp4_path), "status": "ok", "transcript": str(out_path),
                "source": "whisper"}

    try:
        prefix = healthy_prefix_seconds(raw)
    except Exception:
        prefix = 0.0

    if prefix <= 0:
        reason = "no speech detected in audio"
        _clear_superseded_artifacts(out_dir, stem, out_path, "no_speech")
        marker = write_status_marker(out_dir, stem, "no_speech", reason)
        return {"path": str(mp4_path), "status": "no_speech",
                "reason": reason, "marker": str(marker)}

    # Real speech is present but the transcription degenerated into a
    # repetition loop -- try the standard mitigation once before giving up.
    reason = f"repetition loop after ~{int(prefix)}s of valid speech"
    try:
        recovered = _attempt_recovery(mp4_path, out_dir, stem, produced)
    except Exception:
        recovered = None
    if recovered is not None:
        try:
            recovered_text = srt_to_markdown(
                recovered.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            recovered_text = None
        if recovered_text is not None:
            try:
                still_degenerate = is_degenerate_transcript(recovered_text)
            except Exception:
                still_degenerate = True
            if not still_degenerate:
                _clear_superseded_artifacts(out_dir, stem, out_path, "ok")
                out_path.write_text(recovered_text)
                return {"path": str(mp4_path), "status": "ok",
                        "transcript": str(out_path), "source": "whisper"}

    reason += "; retry with condition_on_previous_text=False did not recover"
    _clear_superseded_artifacts(out_dir, stem, out_path, "transcription_failed")
    marker = write_status_marker(out_dir, stem, "transcription_failed", reason)
    return {"path": str(mp4_path), "status": "transcription_failed",
            "reason": reason, "marker": str(marker)}


def contact_sheet(mp4_path, out_path, duration):
    """A 4x4 tile sheet for videos worth skimming. None if too short.

    Guarded exactly like `probe_max_volume`: a missing ffmpeg or a
    `TimeoutExpired` on a multi-gigabyte webinar must fail open (no contact
    sheet) rather than raise straight out of the per-video loop in
    `derive_all`.
    """
    if not duration or duration < constants.CONTACTSHEET_MIN_SECONDS:
        return None
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    interval = max(duration / 16.0, 1.0)
    try:
        result = subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-i", str(mp4_path),
             "-vf", f"fps=1/{interval:.3f},scale=320:-1,tile=4x4",
             "-frames:v", "1", str(out_path)],
            capture_output=True, text=True, timeout=1800)
    except (subprocess.SubprocessError, OSError):
        return None
    return out_path if result.returncode == 0 and out_path.exists() else None


def derive_all(local, out_dir):
    """One record per video, appended even when that video's own processing
    blows up. Every other stage-level loop on this branch already records a
    gap and continues (Ruling: "record a gap and continue"); this was the
    one exception -- a bad Dropbox online-only placeholder, a permission
    error, or any other surprise while reading/writing a transcript used to
    raise straight out of the loop, aborting the multi-hour stage and, since
    the caller only writes media.json after this function returns, leaving
    no manifest at all for videos already processed. The whole per-video
    body is wrapped so one bad asset becomes a `status: "gap"` record
    instead.
    """
    out_dir = Path(out_dir)
    srt_index = {r["path"] for r in local if r.get("ext") == ".srt"}
    records = []
    videos = [r for r in local if r.get("ext") in {".mp4", ".m4v", ".mov"}]
    for index, record in enumerate(videos, start=1):
        stem = Path(record["path"]).stem
        transcript = out_dir / "transcripts" / f"{stem}.transcript.md"
        try:
            if needs_transcription(record, srt_index):
                print(f"    [{index}/{len(videos)}] whisper: {stem}")
                result = transcribe(record["path"], transcript)
            else:
                srt = Path(record["path"]).with_suffix(".srt")
                transcript.parent.mkdir(parents=True, exist_ok=True)
                transcript.write_text(
                    srt_to_markdown(srt.read_text(encoding="utf-8", errors="replace")))
                result = {"path": record["path"], "status": "ok",
                          "transcript": str(transcript), "source": "srt"}
            sheet = contact_sheet(record["path"],
                                  out_dir / "contactsheets" / f"{stem}.jpg",
                                  record.get("duration"))
            result["contactsheet"] = str(sheet) if sheet else None
        except Exception as exc:  # one bad asset must not kill the whole stage
            result = {"path": record["path"], "status": "gap",
                      "error": str(exc), "contactsheet": None}
        records.append(result)
    return records
