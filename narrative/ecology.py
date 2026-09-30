"""Does the world make stories by itself? Measures over a finished run (read-only).

event_diversity           distinct kinds of chosen acts
threads / long_threads    story threads; those spanning >= 3 days with >= 4 events
active_threads_per_day    threads that moved, averaged over days
thread_duration           mean days from first to last event (threads with >= 3 events)
cross_thread_rate         share of threads touching another thread
delayed_consequence_rate  share of chosen thread events caused by something a day or more earlier
information_asymmetry     share of threads with at least one belief the world does not support
relationship_flips        trust reversals per day (from one settled side to the other: world/helpers.trust_reversed)
seed_influence_rate       share of adopted seeds whose thread later has a chosen act
seed_direct_plot_rate     share of seed threads made only of rules, props and seeds (seed = plot: bad)
flat_day_ratio            days without a chosen act of weight >= 0.6, no trust flip and no exposure
goal_change_rate          goal changes per person per day (world/goals.py)
goal_transformations      goals that turned into other goals (recover -> expose -> revenge ...)
goal_crossings            chosen acts driven by a goal that an event of a *different* thread caused: thread A's
                          event changes B's goal, and B's goal moves another thread (causal crossing, not editing)
goal_thread_births        threads whose first chosen act was driven by such a goal
knowledge_gap_rate        share of threads with a knowledge question where someone believes the wrong thing or
                          it concerns someone who does not know (narrative/knowledge.py)
wrong_believers           people holding a wrong answer, summed over threads
seed_outcomes             each adopted seed, classified by its strongest effect:
                          thread_forming > misunderstood > delayed > indirect > ignored
"""
from __future__ import annotations

import json
import sqlite3
from statistics import mean

from narrative.knowledge import knowledge_of
from narrative.threads import derive_threads

EXPOSED = ("lie_exposed", "distortion_exposed", "concealment_exposed", "caught")


def _goal_measures(conn: sqlite3.Connection, threads, ev: dict, day_of: dict, days: int) -> dict:
    changes = [(i, json.loads(r["truth"])) for i, r in ev.items() if r["type"] == "goal_change"]
    people = conn.execute("SELECT COUNT(*) FROM people").fetchone()[0]
    in_thread: dict[int, set[str]] = {}
    for t in threads:
        for e in t.event_ids:
            in_thread.setdefault(e, set()).add(t.thread_id)
    crossings, births = 0, set()
    first_chosen = {t.thread_id: min(t.decision_event_ids) for t in threads if t.decision_event_ids}
    caused = {}  # goal id -> threads of the event that set it
    for i, t in changes:
        if t["to"] in ("formed", "transformed") and t.get("cause_event"):
            caused[t["goal"]] = in_thread.get(t["cause_event"], set())
    for i, r in ev.items():
        if r["trigger_type"] != "decision":
            continue
        reason = json.loads(r["truth"]).get("reason", "")
        if not reason.startswith("goal:"):
            continue
        origin = caused.get(reason[5:])
        if origin is None:
            continue
        here = in_thread.get(i, set())
        if here and not (here & origin):
            crossings += 1
            births |= {tid for tid in here if first_chosen.get(tid) == i}
    return {
        "goal_changes": len(changes),
        "goal_change_rate": round(len(changes) / (people * days), 3) if days else 0.0,
        "goal_transformations": sum(1 for _, t in changes if t["to"] == "transformed"),
        "goal_kinds_formed": sorted({t["kind"] for _, t in changes if t["to"] in ("formed", "transformed")}),
        "goal_crossings": crossings,
        "goal_thread_births": len(births),
    }


def _seed_outcomes(conn: sqlite3.Connection, threads, knowledge, ev: dict, day_of: dict) -> dict:
    wrong = {k.thread_id for k in knowledge if k.wrong}
    out = {"thread_forming": 0, "misunderstood": 0, "delayed": 0, "indirect": 0, "ignored": 0}
    for i, r in ev.items():
        if r["type"] != "seed":
            continue
        ext = json.loads(r["truth"])["external_event_id"]
        mine = [t for t in threads if ext in t.seed_origins]
        chosen = sorted(e for t in mine for e in t.decision_event_ids if e > i)
        if any(len([e for e in t.decision_event_ids if e > i]) >= 3 and t.last_day - day_of[i] >= 1 for t in mine):
            out["thread_forming"] += 1
        elif any(t.thread_id in wrong for t in mine):
            out["misunderstood"] += 1
        elif chosen and day_of[chosen[0]] - day_of[i] >= 1:
            out["delayed"] += 1
        elif chosen or _moved_behaviour(ev, day_of, i):
            out["indirect"] += 1
        else:
            out["ignored"] += 1
    return out


