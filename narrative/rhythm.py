"""Does the story breathe? Read-only measures of rhythm over a window of days of a finished run.

A good long story is calm -> small oddity -> small conflict -> build-up -> outburst -> aftermath -> calm, not conflict
every day. These measures say how a run is paced, how its threads live and die, and how its people change.

Days (each day of the window gets one label, for the whole world and for each person's own life, counting only the
events they were at the centre of):
  peak      an event of weight >= HIGH (a duel, a theft, a trust flip, an exposure, a false accusation ...)
  quiet     nothing of weight >= NOTABLE: talk, work, training, errands
  recovery  neither, the day after a peak
  rising    neither, with a peak in the next two days
  simmer    neither, and no peak close by
Breath:
  longest_peak_run   most peak days in a row
  mean_peak_gap      mean days from one peak to the next
Threads: born, resolved, dormant (a gap of >= DORMANT days), revived (events after such a gap), colliding (touching
another thread).
People: goal changes by kind, trust reversals (world/helpers.trust_reversed: from one settled side to the other), belief reversals (someone who believed a thing later believes its
negation), trait drift and value shift (summed |change| of psyche traits and values).
"""
from __future__ import annotations

import json
import sqlite3
from statistics import mean

from narrative.threads import derive_threads
from world.psyche import ADAPTIVE, VALUES

HIGH = 0.7
NOTABLE = 0.5
DORMANT = 3
EXPOSED = ("lie_exposed", "distortion_exposed", "concealment_exposed", "caught")


PRINCIPAL = ("actor", "target", "victim", "suspect", "receiver")


