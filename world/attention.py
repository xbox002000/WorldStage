"""Attention: who notices an act. Being present is not the same as noticing.

In Experiment A every event had six to eight witnesses, so nothing could stay secret. Here each person present notices
an act with a probability set by how loud it is, scaled by the world variable `visibility` (a blackout lowers it).
The draw is deterministic: world seed + time + act key + person.
"""
from __future__ import annotations

import sqlite3

from world.rng import rng as make_rng

LOUD, NORMAL, QUIET = "loud", "normal", "quiet"
NOTICE_P = {LOUD: 1.0, NORMAL: 0.5, QUIET: 0.2}


def world_seed(conn: sqlite3.Connection) -> str:
    return conn.execute("SELECT value FROM meta WHERE key = 'world_seed'").fetchone()[0]


def var(conn: sqlite3.Connection, key: str, default: float = 0.0) -> float:
    try:
        row = conn.execute("SELECT value FROM world_vars WHERE key = ?", (key,)).fetchone()
    except sqlite3.OperationalError:  # a pre-v3 world
        return default
    return row[0] if row else default


def present(conn: sqlite3.Connection, here: str, *exclude: str) -> list[str]:
    """Every person at a place (sorted), minus the principals. Animals sense instead (world/animals.py)."""
    rows = conn.execute(
        "SELECT p.id FROM people p LEFT JOIN personas s ON s.person_id = p.id WHERE p.location_id = ? "
        "AND p.status <> 'inactive' AND COALESCE(json_extract(s.traits, '$.species'), 'human') = 'human' ORDER BY p.id",
        (here,)).fetchall()
    return [r["id"] for r in rows if r["id"] not in exclude]


def noticers(conn: sqlite3.Connection, here: str, now: int, key: str, loudness: str, *exclude: str) -> list[str]:
    """The people present who notice this act. Loud acts are noticed by everyone, whatever the visibility."""
    people = present(conn, here, *exclude)
    if loudness == LOUD:
        return people
    p = NOTICE_P[loudness] * var(conn, "visibility", 1.0)
    seed = world_seed(conn)
    from world.space import oracle
    space = oracle(conn)
    if space is None:
        return [pid for pid in people if make_rng(seed, now, f"{key}:{pid}", "notice").random() < p]
    # in a world simulated in its space: only those who could see (or hear) it, likelier the closer and more in front
    out = []
    for pid in people:
        w = space.weight(pid, key, now)
        if w > 0 and make_rng(seed, now, f"{key}:{pid}", "notice").random() < min(1.0, p * w):
            out.append(pid)
    return out
