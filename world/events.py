from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Sequence

from contracts.claim import Claim
from world.claims import claim_id
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


SOURCE_TYPES = ("direct_observation", "told_by", "inference", "external_rumor")


@dataclass(frozen=True)
class MemorySpec:
    """What one person now believes. `claim` is the structured belief; `belief` is prompt text only.

    about_self: the belief is about the event being committed (the usual case). Otherwise about_event_id
    names another event, or is None for a general belief, which must cite at least one source.
    """

    observer_id: str
    belief: str
    confidence: float
    claim: Claim | None = None
    about_self: bool = True
    about_event_id: int | None = None
    source_type: str = "direct_observation"
    source_id: str | None = None
    derived_from_events: Sequence[int] = ()
    derived_from_memories: Sequence[int] = ()


@dataclass(frozen=True)
class ClaimSpec:
    claim: Claim
    role: str = "truth"  # truth | asserted | withheld


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
    claims: Sequence[ClaimSpec] = ()


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

        for cs in spec.claims:
            conn.execute(
                "INSERT INTO event_claims(event_id, claim_id, role) VALUES (?,?,?)",
                (event_id, claim_id(conn, cs.claim), cs.role),
            )

        for m in spec.memories:
            _insert_memory(conn, event_id, spec.timestamp, m)
        return int(event_id)


def _insert_memory(conn: sqlite3.Connection, event_id: int, timestamp: int, m: MemorySpec) -> None:
    if m.source_type not in SOURCE_TYPES:
        raise WorldError(f"unknown memory source type {m.source_type!r}")
    if m.source_type == "told_by" and conn.execute("SELECT 1 FROM people WHERE id = ?", (m.source_id,)).fetchone() is None:
        raise WorldError(f"told_by source {m.source_id!r} is not a person")
    about = event_id if m.about_self else m.about_event_id
    sources = [("memory", i) for i in m.derived_from_memories] + [("event", i) for i in m.derived_from_events]
    if m.claim is not None and about is None and not sources:
        raise WorldError("a general belief must cite at least one source")
    cid = claim_id(conn, m.claim) if m.claim is not None else None
    mid = conn.execute(
        "INSERT INTO memories(observer_id, event_id, belief, confidence, created_at, claim_id, about_event_id, "
        "source_type, source_id) VALUES (?,?,?,?,?,?,?,?,?)",
        (m.observer_id, event_id, m.belief, m.confidence, timestamp, cid, about, m.source_type, m.source_id),
    ).lastrowid
    for kind, ref in sources:
        conn.execute(
            "INSERT INTO memory_sources(memory_id, derived_from_memory_id, derived_from_event_id) VALUES (?,?,?)",
            (mid, ref if kind == "memory" else None, ref if kind == "event" else None),
        )


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
