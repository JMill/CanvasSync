"""Stage 4 -- index the local sources by content hash.

Student work is excluded here, at the index, so no later stage can copy or
link it by accident. What is kept is the instructor-authored course material:
prompts, rubrics, media, reference documents.
"""
import fnmatch
import hashlib
import subprocess
from pathlib import Path

from si_archive import constants

MEDIA_EXTS = {".mp4", ".m4v", ".mov", ".mp3", ".m4a", ".wav"}
SKIP_NAMES = {".DS_Store"}


def is_student_work(path):
    path = Path(path)
    if fnmatch.fnmatch(path.name, constants.STUDENT_WORK_FILE_GLOB):
        return True
    return any(fnmatch.fnmatch(part, constants.STUDENT_WORK_DIR_GLOB)
               for part in path.parts)


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def probe_duration(path):
    if Path(path).suffix.lower() not in MEDIA_EXTS:
        return None
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, timeout=120)
        return float(result.stdout.strip())
    except (ValueError, subprocess.SubprocessError):
        return None


def index_tree(root, source):
    root = Path(root)
    records = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name in SKIP_NAMES:
            continue
        # ScreenFlow bundles are directories; never descend into one.
        if any(part.endswith(".screenflow") for part in path.parts):
            continue
        if is_student_work(path):
            continue
        records.append({
            "source": source,
            "path": str(path),
            "relpath": str(path.relative_to(root)),
            "size": path.stat().st_size,
            "sha256": sha256(path),
            "duration": probe_duration(path),
            "ext": path.suffix.lower(),
        })
    return records


def index_screenflow_bundles(root):
    """Referenced, not copied -- 9.5GB of editable production masters."""
    return [{"source": "screenflow", "path": str(p), "relpath": p.name,
             "size": sum(f.stat().st_size for f in p.rglob("*") if f.is_file()),
             "sha256": None, "duration": None, "ext": ".screenflow"}
            for p in sorted(Path(root).rglob("*.screenflow"))]


def build_index():
    records = []
    records += index_tree(constants.CAMPUS_DIR, "campus")
    records += index_tree(constants.GDRIVE_DIR, "gdrive")
    records += index_screenflow_bundles(constants.CAMPUS_DIR)
    pdf = Path(constants.PROVENANCE_PDF)
    if pdf.exists():
        records.append({
            "source": "provenance", "path": str(pdf), "relpath": pdf.name,
            "size": pdf.stat().st_size, "sha256": sha256(pdf),
            "duration": None, "ext": ".pdf",
        })
    return records
