"""Rhythm stress test: does a world breathe over 30, 60 and 90 days, or is every day a peak?

    python rhythm_test.py --seeds 3 --days 90 --out out/rhythm

Arms: jianghu_v1 (closed) and town_v1 (World C with the synthetic feed), each with and without recovery (conflict
fatigue and duel injuries), the same seeds. $0: no model is called.
Writes out/rhythm/results.json and prints one strip per run: . quiet  - simmer  / rising  ^ peak  \\ recovery
"""
from __future__ import annotations

import argparse
import json
from contextlib import contextmanager
from pathlib import Path
from statistics import mean

from agent.volition import VolitionDecider
from narrative.rhythm import rhythm
from narrative.threads import derive_threads
from world.db import connect, init_db
from world.seed import build_world
from world.simulation import Simulation
from world.state import audit

# arm: (recipe, feed, recovery). recovery=False is the ablation: no conflict fatigue (agent.volition.STRAIN_WEIGHT = 0)
# and no duel injuries (world.jianghu.INJURY_DAYS = 0), everything else identical.
ARMS = {"jianghu": ("jianghu_v1", None, True), "jianghu_norecovery": ("jianghu_v1", None, False),
        "town": ("town_v1", "synthetic_v1", True), "town_norecovery": ("town_v1", "synthetic_v1", False)}


@contextmanager
def recovery(on: bool):
    import agent.volition as v
    import world.jianghu as j
    saved = v.STRAIN_WEIGHT, j.INJURY_DAYS
    if not on:
        v.STRAIN_WEIGHT, j.INJURY_DAYS = 0.0, 0
    try:
        yield
    finally:
        v.STRAIN_WEIGHT, j.INJURY_DAYS = saved
BASE_SEED = 1


def run_one(path: Path, seed: int, recipe: str, feed: str | None, days: int, window: int) -> dict:
    if not path.exists():
        conn = connect(path)
        init_db(conn, seed)
        build_world(conn, seed, recipe)
        d = VolitionDecider(seed)
        Simulation(conn, d, d, set(), feed=feed).run(days)
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    else:
        conn = connect(path)
    threads = derive_threads(conn)
    out = {"seed": seed, "audit_problems": len(audit(conn)),
           "windows": [rhythm(conn, lo, lo + window, threads) for lo in range(0, days, window)],
           "whole": rhythm(conn, 0, days, threads)}
    conn.close()
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--window", type=int, default=30)
    ap.add_argument("--out", default="out/rhythm")
    ap.add_argument("--arms", default=",".join(ARMS))
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    from world.ruleset import KERNEL_VERSION, ruleset_hash
    rules = ruleset_hash()  # taken before the runs: the files may not change under a running experiment
    results: dict[str, list[dict]] = {}
    for arm in args.arms.split(","):
        recipe, feed, rec = ARMS[arm]
        for i in range(args.seeds):
            seed = BASE_SEED + i
            with recovery(rec):
                r = run_one(out / f"{arm}_{seed}.db", seed, recipe, feed, args.days, args.window)
            results.setdefault(arm, []).append(r)
            w = r["whole"]
            print(f"{arm:8} seed {seed}  world peak {w['shape']['peak']:.2f}  person peak {w['person_shape']['peak']:.2f} "
                  f"quiet {w['person_shape']['quiet']:.2f}  duels/day {w['duels_per_day']}  {w['strip']}", flush=True)
            for p, strip in list(w["person_strips"].items())[:4]:
                print(f"{'':8} {p:>6}  {strip}", flush=True)
    if ruleset_hash() != rules:
        raise SystemExit("the ruleset changed while the experiment ran: start it again")
    config = {"kernel_version": KERNEL_VERSION, "ruleset_hash": rules, "arms": ARMS, "decider": "volition",
              "seeds": [BASE_SEED + i for i in range(args.seeds)], "days": args.days, "window": args.window}
    summary = {}
    for arm, runs in results.items():
        summary[arm] = []
        for k in range(len(runs[0]["windows"])):
            ws = [r["windows"][k] for r in runs]
            summary[arm].append({
                "days": ws[0]["days"],
                **{m: round(mean(w[m] for w in ws), 2) for m in ("events_per_day", "decisions_per_day",
                                                                  "high_per_day", "duels_per_day", "longest_peak_run")},
                "shape": {s: round(mean(w["shape"][s] for w in ws), 2) for s in ws[0]["shape"]},
                "person_shape": {s: round(mean(w["person_shape"][s] for w in ws), 2) for s in ws[0]["person_shape"]},
                "person_longest_peak_run": round(mean(w["person_longest_peak_run"] for w in ws), 2),
                "threads": {s: round(mean(w["threads"][s] for w in ws), 1) for s in ws[0]["threads"]},
                "people": {s: round(mean(w["people"][s] for w in ws), 2) for s in ("trust_reversals", "belief_reversals",
                                                                                   "trait_drift", "value_shift")},
                "goal_changes": {g: round(sum(w["people"]["goal_changes"].get(g, 0) for w in ws) / len(ws), 1)
                                 for g in sorted({g for w in ws for g in w["people"]["goal_changes"]})},
            })
    (out / "results.json").write_text(json.dumps({"config": config, "runs": results, "summary": summary},
                                                 ensure_ascii=False, indent=2), encoding="utf-8")
    for arm, rows in summary.items():
        print(f"\n{arm}")
        for row in rows:
            print(json.dumps(row, ensure_ascii=False))
    print("ruleset", config["ruleset_hash"][:19])


if __name__ == "__main__":
    main()
