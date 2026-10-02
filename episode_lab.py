"""Episode planner over a produced fortnight.   python episode_lab.py --days 14 --seeds 17,29,31 --out out/episode_lab

The world is run once per seed (the planner only reads, so it cannot change it) and every day each *variant* of the planner makes its
own episode, with its own memory of what it has shown. The variants (narrative/episode_planner.py `Options`):

  v1         the planner as first built: a scene changed only if the world's entities did, set-up scenes kept by a special case,
             a thread chosen by ranking alone, the next goal an event, whatever question the analysis gave
  narrative  plus what the audience gains (a growth the crowd has not seen, a feeling nobody has said) as a kind of change
  ab         the progress planner, with a B story and an ordinary moment in each episode
  progress   plus: a thread in which nothing real happened is not the day's story, the new state is a consequence, voters are
             bystanders, a question is a goal, a choice or a revelation (never "will they regret it")
  script     the control room's setting: ab, plus the season's ledgers (today's events, a hard event in, montage, a question not asked again)

Every plan is also run through the script lint (narrative/lint.py): faults by code, how much of an episode is talk, the same line twice,
and how many days with a hard event had one on screen.

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


from narrative.episode_planner import DEFAULT, V1, Options  # noqa: E402

from narrative.episode_planner import SHOW  # noqa: E402

VARIANTS = {"v1": V1, "narrative": Options("narrative", False, False, "v1", "free"), "progress": DEFAULT, "ab": Options(ab_story=True), "script": SHOW}


def run(args) -> dict:
    seed, days, recipe = args
    sys.path.insert(0, str(ROOT))
    from agent.volition import VolitionDecider
    from contracts.base import to_dict
    from narrative import episode_planner as EP
    from narrative import lint as LN
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
    state = {v: {"shown": set(), "plans": [], "ledger": EP.Ledger() if opt.script else None, "prior": [], "hard": []} for v, opt in VARIANTS.items()}
    for day in range(days):
        sim.run(1)
        sit = analyse(conn)["situations"]
        for v, opt in VARIANTS.items():
            st = state[v]
            recent = tuple(frozenset(q["people"]) for q in st["plans"][-2:] if not q.get("quiet"))
            plan = EP.plan_day(conn, day, st["shown"], sit, recent, opt, st["ledger"])
            hard = LN.hard_events(conn, day)
            if plan is None:
                st["plans"].append({"day": day, "quiet": True, "hard": hard})
                continue
            for b in plan.beats:
                st["shown"] |= set(b.event_ids)
            resolved = LN.resolve(conn, plan)
            issues = LN.lint_episode(resolved, prior=st["prior"], names=resolved["people_names"] + [r[0] for r in conn.execute("SELECT name FROM people")],
                                     facts=LN.object_facts(conn, day))
            st["prior"].append(resolved)
            d = to_dict(plan)
            d.update(hard=hard, lint=[i.as_dict() for i in issues], lint_metrics=LN.metrics(resolved), hard_on_screen=LN.hard_taken(resolved, hard)[1])
            st["plans"].append(d)
    dil = {k: conn.execute("SELECT COUNT(*) FROM events WHERE json_extract(truth, '$.dilemma.tension') >= ?", (k,)).fetchone()[0] for k in (0.3, 0.4, 0.5)}
    return {"seed": seed, "variants": {v: st["plans"] for v, st in state.items()}, "dilemmas": dil}


def summarize(rows: list[dict], variant: str) -> dict:
    plans_by_seed = [r["variants"][variant] for r in rows]
    eps = [p for plans in plans_by_seed for p in plans if not p.get("quiet")]
    n = len(eps)
    days = sum(len(plans) for plans in plans_by_seed)
    filmed = [b for p in eps for b in p["beats"] if b["shoot"]]
    allb = [b for p in eps for b in p["beats"]]
    pay = [p for p in eps if p["kind"] == "payoff"]
    thread = [p for p in eps if p["kind"] == "thread"]
    pairs = [(a, b) for plans in plans_by_seed for a, b in zip(plans, plans[1:]) if not a.get("quiet") and not b.get("quiet")]
    # a growth is *hidden* when the audience was ahead at that scene (the narrative variant measures the gap at every scene; the first
    # planner cannot see it, so it is judged by the same scenes)
    gap = {(r["seed"], i): b["checklist"]["audience_advantage"] for r in rows for p in r["variants"]["narrative"] if not p.get("quiet")
           for b in p["beats"] for i in b["event_ids"] if b["checklist"]["audience_advantage"] > 0}
    seeds = [r["seed"] for r in rows]
    growth_eps, kept = [], []
    for si, plans in enumerate(plans_by_seed):
        for p in plans:
            if p.get("quiet") or p["kind"] != "payoff":
                continue
            ids = {i for g in p["grammar"] if g["step"] == "hidden_growth" for i in g["event_ids"] if (seeds[si], i) in gap}
            if ids:
                growth_eps.append(p)
                if all(b["shoot"] for b in p["beats"] if set(b["event_ids"]) & ids):
                    kept.append(p)
    stagnant = [p for p in thread if not any(b["shoot"] and b["checklist"]["progress"] for b in p["beats"])]
    step = lambda name: sum(1 for p in pay for g in p["grammar"] if g["step"] == name and g["present"])  # noqa: E731
    return {
        "days": days, "episodes": n, "quiet_days": days - n, "payoff": len(pay), "inner": sum(1 for p in eps if p["kind"] == "inner"), "thread": len(thread),
        "repeated_pair_rate": round(sum(1 for a, b in pairs if a["kind"] == "thread" and b["kind"] == "thread" and set(a["people"]) == set(b["people"])) / max(1, len(pairs)), 3),
        "single_intent_rate": round(sum(1 for p in eps if len({b["intent"] for b in p["beats"] if b["shoot"]}) == 1) / max(1, n), 3),
        "stagnant_thread_episodes": len(stagnant), "stagnant_rate": round(len(stagnant) / max(1, len(thread)), 3),
        "hidden_growth_present": len(growth_eps), "hidden_growth_kept": len(kept),
        "bystanders": step("bystanders"), "new_state_or_next_goal": step("new_state"), "payoff_episodes": len(pay),
        "grammar_complete": sum(1 for p in pay if p["grammar_complete"]),
        "core_question": sum(1 for p in eps if p["core_question"]), "open_ending": sum(1 for p in eps if p["ending_question"]),
        "breath": sum(1 for p in eps if p["has_breath"]), "inner_conflict": sum(1 for p in eps if p["inner_conflict"]),
        "regret_questions": sum(1 for p in eps if p["core_question"].endswith("會後悔嗎？") or p["ending_question"].endswith("會後悔嗎？")),
        "question_types": {k: sum(1 for p in eps if p["question_type"] == k) for k in ("goal", "choice", "revelation", "open")} if variant in ("progress", "ab", "script") else {},
        "b_story_episodes": sum(1 for p in eps if any(b["story"] == "B" for b in p["beats"])),
        "texture_episodes": sum(1 for p in eps if any(b["story"] == "texture" for b in p["beats"])),
        "scenes_per_episode": round(len(filmed) / max(1, n), 2),
        "dropped_beats": len(allb) - len(filmed), "beats": len(allb),
        "expectation_scenes": sum(1 for b in filmed if "expectation" in b["checklist"]["delta_kinds"]),
        "distinct_intents_per_episode": round(sum(len({b["intent"] for b in p["beats"] if b["shoot"]}) for p in eps) / max(1, n), 2),
        "lint_issues": sum(len(p["lint"]) for p in eps),
        **{f"lint_{c}": sum(1 for p in eps for i in p["lint"] if i["code"] == c) for c in ("L1", "L2", "L3", "L4", "L5", "L8")},
        "chat_share": round(sum(p["lint_metrics"]["chat_beats"] for p in eps) / max(1, sum(p["lint_metrics"]["beats"] for p in eps)), 3),
        "same_line_twice": sum(p["lint_metrics"]["dup_lines"] for p in eps),
        "hard_days": sum(1 for plans in plans_by_seed for p in plans if p["hard"]),
        "hard_days_on_screen": sum(1 for p in eps if p["hard"] and p["hard_on_screen"]),
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
    s = {v: summarize(rows, v) for v in VARIANTS}
    (Path(a.out) / "summary.json").write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    keys = [k for k in s["v1"] if not isinstance(s["v1"][k], dict)]
    print(f"{'':32}" + "".join(f"{v:>12}" for v in VARIANTS))
    for k in keys:
        print(f"{k:32}" + "".join(f"{s[v][k]:>12}" for v in VARIANTS))
    print("question types (progress):", s["progress"]["question_types"], "(ab):", s["ab"]["question_types"], " dilemmas:", {k: sum(r["dilemmas"][k] for r in rows) for k in rows[0]["dilemmas"]})


if __name__ == "__main__":
    main()
