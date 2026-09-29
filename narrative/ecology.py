"""Does the world make stories by itself? Measures over a finished run (read-only).

event_diversity           distinct kinds of chosen acts
threads / long_threads    story threads; those spanning >= 3 days with >= 4 events
active_threads_per_day    threads that moved, averaged over days
thread_duration           mean days from first to last event (threads with >= 3 events)
cross_thread_rate         share of threads touching another thread
delayed_consequence_rate  share of chosen thread events caused by something a day or more earlier
information_asymmetry     share of threads with at least one belief the world does not support
relationship_flips        trust sign changes per day
seed_influence_rate       share of adopted seeds whose thread later has a chosen act
seed_direct_plot_rate     share of seed threads made only of rules, props and seeds (seed = plot: bad)
flat_day_ratio            days without a chosen act of weight >= 0.6, no trust flip and no exposure
goal_change_rate          goals never change yet (no mechanic): reported so the gap stays visible
"""
from __future__ import annotations

import json
import sqlite3
from statistics import mean

from narrative.threads import derive_threads

EXPOSED = ("lie_exposed", "distortion_exposed", "concealment_exposed", "caught")


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
    flips = conn.execute("SELECT COUNT(*) FROM event_deltas WHERE entity_type = 'relationship' AND field = 'trust' "
                         "AND old_value * new_value < 0").fetchone()[0]
    seeds = [r for r in ev.values() if r["type"] == "seed"]
    seed_threads = [t for t in threads if t.seed_origins]
    influenced = {o for t in seed_threads if t.decision_event_ids for o in t.seed_origins}
    flat = 0
    for d in range(days):
        strong = any(day_of[r["event_id"]] == d and r["importance"] >= 0.6 for r in chosen)
        flip = conn.execute("SELECT 1 FROM event_deltas x JOIN events e USING (event_id) WHERE x.field = 'trust' "
                            "AND x.old_value * x.new_value < 0 AND e.timestamp / 1440 = ? LIMIT 1", (d,)).fetchone()
        exposed = any(day_of[i] == d and json.loads(r["truth"]).get("outcome") in EXPOSED for i, r in ev.items()
                      if r["type"] in ("confront", "accuse"))
        flat += not (strong or flip or exposed)
    long_threads = [t for t in threads if t.last_day - t.first_day >= 2 and len(t.event_ids) >= 4]
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
        "goal_change_rate": 0.0,
        "thread_kinds": {k: sum(1 for t in threads if t.kind == k) for k in ("item", "debt", "rumor", "feud")},
    }
