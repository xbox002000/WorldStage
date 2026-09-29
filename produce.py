"""Turn the best arcs of a world into episodes.

    python produce.py --world out/world.db --top 3 [--landscape] [--dry-run]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from production.pipeline import produce


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--world", required=True)
    ap.add_argument("--prod", default="out/production.db")
    ap.add_argument("--out", default="out/episodes")
    ap.add_argument("--top", type=int, default=3)
    ap.add_argument("--landscape", action="store_true")
    ap.add_argument("--quality", default="looks", choices=["draft", "looks", "delivery"])
    ap.add_argument("--again", action="store_true", help="pick the same stories again instead of the next untold ones")
    ap.add_argument("--dry-run", action="store_true", help="build specs, packets and requests but do not render")
    args = ap.parse_args()

    Path(args.prod).parent.mkdir(parents=True, exist_ok=True)
    results = produce(args.world, args.prod, Path(args.out), top=args.top,
                      orientation="landscape" if args.landscape else "portrait", quality=args.quality,
                      render=not args.dry_run, exclude_used=not args.again)
    for r in results:
        where = r.video if r.video else "-"
        print(f"{r.scene_id} take={r.take_id} {'cache-hit' if r.cache_hit else ('queued' if r.qa_status == 'not_rendered' else 'rendered')} {r.seconds:5.1f}s "
              f"qa={r.qa_status} {where}")
    return 0 if all(r.qa_status.startswith("deterministic_pass") or r.qa_status == "not_rendered" for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
