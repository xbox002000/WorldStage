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
        "FROM people p LEFT JOIN personas s ON s.person_id = p.id WHERE p.location_id = ? AND p.id <> ? "
        "AND p.status <> 'inactive' AND COALESCE(json_extract(s.traits, '$.species'), 'human') = 'human' ORDER BY p.id",
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
    return {"here": obs["others_here"], "steal": steal, "tell": tell, "confront": confront,
            **item_options(conn, actor, obs["me"]["location_id"], here_ids, names)}


def belief_dropped(conn: sqlite3.Connection, actor: str, memory_id: int) -> bool:
    """A later memory that contradicts this one with at least the same confidence supersedes it."""
    from world.confront import _beliefs_about, superseded
    m = conn.execute("SELECT m.memory_id, m.confidence, c.subject, c.act, c.object, c.polarity FROM memories m "
                     "JOIN claims c USING (claim_id) WHERE m.memory_id = ?", (memory_id,)).fetchone()
    return superseded(_beliefs_about(conn, actor, m["subject"], m["object"]), m)


def concerns(conn: sqlite3.Connection, actor: str, obj: str) -> bool:
    """People accuse over what was done to them: a lie told to them, or a thing that is rightfully theirs."""
    if obj == actor:
        return True
    row = conn.execute("SELECT rightful_owner_id FROM objects WHERE id = ?", (obj,)).fetchone()
    return row is not None and row[0] == actor


def item_options(conn: sqlite3.Connection, actor: str, here: str, here_ids: list[str], names: dict[str, str]) -> dict:
    """World C options: things lying here, things to give back, money to lend or repay, people to accuse."""
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'world_vars'").fetchone() is None:
        return {"take": [], "give": [], "lend": [], "repay": [], "accuse": [], "challenge": [], "train": []}
    from world.space import now_of, oracle
    space = oracle(conn)
    take = [{"target": r["id"], "object": r["name"], "value_cents": r["value_cents"], "rightful": r["rightful_owner_id"]}
            for r in conn.execute("SELECT * FROM objects WHERE location_id = ? AND status = 'normal' "
                                  "AND tags NOT LIKE '%\"fixed\"%' ORDER BY id", (here,))
            if space is None or space.perceives_thing(actor, r["id"], now_of(conn))]  # with space: only what one sees
    give = [{"target": r["id"], "object": r["name"], "owner": r["rightful_owner_id"], "value_cents": r["value_cents"]}
            for r in conn.execute("SELECT * FROM objects WHERE owner_person_id = ? AND status = 'normal' "
                                  "AND rightful_owner_id IS NOT NULL AND rightful_owner_id <> ? ORDER BY id", (actor, actor))
            if r["rightful_owner_id"] in here_ids]
    money = conn.execute("SELECT money_cents FROM people WHERE id = ?", (actor,)).fetchone()[0]
    from world.intent import ACCUSABLE, LEND_CENTS, MIN_ACCUSE_CONFIDENCE, already_accused
    lend = [{"target": p} for p in here_ids] if money >= LEND_CENTS else []
    repay = [{"target": r["target_id"], "debt_cents": r["debt_cents"]} for r in conn.execute(
        "SELECT target_id, debt_cents FROM relationships WHERE actor_id = ? AND debt_cents > 0 ORDER BY target_id", (actor,))
        if r["target_id"] in here_ids and money >= min(r["debt_cents"], LEND_CENTS)]
    accuse, seen = [], set()
    for r in conn.execute(
        f"SELECT m.memory_id, m.confidence, m.claim_id, c.subject, c.act, c.object FROM memories m JOIN claims c USING (claim_id) "
        f"WHERE m.observer_id = ? AND c.polarity = 'affirm' AND c.act IN ({','.join('?' * len(ACCUSABLE))}) "
        f"AND m.confidence >= ? ORDER BY m.confidence DESC, m.memory_id", (actor, *ACCUSABLE, MIN_ACCUSE_CONFIDENCE)):
        if r["subject"] in here_ids and r["claim_id"] not in seen and concerns(conn, actor, r["object"])                 and not already_accused(conn, actor, r["claim_id"]) and not belief_dropped(conn, actor, r["memory_id"]):
            seen.add(r["claim_id"])
            accuse.append({"memory_id": r["memory_id"], "target": r["subject"], "confidence": r["confidence"],
                           "act": r["act"], "object": r["object"],
                           "text": describe_claim(Claim(r["subject"], r["act"], r["object"]), names)})
    from world.recipes import enabled
    challenge = train = []
    if enabled(conn, "duel"):
        from world.jianghu import DUEL_ENERGY, injured, recent_duel
        now = conn.execute("SELECT COALESCE(MAX(timestamp), 0) FROM events").fetchone()[0]
        me = conn.execute("SELECT energy FROM people WHERE id = ?", (actor,)).fetchone()[0]
        hurt = injured(conn, actor, now)
        challenge = [{"target": p} for p in here_ids if not hurt and me >= DUEL_ENERGY
                     and conn.execute("SELECT energy FROM people WHERE id = ?", (p,)).fetchone()[0] >= DUEL_ENERGY
                     and not recent_duel(conn, actor, p, now) and not injured(conn, p, now)]
    if enabled(conn, "martial_arts"):
        tags = conn.execute("SELECT tags FROM locations WHERE id = ?", (here,)).fetchone()[0]
        train = [{"here": here}] if '"training"' in tags else []
    return {"take": take, "give": give, "lend": lend, "repay": repay, "accuse": accuse, "challenge": challenge, "train": train}


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
