"""Confront: catching someone out. This module only decides whether a confrontation is legal and what
grounds it; the outcome is resolved in world/social.py.

Memories are append-only, so a belief is never edited: a newer memory that contradicts it with at least the same
confidence *supersedes* it. A superseded belief is no longer a reason to doubt anyone.
"""
from __future__ import annotations

import sqlite3

from contracts.claim import Claim, contradicts
from world.state import WorldError


def _claim(row: sqlite3.Row) -> Claim:
    return Claim(row["subject"], row["act"], row["object"], row["polarity"])


def _beliefs_about(conn: sqlite3.Connection, actor: str, subject: str, obj: str) -> list[sqlite3.Row]:
    """The actor's memories about one subject and object, oldest first."""
    return conn.execute(
        "SELECT m.memory_id, m.event_id, m.confidence, c.subject, c.act, c.object, c.polarity "
        "FROM memories m JOIN claims c USING (claim_id) "
        "WHERE m.observer_id = ? AND c.subject = ? AND c.object = ? ORDER BY m.memory_id",
        (actor, subject, obj)).fetchall()


def superseded(beliefs: list[sqlite3.Row], g: sqlite3.Row) -> bool:
    gc = _claim(g)
    return any(h["memory_id"] > g["memory_id"] and h["confidence"] >= g["confidence"] and contradicts(gc, _claim(h))
               for h in beliefs)


def find_grounds(conn: sqlite3.Connection, actor: str, claim: Claim, exclude_memory_id: int) -> sqlite3.Row | None:
    """The actor's most confident live memory that contradicts `claim`: their reason to doubt what they were told."""
    beliefs = _beliefs_about(conn, actor, claim.subject, claim.object)
    live = [g for g in beliefs if g["memory_id"] != exclude_memory_id and contradicts(claim, _claim(g))
            and not superseded(beliefs, g)]
    return min(live, key=lambda g: (-g["confidence"], g["memory_id"]), default=None)


def already_confronted(conn: sqlite3.Connection, actor: str, target: str, claim_id: int) -> bool:
    """One confrontation per person per proposition: the argument has been had."""
    return conn.execute(
        "SELECT 1 FROM events WHERE type = 'confront' AND json_extract(truth, '$.actor') = ? "
        "AND json_extract(truth, '$.target') = ? AND json_extract(truth, '$.claim_id') = ? LIMIT 1",
        (actor, target, claim_id)).fetchone() is not None


def confrontable(conn: sqlite3.Connection, actor: str) -> list[dict]:
    """Things the actor was told, by someone standing here, that conflict with something else they still believe."""
    here = conn.execute("SELECT location_id FROM people WHERE id = ?", (actor,)).fetchone()[0]
    told = conn.execute(
        "SELECT m.memory_id, m.claim_id, m.source_id, m.confidence, c.subject, c.act, c.object, c.polarity "
        "FROM memories m JOIN claims c USING (claim_id) JOIN people p ON p.id = m.source_id "
        "WHERE m.observer_id = ? AND m.source_type = 'told_by' AND p.location_id = ? AND p.id <> ? "
        "ORDER BY m.memory_id", (actor, here, actor)).fetchall()
    out = []
    for r in told:
        if already_confronted(conn, actor, r["source_id"], r["claim_id"]):
            continue
        grounds = find_grounds(conn, actor, _claim(r), r["memory_id"])
        if grounds is not None:
            out.append({"memory_id": r["memory_id"], "target": r["source_id"], "claim": _claim(r),
                        "grounds_memory_id": grounds["memory_id"], "grounds": _claim(grounds)})
    return out


def validate_confront(conn: sqlite3.Connection, actor: str, target: str | None, memory_id: int | None) -> None:
    if not target:
        raise WorldError("a confrontation needs a target")
    where = {r["id"]: r["location_id"] for r in conn.execute(
        "SELECT id, location_id FROM people WHERE id IN (?, ?)", (actor, target))}
    if target not in where:
        raise WorldError(f"person {target!r} does not exist")
    if actor == target:
        raise WorldError("cannot confront yourself")
    if where[actor] != where[target]:
        raise WorldError(f"{target} is not here")
    if memory_id is None:
        raise WorldError("a confrontation must name the memory it is based on")
    m1 = conn.execute(
        "SELECT m.memory_id, m.claim_id, m.observer_id, m.source_type, m.source_id, c.subject, c.act, c.object, c.polarity "
        "FROM memories m JOIN claims c USING (claim_id) WHERE m.memory_id = ?", (memory_id,)).fetchone()
    if m1 is None or m1["observer_id"] != actor:
        raise WorldError("actor does not hold that memory")
    if m1["source_type"] != "told_by" or m1["source_id"] != target:
        raise WorldError("that memory was not told to the actor by the target")
    if already_confronted(conn, actor, target, m1["claim_id"]):
        raise WorldError("already confronted about this")
    if find_grounds(conn, actor, _claim(m1), memory_id) is None:
        raise WorldError("no grounds: nothing the actor still believes contradicts what they were told")
