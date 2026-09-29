"""Experiment C: does World C make stories by itself, and do outside events add to them without writing them?

    python experiment_c.py --seeds 5 --days 14 --out out/expC

C0 = rule motives, closed town. C1 = the same worlds plus the synthetic_v1 feed. $0: no model is called.
Writes out/expC/results.json and prints a table; the worlds are kept (out/expC/<arm>_<seed>.db) for explain.py.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean

from agent.volition import VolitionDecider
from narrative.ecology import measure
from world.db import connect, init_db
from world.seed import build_world
from world.simulation import Simulation
from world.state import audit

ARMS = {"C0": None, "C1": "synthetic_v1"}
BASE_SEED = 260930


def run_one(path: Path, seed: int, feed: str | None, days: int) -> dict:
    path.unlink(missing_ok=True)
    conn = connect(path)
    init_db(conn, seed)
    build_world(conn, seed)
    d = VolitionDecider(seed)
    Simulation(conn, d, d, set(), feed=feed).run(days)
    problems = audit(conn)
    result = measure(conn, days)
    result["audit_problems"] = len(problems)
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=5)
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--out", default="out/expC")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    results: dict[str, list[dict]] = {}
    for arm, feed in ARMS.items():
        for i in range(args.seeds):
            seed = BASE_SEED + i
            r = run_one(out / f"{arm}_{seed}.db", seed, feed, args.days)
            r["seed"] = seed
            results.setdefault(arm, []).append(r)
            print(arm, seed, "threads", r["threads"], "long", r["long_threads"], "flat", r["flat_day_ratio"], flush=True)
    summary = {}
    for arm, runs in results.items():
        keys = [k for k, v in runs[0].items() if isinstance(v, (int, float)) and k != "seed"]
        summary[arm] = {k: round(mean(r[k] for r in runs if r[k] is not None), 3) for k in keys
                        if any(r[k] is not None for r in runs)}
    (out / "results.json").write_text(json.dumps({"runs": results, "summary": summary}, ensure_ascii=False, indent=2),
                                      encoding="utf-8")
    keys = sorted(set(summary["C0"]) | set(summary["C1"]))
    print(f"\n{'measure':28} {'C0':>8} {'C1':>8}")
    for k in keys:
        print(f"{k:28} {summary['C0'].get(k, '-'):>8} {summary['C1'].get(k, '-'):>8}")


if __name__ == "__main__":
    main()
