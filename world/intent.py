from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass

from world.state import WorldError

ACTIONS = ("move", "eat", "work", "rest", "talk", "steal")
TONES = ("warm", "neutral", "cold", "hostile")

EAT_COST_CENTS = 800
WORK_ENERGY = 15


@dataclass(frozen=True)
class Intent:
    """What a character wants to do. Proposals only: nothing here changes the world."""

    actor: str
    action: str
    target: str | None = None  # location id, person id or object id depending on action
    tone: str | None = None
    reason: str = ""
    priority: float = 0.5
    source: str = ""  # which model proposed it; empty for rule/seeded decisions


def intent_hash(it: Intent) -> str:
    """Identity of a proposed action, independent of who wrote the reason text."""
    payload = json.dumps([it.actor, it.action, it.target, it.tone], separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def intent_sort_key(timestamp: int, it: Intent) -> tuple:
    """Total order for actions competing at one moment: time, priority (high first), actor, content hash.

    No two distinct intents share a key, so the order never depends on dict or SQL row order.
    """
    return (timestamp, -it.priority, it.actor, intent_hash(it))


def parse_intent(actor: str, raw: dict) -> Intent:
    """Turn model output into an Intent. Never trusts the model for the actor."""
    if not isinstance(raw, dict):
        raise WorldError("intent must be an object")
    try:
        priority = float(raw.get("priority", 0.5))
    except (TypeError, ValueError):
        raise WorldError("priority must be a number")
    return Intent(
        actor=actor,
        action=str(raw.get("action", "")),
        target=raw.get("target") or None,
        tone=raw.get("tone") or None,
        reason=str(raw.get("reason", ""))[:300],
        priority=min(1.0, max(0.0, priority)),
    )


def tags_of(conn: sqlite3.Connection, location_id: str) -> list[str]:
    row = conn.execute("SELECT tags FROM locations WHERE id = ?", (location_id,)).fetchone()
    return json.loads(row["tags"]) if row else []


def validate(conn: sqlite3.Connection, it: Intent) -> None:
    """Raise WorldError unless the intent is legal in the current world. Never creates entities."""
    actor = conn.execute("SELECT * FROM people WHERE id = ?", (it.actor,)).fetchone()
    if actor is None:
        raise WorldError(f"actor {it.actor!r} does not exist")
    if actor["status"] == "inactive":
        raise WorldError(f"{it.actor} is inactive")
    if it.action not in ACTIONS:
        raise WorldError(f"action {it.action!r} is not allowed")
    here = actor["location_id"]

    if it.action == "move":
        dest = conn.execute("SELECT * FROM locations WHERE id = ?", (it.target,)).fetchone()
        if dest is None:
            raise WorldError(f"location {it.target!r} does not exist")
        if conn.execute(
            "SELECT 1 FROM location_edges WHERE from_location_id = ? AND to_location_id = ?", (here, dest["id"])
        ).fetchone() is None:
            raise WorldError(f"{dest['id']} is not reachable from {here}")
        occupants = conn.execute("SELECT COUNT(*) FROM people WHERE location_id = ?", (dest["id"],)).fetchone()[0]
        if occupants >= dest["capacity"]:
            raise WorldError(f"{dest['id']} is full")
    elif it.action == "eat":
        if "food" not in tags_of(conn, here):
            raise WorldError(f"no food at {here}")
        if actor["money_cents"] < EAT_COST_CENTS:
            raise WorldError("not enough money")
    elif it.action == "work":
        if "work" not in tags_of(conn, here):
            raise WorldError(f"no work at {here}")
        if actor["energy"] < WORK_ENERGY:
            raise WorldError("too tired to work")
    elif it.action == "talk":
        other = conn.execute("SELECT * FROM people WHERE id = ?", (it.target,)).fetchone()
        if other is None:
            raise WorldError(f"person {it.target!r} does not exist")
        if other["id"] == it.actor:
            raise WorldError("cannot talk to yourself")
        if other["location_id"] != here:
            raise WorldError(f"{other['id']} is not here")
        if it.tone not in TONES:
            raise WorldError(f"tone {it.tone!r} is not allowed")
    elif it.action == "steal":
        obj = conn.execute("SELECT * FROM objects WHERE id = ?", (it.target,)).fetchone()
        if obj is None:
            raise WorldError(f"object {it.target!r} does not exist")
        owner = obj["owner_person_id"]
        if owner is None or owner == it.actor:
            raise WorldError("nothing to steal")
        owner_row = conn.execute("SELECT location_id FROM people WHERE id = ?", (owner,)).fetchone()
        if owner_row["location_id"] != here:
            raise WorldError("owner is not here")
