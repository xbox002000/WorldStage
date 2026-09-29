from __future__ import annotations

import sqlite3

from world.db import connect, init_db


def seeded(world_seed: int = 1, john_at: str = "home", all_pairs: bool = False) -> sqlite3.Connection:
    """Small world: home + cafe, john + mary, one phone, one relationship each way."""
    conn = connect()
    init_db(conn, world_seed)
    conn.execute("INSERT INTO locations VALUES ('home','Home',0,0,5,'[]')")
    conn.execute("INSERT INTO locations VALUES ('cafe','Cafe',2,0,20,'[]')")
    conn.execute("INSERT INTO location_edges VALUES ('home','cafe',10)")
    conn.execute("INSERT INTO location_edges VALUES ('cafe','home',10)")
    for pid, name, loc, money in (("john", "John", john_at, 12000), ("mary", "Mary", "cafe", 8000), ("tom", "Tom", "cafe", 5000)):
        conn.execute(
            "INSERT INTO people VALUES (?,?,?,100,?,10,'goal','calm','{}','active')", (pid, name, loc, money)
        )
    for a, b in (("john", "mary"), ("mary", "john"), ("tom", "mary")):
        conn.execute("INSERT INTO relationships(actor_id, target_id, trust) VALUES (?,?,0.6)", (a, b))
    if all_pairs:
        for a in ("john", "mary", "tom"):
            for b in ("john", "mary", "tom"):
                if a != b:
                    conn.execute("INSERT OR IGNORE INTO relationships(actor_id, target_id, trust) VALUES (?,?,0.2)", (a, b))
    conn.execute("INSERT INTO objects(id, name, owner_person_id) VALUES ('phone','Phone','mary')")
    return conn


def dump_state(conn: sqlite3.Connection) -> list[tuple]:
    out: list[tuple] = []
    for table in ("people", "relationships", "objects", "events", "event_deltas", "memories"):
        out += [tuple(r) for r in conn.execute(f"SELECT * FROM {table} ORDER BY 1, 2")]
    return out
