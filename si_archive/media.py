"""Stage 6 -- one transcript per video, contact sheets for the long ones.

27 of the 47 archived MP4s ship with an SRT. The other 20 are transcribed with
mlx-whisper (large-v3, Metal-accelerated on Apple Silicon). Existing SRTs are
converted to the same markdown shape so the site presents one artifact type
regardless of where the text came from.

Whisper has no failure mode for "nothing to transcribe" -- given silence or
music it emits a fluent, plausible, entirely fabricated continuation. Two
guards catch this before a hallucination reaches the archive as a transcript:
a pre-transcription silence probe (`probe_max_volume` / `is_silent`), and a
post-transcription degeneracy screen (`is_degenerate_transcript`) for cases
like music-only audio where the track isn't silent but carries no speech.
Both are recorded as `status: "no_speech"` with an honest marker file in
place of a `.transcript.md` -- never silence, never a fabricated transcript.
"""
import re
import subprocess
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

WORD_RE = re.compile(r"[a-z']+")


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
    """Flag Whisper hallucination on non-speech audio: a handful of words
    looping rather than real prose.
    """
    words = WORD_RE.findall(text.lower())
    if not words:
        return True
    counts = Counter(words)
    top_share = counts.most_common(1)[0][1] / len(words)
    return top_share > DEGENERATE_TOP_WORD_SHARE or len(counts) < DEGENERATE_MIN_UNIQUE_WORDS


def write_no_speech_marker(out_dir, stem, reason):
    """A short, honest marker in place of a transcript -- never a degenerate
    `.transcript.md`, and never silence either.
    """
    marker = Path(out_dir) / f"{stem}.no_speech.md"
    marker.write_text(
        f"No speech detected in this video's audio track: {reason}.\n"
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


def transcribe(mp4_path, out_path):
    """mlx-whisper large-v3. Returns a record; never raises.

    Guards against Whisper hallucination on non-speech audio: a silence probe
    before transcribing (skips Whisper entirely), and a degeneracy screen on
    the resulting text after. Either can turn a transcription attempt into a
    `status: "no_speech"` record instead of `"ok"`.
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
        marker = write_no_speech_marker(out_dir, stem, "silent audio track")
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
        text = srt_to_markdown(produced.read_text(encoding="utf-8", errors="replace"))
    except OSError as exc:
        return {"path": str(mp4_path), "status": "gap", "error": str(exc)}

    try:
        degenerate = is_degenerate_transcript(text)
    except Exception:
        degenerate = False
    if degenerate:
        marker = write_no_speech_marker(out_dir, stem, "no speech detected in audio")
        return {"path": str(mp4_path), "status": "no_speech",
                "reason": "no speech detected in audio", "marker": str(marker)}

    out_path.write_text(text)
    return {"path": str(mp4_path), "status": "ok", "transcript": str(out_path),
            "source": "whisper"}


def contact_sheet(mp4_path, out_path, duration):
    """A 4x4 tile sheet for videos worth skimming. None if too short."""
    if not duration or duration < constants.CONTACTSHEET_MIN_SECONDS:
        return None
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    interval = max(duration / 16.0, 1.0)
    result = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(mp4_path),
         "-vf", f"fps=1/{interval:.3f},scale=320:-1,tile=4x4",
         "-frames:v", "1", str(out_path)],
        capture_output=True, text=True, timeout=1800)
    return out_path if result.returncode == 0 and out_path.exists() else None


def derive_all(local, out_dir):
    out_dir = Path(out_dir)
    srt_index = {r["path"] for r in local if r.get("ext") == ".srt"}
    records = []
    videos = [r for r in local if r.get("ext") in {".mp4", ".m4v", ".mov"}]
    for index, record in enumerate(videos, start=1):
        stem = Path(record["path"]).stem
        transcript = out_dir / "transcripts" / f"{stem}.transcript.md"
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
        records.append(result)
    return records
