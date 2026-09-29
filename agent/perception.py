"""What a character is allowed to know and what they could do about it right now.

Everything here is read from the world through the character's own eyes: their state, who is present, their own
feelings and their own memories. Nothing is visible that they did not see, hear or work out.
"""
from __future__ import annotations

import sqlite3

from contracts.claim import Claim, can_distort
from world.claims import describe_claim, labels
from world.confront import confrontable
from world.intent import TONES
from world.tell import already_told, best_memory, holds, tellable

MEMORY_RECENT = 5
MEMORY_IMPORTANT = 3
MAX_STEAL_OPTIONS = 2


def source_label(memory: sqlite3.Row | None, names: dict[str, str]) -> str:
    if memory is None or memory["source_type"] == "direct_observation":
        return "親眼看到"
    if memory["source_type"] == "told_by":
        return f"聽{names.get(memory['source_id'], memory['source_id'])}說"
    if memory["source_type"] == "external_rumor":
        return "外面的傳聞"
    return "自己推測"


def memory_lines(conn: sqlite3.Connection, actor: str, names: dict[str, str]) -> list[dict]:
    """A handful of memories: the most recent, plus the weightiest ones not already listed."""
    cols = ("m.memory_id, m.belief, m.confidence, m.source_type, m.source_id, "
            "COALESCE((SELECT importance FROM events WHERE event_id = COALESCE(m.about_event_id, m.event_id)), 0) AS importance")
    recent = conn.execute(f"SELECT {cols} FROM memories m WHERE m.observer_id = ? AND m.claim_id IS NOT NULL "
                          "ORDER BY m.memory_id DESC LIMIT ?", (actor, MEMORY_RECENT)).fetchall()
    seen = {r["memory_id"] for r in recent}
    weighty = [r for r in conn.execute(
        f"SELECT {cols} FROM memories m WHERE m.observer_id = ? AND m.claim_id IS NOT NULL "
        "ORDER BY importance DESC, m.memory_id DESC LIMIT ?", (actor, MEMORY_IMPORTANT + MEMORY_RECENT)).fetchall()
        if r["memory_id"] not in seen][:MEMORY_IMPORTANT]
    rows = sorted(recent + weighty, key=lambda r: r["memory_id"])
    return [{"memory_id": r["memory_id"], "text": r["belief"], "confidence": r["confidence"],
             "how": source_label(r, names)} for r in rows]


def observe(conn: sqlite3.Connection, actor: str) -> dict:
    """Everything the character is allowed to know: own state, who is here, own feelings, own memories."""
    me = conn.execute("SELECT * FROM people WHERE id = ?", (actor,)).fetchone()
    here = conn.execute(
        "SELECT p.id, p.name, "
        "COALESCE((SELECT trust FROM relationships WHERE actor_id = ? AND target_id = p.id), 0) AS trust, "
        "COALESCE((SELECT affection FROM relationships WHERE actor_id = ? AND target_id = p.id), 0) AS affection "
        "FROM people p WHERE p.location_id = ? AND p.id <> ? ORDER BY p.id",
        (actor, actor, me["location_id"], actor),
    ).fetchall()
    persona = conn.execute("SELECT text FROM personas WHERE person_id = ?", (actor,)).fetchone()
    names = labels(conn)
    return {
        "persona": persona[0] if persona else "",
        "me": {k: me[k] for k in ("id", "name", "goal", "emotion", "energy", "hunger", "money_cents", "location_id")},
        "others_here": [dict(r) for r in here],
        "memories": memory_lines(conn, actor, names),
    }


def social_options(conn: sqlite3.Connection, actor: str) -> dict:
    """Structured options for this moment. The validator still has the final word."""
    obs = observe(conn, actor)
    names = labels(conn)
    here_ids = [o["id"] for o in obs["others_here"]]
    # Theft is only worth listing against the people the actor trusts least, and never more than a couple of them.
    steal = [{"target": r["id"], "object": r["name"], "owner": r["owner_person_id"]} for r in conn.execute(
        "SELECT o.id, o.name, o.owner_person_id FROM objects o JOIN people p ON p.id = o.owner_person_id "
        "LEFT JOIN relationships rel ON rel.actor_id = ? AND rel.target_id = o.owner_person_id "
        "WHERE p.location_id = ? AND o.owner_person_id <> ? ORDER BY COALESCE(rel.trust, 0), o.id LIMIT ?",
        (actor, obs["me"]["location_id"], actor, MAX_STEAL_OPTIONS))]

    tell = []
    for row in tellable(conn, actor):
        targets = [p for p in here_ids if not holds(conn, p, row["claim_id"]) and not already_told(conn, actor, p, row["claim_id"])]
        if targets:
            claim = Claim(row["subject"], row["act"], row["object"], row["polarity"])
            tell.append({"claim_id": row["claim_id"], "claim": claim, "text": describe_claim(claim, names),
                         "how": source_label(best_memory(conn, actor, row["claim_id"]), names), "targets": targets,
                         "can_distort": can_distort(claim)})
    confront = [{"memory_id": c["memory_id"], "target": c["target"], "text": describe_claim(c["claim"], names),
                 "grounds_text": describe_claim(c["grounds"], names), "claim": c["claim"]} for c in confrontable(conn, actor)]
    return {"here": obs["others_here"], "steal": steal, "tell": tell, "confront": confront}


def candidates(conn: sqlite3.Connection, actor: str) -> list[dict]:
    """The same options as one flat list (each entry is one distinct proposal)."""
    opts = social_options(conn, actor)
    out: list[dict] = [{"action": "idle"}]
    out += [{"action": "talk", "target": o["id"], "tones": list(TONES)} for o in opts["here"]]
    out += [{"action": "steal", "target": s["target"], "object": s["object"], "owner": s["owner"]} for s in opts["steal"]]
    for t in opts["tell"]:
        out += [{"action": "tell", "target": p, "claim_id": t["claim_id"]} for p in t["targets"]]
    out += [{"action": "confront", "target": c["target"], "memory_id": c["memory_id"]} for c in opts["confront"]]
    return out
