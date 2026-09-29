"""Canonical world snapshot: current state + immutable history at revision N.

Row order, number formatting and JSON layout are fixed so the same data hashes the same on any machine,
whatever order it was inserted in and whether the database was created fresh or migrated.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import unicodedata

from world.db import schema_version
from world.ruleset import KERNEL_VERSION, ruleset_hash

# table -> ORDER BY (primary-key order)
TABLES: dict[str, str] = {
    "locations": "id",
    "location_edges": "from_location_id, to_location_id",
    "people": "id",
    "personas": "person_id",
    "objects": "id",
    "relationships": "actor_id, target_id",
    "events": "event_id",
    "event_participants": "event_id, person_id, role",
    "event_deltas": "delta_id",
    "claims": "claim_id",
    "event_claims": "event_id, claim_id, role",
    "memories": "memory_id",
    "memory_sources": "memory_id, COALESCE(derived_from_memory_id, 0), COALESCE(derived_from_event_id, 0)",
}
JSON_COLUMNS = {"tags", "schedule", "truth"}


def world_revision(conn: sqlite3.Connection) -> int:
    """Last committed event id; 0 for a world with no events."""
    return conn.execute("SELECT COALESCE(MAX(event_id), 0) FROM events").fetchone()[0]


def world_time(conn: sqlite3.Connection) -> int:
    """Time only moves when an event commits: it is the last event's timestamp (0 before any event)."""
    return conn.execute("SELECT COALESCE(MAX(timestamp), 0) FROM events").fetchone()[0]


def _value(column: str, v):
    if v is None or isinstance(v, int):
        return v
    if isinstance(v, float):
        return f"{v:.6f}"
    if column in JSON_COLUMNS:
        return json.loads(v)
    return unicodedata.normalize("NFC", v)


def _canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def table_hash(conn: sqlite3.Connection, table: str) -> str:
    columns = sorted(r["name"] for r in conn.execute(f"PRAGMA table_info({table})"))
    rows = conn.execute(f"SELECT {', '.join(columns)} FROM {table} ORDER BY {TABLES[table]}").fetchall()
    return _sha(_canonical([{c: _value(c, row[c]) for c in columns} for row in rows]))


def snapshot_manifest(conn: sqlite3.Connection) -> dict:
    seed = conn.execute("SELECT value FROM meta WHERE key = 'world_seed'").fetchone()[0]
    return {
        "schema_version": schema_version(conn),
        "kernel_version": KERNEL_VERSION,
        "ruleset_hash": ruleset_hash(),
        "world_seed": seed,
        "world_revision": world_revision(conn),
        "tables": {t: table_hash(conn, t) for t in TABLES},
    }


def snapshot_hash(conn: sqlite3.Connection) -> str:
    return _sha(_canonical(snapshot_manifest(conn)))