def _moved_behaviour(ev: dict, day_of: dict, seed_event: int) -> bool:
    """Crude: in the two days after a seed with no thread (a price rise, a power cut), more pressured choices
    (steal, take, lend, accuse, hostile words) than in the two days before."""
    d = day_of[seed_event]
    pressured = ("steal", "take", "lend", "accuse")

    def count(lo: int, hi: int) -> int:
        return sum(1 for i, r in ev.items() if r["trigger_type"] == "decision" and lo <= day_of[i] < hi and (
            r["type"] in pressured or json.loads(r["truth"]).get("tone") == "hostile"))
    return count(d, d + 2) > count(d - 2, d)


def measure(conn: sqlite3.Connection, days: int) -> dict:
    threads = derive_threads(conn)
    ev = {r["event_id"]: r for r in conn.execute("SELECT event_id, timestamp, type, trigger_type, importance, "
                                                   "parent_event_id, truth FROM events")}
    day_of = {i: r["timestamp"] // 1440 for i, r in ev.items()}
    chosen = [r for r in ev.values() if r["trigger_type"] == "decision"]
    per_day = []
    for d in range(days):
        per_day.append(sum(1 for t in threads if any(day_of[e] == d for e in t.event_ids)))
    delayed = total = 0
    for t in threads:
        for e in t.decision_event_ids:
            r = ev[e]
            causes = [r["parent_event_id"]] + [int(x) for x in json.loads(r["truth"]).get("depends_on", [])]
            causes = [c for c in causes if c is not None and c in ev]
            if not causes:
                continue
            total += 1
            delayed += any(day_of[e] - day_of[c] >= 1 for c in causes)
    flips = conn.execute("SELECT COUNT(*) FROM events WHERE json_extract(truth, '$.trust_flipped') = 1").fetchone()[0]
    seeds = [r for r in ev.values() if r["type"] == "seed"]
    seed_threads = [t for t in threads if t.seed_origins]
    influenced = {o for t in seed_threads if t.decision_event_ids for o in t.seed_origins}
    flat = 0
    for d in range(days):
        strong = any(day_of[r["event_id"]] == d and r["importance"] >= 0.6 for r in chosen)
        flip = conn.execute("SELECT 1 FROM events WHERE json_extract(truth, '$.trust_flipped') = 1 "
                            "AND timestamp / 1440 = ? LIMIT 1", (d,)).fetchone()
        exposed = any(day_of[i] == d and json.loads(r["truth"]).get("outcome") in EXPOSED for i, r in ev.items()
                      if r["type"] in ("confront", "accuse"))
        flat += not (strong or flip or exposed)
    long_threads = [t for t in threads if t.last_day - t.first_day >= 2 and len(t.event_ids) >= 4]
    goals = _goal_measures(conn, threads, ev, day_of, days)
    knowledge = [k for k in (knowledge_of(conn, t) for t in threads) if k is not None]
    outcomes = _seed_outcomes(conn, threads, knowledge, ev, day_of)
    multi = [t for t in threads if len(t.event_ids) >= 3]
    return {
        "days": days,
        "event_diversity": len({r["type"] for r in chosen}),
        "threads": len(threads),
        "long_threads": len(long_threads),
        "active_threads_per_day": round(mean(per_day), 2) if per_day else 0.0,
        "thread_duration": round(mean(t.last_day - t.first_day + 1 for t in multi), 2) if multi else 0.0,
        "cross_thread_rate": round(sum(1 for t in threads if t.cross_threads) / len(threads), 3) if threads else 0.0,
        "delayed_consequence_rate": round(delayed / total, 3) if total else 0.0,
        "information_asymmetry": round(sum(1 for t in threads if t.information_asymmetry) / len(threads), 3) if threads else 0.0,
        "relationship_flips_per_day": round(flips / days, 2),
        "seeds_adopted": len(seeds),
        "seed_influence_rate": round(len(influenced) / len(seeds), 3) if seeds else None,
        "seed_direct_plot_rate": round(sum(1 for t in seed_threads if not t.decision_event_ids) / len(seed_threads), 3)
        if seed_threads else None,
        "flat_day_ratio": round(flat / days, 3),
        **goals,
        "knowledge_questions": len(knowledge),
        "knowledge_gap_rate": round(sum(1 for k in knowledge if k.gap > 0) / len(knowledge), 3) if knowledge else 0.0,
        "wrong_believers": sum(len(k.wrong) for k in knowledge),
        "seed_outcomes": outcomes,
        "thread_kinds": {k: sum(1 for t in threads if t.kind == k) for k in ("item", "debt", "rumor", "feud")},
    }
