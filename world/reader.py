"""Read-only access to a world database, enforced by SQLite itself.

Production code must open world.db only through open_world_reader(). `immutable=1` is deliberately not
used: the database runs in WAL mode and `immutable` would ignore the WAL, silently returning stale rows.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path


def open_world_reader(path: str | Path) -> sqlite3.Connection:
    uri = Path(path).resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    return conn
