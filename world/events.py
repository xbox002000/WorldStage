from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Sequence

from world.db import mutation
from world.state import NUMERIC_INT, ENTITIES, WorldError, entity_key, read_entity, value_kind


@dataclass(frozen=True)
class Change:
    """One field change. Numeric fields take `delta`; set fields take `value`."""

    entity_type: str
    entity_id: str
    field: str
    delta: int | float | None = None
    value: Any = None


@dataclass(frozen=True)
class MemorySpec:
    observer_id: str
    belief: str
    confidence: float


@dataclass(frozen=True)
class EventSpec:
    timestamp: int
    type: str
    trigger_type: str
    location_id: str | None = None
    parent_event_id: int | None = None
    importance: float = 0.0
    truth: dict = field(default_factory=dict)
    participants: Sequence[tuple[str, str]] = ()  # (person_id, role)
    changes: Sequence[Change] = ()
    memories: Sequence[MemorySpec] = ()


def apply_event(conn: sqlite3.Connection, spec: EventSpec) -> int:
    """The only path that changes the world. Event, deltas, state and memories commit together
    or not at all. Returns the new event_id."""
    with mutation(conn):
        last_ts = conn.execute("SELECT COALESCE(MAX(timestamp), 0) FROM events").fetchone()[0]
        if spec.timestamp < last_ts:
            raise WorldError(f"timestamp {spec.timestamp} is earlier than last event {last_ts}")

        event_id = conn.execute(
            "INSERT INTO events(timestamp, type, location_id, parent_event_id, trigger_type, importance, truth) "
            "VALUES (?,?,?,?,?,?,?)",
            (spec.timestamp, spec.type, spec.location_id, spec.parent_event_id,
             spec.trigger_type, spec.importance, json.dumps(spec.truth, sort_keys=True)),
        ).lastrowid

        for person_id, role in spec.participants:
            conn.execute(
                "INSERT INTO event_participants(event_id, person_id, role) VALUES (?,?,?)",
                (event_id, person_id, role),
            )

        by_entity: dict[tuple[str, str], list[Change]] = {}
        for ch in spec.changes:
            by_entity.setdefault((ch.entity_type, ch.entity_id), []).append(ch)
        for (etype, eid), changes in by_entity.items():
            _apply_entity_changes(conn, event_id, etype, eid, changes)

        for m in spec.memories:
            conn.execute(
                "INSERT INTO memories(observer_id, event_id, belief, confidence, created_at) VALUES (?,?,?,?,?)",
                (m.observer_id, event_id, m.belief, m.confidence, spec.timestamp),
            )
        return int(event_id)


def _apply_entity_changes(
    conn: sqlite3.Connection, event_id: int, etype: str, eid: str, changes: list[Change]
) -> None:
    if etype not in ENTITIES:
        raise WorldError(f"unknown entity type {etype!r}")
    row = read_entity(conn, etype, eid)
    if row is None:
        raise WorldError(f"{etype} {eid!r} does not exist")

    assignments: list[tuple[str, Any]] = []
    for ch in changes:
        kind = value_kind(etype, ch.field)
        old = row[ch.field]
        if kind == "numeric":
            if ch.delta is None or ch.value is not None:
                raise WorldError(f"{etype}.{ch.field} takes a delta, not a value")
            is_int = ch.field in NUMERIC_INT.get(etype, ())
            if is_int and not isinstance(ch.delta, int):
                raise WorldError(f"{etype}.{ch.field} takes an integer delta")
            new = old + ch.delta if is_int else round(old + ch.delta, 6)
            delta = new - old
            conn.execute(
                "INSERT INTO event_deltas(event_id, entity_type, entity_id, field, old_value, new_value, "
                "delta_value, value_kind) VALUES (?,?,?,?,?,?,?, 'numeric')",
                (event_id, etype, eid, ch.field, old, new, delta),
            )
        else:
            if ch.delta is not None:
                raise WorldError(f"{etype}.{ch.field} takes a value, not a delta")
            new = ch.value
            conn.execute(
                "INSERT INTO event_deltas(event_id, entity_type, entity_id, field, old_value, new_value, "
                "delta_value, value_kind) VALUES (?,?,?,?,?,?,NULL, 'set')",
                (event_id, etype, eid, ch.field, old, new),
            )
        assignments.append((ch.field, new))

    # One UPDATE per entity so multi-field CHECKs (e.g. object owner vs location) see the final row.
    table, cols = ENTITIES[etype]
    sets = ", ".join(f"{f} = ?" for f, _ in assignments)
    where = " AND ".join(f"{c} = ?" for c in cols)
    conn.execute(
        f"UPDATE {table} SET {sets} WHERE {where}",
        [v for _, v in assignments] + list(entity_key(etype, eid)),
    )