def _day_weights(conn: sqlite3.Connection, pid: str | None = None) -> dict[int, list[tuple[str, float]]]:
    """Per day, (type, weight) of every event, or only those where pid is at the centre."""
    sql = "SELECT e.timestamp, e.type, e.importance, e.truth FROM events e"
    args: tuple = ()
    if pid is not None:
        sql += (" WHERE EXISTS (SELECT 1 FROM event_participants p WHERE p.event_id = e.event_id AND p.person_id = ? "
                f"AND p.role IN ({','.join('?' * len(PRINCIPAL))}))")
        args = (pid, *PRINCIPAL)
    out: dict[int, list[tuple[str, float]]] = {}
    for ts, t, imp, truth in conn.execute(sql + " ORDER BY e.event_id", args):
        d = json.loads(truth)
        w = max(imp, HIGH) if d.get("trust_flipped") else imp
        if t in ("accuse", "confront") and d.get("outcome") in EXPOSED + ("false",):
            w = max(w, HIGH)
        out.setdefault(ts // 1440, []).append((t, w))
    return out


def label_days(conn: sqlite3.Connection, days: int, pid: str | None = None) -> list[str]:
    weights = _day_weights(conn, pid)
    peak = [any(w >= HIGH for _, w in weights.get(d, [])) for d in range(days)]
    labels = []
    for d in range(days):
        if peak[d]:
            labels.append("peak")
        elif not any(w >= NOTABLE for _, w in weights.get(d, [])):
            labels.append("quiet")
        elif d and peak[d - 1]:
            labels.append("recovery")
        elif any(peak[d + k] for k in (1, 2) if d + k < days):
            labels.append("rising")
        else:
            labels.append("simmer")
    return labels


STRIP = {"quiet": ".", "simmer": "-", "rising": "/", "peak": "^", "recovery": "\\"}


def _is_animal(conn: sqlite3.Connection, pid: str) -> bool:
    from world.animals import is_animal
    return is_animal(conn, pid)


def _runs(labels: list[str]) -> tuple[int, float | None]:
    longest = run = 0
    peaks = [i for i, x in enumerate(labels) if x == "peak"]
    for x in labels:
        run = run + 1 if x == "peak" else 0
        longest = max(longest, run)
    gaps = [b - a for a, b in zip(peaks, peaks[1:])]
    return longest, (round(mean(gaps), 2) if gaps else None)


def _thread_life(threads, conn: sqlite3.Connection, lo: int, hi: int) -> dict:
    day_of = {i: ts // 1440 for i, ts in conn.execute("SELECT event_id, timestamp FROM events")}
    born = resolved = dormant = revived = colliding = 0
    for t in threads:
        days = sorted({day_of[e] for e in t.event_ids})
        born += lo <= t.first_day < hi
        colliding += lo <= t.first_day < hi and bool(t.cross_threads)
        resolved += t.status == "resolved" and lo <= t.last_day < hi
        for a, b in zip(days, days[1:]):
            if b - a >= DORMANT and lo <= b < hi:
                dormant += 1
                revived += 1  # the gap ended: the thread came back
        if days and days[-1] < hi - DORMANT and days[-1] >= lo and t.status != "resolved":
            dormant += 1  # fell silent inside the window and stayed silent
    return {"born": born, "resolved": resolved, "dormant": dormant, "revived": revived, "colliding": colliding}


def _people_change(conn: sqlite3.Connection, lo: int, hi: int) -> dict:
    a, b = lo * 1440, hi * 1440
    goals: dict[str, int] = {}
    for (to,) in conn.execute("SELECT json_extract(truth, '$.to') FROM events WHERE type = 'goal_change' "
                              "AND timestamp >= ? AND timestamp < ?", (a, b)):
        goals[to] = goals.get(to, 0) + 1
    trust = conn.execute("SELECT COUNT(*) FROM events WHERE json_extract(truth, '$.trust_flipped') = 1 "
                         "AND timestamp >= ? AND timestamp < ?", (a, b)).fetchone()[0]
    beliefs = conn.execute(
        "SELECT COUNT(*) FROM memories m2 JOIN claims c2 ON c2.claim_id = m2.claim_id WHERE m2.created_at >= ? "
        "AND m2.created_at < ? AND EXISTS (SELECT 1 FROM memories m1 JOIN claims c1 ON c1.claim_id = m1.claim_id "
        "WHERE m1.observer_id = m2.observer_id AND m1.memory_id < m2.memory_id AND c1.subject = c2.subject "
        "AND c1.act = c2.act AND c1.object IS c2.object AND c1.polarity <> c2.polarity)", (a, b)).fetchone()[0]
    drift = {"traits": 0.0, "values": 0.0}
    for eid, old, new in conn.execute(
            "SELECT x.entity_id, x.old_value, x.new_value FROM event_deltas x JOIN events e USING (event_id) "
            "WHERE x.entity_type = 'var' AND x.entity_id LIKE 'psy.%' AND e.timestamp >= ? AND e.timestamp < ?", (a, b)):
        key = eid.split(".", 2)[2]
        if key in ADAPTIVE:
            drift["traits"] += abs((new or 0) - (old or 0))
        elif key in VALUES:
            drift["values"] += abs((new or 0) - (old or 0))
    return {"goal_changes": dict(sorted(goals.items())), "trust_reversals": trust, "belief_reversals": beliefs,
            "trait_drift": round(drift["traits"], 3), "value_shift": round(drift["values"], 3)}


def rhythm(conn: sqlite3.Connection, lo: int, hi: int, threads=None) -> dict:
    """Measures for days [lo, hi) of a run that has at least hi days."""
    labels = label_days(conn, hi)[lo:]
    n = hi - lo
    weights = _day_weights(conn)
    window = [weights.get(d, []) for d in range(lo, hi)]
    decisions = conn.execute("SELECT COUNT(*) FROM events WHERE trigger_type = 'decision' AND timestamp >= ? "
                             "AND timestamp < ?", (lo * 1440, hi * 1440)).fetchone()[0]
    longest, gap = _runs(labels)
    humans = [r[0] for r in conn.execute("SELECT id FROM people WHERE status <> 'inactive' ORDER BY id")
              if not _is_animal(conn, r[0])]
    lives = {p: label_days(conn, hi, p)[lo:] for p in humans}
    person_runs = [_runs(v) for v in lives.values()]
    return {
        "days": [lo, hi],
        "events_per_day": round(sum(len(w) for w in window) / n, 2),
        "decisions_per_day": round(decisions / n, 2),
        "high_per_day": round(sum(1 for w in window for _, x in w if x >= HIGH) / n, 2),
        "duels_per_day": round(sum(1 for w in window for t, _ in w if t == "duel") / n, 2),
        "shape": {k: round(labels.count(k) / n, 2) for k in ("quiet", "simmer", "rising", "peak", "recovery")},
        "longest_peak_run": longest,
        "mean_peak_gap": gap,
        "strip": "".join(STRIP[x] for x in labels),
        "person_shape": {k: round(mean(v.count(k) / n for v in lives.values()), 2)
                         for k in ("quiet", "simmer", "rising", "peak", "recovery")} if lives else {},
        "person_longest_peak_run": round(mean(r[0] for r in person_runs), 2) if person_runs else 0,
        "person_strips": {p: "".join(STRIP[x] for x in v) for p, v in lives.items()},
        "threads": _thread_life(threads if threads is not None else derive_threads(conn), conn, lo, hi),
        "people": _people_change(conn, lo, hi),
    }
