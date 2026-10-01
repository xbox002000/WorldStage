"""Drama gate: is there anything to watch? A few seeds, a few days, measured from world.db only (read-only).

    python drama_gate.py --days 5 --seeds 260934,3,55 --recipe town_spatial_v1 --out out/gates/drama_001
    python drama_gate.py --days 30 --without social.topics,life.work --out out/gates/life_off   # the same, minus packs

What it measures, per world and averaged:

  social        interpersonal events a day (talk, tell, confront, accuse, lend, give, steal, ...)
  conflict      clashes a day: cold or hostile words, accusations, confrontations, thefts
  scenes        exchanges: two people going back and forth (3 or more turns, each within 20 minutes of the last)
  longest       the longest exchange, in turns
  escalations   exchanges whose tone got worse along the way
  negative      share of person-days that end in a negative feeling (angry, hurt, ashamed, uneasy, ...)
  feelings      how many different feelings the cast went through
  trust flips   a relationship crossing from trust to distrust or back
  crowd         the most people in one place at once, against the seats and standing spots it has
  tension       the Dramaturgy analysis's potential tension per day (narrative/dramaturgy.py): early (days 0-13)
                against late (day 14 on) says whether the drama renews or runs out
  life          what people's own lives produced: goals to leave, demands, praise, searches, offers, resignations
  inner         the inner chain: relationships stuck at the ends (|trust| or |affection| >= 0.95), self-models formed
                (by kind), the median aggression, and outbursts (body.arousal)

Nothing here judges quality: it is a floor. A world that fails it has nothing a director could find.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOCIAL = ("talk", "tell", "confront", "accuse", "lend", "repay", "give", "steal", "challenge")
NEGATIVE = {"angry", "hurt", "ashamed", "uneasy", "scared", "embarrassed", "jealous", "sad"}
TONE_RANK = {"warm": 0, "neutral": 1, "cold": 2, "hostile": 3}
GAP = 20  # minutes between two turns of one exchange


def _pair(truth: dict) -> tuple | None:
    a, b = truth.get("actor"), truth.get("target") or truth.get("victim")
    return tuple(sorted((a, b))) if a and b and a != b else None


def _rank(kind: str, truth: dict) -> int:
    if kind == "talk":
        return TONE_RANK.get(truth.get("tone"), 1)
    return {"accuse": 3, "confront": 3, "steal": 3, "challenge": 3}.get(kind, 1)


def measure(conn: sqlite3.Connection) -> dict:
    rows = conn.execute("SELECT event_id, timestamp, type, location_id, truth FROM events ORDER BY event_id").fetchall()
    days = max(1, (max((r[1] for r in rows), default=0) // 1440) + 1)
    social = conflict = 0
    open_ex: dict[tuple, list] = {}
    exchanges: list[list] = []
    for eid, ts, kind, loc, truth in rows:
        if kind not in SOCIAL:
            continue
        t = json.loads(truth or "{}")
        social += 1
        rank = _rank(kind, t)
        conflict += rank >= 2 or kind in ("accuse", "confront", "steal")
        p = _pair(t)
        if p is None:
            continue
        ex = open_ex.get(p)
        if ex and ts - ex[-1][0] <= GAP:
            ex.append((ts, rank, eid))
        else:
            if ex:
                exchanges.append(ex)
            open_ex[p] = [(ts, rank, eid)]
    exchanges += list(open_ex.values())
    scenes = [x for x in exchanges if len(x) >= 3]
    escalations = sum(1 for x in scenes if max(r for _, r, _ in x[1:]) > x[0][1])

    # feelings: replay the emotion deltas; the feeling a person ends each day with
    emo = {r[0]: "calm" for r in conn.execute("SELECT id FROM people")}
    seen = Counter()
    ends = []
    deltas = defaultdict(list)
    for eid, pid, val in conn.execute("SELECT event_id, entity_id, new_value FROM event_deltas "
                                      "WHERE entity_type = 'person' AND field = 'emotion' ORDER BY delta_id"):
        deltas[eid].append((pid, json.loads(val) if val and val.startswith('"') else val))
    animals = {r[0] for r in conn.execute("SELECT person_id FROM personas WHERE json_extract(traits, '$.species') IS NOT NULL")}
    for eid, ts, kind, loc, truth in rows:
        for pid, val in deltas.get(eid, ()):
            emo[pid] = val
            seen[val] += 1
        if kind == "day_end":
            ends += [v for k, v in emo.items() if k not in animals]
    negative = sum(v in NEGATIVE for v in ends) / max(1, len(ends))

    flips = conn.execute("SELECT COUNT(*) FROM events WHERE json_extract(truth, '$.trust_flipped') = 1").fetchone()[0]

    # crowd: people in one place at once, from the location deltas
    moves = [(pid, *(json.loads(v) if v and v.startswith('"') else v for v in (old, new))) for pid, old, new in conn.execute(
        "SELECT entity_id, old_value, new_value FROM event_deltas WHERE entity_type = 'person' AND field = 'location_id' "
        "ORDER BY delta_id") if pid not in animals]
    start = {}
    for pid, o, _ in moves:
        start.setdefault(pid, o)  # where each person was before their first move
    occ = Counter(v for v in start.values() if v)
    peak = Counter(occ)
    for pid, o, n in moves:
        if o:
            occ[o] -= 1
        occ[n] += 1
        peak[n] = max(peak[n], occ[n])
    from narrative.layouts import LAYOUTS
    room = {}
    for loc, lay in LAYOUTS.items():
        seats = sum(1 for k in lay["anchors"] if ".seat" in k)
        room[loc] = {"peak": peak.get(loc, 0), "seats": seats, "spots": seats + len(lay.get("stand", []))}
    from narrative.dramaturgy import analyse
    t_an = time.perf_counter()
    rep = analyse(conn)
    analyse_ms = round((time.perf_counter() - t_an) * 1000)
    curve, curve_all = rep["curve"], rep["curve_all"]  # v1 (frozen) and v1 + the domain packs' situations
    early, late = curve[:14], curve[14:]
    life = dict(Counter(r[0] for r in conn.execute(
        "SELECT type FROM events WHERE type IN ('overtime', 'praise', 'job_search', 'job_offer', 'resign', 'decline_offer')")))
    life["leave_job_goals"] = conn.execute("SELECT COUNT(*) FROM events WHERE type = 'goal_change' AND "
                                           "json_extract(truth, '$.kind') = 'leave_job' AND json_extract(truth, '$.to') = 'formed'").fetchone()[0]
    life["goals_formed"] = conn.execute("SELECT COUNT(*) FROM events WHERE type = 'goal_change' AND "
                                        "json_extract(truth, '$.to') IN ('formed', 'transformed')").fetchone()[0]
    people = [r[0] for r in conn.execute("SELECT id FROM people") if r[0] not in animals]
    rels = [(t, a) for x, y, t, a in conn.execute("SELECT actor_id, target_id, trust, affection FROM relationships")
            if x != y and x not in animals and y not in animals]
    aggression = sorted(r[0] for r in conn.execute("SELECT value FROM world_vars WHERE key LIKE 'psy.%.aggression'"))
    inner = {
        "stuck_trust": round(sum(abs(r[0]) >= 0.95 for r in rels) / max(1, len(rels)), 3),
        "stuck_affection": round(sum(abs(r[1]) >= 0.95 for r in rels) / max(1, len(rels)), 3),
        "self_models": dict(Counter(k.split(".")[-1] for k, v in conn.execute(
            "SELECT key, value FROM world_vars WHERE key LIKE 'psy.%.self.%'") if v >= 0.5)),
        "aggression_median": round(aggression[len(aggression) // 2], 3) if aggression else None,
        "outbursts": conn.execute("SELECT COUNT(*) FROM events WHERE type IN ('shove', 'strike', 'smash', 'break_down')").fetchone()[0],
    }
    return {
        "inner": inner,
        "metric": rep["metric"], "analyse_ms": analyse_ms,
        "tension_early": round(sum(early) / max(1, len(early)), 2),
        "tension_late": round(sum(late) / len(late), 2) if late else None, "tension": curve,
        "tension_all_early": round(sum(curve_all[:14]) / max(1, len(curve_all[:14])), 2),
        "tension_all_late": round(sum(curve_all[14:]) / len(curve_all[14:]), 2) if curve_all[14:] else None,
        "tension_all": curve_all, "life": life,
        "days": days, "social_per_day": round(social / days, 1), "conflict_per_day": round(conflict / days, 2),
        "scenes_per_day": round(len(scenes) / days, 2), "longest_exchange": max((len(x) for x in exchanges), default=0),
        "escalations": escalations, "negative_day_ends": round(negative, 3), "feelings": sorted(seen),
        "trust_flips": flips, "crowd": room,
    }


def _derived(recipe: str, without: str) -> str:
    """A recipe minus some primitives, registered at run time (for comparisons); returns its id."""
    if not without:
        return recipe
    from dataclasses import replace
    from world.recipes import load_recipe, register_recipe
    drop = set(without.split(","))
    r = load_recipe(recipe)
    rid = f"{recipe}-minus-{'-'.join(sorted(drop))}"
    register_recipe(replace(r, recipe_id=rid, base=[p for p in r.base if p not in drop],
                            pillars=[p for p in r.pillars if p not in drop], accents=[p for p in r.accents if p not in drop]))
    return rid


def one(seed: int, recipe: str, days: int, out: str, without: str = "") -> dict:
    sys.path.insert(0, str(ROOT))
    from agent.volition import VolitionDecider
    from world.db import connect, init_db
    from world.seed import build_world
    from world.simulation import Simulation
    from world.db import save_to
    db = Path(out) / f"world_{seed}.db"
    conn = connect()  # simulated in memory; kept as a file at the end (save_to)
    init_db(conn, seed)
    recipe = _derived(recipe, without)
    build_world(conn, seed, recipe)
    d = VolitionDecider(seed)
    t0 = time.perf_counter()
    sim = Simulation(conn, d, d, set(), feed="synthetic_v1")
    sim.run(days)
    seconds = round(time.perf_counter() - t0, 1)
    t1 = time.perf_counter()
    m = measure(conn)
    m.update(seed=seed, seconds=seconds, measure_seconds=round(time.perf_counter() - t1, 1), profile=sim.profile.report())
    save_to(conn, db)
    return m


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=5)
    ap.add_argument("--seeds", default="260934,3,55")
    ap.add_argument("--recipe", default="town_spatial_v1")
    ap.add_argument("--out", default="out/gates/drama")
    ap.add_argument("--db", help="measure an existing world instead")
    ap.add_argument("--without", default="", help="primitives to leave out of the recipe (comma-separated)")
    a = ap.parse_args()
    if a.db:
        print(json.dumps(measure(sqlite3.connect(a.db)), ensure_ascii=False, indent=1))
        return
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    seeds = [int(s) for s in a.seeds.split(",")]
    with ProcessPoolExecutor(len(seeds)) as ex:
        runs = list(ex.map(one, seeds, [a.recipe] * len(seeds), [a.days] * len(seeds), [str(out)] * len(seeds),
                           [a.without] * len(seeds)))
    keys = ("social_per_day", "conflict_per_day", "scenes_per_day", "longest_exchange", "escalations",
            "negative_day_ends", "trust_flips", "seconds", "tension_early")
    lates = [r["tension_late"] for r in runs if r["tension_late"] is not None]
    summary = {k: round(sum(r[k] for r in runs) / len(runs), 3) for k in keys}
    summary["tension_late"] = round(sum(lates) / len(lates), 3) if lates else None
    summary["life"] = {k: sum(r["life"].get(k, 0) for r in runs) for k in sorted({k for r in runs for k in r["life"]})}
    summary["inner"] = {
        "stuck_trust": round(sum(r["inner"]["stuck_trust"] for r in runs) / len(runs), 3),
        "stuck_affection": round(sum(r["inner"]["stuck_affection"] for r in runs) / len(runs), 3),
        "self_models": dict(sum((Counter(r["inner"]["self_models"]) for r in runs), Counter())),
        "aggression_median": [r["inner"]["aggression_median"] for r in runs],
        "outbursts": [r["inner"]["outbursts"] for r in runs]}
    summary["feelings"] = sorted({f for r in runs for f in r["feelings"]})
    summary["crowd"] = {loc: {"peak": max(r["crowd"][loc]["peak"] for r in runs), "seats": runs[0]["crowd"][loc]["seats"],
                              "spots": runs[0]["crowd"][loc]["spots"]} for loc in runs[0]["crowd"]}
    report = {"recipe": a.recipe, "without": a.without, "days": a.days, "seeds": seeds, "summary": summary, "runs": runs}
    (out / "drama.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
