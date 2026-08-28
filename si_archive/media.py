"""Stage 6 -- one transcript per video, contact sheets for the long ones.

27 of the 47 archived MP4s ship with an SRT. The other 20 are transcribed with
mlx-whisper (large-v3, Metal-accelerated on Apple Silicon). Existing SRTs are
converted to the same markdown shape so the site presents one artifact type
regardless of where the text came from.
"""
import re
import subprocess
from pathlib import Path

from si_archive import constants

TIMECODE_RE = re.compile(r"^\d{2}:\d{2}:\d{2}[,.]\d{3}\s*-->")


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


def transcribe(mp4_path, out_path):
    """mlx-whisper large-v3. Returns a record; never raises."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        result = subprocess.run(
            ["/Users/jmill/coding/github/CanvasSync/.venv/bin/mlx_whisper",
             "--model", "mlx-community/whisper-large-v3-mlx",
             "--output-format", "srt", "--output-dir", str(out_path.parent),
             str(mp4_path)],
            capture_output=True, text=True, timeout=7200)
    except subprocess.SubprocessError as exc:
        return {"path": str(mp4_path), "status": "gap", "error": str(exc)}
    if result.returncode != 0:
        return {"path": str(mp4_path), "status": "gap",
                "error": (result.stderr or "").strip()[-500:]}
    produced = out_path.parent / (Path(mp4_path).stem + ".srt")
    if not produced.exists():
        return {"path": str(mp4_path), "status": "gap",
                "error": "mlx_whisper produced no srt"}
    out_path.write_text(srt_to_markdown(produced.read_text()))
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
