"""Stage 5 -- deduplicate and rendition-match into a single ledger.

Three relationships between copies of the same thing:

  1. byte-identical      -- collapse by SHA-256, keep aliases
  2. same work, different encoding -- cannot hash-match; pair on normalized
     title and duration, keep the better copy, record the other
  3. distinct works      -- keep separately

Nothing is deleted from the record. A file that loses to a better rendition is
still named in the ledger, so the archive can always say what it chose and why.
"""
import re
import unicodedata
from pathlib import Path


def normalize_title(text):
    """Fold to lowercase words so 'MIT_INN_M1_V2.mp4' == 'MIT_INN_M1_V2'."""
    if not text:
        return ""
    stem = Path(text).stem if "." in Path(text).name else text
    folded = unicodedata.normalize("NFKD", stem)
    folded = folded.encode("ascii", "ignore").decode("ascii")
    folded = re.sub(r"[^\w\s]", " ", folded)
    return re.sub(r"\s+", " ", folded.replace("_", " ")).strip().lower()


def group_by_hash(records):
    """Collapse byte-identical files. First-seen path wins as canonical."""
    groups = {}
    for record in records:
        digest = record.get("sha256")
        if not digest:
            continue
        group = groups.setdefault(digest, {"sha256": digest, "canonical": record["path"],
                                           "aliases": [], "size": record.get("size")})
        if record["path"] != group["canonical"]:
            group["aliases"].append(record["path"])
    return list(groups.values())


def match_renditions(local, vimeo, tolerance=2.0):
    """Pair Vimeo downloads with local MP4s of the same work."""
    candidates = [r for r in local
                  if r.get("ext") == ".mp4" and r.get("duration")]
    matches = []
    claimed_paths = set()
    for video in vimeo:
        if video.get("status") != "ok" or not video.get("duration"):
            continue
        vtitle = normalize_title(video.get("title") or "")
        for record in candidates:
            if record["path"] in claimed_paths:
                continue
            if abs(record["duration"] - video["duration"]) > tolerance:
                continue
            if normalize_title(Path(record["path"]).name) != vtitle:
                continue
            local_size = record.get("size") or 0
            vimeo_size = video.get("size") or 0
            if vimeo_size > local_size:
                canonical, reason = video["path"], "vimeo copy is larger"
            else:
                canonical, reason = record["path"], "local copy is at least as large"
            matches.append({
                "work": vtitle,
                "local_path": record["path"],
                "vimeo_id": video["id"],
                "vimeo_path": video.get("path"),
                "local_duration": record["duration"],
                "vimeo_duration": video["duration"],
                "canonical": canonical,
                "reason": reason,
            })
            claimed_paths.add(record["path"])
            break
    return matches


def build_ledger(local, vimeo):
    files = group_by_hash(local)
    renditions = match_renditions(local, vimeo)
    matched_ids = {m["vimeo_id"] for m in renditions}
    online_only = [v for v in vimeo
                   if v.get("status") == "ok" and v["id"] not in matched_ids]
    gaps = [v for v in vimeo if v.get("status") == "gap"]
    return {
        "files": files,
        "renditions": renditions,
        "online_only": online_only,
        "gaps": gaps,
        "stats": {
            "local_records": len(local),
            "unique_files": len(files),
            "duplicate_paths": sum(len(f["aliases"]) for f in files),
            "renditions": len(renditions),
            "online_only": len(online_only),
            "vimeo_gaps": len(gaps),
        },
    }
