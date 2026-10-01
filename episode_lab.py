"""Episode planner over a produced fortnight.   python episode_lab.py --days 14 --seeds 17,29,31 --out out/episode_lab

For each seed a world is run (jianghu_story_v1, the greedy director) a day at a time, and each day the planner makes the episode
(narrative/episode_planner.py). Reported: how many days had an episode, how many were a release the audience waited for
("payoff") against a running story ("thread"), how many have a core question and something left open at the end, how many
breathe, how many turn on an inner conflict, how many scenes were dropped because nothing changed, and for the payoff episodes
how much of the web-novel line the world really produced. The plans are saved so that they can be read, scene by scene.
"""
from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def run(args) -> dict:
    seed, days, recipe = args
    sys.path.insert(0, str(ROOT))
    from agent.volition import VolitionDecider
    from contracts.base import to_dict
    from narrative import episode_planner as EP
    from narrative.dramaturgy import analyse
    from producer.director import Director
    from world.db import connect, init_db
    from world.seed import build_world
    from world.simulation import Simulation
    conn = connect()
    init_db(conn, seed)
    build_world(conn, seed, recipe)
    d = VolitionDecider(seed)
    sim = Simulation(conn, d, d, set(), feed="synthetic_v1", producer=Director("greedy", seed))
    shown: set[int] = set()
    plans = []
    dilemmas = 0
    for day in range(days):
        sim.run(1)
        sit = analyse(conn)["situations"]
        recent = tuple(frozenset(q["people"]) for q in plans[-2:] if not q.get("quiet"))
        plan = EP.plan_day(conn, day, shown, sit, recent)
        if plan is None:
            plans.append({"day": day, "quiet": True})
            continue
        for b in plan.beats:
            shown |= set(b.event_ids)
        plans.append(to_dict(plan))
    dil = {k: conn.execute("SELECT COUNT(*) FROM events WHERE json_extract(truth, '$.dilemma.tension') >= ?", (k,)).fetchone()[0] for k in (0.3, 0.4, 0.5)}
    return {"seed": seed, "plans": plans, "dilemmas_05": dil[0.5], "dilemmas": dil}


def summarize(rows: list[dict]) -> dict:
    eps = [p for r in rows for p in r["plans"] if not p.get("quiet")]
    n = len(eps)
    days = sum(len(r["plans"]) for r in rows)
    filmed = [b for p in eps for b in p["beats"] if b["shoot"]]
    allb = [b for p in eps for b in p["beats"]]
    pay = [p for p in eps if p["kind"] == "payoff"]
    return {
        "days": days, "episodes": n, "quiet_days": days - n, "payoff_episodes": len(pay), "thread_episodes": n - len(pay),
        "core_question": sum(1 for p in eps if p["core_question"]), "open_ending": sum(1 for p in eps if p["ending_question"]),
        "breath": sum(1 for p in eps if p["has_breath"]), "inner_conflict": sum(1 for p in eps if p["inner_conflict"]),
        "near_miss": sum(1 for p in eps if p["near_miss"]), "shootable": sum(1 for p in eps if p["shootable"]),
        "beats": len(allb), "dropped_beats": len(allb) - len(filmed),
        "intents": {k: sum(1 for b in filmed if b["intent"] == k) for k in sorted({b["intent"] for b in filmed})},
        "distinct_intents_per_episode": round(sum(len({b["intent"] for b in p["beats"] if b["shoot"]}) for p in eps) / n, 2) if n else 0,
        "grammar_complete": sum(1 for p in pay if p["grammar_complete"]),
        "grammar_missing": {s: sum(1 for p in pay for g in p["grammar"] if g["step"] == s and not g["present"]) for s in
                            ("belittled", "hidden_growth", "gathering", "reversal", "bystanders", "next_goal")},
        "dilemma_events": {str(k): sum(r["dilemmas"][k] if k in r["dilemmas"] else r["dilemmas"][str(k)] for r in rows) for k in (0.3, 0.4, 0.5)},
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--seeds", default="17,29,31,43,59,67,73,89")
    ap.add_argument("--recipe", default="jianghu_story_v1")
    ap.add_argument("--out", default="out/episode_lab")
    a = ap.parse_args()
    seeds = [int(s) for s in a.seeds.split(",")]
    with ProcessPoolExecutor(min(8, len(seeds))) as ex:
        rows = list(ex.map(run, [(s, a.days, a.recipe) for s in seeds]))
    Path(a.out).mkdir(parents=True, exist_ok=True)
    (Path(a.out) / "plans.json").write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    s = summarize(rows)
    (Path(a.out) / "summary.json").write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(s, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
