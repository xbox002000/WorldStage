from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def connect(path: str | Path = ":memory:") -> sqlite3.Connection:
    # Autocommit mode: transactions are opened explicitly by mutation().
    conn = sqlite3.connect(path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    if str(path) != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db(conn: sqlite3.Connection, world_seed: int = 0) -> None:
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.execute(
        "INSERT OR IGNORE INTO meta(key, value) VALUES ('world_seed', ?)", (str(world_seed),)
    )


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
