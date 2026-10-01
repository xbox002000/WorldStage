"""Producer on / off: what does the showrunner add, beyond what the world makes of itself?

    python producer_lab.py --days 28 --seeds 3,55,260934 --out out/producer_lab

The same genomes, the same recipe (jianghu_story_v1), the same seed, the same model, the same start. Only the producer differs:

  off      nobody arranges anything (what the world does alone)
  random   the control: the same kinds of opportunity on the same days at the same cost, aimed at nobody in particular
  full     the showrunner as designed
  stage    only the occasions (gatherings, vacancies)         \\
  cast     only the parts                                      > what each kind of opportunity is worth by itself
  parcel   only the parcels                                   /

For each branch it reports what the story got (narrative/payoff.py: how many payoffs, how much of them was earned, how fairly they
were shared), the frozen tension measure (dramaturgy_metric_v1), how much the world did (events, turning points, relationship
events), how far people ended up from their un-produced selves, and what it cost. The numbers that matter:

  creative_yield   (earned payoff of the branch - earned payoff with the producer off) / intervention cost: how much more *earned*
                   story one unit of intervention bought. Not how many more events.
  aim              the same, against `random`: how much of the effect is in choosing who, not in doing something
  own_share        earned / base: the share of the payoff that the people made themselves (agency attribution)
  stuffing         events with the producer / events without: an index that rises because the world is crowded and not because
                   anything is better would show here

Producer 2 (producer/director.py) adds strategies that are compared in pairs, seed by seed, with a bootstrap interval over seeds:

  greedy      the director as designed             matched    the same, but a story drawn at random from those the world is making
  blind       the same, a random pair of fighters  aggressive greedy without the pacing (never keeps still)
  unlimited   greedy without the week's budget
  lookahead   greedy that imagines the next days (copies of the world under other luck) before it decides, and may decide to do nothing

Differences are reported as mean (90% interval over seeds); "shown" means the interval's lower end is above zero, and nothing weaker
is called shown. `episodes` follow each story the director took up for ten days: was it played (the bout, the courtship, the vote
took place), and did the protagonist have their moment, against the same person's same ten days in the world with no producer.

This only records. Nothing the producer does is learnt from it (yet): there are too few payoffs in a month to learn from, and a
producer that learns from them would learn to hand them over.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent
V1 = ("random", "full", "stage", "cast", "parcel")
V2 = ("greedy", "portfolio", "lookahead", "matched", "blind", "aggressive", "unlimited")
STRATEGIES = ("off",) + V1 + V2
EPISODE_DAYS = 10
PAIRS = (("portfolio", "off"), ("portfolio", "matched"), ("portfolio", "greedy"), ("greedy", "off"), ("matched", "off"), ("blind", "off"), ("greedy", "matched"), ("greedy", "blind"), ("matched", "blind"),
         ("aggressive", "greedy"), ("unlimited", "greedy"), ("lookahead", "greedy"), ("lookahead", "off"), ("lookahead", "matched"), ("full", "off"), ("greedy", "full"))
TURNING = ("breakthrough", "succession", "found_faction", "defect", "confession", "break_up", "duel")
RELATION_EVENTS = ("flirt", "confession", "date", "break_up", "recruit", "defect", "campaign", "succession")


RECIPE = "jianghu_story_v1"


def run_branch(seed: int, strategy: str, days: int, recipe: str = RECIPE) -> dict:
    sys.path.insert(0, str(ROOT))
    from agent.volition import VolitionDecider
    from drama_gate import measure
    from narrative import novelty, payoff
    from persona_lab import TRAITS, VALUES, _life
    from producer.showrunner import Showrunner
    from world.db import connect, init_db
    from world.seed import build_world
    from world.simulation import Simulation
    conn = connect()
    init_db(conn, seed)
    build_world(conn, seed, recipe)
    d = VolitionDecider(seed)
    if strategy == "off":
        sr = None
    elif strategy in V2:
        from producer.director import Director
        sr = Director(strategy, seed)
    else:
        sr = Showrunner(strategy, seed)
    Simulation(conn, d, d, set(), feed="synthetic_v1", producer=sr).run(days)
    found = payoff.payoffs(conn)
    ledger = sr.ledger.entries if sr else []
    marks = ",".join("?" * len(TURNING))
    rel_marks = ",".join("?" * len(RELATION_EVENTS))
    m = measure(conn)
    return {
        "seed": seed, "strategy": strategy, "payoff": payoff.summary(conn, found), "payoffs": found,
        "tension_v1": round(sum(m["tension"]) / len(m["tension"]), 3) if m.get("tension") else None, "events": conn.execute("SELECT COUNT(*) FROM events").fetchone()[0],
        "decisions": conn.execute("SELECT COUNT(*) FROM events WHERE trigger_type = 'decision'").fetchone()[0],
        "turning_points": conn.execute(f"SELECT COUNT(*) FROM events WHERE type IN ({marks})", TURNING).fetchone()[0],
        "relationship_events": conn.execute(f"SELECT COUNT(*) FROM events WHERE type IN ({rel_marks})", RELATION_EVENTS).fetchone()[0],
        "cost": sum(e["budget_cost"] for e in ledger if e["admitted"]),
        "admitted": sum(1 for e in ledger if e["admitted"]), "refused": sum(1 for e in ledger if not e["admitted"]),
        "by_type": {t: sum(e["budget_cost"] for e in ledger if e["admitted"] and e["type"] == t) for t in sorted({e["type"] for e in ledger})},
        "life": _life(conn)["people"], "traits": TRAITS, "values": VALUES,
        "director": list(getattr(getattr(sr, "ledger", None), "decisions", [])), "episodes": episodes(conn, sr, found),
        "calibration": calibration(sr, found), "novel": novelty.summary(found),
        "threads": dict(Counter(t.status for t in sr.threads.by_id.values())) if hasattr(sr, "threads") else {},
    }


def episodes(conn, sr, found: list[dict]) -> list[dict]:
    """Each story the director took up, followed for EPISODE_DAYS from the day it first acted: was it played, did the hero have their moment."""
    if not hasattr(sr, "threads"):
        return []
    first: dict[str, dict] = {}
    for d in sr.ledger.decisions:
        if d["action"] == "intervene" and d["opportunity"] not in first:
            first[d["opportunity"]] = d
    out = []
    for d in first.values():
        lo, hi = d["day"] * 1440, (d["day"] + EPISODE_DAYS) * 1440
        h, others = d["protagonist"], d["others"]
        rows = [(r["type"], json.loads(r["truth"])) for r in conn.execute(
            "SELECT type, truth FROM events WHERE timestamp >= ? AND timestamp < ? AND type IN ('duel', 'flirt', 'confession', 'succession')", (lo, hi))]
        if d["kind"] == "reversal":
            played = any(t == "duel" and h in (x.get("winner"), x.get("loser")) for t, x in rows)
        elif d["kind"] == "triangle":
            played = any(t in ("flirt", "confession") and x.get("actor") in [h, *others] for t, x in rows)
        else:
            played = any(t == "succession" for t, _ in rows)
        # a succession is the contest itself, so its moment is the vote's (anybody's) payoff; the others are the hero's own
        out.append({"day": d["day"], "kind": d["kind"], "protagonist": h, "played": played,
                    "moment": any((p["protagonist"] == h or (d["kind"] == "succession" and p["kind"] == "succession")) and d["day"] <= p["day"] < d["day"] + EPISODE_DAYS
                                  for p in found)})
    return out


def calibration(sr, found: list[dict]) -> list[dict]:
    """Where the director imagined (lookahead): what it said the chance of a payoff in the next days was, against what happened."""
    from producer.forecast import HORIZON
    out = []
    for d in getattr(getattr(sr, "ledger", None), "decisions", []):
        f = d.get("imagined")
        if f:
            out.append({"day": d["day"], "p_payoff": f["forecast"]["p_payoff"], "p_silence": f["silence"]["p_payoff"],
                        "got": any(d["day"] <= p["day"] < d["day"] + HORIZON for p in found)})
    return out


def _mean(xs) -> float:
    xs = list(xs)
    return round(sum(xs) / len(xs), 4) if xs else 0.0


def divergence(a: dict, b: dict) -> float:
    """How far apart the people of two branches ended up (traits and values, mean absolute difference)."""
    pa, pb = a["life"], b["life"]
    if pa is None or pb is None:
        return 0.0   # (a report rebuilt from saved runs has no inner lives)
    return _mean(abs(pb[p]["traits"][k] - pa[p]["traits"][k]) for p in pa for k in a["traits"]) + \
        _mean(abs(pb[p]["values"][k] - pa[p]["values"][k]) for p in pa for k in a["values"])


def bootstrap(diffs: list[float], n: int = 2000) -> tuple[float, float, float]:
    """Mean of paired differences and its 90% interval, resampling the seeds."""
    import random
    r = random.Random(0)
    m = sum(diffs) / len(diffs)
    means = sorted(sum(r.choice(diffs) for _ in diffs) / len(diffs) for _ in range(n))
    return round(m, 4), round(means[int(0.05 * n)], 4), round(means[int(0.95 * n) - 1], 4)


def _hero_rate(by, seeds, strategy) -> tuple[float, float, float]:
    """(share of followed stories in which the hero had their moment, the same person's same days with no producer, share played)."""
    eps = [(s, e) for s in seeds for e in by[(s, strategy)]["episodes"]]
    if not eps:
        return 0.0, 0.0, 0.0
    got = sum(e["moment"] for _, e in eps)
    base = sum(any((p["protagonist"] == e["protagonist"] or (e["kind"] == "succession" and p["kind"] == "succession")) and e["day"] <= p["day"] < e["day"] + EPISODE_DAYS
                   for p in by[(s, "off")]["payoffs"]) for s, e in eps)
    return round(got / len(eps), 3), round(base / len(eps), 3), round(sum(e["played"] for _, e in eps) / len(eps), 3)


METRICS = {"payoffs": lambda r: r["payoff"]["count"], "earned": lambda r: r["payoff"]["earned"], "earned_payoffs": lambda r: r["payoff"]["earned_payoffs"],
           "tension_v1": lambda r: r["tension_v1"] or 0.0, "turning_points": lambda r: r["turning_points"], "events": lambda r: r["events"],
           "cost": lambda r: r["cost"], "earned_novel": lambda r: r["novel"]["earned_novel"], "mean_novelty": lambda r: r["novel"]["mean_novelty"],
           "mechanics": lambda r: r["novel"]["mechanics"]}


def paired(by, seeds, a: str, b: str) -> dict:
    out = {name: bootstrap([f(by[(s, a)]) - f(by[(s, b)]) for s in seeds]) for name, f in METRICS.items()}
    out["shown"] = [k for k in ("payoffs", "earned", "earned_payoffs", "earned_novel") if out[k][1] > 0]
    return out


def compare(off: dict, rnd: dict, br: dict) -> dict:
    cost = br["cost"]
    earned, base_e, rnd_e = br["payoff"]["earned"], off["payoff"]["earned"], rnd["payoff"]["earned"]
    return {
        "payoffs": [off["payoff"]["count"], rnd["payoff"]["count"], br["payoff"]["count"]],
        "earned": [base_e, rnd_e, earned], "earned_payoffs": [off["payoff"]["earned_payoffs"], rnd["payoff"]["earned_payoffs"], br["payoff"]["earned_payoffs"]],
        "own_share": br["payoff"]["earned_share"], "mean_agency": br["payoff"]["mean_agency"], "fairness_gini": br["payoff"]["fairness_gini"],
        "protagonists": br["payoff"]["protagonists"], "tension_v1": [off["tension_v1"], rnd["tension_v1"], br["tension_v1"]],
        "turning_points": [off["turning_points"], rnd["turning_points"], br["turning_points"]],
        "relationship_events": [off["relationship_events"], rnd["relationship_events"], br["relationship_events"]],
        "cost": cost, "creative_yield": round((earned - base_e) / cost, 4) if cost else 0.0,
        "aim": round((earned - rnd_e) / cost, 4) if cost else 0.0,
        "stuffing": round(br["events"] / off["events"], 3), "decisions_share": round(br["decisions"] / br["events"], 3),
        "divergence_from_off": round(divergence(off, br), 4), "admitted": br["admitted"], "refused": br["refused"], "cost_by_type": br["by_type"],
    }


def average(per_seed: list[dict]) -> dict:
    first = per_seed[0]
    if isinstance(first, dict):
        keys = sorted({k for s in per_seed for k in s})  # a key some seeds lack (a kind of opportunity not used there) counts 0
        return {k: average([s.get(k, 0) for s in per_seed]) for k in keys}
    if isinstance(first, (int, float)) and not isinstance(first, bool):
        return round(sum(per_seed) / len(per_seed), 4)
    if isinstance(first, list) and first and all(isinstance(x, (int, float)) or x is None for x in first):
        return [None if any(s[i] is None for s in per_seed) else round(sum(s[i] for s in per_seed) / len(per_seed), 3) for i in range(len(first))]
    return first


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=28)
    ap.add_argument("--seeds", default="3,55,260934")
    ap.add_argument("--strategies", default=",".join(STRATEGIES))
    ap.add_argument("--out", default="out/producer_lab")
    ap.add_argument("--recipe", default=RECIPE)
    ap.add_argument("--from-runs", default="", help="rebuild the report from a saved runs.json instead of running")
    a = ap.parse_args()
    seeds = [int(s) for s in a.seeds.split(",")]
    strategies = [s for s in a.strategies.split(",") if s]
    if "off" not in strategies:
        strategies.insert(0, "off")
    if any(x in strategies for x in V1) and "random" not in strategies:
        strategies.insert(1, "random")
    jobs = [(s, st, a.days, a.recipe) for s in seeds for st in strategies]
    jobs.sort(key=lambda j: j[1] != "lookahead")   # the slow ones first, so that they are not the tail
    if a.from_runs:
        runs = json.loads(Path(a.from_runs).read_text(encoding="utf-8"))
        for r in runs:
            if isinstance(r.get("decisions"), list):   # (a first version saved the director's record under the key of a count)
                r["director"], r["decisions"] = r["decisions"], 0
            r.setdefault("director", [])
            r.setdefault("life", None)
    else:
        with ProcessPoolExecutor(min(8, len(jobs))) as ex:
            runs = list(ex.map(run_branch, *zip(*jobs)))
    by = {(r["seed"], r["strategy"]): r for r in runs}
    Path(a.out).mkdir(parents=True, exist_ok=True)  # the runs first: a slip in the arithmetic below must not lose them
    (Path(a.out) / "runs.json").write_text(json.dumps([{k: v for k, v in r.items() if k not in ("life", "traits", "values")} for r in runs],
                                                      ensure_ascii=False), encoding="utf-8")
    report: dict = {"metric": "payoff_metric_v0.1", "days": a.days, "seeds": seeds, "branches": {}, "off": {}}
    for st in strategies:
        if st in ("off", "random") or st in V2:
            continue
        report["branches"][st] = average([compare(by[(s, "off")], by[(s, "random")], by[(s, st)]) for s in seeds])
    report["off"] = average([{"payoffs": by[(s, "off")]["payoff"]["count"], "earned": by[(s, "off")]["payoff"]["earned"],
                              "tension_v1": by[(s, "off")]["tension_v1"], "turning_points": by[(s, "off")]["turning_points"],
                              "events": by[(s, "off")]["events"]} for s in seeds])
    if "random" in strategies:
        report["random"] = average([{"payoffs": by[(s, "random")]["payoff"]["count"], "earned": by[(s, "random")]["payoff"]["earned"],
                                     "cost": by[(s, "random")]["cost"]} for s in seeds])
    report["paired"] = {f"{a} - {b}": paired(by, seeds, a, b) for a, b in PAIRS if a in strategies and b in strategies}
    report["episodes"] = {st: dict(zip(("moment", "moment_without_producer", "played"), _hero_rate(by, seeds, st))) for st in strategies if st in V2}
    report["spend"] = {st: {"cost": _mean(by[(s, st)]["cost"] for s in seeds), "admitted": _mean(by[(s, st)]["admitted"] for s in seeds),
                            "silences": _mean(sum(1 for d in by[(s, st)]["director"] if d["action"] == "silence") for s in seeds),
                            "own_share": _mean(by[(s, st)]["payoff"]["earned_share"] for s in seeds),
                            "stuffing": _mean(by[(s, st)]["events"] / by[(s, "off")]["events"] for s in seeds),
                            "fairness_gini": _mean(by[(s, st)]["payoff"]["fairness_gini"] for s in seeds),
                            "earned_novel": _mean(by[(s, st)]["novel"]["earned_novel"] for s in seeds),
                            "threads": {k: _mean(by[(s, st)]["threads"].get(k, 0) for s in seeds) for k in ("active", "completed", "failed", "dormant", "abandoned")},
                            "payoff_kinds": {k: _mean(by[(s, st)]["payoff"]["by_kind"].get(k, 0) for s in seeds) for k in ("face_slap", "chosen", "succession")}}
                       for st in strategies if st in V2}
    Path(a.out).mkdir(parents=True, exist_ok=True)
    slim = [{k: v for k, v in r.items() if k not in ("life", "traits", "values")} for r in runs]
    (Path(a.out) / "opportunities.jsonl").write_text("\n".join(json.dumps({"seed": r["seed"], "strategy": r["strategy"], **d}, ensure_ascii=False)
                                                              for r in runs for d in r["director"]), encoding="utf-8")
    cal = [c for st in ("lookahead",) for s in seeds if (s, st) in by for c in by[(s, st)]["calibration"]]
    report["calibration"] = cal
    (Path(a.out) / "producer_lab.json").write_text(json.dumps({**report, "runs": slim}, ensure_ascii=False, indent=1), encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    print(f"producer lab: {a.days} days, seeds {seeds}")
    print("producer off:", report["off"])
    if "random" in report:
        print("random control:", report["random"])
    for k, r in report["paired"].items():
        print(f"\n[{k}]  " + "  ".join(f"{m} {v[0]:+.2f} ({v[1]:+.2f}..{v[2]:+.2f})" for m, v in r.items() if m != "shown") + f"   SHOWN: {r['shown']}")
    if cal:
        print(f"\nlookahead calibration over {len(cal)} decisions: said P(payoff) {sum(c['p_payoff'] for c in cal) / len(cal):.2f} "
              f"(without it {sum(c['p_silence'] for c in cal) / len(cal):.2f}), what followed {sum(c['got'] for c in cal) / len(cal):.2f}")
    for st, e in report["episodes"].items():
        print(f"episodes [{st}] {e}   spend {report['spend'][st]}")
    for st, r in report["branches"].items():
        print(f"\n[{st}]  payoffs (off, random, this) {r['payoffs']}  earned {r['earned']}  tension v1 {r['tension_v1']}")
        print(f"  cost {r['cost']} (admitted {r['admitted']}, refused {r['refused']})  creative_yield {r['creative_yield']}  aim {r['aim']}")
        print(f"  own_share {r['own_share']}  mean_agency {r['mean_agency']}  stuffing {r['stuffing']}  decisions_share {r['decisions_share']}  "
              f"turning points {r['turning_points']}  relationship events {r['relationship_events']}  divergence {r['divergence_from_off']}")


if __name__ == "__main__":
    main()
