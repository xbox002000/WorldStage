"""Run the V0 world. Default: no LLM at all (seeded ambient decisions for everyone)."""
from __future__ import annotations

import argparse
import sys

from agent.decision import GeminiDecider, SeededDecider
from agent.llm import DEFAULT_MODEL, build_chain
from world.db import connect, init_db
from world.seed import build_world
from world.simulation import Simulation
from world.state import audit

ACTIVE = {"ming", "mei", "jun", "lan"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--seed", type=int, default=184729)
    ap.add_argument("--db", default=":memory:")
    ap.add_argument("--llm", action="store_true", help="use Gemini for the active tier")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--max-calls", type=int, default=40)
    ap.add_argument("--min-interval", type=float, default=4.0)
    ap.add_argument("--no-fallback", action="store_true", help="do not use OpenRouter free models")
    ap.add_argument("--active", default=",".join(sorted(ACTIVE)))
    args = ap.parse_args()

    conn = connect(args.db)
    init_db(conn, args.seed)
    build_world(conn, args.seed)

    ambient = SeededDecider(args.seed)
    client = None
    if args.llm:
        client = build_chain(args.model, max_calls=args.max_calls, min_interval=args.min_interval,
                             use_openrouter=not args.no_fallback)
        active = GeminiDecider(client)
        active_ids = set(args.active.split(","))
    else:
        active, active_ids = ambient, set()

    sim = Simulation(conn, active, ambient, active_ids)
    sim.run(args.days)

    n_events = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    social = conn.execute("SELECT COUNT(*) FROM events WHERE type IN ('talk','steal')").fetchone()[0]
    flips = conn.execute(
        "SELECT COUNT(*) FROM events WHERE type='talk' AND json_extract(truth,'$.trust_flipped') = 1"
    ).fetchone()[0]
    print(f"events={n_events} social={social} trust_flips={flips} audit_problems={len(audit(conn))}")
    print("stats:", dict(sim.stats))
    if client:
        print(f"llm: models={[c.model for c in client.clients]} calls={client.calls} failures={client.failures} "
              f"switches={client.switches} decider_errors={active.errors}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
