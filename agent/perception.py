from __future__ import annotations

import sqlite3

from world.intent import TONES


def observe(conn: sqlite3.Connection, actor: str, memory_limit: int = 5) -> dict:
    """Everything the character is allowed to know: own state, who is here, own feelings, own memories."""
    me = conn.execute("SELECT * FROM people WHERE id = ?", (actor,)).fetchone()
    here = conn.execute(
        "SELECT p.id, p.name, "
        "COALESCE((SELECT trust FROM relationships WHERE actor_id = ? AND target_id = p.id), 0) AS trust, "
        "COALESCE((SELECT affection FROM relationships WHERE actor_id = ? AND target_id = p.id), 0) AS affection "
        "FROM people p WHERE p.location_id = ? AND p.id <> ? ORDER BY p.id",
        (actor, actor, me["location_id"], actor),
    ).fetchall()
    memories = conn.execute(
        "SELECT belief, confidence FROM memories WHERE observer_id = ? ORDER BY memory_id DESC LIMIT ?",
        (actor, memory_limit),
    ).fetchall()
    persona = conn.execute("SELECT text FROM personas WHERE person_id = ?", (actor,)).fetchone()
    return {
        "persona": persona[0] if persona else "",
        "me": {k: me[k] for k in ("id", "name", "goal", "emotion", "energy", "hunger", "money_cents", "location_id")},
        "others_here": [dict(r) for r in here],
        "memories": [dict(r) for r in memories],
    }


def candidates(conn: sqlite3.Connection, actor: str) -> list[dict]:
    """Legal-looking social options at this moment. The validator still has the final word."""
    obs = observe(conn, actor)
    out: list[dict] = [{"action": "idle"}]
    for o in obs["others_here"]:
        out.append({"action": "talk", "target": o["id"], "tones": list(TONES)})
    rows = conn.execute(
        "SELECT o.id, o.name, o.owner_person_id FROM objects o JOIN people p ON p.id = o.owner_person_id "
        "WHERE p.location_id = ? AND o.owner_person_id <> ? ORDER BY o.id",
        (conn.execute("SELECT location_id FROM people WHERE id = ?", (actor,)).fetchone()[0], actor),
    ).fetchall()
    out += [{"action": "steal", "target": r["id"], "object": r["name"], "owner": r["owner_person_id"]} for r in rows]
    return out
