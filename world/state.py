from __future__ import annotations

import sqlite3
from dataclasses import dataclass

# entity_type -> (table, key columns)
ENTITIES: dict[str, tuple[str, tuple[str, ...]]] = {
    "person": ("people", ("id",)),
    "relationship": ("relationships", ("actor_id", "target_id")),
    "object": ("objects", ("id",)),
}

# entity_type -> field -> value_kind. Integer fields must receive ints.
NUMERIC_INT = {
    "person": {"energy", "money_cents", "hunger"},
    "relationship": {"debt_cents"},
}
NUMERIC_REAL = {"relationship": {"trust", "affection", "fear", "rivalry"}}
SET_FIELDS = {
    "person": {"location_id", "goal", "emotion", "status"},
    "object": {"owner_person_id", "location_id", "status"},
}

TOLERANCE = 1e-6


class WorldError(ValueError):
    """A proposed change or event violates a world rule."""


def entity_key(entity_type: str, entity_id: str) -> tuple[str, ...]:
    """Relationship ids are 'actor:target'; the others are a single id."""
    _, cols = ENTITIES[entity_type]
    parts = tuple(entity_id.split(":"))
    if len(parts) != len(cols):
        raise WorldError(f"bad {entity_type} id {entity_id!r}")
    return parts


def read_entity(conn: sqlite3.Connection, entity_type: str, entity_id: str) -> sqlite3.Row | None:
    table, cols = ENTITIES[entity_type]
    where = " AND ".join(f"{c} = ?" for c in cols)
    return conn.execute(f"SELECT * FROM {table} WHERE {where}", entity_key(entity_type, entity_id)).fetchone()


def value_kind(entity_type: str, field: str) -> str:
    if field in NUMERIC_INT.get(entity_type, ()) or field in NUMERIC_REAL.get(entity_type, ()):
        return "numeric"
    if field in SET_FIELDS.get(entity_type, ()):
        return "set"
    raise WorldError(f"{entity_type} has no mutable field {field!r}")


@dataclass(frozen=True)
class Problem:
    entity_type: str
    entity_id: str
    field: str
    message: str


def _same(a, b) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) <= TOLERANCE
    return a == b


def audit(conn: sqlite3.Connection) -> list[Problem]:
    """Check that history explains current state.

    For every (entity, field) the delta chain must be continuous (each old == previous new) and its
    last new value must equal the current value. A state edit made without an event shows up here.
    """
    problems: list[Problem] = []
    rows = conn.execute(
        "SELECT entity_type, entity_id, field, old_value, new_value FROM event_deltas ORDER BY delta_id"
    ).fetchall()
    last: dict[tuple[str, str, str], object] = {}
    for r in rows:
        key = (r["entity_type"], r["entity_id"], r["field"])
        if key in last and not _same(last[key], r["old_value"]):
            problems.append(Problem(*key, f"chain broken: expected old={last[key]!r}, got {r['old_value']!r}"))
        last[key] = r["new_value"]
    for r in conn.execute(
        "SELECT m.memory_id FROM memories m WHERE m.claim_id IS NOT NULL AND m.about_event_id IS NULL "
        "AND NOT EXISTS (SELECT 1 FROM memory_sources s WHERE s.memory_id = m.memory_id) ORDER BY m.memory_id"
    ):
        problems.append(Problem("memory", str(r["memory_id"]), "claim", "general belief has no source"))
    for (etype, eid, field), new in last.items():
        row = read_entity(conn, etype, eid)
        if row is None:
            problems.append(Problem(etype, eid, field, "entity missing"))
        elif not _same(row[field], new):
            problems.append(Problem(etype, eid, field, f"state={row[field]!r} but history ends at {new!r}"))
    return problems


def relationship_history(conn: sqlite3.Connection, actor: str, target: str, field: str) -> list[sqlite3.Row]:
    """Value over time with the event that caused each step (Day 1 +0.60 -> ... -> Day 7 -0.32)."""
    return conn.execute(
        "SELECT d.event_id, e.timestamp, d.old_value, d.new_value, d.delta_value, e.type, e.parent_event_id "
        "FROM event_deltas d JOIN events e USING (event_id) "
        "WHERE d.entity_type = 'relationship' AND d.entity_id = ? AND d.field = ? ORDER BY d.delta_id",
        (f"{actor}:{target}", field),
    ).fetchall()
