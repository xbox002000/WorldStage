"""Persona probe: what would each person do in the same circumstance? Exact probabilities, not samples.

    python persona_probe.py --days 0,20 --seeds 3,55,260934

Counting what people happened to do in a month measures their luck as much as their character: in 20 days someone is
caught in the wrong two or three times (cross_domain.py could not tell apology from noise). A probe puts everyone in
the same standard circumstances instead, on a throwaway copy of their world, and reads the rule agent's own
probabilities for each answer (the softmax over its scores), with no draw:

  gossip   they hold something damaging about a third person, and someone who does not know it is with them:
           how likely are they to pass it on?
  apology  someone catches them in the wrong, to their face: how likely are they to apologise?
  defend   someone wrongly accuses them: how likely are they to hit back or deny?
  accuse   they believe someone deceived them, and that person is with them: how likely are they to accuse?

The same people (the town's genomes) are probed in the town and in the jianghu, at day 0 and after N days of life.
Across people, a disposition should rank them alike in both worlds (Spearman, per probe); after a life, the same
probe shows how far each has moved.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WORLDS = {"town": "town_life_v1", "jianghu": "town_in_jianghu_v1"}
PROBES = ("gossip", "apology", "defend", "accuse")


def _copy(conn):
    from world.db import connect
    mem = connect()
    conn.backup(mem)
    return mem


def _probs(scored: list, temperature: float) -> list[tuple[float, object]]:
    if not scored:
        return []
    top = max(s for s, _ in scored)
    w = [math.exp((s - top) / temperature) for s, _ in scored]
    total = sum(w)
    return [(x / total, it) for x, (_, it) in zip(w, scored)]


def _setup(c, now: int, place: str, people: list[str], memories=(), claims=(), truth_event=None, importance: float = 0.0):
    from world.events import Change, EventSpec, apply_event
    ch = [Change("person", p, "location_id", value=place) for p in people
          if c.execute("SELECT location_id FROM people WHERE id = ?", (p,)).fetchone()[0] != place]
    apply_event(c, EventSpec(timestamp=now, type="setup", trigger_type="rule", location_id=place, changes=ch,
                             importance=importance, memories=list(memories), claims=list(claims)))
    if truth_event is not None:
        return apply_event(c, truth_event)
    return None


def probe(conn, seed: int) -> dict[str, dict[str, float]]:
    """Each person's probabilities in the standard circumstances (on copies: the world is untouched)."""
    sys.path.insert(0, str(ROOT))
    from agent.reply import TEMPERATURE as REPLY_T, Replier
    from agent.volition import TEMPERATURE as VOLITION_T, VolitionDecider
    from contracts.claim import Claim
    from world.claims import describe_claim, labels
    from world.events import ClaimSpec, EventSpec, MemorySpec
    people = [r[0] for r in conn.execute("SELECT person_id FROM character_profiles ORDER BY person_id")]
    place = conn.execute("SELECT id FROM locations WHERE tags LIKE '%\"social\"%' ORDER BY id LIMIT 1").fetchone()[0]
    now = (conn.execute("SELECT COALESCE(MAX(timestamp), 0) FROM events").fetchone()[0] // 1440 + 1) * 1440 + 600
    out: dict[str, dict[str, float]] = {}
    for i, p in enumerate(people):
        other = people[(i + 1) % len(people)]
        third = people[(i + 2) % len(people)]
        fourth = people[(i + 3) % len(people)]
        res = {}
        # gossip: p knows third deceived fourth; other does not
        c = _copy(conn)
        claim = Claim(third, "deceive", fourth)
        text = describe_claim(claim, labels(c))
        _setup(c, now, place, [p, other], memories=[MemorySpec(p, text, 0.9, claim=claim)], claims=[ClaimSpec(claim)],
               importance=0.95)  # a grave thing: it must rank among the few one would pass on (tellable keeps 4)
        probs = _probs(VolitionDecider(seed).scored(c, p, now + 1), VOLITION_T)
        res["gossip"] = round(sum(x for x, it in probs if it is not None and it.action == "tell" and it.claim_id is not None
                                  and c.execute("SELECT subject FROM claims WHERE claim_id = ?", (it.claim_id,)).fetchone()[0] == third), 4)
        # accuse: p believes other deceived them, other is here
        c = _copy(conn)
        claim = Claim(other, "deceive", p)
        _setup(c, now, place, [p, other], memories=[MemorySpec(p, describe_claim(claim, labels(c)), 0.8, claim=claim)],
               claims=[ClaimSpec(claim)])
        probs = _probs(VolitionDecider(seed).scored(c, p, now + 1), VOLITION_T)
        res["accuse"] = round(sum(x for x, it in probs if it is not None and it.action == "accuse" and it.target == other), 4)
        # apology / defend: other confronts p, caught in the wrong / wrongly accused
        for key, outcome, want in (("apology", "caught", ("apologize",)), ("defend", "false", ("retort", "deny"))):
            c = _copy(conn)
            eid = _setup(c, now, place, [p, other], truth_event=EventSpec(
                timestamp=now, type="accuse", trigger_type="decision", location_id=place, importance=0.9,
                truth={"actor": other, "target": p, "outcome": outcome}, participants=[(other, "actor"), (p, "target")]))
            row = c.execute("SELECT * FROM events WHERE event_id = ?", (eid,)).fetchone()
            probs = _probs(Replier(seed).scored(c, row, 1, now) or [], REPLY_T)
            res[key] = round(sum(x for x, it in probs if it is not None and (it.reason or "").split(":")[-1] in want), 4)
        out[p] = res
    return out


def one(world: str, seed: int, days: int) -> dict:
    sys.path.insert(0, str(ROOT))
    from agent.volition import VolitionDecider
    from world.db import connect, init_db
    from world.seed import build_world
    from world.simulation import Simulation
    conn = connect()
    init_db(conn, seed)
    build_world(conn, seed, WORLDS[world])
    if days:
        d = VolitionDecider(seed)
        Simulation(conn, d, d, set(), feed="synthetic_v1" if world == "town" else None).run(days)
    return {"world": world, "seed": seed, "day": days, "probe": probe(conn, seed)}


def main() -> None:
    from cross_domain import spearman
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", default="0,20")
    ap.add_argument("--seeds", default="3,55,260934")
    ap.add_argument("--out", default="out/persona_probe")
    a = ap.parse_args()
    days = [int(x) for x in a.days.split(",")]
    seeds = [int(s) for s in a.seeds.split(",")]
    jobs = [(w, s, d) for d in days for s in seeds for w in WORLDS]
    with ProcessPoolExecutor(min(8, len(jobs))) as ex:
        runs = list(ex.map(one, *zip(*jobs)))
    by = {(r["world"], r["seed"], r["day"]): r["probe"] for r in runs}
    report = {"seeds": seeds, "days": days, "rank_correlation": {}, "runs": runs}
    sys.stdout.reconfigure(encoding="utf-8")
    for d in days:
        rho = {}
        for k in PROBES:
            vals = []
            for s in seeds:
                a_, b_ = by[("town", s, d)], by[("jianghu", s, d)]
                ppl = sorted(set(a_) & set(b_))
                vals.append(spearman([a_[p][k] for p in ppl], [b_[p][k] for p in ppl]))
            rho[k] = round(sum(vals) / len(vals), 3)
        report["rank_correlation"][f"day_{d}"] = rho
        print(f"day {d}: town vs jianghu, Spearman per probe:", rho)
    Path(a.out).mkdir(parents=True, exist_ok=True)
    (Path(a.out) / "persona_probe.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
