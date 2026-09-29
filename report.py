"""Experiment report: the acceptance checks for a run of the channel.

    python report.py --world out/world.db --prod out/production.db [--experiment A] [--days 7] [--replay]
"""
from __future__ import annotations

import argparse
import json
import sys

from production import db as prod
from production.metrics import acceptance, format_report
from channel.replay import replay_check
from world.reader import open_world_reader


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--world", default="out/world.db")
    ap.add_argument("--prod", default="out/production.db")
    ap.add_argument("--experiment")
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--replay", action="store_true", help="also rebuild the world from the recorded answers and compare")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    world = open_world_reader(args.world)
    conn = prod.open_production_db(args.prod)
    replay_ok = None
    if args.replay:
        r = replay_check(args.world)
        replay_ok = r["identical"]
        print(f"replay: {'identical' if replay_ok else 'DIFFERENT'} over {r['days']} days from {r['recorded_answers']} recorded answers")
    result = acceptance(world, conn, experiment_id=args.experiment, days=args.days, replay_ok=replay_ok)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str) if args.json else format_report(result))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
