#!/usr/bin/env python
"""Build the Systematic Innovation offline archive.

Eight stages, each independently re-runnable. See
docs/superpowers/specs/2026-08-27-systematic-innovation-archive-design.md
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

STAGES = ["cartridge", "elucidat", "vimeo", "local",
          "reconcile", "media", "render", "verify"]

# elucidat and vimeo are the two stages that depend on a third-party server
# having a good day. A bad day doesn't fail loudly -- it returns a
# structurally valid, gap-heavy result (elucidat.mirror_project appends a
# `_project_gap` with `pages: []` per failed project rather than raising),
# and `run_stage` overwrites that stage's _build/*.json unconditionally. For
# elucidat specifically that then propagates: render.py's clean_owned_output
# deletes sections/ and rebuilds it from whatever elucidat.json says, so one
# bad network day for `si_archive all` can silently gut the delivered site
# down to its gaps. Every other stage is either purely local (cartridge,
# local, reconcile, render, verify) or, for media, already cheap to re-run
# via its own on-disk resume logic (find_existing_srt) rather than blind
# overwrite. So `all` skips re-fetching a network stage that already has
# output, unless --force says otherwise; running a stage by name directly
# (`si_archive elucidat`) is a deliberate, explicit re-fetch and always runs.
NETWORK_STAGE_OUTPUT = {"elucidat": "elucidat.json", "vimeo": "vimeo.json"}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("stage", choices=STAGES + ["all"],
                    help="pipeline stage to run")
    ap.add_argument("--out", default=None,
                    help="archive root (default: constants.OUTPUT_ROOT)")
    ap.add_argument("--min-gap", type=float, default=1.5)
    ap.add_argument("--jitter", type=float, default=1.5)
    ap.add_argument("--rest-every", type=int, default=25)
    ap.add_argument("--force", action="store_true",
                    help="with the 'all' driver, re-run the elucidat/vimeo network "
                         "stages even if their _build/*.json output already exists")
    args = ap.parse_args(argv)

    from si_archive import constants
    out = Path(args.out or constants.OUTPUT_ROOT)

    stages = STAGES if args.stage == "all" else [args.stage]
    for name in stages:
        output_name = NETWORK_STAGE_OUTPUT.get(name)
        if (args.stage == "all" and not args.force and output_name
                and (out / "_build" / output_name).exists()):
            print(f"==> {name} (skipped: _build/{output_name} already exists -- "
                  "pass --force to re-fetch)")
            continue
        print(f"==> {name}")
        run_stage(name, args)
    return 0


def run_stage(name, args):
    from pathlib import Path

    from si_archive import constants

    out = Path(args.out or constants.OUTPUT_ROOT)

    if name == "cartridge":
        from si_archive import cartridge
        course = cartridge.write_course_json(constants.CARTRIDGE_DIR,
                                             out / "_build" / "course.json")
        print(f"    {len(course['sections'])} sections")
        return

    if name == "elucidat":
        import json

        from si_archive import elucidat
        from si_archive.net import Throttle
        throttle = Throttle(min_gap=args.min_gap, jitter=args.jitter,
                            rest_every=args.rest_every)
        projects = elucidat.mirror_all(out / "_source" / "elucidat", throttle)
        target = out / "_build" / "elucidat.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(projects, indent=2, ensure_ascii=False))
        total = sum(len(p["pages"]) for p in projects.values())
        print(f"    {len(projects)} projects, {total} pages")
        return

    if name == "vimeo":
        import json

        from si_archive import vimeo
        from si_archive.net import Throttle
        doc = json.loads((out / "_build" / "elucidat.json").read_text())
        throttle = Throttle(min_gap=max(args.min_gap, 3.0), jitter=args.jitter,
                            rest_every=args.rest_every)
        records = vimeo.download_all(doc, out / "_build" / "vimeo", throttle)
        (out / "_build" / "vimeo.json").write_text(
            json.dumps(records, indent=2, ensure_ascii=False))
        gaps = [r for r in records if r["status"] == "gap"]
        print(f"    {len(records)} videos, {len(gaps)} gaps")
        return

    if name == "local":
        import json

        from si_archive import localsrc
        records = localsrc.build_index()
        target = out / "_build" / "local.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(records, indent=2, ensure_ascii=False))
        mp4 = [r for r in records if r["ext"] == ".mp4"]
        print(f"    {len(records)} files, {len(mp4)} mp4")
        return

    if name == "media":
        import json

        from si_archive import media
        local = json.loads((out / "_build" / "local.json").read_text())
        records = media.derive_all(local, out / "_build")
        (out / "_build" / "media.json").write_text(
            json.dumps(records, indent=2, ensure_ascii=False))
        ok = [r for r in records if r["status"] == "ok"]
        sheets = [r for r in records if r.get("contactsheet")]
        print(f"    {len(ok)}/{len(records)} transcripts, {len(sheets)} contact sheets")
        return

    if name == "reconcile":
        import json

        from si_archive import reconcile
        local = json.loads((out / "_build" / "local.json").read_text())
        vimeo_records = json.loads((out / "_build" / "vimeo.json").read_text())
        ledger = reconcile.build_ledger(local, vimeo_records)
        (out / "_build" / "ledger.json").write_text(
            json.dumps(ledger, indent=2, ensure_ascii=False))
        for key, value in ledger["stats"].items():
            print(f"    {key}: {value}")
        return

    if name == "render":
        from si_archive import render
        stats = render.render_site(out / "_build", out)
        print(f"    {stats['pages_written']} pages, {stats['sections']} sections, "
              f"{stats['media_placed']} media files, {stats['documents']} documents, "
              f"{stats['gaps']} gaps, {stats['links_fixed']} cross-reference links resolved")
        return

    if name == "verify":
        from si_archive import verify
        report = verify.build_report(out)
        (out / "REPORT.md").write_text(report)
        print(report)
        return

    raise NotImplementedError(f"stage {name!r} not yet implemented")


if __name__ == "__main__":
    sys.exit(main())
