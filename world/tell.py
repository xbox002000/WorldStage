"""Validation and claim derivation for TellIntent. The world effects of a tell are applied in P1's rules."""
from __future__ import annotations

import sqlite3

from contracts.claim import Claim, distort, negate
from contracts.tell import TELL_MODES, TellIntent
from world.claims import load_claim
from world.state import WorldError


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


def asserted_claim(conn: sqlite3.Connection, t: TellIntent) -> Claim:
    """The proposition actually spoken, derived from the source claim by a fixed rule."""
    source = load_claim(conn, t.source_claim_id)
    if t.mode == "lie":
        return negate(source)  # P1: polarity flip only; scapegoating comes later
    if t.mode == "distortion":
        return distort(source)
    return source  # truth and omission say the source claim itself
