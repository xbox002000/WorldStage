"""Turn the best arcs of a world into episodes.

    python produce.py --world out/world.db --top 3 [--landscape] [--dry-run] [--route shots] [--mcp]

--route procedural  HyperFrames draws every shot (default)
--route shots       each shot from a visual.generate provider (staged, diagnosed, repaired), composed with ffmpeg
--mcp               also offer visual.generate through the local MCP server (capability/mcp_servers/visual_mock.py)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from capability.defaults import default_registry
from contracts.capability import Policy
from production import db as prod
from production.pipeline import ROUTES, produce


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
    ap.add_argument("--route", default="procedural", choices=ROUTES)
    ap.add_argument("--mcp", action="store_true", help="register the MCP visual provider as well")
    ap.add_argument("--prefer", nargs="*", default=[], help="provider ids to try first, e.g. mcp:visual-mock")
    args = ap.parse_args()

    Path(args.prod).parent.mkdir(parents=True, exist_ok=True)
    conn = prod.open_production_db(args.prod)
    registry = default_registry(lambda h: prod.load_packet(conn, h), mcp=args.mcp)
    results = produce(args.world, args.prod, Path(args.out), top=args.top,
                      orientation="landscape" if args.landscape else "portrait", quality=args.quality,
                      render=not args.dry_run, exclude_used=not args.again, route=args.route, registry=registry,
                      policy=Policy(order=args.prefer), prod_conn=conn)
    conn.close()
    for r in results:
        where = r.video if r.video else "-"
        print(f"{r.scene_id} take={r.take_id} {'cache-hit' if r.cache_hit else ('queued' if r.qa_status == 'not_rendered' else 'rendered')} {r.seconds:5.1f}s "
              f"qa={r.qa_status} {where}")
        print(f"    providers: {r.providers}")
        for o in r.shots or []:
            print(f"    {o.shot_id}: {'ok' if o.ok else 'FAILED'} via {o.provider} in {o.attempts} attempt(s)"
                  + (f", repaired {[f.code for f in o.failures]}" if o.failures else ""))
    return 0 if all(r.qa_status.startswith("deterministic_pass") or r.qa_status == "not_rendered" for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
