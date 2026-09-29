"""The channel's daily job.

    python daily.py --world out/world.db --init --seed 184729 --days 1                 # no LLM, first day
    python daily.py --world out/world.db --llm --experiment A --days 1                 # Gemini decides for the active tier
"""
from __future__ import annotations

import argparse
import sys

from agent.llm import DEFAULT_MODEL
from channel.daily import DEFAULT_ACTIVE, DailyConfig, run_daily


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--world", default="out/world.db")
    ap.add_argument("--prod", default="out/production.db")
    ap.add_argument("--out", default="out/episodes")
    ap.add_argument("--days", type=int, default=1)
    ap.add_argument("--init", action="store_true", help="create the world if it does not exist")
    ap.add_argument("--seed", type=int, default=184729)
    ap.add_argument("--llm", action="store_true", help="a language model decides for the active characters")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--max-calls", type=int, default=60)
    ap.add_argument("--min-interval", type=float, default=4.0)
    ap.add_argument("--no-fallback", action="store_true", help="do not fall back to OpenRouter free models")
    ap.add_argument("--active", default=",".join(DEFAULT_ACTIVE))
    ap.add_argument("--experiment", help="freeze the setup under this id and refuse to continue if it drifts")
    ap.add_argument("--landscape", action="store_true")
    ap.add_argument("--quality", default="looks", choices=["draft", "looks", "delivery"])
    ap.add_argument("--dry-run", action="store_true", help="do everything except render the video")
    ap.add_argument("--world-c", action="store_true",
                    help="rule motives, the story director (threads) and a spatial plan per episode")
    ap.add_argument("--feed", default="synthetic_v1", help="outside-event feed for --world-c ('none' for a closed town)")
    args = ap.parse_args()

    cfg = DailyConfig(
        world_db=args.world, prod_db=args.prod, out_dir=args.out, days=args.days, seed=args.seed, init=args.init,
        use_llm=args.llm, model=args.model, max_calls=args.max_calls, min_interval=args.min_interval,
        use_openrouter=not args.no_fallback, active_ids=tuple(args.active.split(",")), experiment=args.experiment,
        orientation="landscape" if args.landscape else "portrait", quality=args.quality, render=not args.dry_run,
        world_c=args.world_c, feed=None if args.feed == "none" else args.feed)
    def show(r) -> None:
        e = r.episode
        print(f"day {r.sim_day + 1}: {r.status}" + (f" | {e.title} | qa={e.qa_status} | {e.video}" if e else "")
              + f" | llm calls={r.usage['llm_calls']} failures={r.usage['llm_failures']}", flush=True)

    run_daily(cfg, on_day=show)
    return 0


if __name__ == "__main__":
    sys.exit(main())
