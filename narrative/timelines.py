"""Timelines as read models of the one event log: world, character, relationship, thread. Nothing here is stored.

`why_changed(conn, pid, day_a, day_b)` answers the milestone question: why is she, on day 60, not who she was on
day 1? Each shifted trait, value and self-belief is traced to the reflection events that moved it, and each
reflection to the events it cites.
"""
from __future__ import annotations

import json
import sqlite3

from world.explain import summarize
from world.psyche import ADAPTIVE, SELF_MODEL, VALUES

DAY = 1440


def world_timeline(conn: sqlite3.Connection, day: int, min_importance: float = 0.5) -> list[str]:
    return [summarize(conn, r[0]) for r in conn.execute(
        "SELECT event_id FROM events WHERE timestamp >= ? AND timestamp < ? AND importance >= ? ORDER BY event_id",
        (day * DAY, (day + 1) * DAY, min_importance))]


def character_timeline(conn: sqlite3.Connection, pid: str, min_importance: float = 0.4) -> list[dict]:
    """What this person lived through: acts they were part of or saw, goal changes, reflections."""
    rows = conn.execute(
        "SELECT DISTINCT e.event_id, e.timestamp, e.type, e.importance, e.truth FROM events e "
        "JOIN event_participants p ON p.event_id = e.event_id WHERE p.person_id = ? "
        "AND (e.importance >= ? OR e.type IN ('goal_change', 'reflection')) "
        "AND e.type NOT IN ('upkeep', 'move', 'eat', 'work', 'day_end') ORDER BY e.event_id", (pid, min_importance)).fetchall()
    out = []
    for r in rows:
        t = json.loads(r["truth"])
        line = summarize(conn, r["event_id"])
        if r["type"] == "reflection":
            line = f"第{r['timestamp'] // DAY + 1}天 夜裡回想：" + "、".join(f"{k} {v:+.2f}" for k, v in t["shifted"].items()) + \
                   ("；" + "、".join(t["self_model"]) if t.get("self_model") else "")
        out.append({"event_id": r["event_id"], "day": r["timestamp"] // DAY + 1, "type": r["type"], "text": line})
    return out


def relationship_timeline(conn: sqlite3.Connection, a: str, b: str, field: str = "trust") -> list[dict]:
    """a's feeling toward b over time, each step with its cause (from event_deltas; never stored twice)."""
    return [{"day": r["timestamp"] // DAY + 1, "old": r["old_value"], "new": r["new_value"], "event_id": r["event_id"],
             "cause": summarize(conn, r["event_id"])}
            for r in conn.execute(
                "SELECT d.event_id, d.old_value, d.new_value, e.timestamp FROM event_deltas d JOIN events e USING (event_id) "
                "WHERE d.entity_type = 'relationship' AND d.entity_id = ? AND d.field = ? ORDER BY d.delta_id",
                (f"{a}:{b}", field))]


def thread_timeline(conn: sqlite3.Connection, event_ids: list[int]) -> list[str]:
    return [summarize(conn, e) for e in event_ids]


def state_at(conn: sqlite3.Connection, pid: str, day: int) -> dict[str, float]:
    """The slow layers of `pid` at the end of `day`, rebuilt from the deltas (day -1 = before anything happened)."""
    keys = [*ADAPTIVE, *(f"value.{v}" for v in VALUES), *(f"self.{s}" for s in SELF_MODEL)]
    out = {}
    for k in keys:
        full = f"psy.{pid}.{k}"
        row = conn.execute(
            "SELECT d.new_value FROM event_deltas d JOIN events e USING (event_id) WHERE d.entity_type = 'var' "
            "AND d.entity_id = ? AND e.timestamp < ? ORDER BY d.delta_id DESC LIMIT 1", (full, (day + 1) * DAY)).fetchone()
        if row is None:
            first = conn.execute("SELECT old_value FROM event_deltas WHERE entity_type = 'var' AND entity_id = ? "
                                 "ORDER BY delta_id LIMIT 1", (full,)).fetchone()
            now = conn.execute("SELECT value FROM world_vars WHERE key = ?", (full,)).fetchone()
            out[k] = first[0] if first else (now[0] if now else 0.0)
        else:
            out[k] = row[0]
    return out


def why_changed(conn: sqlite3.Connection, pid: str, day_a: int, day_b: int) -> dict:
    before, after = state_at(conn, pid, day_a), state_at(conn, pid, day_b)
    moved = {k: (round(before[k], 3), round(after[k], 3)) for k in before if abs(after[k] - before[k]) > 1e-6}
    because = []
    for r in conn.execute("SELECT event_id, timestamp, truth FROM events WHERE type = 'reflection' "
                          "AND json_extract(truth, '$.actor') = ? AND timestamp >= ? AND timestamp < ? ORDER BY event_id",
                          (pid, (day_a + 1) * DAY, (day_b + 1) * DAY)):
        t = json.loads(r["truth"])
        if not t["shifted"]:
            continue
        because.append({"day": r["timestamp"] // DAY + 1, "shifted": t["shifted"], "self_model": t.get("self_model", []),
                        "experiences": t["experiences"], "because_of": [summarize(conn, e) for e in t["cites"][:6]]})
    return {"person": pid, "from_day": day_a + 1, "to_day": day_b + 1, "moved": moved, "because": because}
