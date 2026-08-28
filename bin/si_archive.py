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
    args = ap.parse_args(argv)

    stages = STAGES if args.stage == "all" else [args.stage]
    for name in stages:
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

    raise NotImplementedError(f"stage {name!r} not yet implemented")


if __name__ == "__main__":
    sys.exit(main())
