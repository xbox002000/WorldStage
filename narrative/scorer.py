from __future__ import annotations

import json
import sqlite3

from narrative.arcs import Arc, Ev

WEIGHTS = {
    "conflict": 0.25,
    "relationship_change": 0.20,
    "reversal": 0.20,
    "causality": 0.10,
    "character_importance": 0.10,
    "unresolved_tension": 0.10,
    "visual_potential": 0.05,
}
COLD_TONES = ("cold", "hostile")


def _location_tags(conn: sqlite3.Connection, location_id: str | None) -> list[str]:
    row = conn.execute("SELECT tags FROM locations WHERE id = ?", (location_id,)).fetchone()
    return json.loads(row["tags"]) if row else []


def _unresolved(arc: Arc, events: dict[int, Ev]) -> float:
    """Ends on a cold/hostile beat or a theft, and nothing later between the same pair repairs it."""
    last = arc.events[-1]
    if last.type == "steal":
        bad = True
    else:
        bad = last.truth.get("tone") in COLD_TONES
    if not bad:
        return 0.0
    pair = set(last.people[:2])
    for e in events.values():
        if e.id > last.id and e.type in ("talk", "steal") and set(e.people[:2]) == pair:
            return 0.3 if e.truth.get("tone") == "warm" else 0.6
    return 1.0


def score_arc(conn: sqlite3.Connection, arc: Arc, events: dict[int, Ev], protagonists: set[str]) -> tuple[float, dict]:
    people = {p for e in arc.events for p in e.people[:2]}
    social_people = people or {""}
    parts = {
        "conflict": max(e.importance for e in arc.events),
        "relationship_change": min(1.0, sum(e.trust_shift for e in arc.events)),
        "reversal": min(1.0, sum(e.flipped for e in arc.events) + 0.5 * any(e.type == "steal" for e in arc.events)),
        "causality": min(1.0, (len(arc.events) - 1) / 4),
        "character_importance": 0.3 + 0.7 * len(social_people & protagonists) / len(social_people),
        "unresolved_tension": _unresolved(arc, events),
        "visual_potential": min(1.0, 0.4 + 0.3 * ("social" in _location_tags(conn, arc.peak.location_id))
                                + 0.3 * min(len(arc.peak.people), 4) / 4),
    }
    breakdown = {k: round(v, 3) for k, v in parts.items()}
    return round(sum(WEIGHTS[k] * v for k, v in parts.items()), 4), breakdown
