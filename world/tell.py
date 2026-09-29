"""Telling: what a character may say, and the proposition that actually comes out. Effects are in world/social.py."""
from __future__ import annotations

import sqlite3

from contracts.claim import Claim, can_distort, distort, negate
from contracts.tell import TELL_MODES, TellIntent
from world.claims import load_claim
from world.state import WorldError


MIN_TELLING_IMPORTANCE = 0.25  # idle chatter is not worth passing on


def held_claim_ids(conn: sqlite3.Connection, person: str) -> set[int]:
    """Claims this person holds in memory (what they saw, were told, or inferred)."""
    return {r[0] for r in conn.execute(
        "SELECT DISTINCT claim_id FROM memories WHERE observer_id = ? AND claim_id IS NOT NULL", (person,))}


def validate_tell(conn: sqlite3.Connection, t: TellIntent) -> None:
    if t.mode not in TELL_MODES:
        raise WorldError(f"tell mode {t.mode!r} is not allowed")
    rows = {r["id"]: r["location_id"] for r in conn.execute("SELECT id, location_id FROM people WHERE id IN (?, ?)", (t.actor, t.target))}
    for who in (t.actor, t.target):
        if who not in rows:
            raise WorldError(f"person {who!r} does not exist")
    if t.actor == t.target:
        raise WorldError("cannot tell yourself")
    if rows[t.actor] != rows[t.target]:
        raise WorldError(f"{t.target} is not here")
    held = held_claim_ids(conn, t.actor)
    if t.source_claim_id not in held:
        raise WorldError("actor does not hold that claim")
    if t.withheld_claim_ids and t.mode != "omission":
        raise WorldError("only an omission can withhold claims")
    if t.mode == "omission" and not t.withheld_claim_ids:
        raise WorldError("an omission must name what is withheld")
    for cid in t.withheld_claim_ids:
        if cid not in held or cid == t.source_claim_id:
            raise WorldError("withheld claims must be other claims the actor holds")
    if t.mode == "distortion" and not can_distort(load_claim(conn, t.source_claim_id)):
        raise WorldError("that claim has no rule-defined distortion")


def asserted_claim(conn: sqlite3.Connection, t: TellIntent) -> Claim:
    """The proposition actually spoken, derived from the source claim by a fixed rule."""
    source = load_claim(conn, t.source_claim_id)
    if t.mode == "lie":
        return negate(source)  # P1: polarity flip only; scapegoating comes later
    if t.mode == "distortion":
        return distort(source)
    return source  # truth and omission say the source claim itself


def best_memory(conn: sqlite3.Connection, person: str, claim_id: int) -> sqlite3.Row:
    """The memory a person would pass this claim on from: their most confident one, earliest first on ties."""
    return conn.execute(
        "SELECT memory_id, event_id, about_event_id, confidence, source_type, source_id FROM memories "
        "WHERE observer_id = ? AND claim_id = ? ORDER BY confidence DESC, memory_id LIMIT 1", (person, claim_id)).fetchone()


def already_told(conn: sqlite3.Connection, actor: str, target: str, claim_id: int) -> bool:
    return conn.execute(
        "SELECT 1 FROM events WHERE type = 'tell' AND json_extract(truth, '$.actor') = ? "
        "AND json_extract(truth, '$.target') = ? AND json_extract(truth, '$.source_claim') = ? LIMIT 1",
        (actor, target, claim_id)).fetchone() is not None


def tellable(conn: sqlite3.Connection, actor: str, limit: int = 4) -> list[sqlite3.Row]:
    """The claims most worth passing on: what the actor holds, weightiest incident first, then most recent."""
    return conn.execute(
        "SELECT m.claim_id, MAX(m.confidence) AS confidence, MAX(COALESCE(e.importance, 0)) AS importance, "
        "MAX(m.memory_id) AS last_memory, c.subject, c.act, c.object, c.polarity "
        "FROM memories m JOIN claims c USING (claim_id) "
        "LEFT JOIN events e ON e.event_id = COALESCE(m.about_event_id, m.event_id) "
        "WHERE m.observer_id = ? GROUP BY m.claim_id HAVING importance >= ? "
        "ORDER BY importance DESC, last_memory DESC, m.claim_id LIMIT ?",
        (actor, MIN_TELLING_IMPORTANCE, limit)).fetchall()


def holds(conn: sqlite3.Connection, person: str, claim_id: int) -> bool:
    return conn.execute("SELECT 1 FROM memories WHERE observer_id = ? AND claim_id = ? LIMIT 1",
                        (person, claim_id)).fetchone() is not None
