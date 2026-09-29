"""Small read-only helpers shared by the rule modules. Nothing here writes to the world."""
from __future__ import annotations

import sqlite3

from world.events import Change


def clamp_delta(current: float, delta: float, lo: float, hi: float) -> float:
    return round(min(hi, max(lo, current + delta)) - current, 6)


def person(conn: sqlite3.Connection, pid: str) -> sqlite3.Row:
    return conn.execute("SELECT * FROM people WHERE id = ?", (pid,)).fetchone()


def rel(conn: sqlite3.Connection, actor: str, target: str, field: str) -> float:
    return conn.execute(
        f"SELECT {field} FROM relationships WHERE actor_id = ? AND target_id = ?", (actor, target)
    ).fetchone()[0]


def bystanders(conn: sqlite3.Connection, here: str, *exclude: str) -> list[str]:
    rows = conn.execute("SELECT id FROM people WHERE location_id = ? ORDER BY id", (here,)).fetchall()
    return [r["id"] for r in rows if r["id"] not in exclude]


def last_event_between(conn: sqlite3.Connection, a: str, b: str) -> int | None:
    """Most recent social event where both were principals (not mere witnesses): the causal parent."""
    return conn.execute(
        "SELECT MAX(e.event_id) FROM events e "
        "JOIN event_participants p1 ON p1.event_id = e.event_id AND p1.person_id = ? "
        "  AND p1.role IN ('actor', 'target', 'victim') "
        "JOIN event_participants p2 ON p2.event_id = e.event_id AND p2.person_id = ? "
        "  AND p2.role IN ('actor', 'target', 'victim') "
        "WHERE e.type IN ('talk', 'steal', 'tell', 'confront')",
        (a, b),
    ).fetchone()[0]


def trust_change(conn: sqlite3.Connection, observer: str, subject: str, delta: float) -> Change | None:
    d = clamp_delta(rel(conn, observer, subject, "trust"), delta, -1.0, 1.0)
    return Change("relationship", f"{observer}:{subject}", "trust", delta=d) if d else None


def field_change(conn: sqlite3.Connection, observer: str, subject: str, field: str, delta: float) -> Change | None:
    """A clamped change to one relationship field (values live in [-1, 1])."""
    d = clamp_delta(rel(conn, observer, subject, field), delta, -1.0, 1.0)
    return Change("relationship", f"{observer}:{subject}", field, delta=d) if d else None


class RelDeltas:
    """Collects relationship changes and emits at most one clamped Change per (observer, subject, field).

    event_deltas is unique per (event, entity, field), so several causes for the same field must be summed first.
    """

    def __init__(self) -> None:
        self._sum: dict[tuple[str, str, str], float] = {}

    def add(self, observer: str, subject: str, field: str, delta: float) -> None:
        if observer != subject and delta:
            key = (observer, subject, field)
            self._sum[key] = self._sum.get(key, 0.0) + delta

    def changes(self, conn: sqlite3.Connection) -> list[Change]:
        out = []
        for (observer, subject, field), delta in sorted(self._sum.items()):
            ch = field_change(conn, observer, subject, field, delta)
            if ch:
                out.append(ch)
        return out
