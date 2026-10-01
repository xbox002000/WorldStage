"""Does dramatic debt predict a payoff?  python debt_lab.py --days 28 --seeds ...

In worlds with no producer, each morning from day 3 to day 21, every person's debt is read; then it is asked whether the people who
carried more went on to have a payoff in the next ten days. Reported as an AUC (the chance that a person who had a payoff carried
more debt than one who did not; 0.5 is no information), for the debt, each of its parts, and the opportunity detector's own worth,
so that "a new read model" has to beat what was already there.
"""
from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent
AHEAD = 10


class Recorder:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    def dawn(self, conn, day, now):
        if not 3 <= day <= 21:
            return
        from narrative import debt, opportunity
        worth: dict[str, float] = {}
        for o in opportunity.detect(conn, day):
            worth[o.protagonist] = max(worth.get(o.protagonist, 0.0), o.potential)
        for r in debt.ledger(conn):
            self.rows.append({"day": day, "person": r["person"], "debt": r["debt"], "worth": worth.get(r["person"], 0.0), **r["parts"]})


def run(args) -> list[dict]:
    seed, days = args
    sys.path.insert(0, str(ROOT))
    from agent.volition import VolitionDecider
    from narrative import payoff
    from world.db import connect, init_db
    from world.seed import build_world
    from world.simulation import Simulation
    conn = connect()
    init_db(conn, seed)
    build_world(conn, seed, "jianghu_story_v1")
    rec = Recorder()
    d = VolitionDecider(seed)
    Simulation(conn, d, d, set(), feed="synthetic_v1", producer=rec).run(days)
    found = payoff.payoffs(conn)
    for r in rec.rows:
        r["seed"] = seed
        r["paid"] = any(p["protagonist"] == r["person"] and r["day"] <= p["day"] < r["day"] + AHEAD for p in found)
    return rec.rows


def auc(rows: list[dict], key: str) -> float:
    pos = [r[key] for r in rows if r["paid"]]
    neg = [r[key] for r in rows if not r["paid"]]
    if not pos or not neg:
        return 0.5
    wins = sum((p > n) + 0.5 * (p == n) for p in pos for n in neg)
    return wins / (len(pos) * len(neg))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=28)
    ap.add_argument("--seeds", default="17,29,31,43,59,67,73,89")
    ap.add_argument("--out", default="out/debt_lab.json")
    a = ap.parse_args()
    seeds = [int(s) for s in a.seeds.split(",")]
    with ProcessPoolExecutor(min(8, len(seeds))) as ex:
        rows = [r for part in ex.map(run, [(s, a.days) for s in seeds]) for r in part]
    res = {k: round(auc(rows, k), 3) for k in ("debt", "worth", "humiliation", "betrayal", "gap", "longing", "grudge")}
    res.update(n=len(rows), paid=sum(r["paid"] for r in rows))
    Path(a.out).write_text(json.dumps({"auc": res, "seeds": seeds}, indent=1), encoding="utf-8")
    print(res)


if __name__ == "__main__":
    main()
