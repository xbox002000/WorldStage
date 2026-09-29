"""Run the same world with and without a narrative mechanic and print what changed.

    python mechanics_demo.py rebirth --who jun --fork-day 0
    python mechanics_demo.py system --who mei

Worlds are kept in out/mechanics/ for explain.py. $0: rule motives only.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from agent.volition import VolitionDecider
from contracts.mechanic import MechanicSpec, NarrativeMechanicPack
from narrative.threads import derive_threads
from world.db import connect, init_db
from world.explain import summarize
from world.mechanics.base import record_pack
from world.mechanics.rebirth import fork
from world.seed import build_world
from world.simulation import Simulation
from world.snapshot import snapshot_hash
from world.state import audit


def fresh(path: Path, seed: int):
    for suffix in ("", "-wal", "-shm"):
        Path(str(path) + suffix).unlink(missing_ok=True)
    conn = connect(path)
    return conn


def story_of(conn, who: str) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT e.event_id FROM events e JOIN event_participants p ON p.event_id = e.event_id "
        "WHERE p.person_id = ? AND p.role IN ('actor', 'target', 'victim', 'suspect') AND (e.importance >= 0.4 OR e.type LIKE 'system_%') "
        "AND e.type NOT IN ('upkeep', 'move', 'eat', 'work', 'day_end') ORDER BY e.event_id", (who,)).fetchall()
    return [summarize(conn, r[0]) for r in rows]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("mechanic", choices=["rebirth", "system"])
    ap.add_argument("--who", default="jun")
    ap.add_argument("--seed", type=int, default=260931)
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--fork-day", type=int, default=0)
    ap.add_argument("--feed", default="synthetic_v1")
    args = ap.parse_args()
    out = Path("out/mechanics")
    out.mkdir(parents=True, exist_ok=True)
    feed = None if args.feed == "none" else args.feed

    a = fresh(out / f"{args.mechanic}_A.db", args.seed)
    init_db(a, args.seed)
    build_world(a, args.seed)
    d = VolitionDecider(args.seed)
    Simulation(a, d, d, set(), feed=feed, mechanics=[]).run(args.days)

    b = fresh(out / f"{args.mechanic}_B.db", args.seed)
    if args.mechanic == "rebirth":
        fork(a, b, args.seed, feed, args.fork_day, args.who, lambda m: VolitionDecider(args.seed))
        Simulation(b, d, d, set(), feed=feed).run(args.days - args.fork_day)
    else:
        init_db(b, args.seed)
        build_world(b, args.seed)
        record_pack(b, NarrativeMechanicPack("system", [MechanicSpec("system", "character", args.who)]), 1)
        Simulation(b, d, d, set(), feed=feed).run(args.days)

    for name, conn in (("A (no mechanic)", a), (f"B ({args.mechanic} for {args.who})", b)):
        print(f"\n===== timeline {name}   audit={len(audit(conn))} problems   snapshot={snapshot_hash(conn)[:19]}")
        for line in story_of(conn, args.who):
            print("  ", line)
        if args.mechanic == "system":
            for (t,) in conn.execute("SELECT truth FROM events WHERE type LIKE 'system_%' ORDER BY event_id"):
                print("   [system]", t[:160])
    ta = {t.thread_id: len(t.event_ids) for t in derive_threads(a)}
    tb = {t.thread_id: len(t.event_ids) for t in derive_threads(b)}
    changed = sorted(k for k in set(ta) | set(tb) if ta.get(k) != tb.get(k))
    print(f"\nthreads A={len(ta)} B={len(tb)}; changed or new: {len(changed)}")


if __name__ == "__main__":
    main()
