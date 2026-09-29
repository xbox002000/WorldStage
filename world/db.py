from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
MIGRATIONS_DIR = Path(__file__).with_name("migrations")
SCHEMA_VERSION = 3


def connect(path: str | Path = ":memory:") -> sqlite3.Connection:
    # Autocommit mode: transactions are opened explicitly by mutation().
    conn = sqlite3.connect(path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    if str(path) != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db(conn: sqlite3.Connection, world_seed: int = 0) -> None:
    """Create a fresh database at the current schema version."""
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.execute("INSERT OR IGNORE INTO meta(key, value) VALUES ('world_seed', ?)", (str(world_seed),))
    conn.execute("INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))


def schema_version(conn: sqlite3.Connection) -> int:
    """Databases created before versioning existed are version 1."""
    try:
        row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    except sqlite3.OperationalError:
        return 0
    return int(row[0]) if row else 1


def migrate(conn: sqlite3.Connection) -> int:
    """Upgrade an existing database to SCHEMA_VERSION by applying world/migrations/vNNN.sql in order."""
    version = schema_version(conn)
    if version == 0:
        raise RuntimeError("not a world database")
    if version > SCHEMA_VERSION:
        raise RuntimeError(f"database is version {version}, this code only knows {SCHEMA_VERSION}")
    while version < SCHEMA_VERSION:
        version += 1
        sql = (MIGRATIONS_DIR / f"v{version:03d}.sql").read_text(encoding="utf-8")
        conn.executescript("BEGIN;\n" + sql + "\nCOMMIT;")
        conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('schema_version', ?)", (str(version),))
    return version


@contextmanager
def mutation(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """One atomic write scope. The guard row is visible only inside the transaction."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("INSERT INTO mutation_guard(id) VALUES (1)")
        yield conn
        conn.execute("DELETE FROM mutation_guard")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")
