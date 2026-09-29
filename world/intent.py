from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass

from world.state import WorldError

ACTIONS = ("move", "eat", "work", "rest", "talk", "steal", "tell", "confront",
           "take", "give", "lend", "repay", "accuse")
TONES = ("warm", "neutral", "cold", "hostile")

EAT_COST_CENTS = 800  # base price; the world variable price_food overrides it
WORK_ENERGY = 15
LEND_CENTS = 3000
ACCUSABLE = ("steal", "take", "deceive", "conceal", "threaten")
MIN_ACCUSE_CONFIDENCE = 0.3


def food_price(conn: sqlite3.Connection) -> int:
    from world.attention import var
    return int(round(var(conn, "price_food", EAT_COST_CENTS)))


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
    claim_id: int | None = None  # tell: the held claim to pass on
    mode: str | None = None  # tell: truth | omission | lie | distortion
    withheld: tuple[int, ...] = ()  # tell (omission): other held claims to keep quiet about
    memory_id: int | None = None  # confront: the told memory being challenged


def intent_hash(it: Intent) -> str:
    """Identity of a proposed action, independent of who wrote the reason text."""
    payload = json.dumps([it.actor, it.action, it.target, it.tone, it.claim_id, it.mode, list(it.withheld), it.memory_id],
                         separators=(",", ":"), ensure_ascii=False)
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
    def integer(name: str) -> int | None:
        value = raw.get(name)
        if value in (None, "", 0):  # ids start at 1, so 0 means "not given"
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            raise WorldError(f"{name} must be an integer")

    withheld = integer("withheld_claim_id")
    return Intent(
        actor=actor,
        action=str(raw.get("action", "")),
        target=raw.get("target") or None,
        tone=raw.get("tone") or None,
        reason=str(raw.get("reason", ""))[:300],
        priority=min(1.0, max(0.0, priority)),
        claim_id=integer("claim_id"),
        mode=raw.get("mode") or None,
        withheld=(withheld,) if withheld else (),
        memory_id=integer("memory_id"),
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
        if actor["money_cents"] < food_price(conn):
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
    elif it.action == "tell":
        from contracts.tell import TellIntent
        from world.tell import validate_tell
        if it.claim_id is None or not it.target:
            raise WorldError("a tell needs a target and a claim")
        validate_tell(conn, TellIntent(it.actor, it.target, it.mode or "", it.claim_id, list(it.withheld)))
    elif it.action == "confront":
        from world.confront import validate_confront
        validate_confront(conn, it.actor, it.target, it.memory_id)
    elif it.action == "take":
        obj = conn.execute("SELECT * FROM objects WHERE id = ?", (it.target,)).fetchone()
        if obj is None:
            raise WorldError(f"object {it.target!r} does not exist")
        if obj["location_id"] != here or obj["status"] != "normal":
            raise WorldError(f"{it.target} is not lying here")
        if "fixed" in json.loads(obj["tags"]):
            raise WorldError(f"{it.target} cannot be carried off")
    elif it.action == "give":
        obj = conn.execute("SELECT * FROM objects WHERE id = ?", (it.target,)).fetchone()
        if obj is None or obj["owner_person_id"] != it.actor:
            raise WorldError("actor does not hold that item")
        owner = obj["rightful_owner_id"]
        if owner is None or owner == it.actor:
            raise WorldError("the item is the actor's own")
        _present_person(conn, it.actor, owner, here)
    elif it.action == "lend":
        _present_person(conn, it.actor, it.target, here)
        if actor["money_cents"] < LEND_CENTS:
            raise WorldError("not enough money to lend")
    elif it.action == "repay":
        _present_person(conn, it.actor, it.target, here)
        debt = conn.execute("SELECT debt_cents FROM relationships WHERE actor_id = ? AND target_id = ?",
                            (it.actor, it.target)).fetchone()
        if debt is None or debt[0] <= 0:
            raise WorldError("no debt to repay")
        if actor["money_cents"] < min(debt[0], LEND_CENTS):
            raise WorldError("not enough money to repay")
    elif it.action == "accuse":
        _present_person(conn, it.actor, it.target, here)
        validate_accusation(conn, it.actor, it.target, it.memory_id)


def _present_person(conn: sqlite3.Connection, actor: str, target: str | None, here: str) -> None:
    other = conn.execute("SELECT location_id FROM people WHERE id = ?", (target,)).fetchone() if target else None
    if other is None:
        raise WorldError(f"person {target!r} does not exist")
    if target == actor:
        raise WorldError("cannot do that to yourself")
    if other["location_id"] != here:
        raise WorldError(f"{target} is not here")


def accusation_claim(conn: sqlite3.Connection, memory_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT m.memory_id, m.observer_id, m.confidence, m.claim_id, m.source_type, m.event_id, m.about_event_id, "
        "c.subject, c.act, c.object, c.polarity FROM memories m JOIN claims c USING (claim_id) WHERE m.memory_id = ?",
        (memory_id,)).fetchone()


def already_accused(conn: sqlite3.Connection, actor: str, claim_id: int) -> bool:
    """One accusation per person per proposition."""
    return conn.execute(
        "SELECT 1 FROM events WHERE type = 'accuse' AND json_extract(truth, '$.actor') = ? "
        "AND json_extract(truth, '$.claim_id') = ? LIMIT 1", (actor, claim_id)).fetchone() is not None


def validate_accusation(conn: sqlite3.Connection, actor: str, target: str, memory_id: int | None) -> None:
    if memory_id is None:
        raise WorldError("an accusation must name the belief it rests on")
    m = accusation_claim(conn, memory_id)
    if m is None or m["observer_id"] != actor:
        raise WorldError("actor does not hold that memory")
    if m["subject"] != target or m["act"] not in ACCUSABLE or m["polarity"] != "affirm":
        raise WorldError("that belief does not accuse the target of anything")
    if m["confidence"] < MIN_ACCUSE_CONFIDENCE:
        raise WorldError("too unsure to accuse")
    if already_accused(conn, actor, m["claim_id"]):
        raise WorldError("already accused about this")
    from agent.perception import belief_dropped, concerns
    if not concerns(conn, actor, m["object"]):
        raise WorldError("people only accuse over what was done to them")
    if belief_dropped(conn, actor, memory_id):
        raise WorldError("the actor no longer believes that")
