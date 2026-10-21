"""Dramatic debt: what a person has piled up that has not yet been answered (read model, never truth).

A producer should not ask "who deserves a turn?" but "where has something built up with nowhere to go?". Debt is that, taken from
what the world already holds, each part visible and named so that a reader can say *why* somebody is carrying a lot:

  humiliation   shame, wrongs and failures still unhealed (the psyche's decaying experience accumulators)
  betrayal      being betrayed and hostility still felt
  gap           what they can really do beyond what the others take them for (the underdog's debt)
  longing       a love that is not returned (attraction well above the other's)
  grudge        a resentment held against somebody, not yet settled

`debt_model_v0.1`: a draft. It is a *read model*: whether it predicts anything is measured (debt_lab.py), not assumed.
"""
from __future__ import annotations

import sqlite3

DEBT_VERSION = "debt_model_v0.1"
WEIGHTS = {"humiliation": 1.0, "betrayal": 1.0, "gap": 3.0, "longing": 1.0, "grudge": 0.8}
LONGING_AT = 0.30
UNRETURNED = 0.15
GRUDGE_AT = 0.30


def _exp(conn: sqlite3.Connection, pid: str, key: str) -> float:
    r = conn.execute("SELECT value FROM world_vars WHERE key = ?", (f"psy.{pid}.exp.{key}",)).fetchone()
    return r[0] if r else 0.0


def components(conn: sqlite3.Connection, pid: str) -> dict[str, float]:
    ability = conn.execute("SELECT value FROM world_vars WHERE key = ?", (f"skill.{pid}",)).fetchone()
    crowd = conn.execute("SELECT AVG(estimate) FROM relationships WHERE target_id = ? AND actor_id != ?", (pid, pid)).fetchone()[0]
    gap = max(0.0, (ability[0] - crowd)) if ability is not None and crowd is not None else 0.0
    longing = sum(1 for r in conn.execute(
        "SELECT r.attraction, b.attraction AS back FROM relationships r JOIN relationships b ON b.actor_id = r.target_id AND b.target_id = r.actor_id "
        "WHERE r.actor_id = ?", (pid,)) if r["attraction"] >= LONGING_AT and r["attraction"] - r["back"] >= UNRETURNED)
    grudge = conn.execute("SELECT COALESCE(MAX(resentment), 0) FROM relationships WHERE actor_id = ? AND target_id != ?", (pid, pid)).fetchone()[0]
    return {"humiliation": round(_exp(conn, pid, "shame") + _exp(conn, pid, "wronged") + _exp(conn, pid, "failure"), 4),
            "betrayal": round(_exp(conn, pid, "betrayal") + _exp(conn, pid, "hostility"), 4),
            "gap": round(gap, 4), "longing": float(longing), "grudge": round(grudge if grudge >= GRUDGE_AT else 0.0, 4)}


def debt(conn: sqlite3.Connection, pid: str) -> tuple[float, dict[str, float]]:
    c = components(conn, pid)
    return round(sum(WEIGHTS[k] * v for k, v in c.items()), 4), c


def ledger(conn: sqlite3.Connection, people: list[str] | None = None) -> list[dict]:
    """Everybody's debt, the heaviest first."""
    people = people or [r[0] for r in conn.execute("SELECT person_id FROM character_profiles ORDER BY person_id")]
    rows = []
    for p in people:
        total, c = debt(conn, p)
        rows.append({"person": p, "debt": total, "parts": c})
    return sorted(rows, key=lambda r: (-r["debt"], r["person"]))
