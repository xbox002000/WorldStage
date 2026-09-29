from __future__ import annotations

import json
import sqlite3

from contracts.stylepack import SCORE_WEIGHTS_V1
from narrative.arcs import EXPOSED, Arc, Ev

COLD_TONES = ("cold", "hostile")
WEAK_OUTCOMES = ("unfounded", "misinformed", "inconclusive")


def _location_tags(conn: sqlite3.Connection, location_id: str | None) -> list[str]:
    row = conn.execute("SELECT tags FROM locations WHERE id = ?", (location_id,)).fetchone()
    return json.loads(row["tags"]) if row else []


def _pair_tension(arc: Arc, events: dict[int, Ev]) -> float:
    """Ends on a cold/hostile beat or a theft, and nothing later between the same pair repairs it."""
    last = arc.events[-1]
    bad = last.type == "steal" or last.truth.get("tone") in COLD_TONES
    if not bad:
        return 0.0
    pair = set(last.people[:2])
    for e in events.values():
        if e.id > last.id and e.type in ("talk", "steal") and set(e.people[:2]) == pair:
            return 0.3 if e.truth.get("tone") == "warm" else 0.6
    return 1.0


def unresolved_tension(arc: Arc, events: dict[int, Ev]) -> float:
    if arc.kind == "incident":
        exposed = any(e.outcome in EXPOSED for e in arc.events)
        if any(e.deceptive for e in arc.events) and not exposed:
            return 1.0  # a lie is still out there
        if arc.events[-1].outcome in WEAK_OUTCOMES:
            return 0.7  # an argument left hanging on a misunderstanding
        if exposed:
            return 0.3
    return _pair_tension(arc, events)


def _revelation(arc: Arc) -> float:
    if any(e.outcome in EXPOSED for e in arc.events):
        return 1.0  # someone was caught out
    if any(e.deceptive for e in arc.events):
        return 0.5  # a secret is in play
    if any(e.outcome in WEAK_OUTCOMES for e in arc.events):
        return 0.3
    return 0.0


def score_arc(conn: sqlite3.Connection, arc: Arc, events: dict[int, Ev], protagonists: set[str],
              weights: dict[str, float] = SCORE_WEIGHTS_V1) -> tuple[float, dict]:
    people = {p for e in arc.events for p in e.people[:2]}
    social_people = people or {""}
    parts = {
        "conflict": max(e.importance for e in arc.events),
        "relationship_change": min(1.0, sum(e.trust_shift for e in arc.events)),
        "reversal": min(1.0, sum(e.flipped for e in arc.events) + 0.5 * any(e.type == "steal" for e in arc.events)
                        + 0.5 * any(e.outcome in EXPOSED for e in arc.events)),
        "causality": min(1.0, (len(arc.events) - 1) / 4),
        "character_importance": 0.3 + 0.7 * len(social_people & protagonists) / len(social_people),
        "unresolved_tension": unresolved_tension(arc, events),
        "visual_potential": min(1.0, 0.4 + 0.3 * ("social" in _location_tags(conn, arc.peak.location_id))
                                + 0.3 * min(len(arc.peak.people), 4) / 4),
        "revelation": _revelation(arc),
    }
    breakdown = {k: round(v, 3) for k, v in parts.items()}
    return round(sum(weights[k] * v for k, v in parts.items()), 4), breakdown
