"""Items that go astray: left behind, picked up, missed, suspected, found, given back, and accusations about them.

The rightful owner of an item (`rightful_owner_id`) and whoever holds it (`owner_person_id`) are different facts.
Losing something is quiet; the owner only finds out at night, and then guesses who took it from who was around.
The guess is a belief (an `inference` memory) and it can be wrong. Accusations are judged against world truth.
"""
from __future__ import annotations

import json
import sqlite3

from contracts.claim import AFFIRM, DENY, PARTIAL, TRUE, Claim
from world.attention import LOUD, NORMAL, QUIET, noticers, present, var
from world.claims import describe_claim, evaluate, labels
from world.events import Change, ClaimSpec, EventSpec, MemorySpec
from world.helpers import RelDeltas, person, rel
from world.intent import Intent, accusation_claim
from world.state import WorldError


def item(conn: sqlite3.Connection, oid: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM objects WHERE id = ?", (oid,)).fetchone()
    if row is None:
        raise WorldError(f"object {oid!r} does not exist")
    return row


def _emotion(conn: sqlite3.Connection, pid: str, emotion: str) -> list[Change]:
    return [Change("person", pid, "emotion", value=emotion)] if person(conn, pid)["emotion"] != emotion else []


def _missing_flag(conn: sqlite3.Connection, oid: str, value: float) -> list[Change]:
    """`missing.<item>` is 1 while the rightful owner knows the item is gone."""
    cur = var(conn, f"missing.{oid}", None)
    if cur is None or cur == value:
        return []
    return [Change("var", f"missing.{oid}", "value", delta=value - cur)]


# -- misplace ---------------------------------------------------------------------------------------------------------
def misplace(conn: sqlite3.Connection, holder: str, oid: str, now: int) -> EventSpec:
    """The holder walks off without the item. Nobody but a few noticers knows where it is."""
    here = person(conn, holder)["location_id"]
    names = labels(conn)
    around = present(conn, here, holder)
    seen = noticers(conn, here, now, f"misplace:{holder}:{oid}", NORMAL, holder)
    lost = Claim(holder, "lose", oid)
    return EventSpec(
        timestamp=now, type="misplace", trigger_type="rule", location_id=here, importance=0.3,
        truth={"actor": holder, "object": oid, "rightful_owner": item(conn, oid)["rightful_owner_id"],
               "present": around, "noticed_by": seen},
        participants=[(holder, "actor")] + [(w, "witness") for w in seen],
        changes=[Change("object", oid, "owner_person_id", value=None), Change("object", oid, "location_id", value=here)],
        memories=[MemorySpec(w, describe_claim(lost, names) + f"，東西還在{names.get(here, here)}", 0.8, claim=lost)
                  for w in seen],
        claims=[ClaimSpec(lost)],
    )


# -- take / find back ---------------------------------------------------------------------------------------------------
def resolve_take(conn: sqlite3.Connection, it: Intent, now: int, trigger: str) -> EventSpec:
    obj = item(conn, it.target)
    a, here = it.actor, person(conn, it.actor)["location_id"]
    names = labels(conn)
    owner = obj["rightful_owner_id"]
    changes = [Change("object", obj["id"], "location_id", value=None), Change("object", obj["id"], "owner_person_id", value=a)]
    if owner == a:  # finding one's own lost item
        found = Claim(a, "find", obj["id"])
        return EventSpec(
            timestamp=now, type="find", trigger_type=trigger, location_id=here, importance=0.45,
            truth={"actor": a, "object": obj["id"], "own": True, "reason": it.reason, "source": it.source},
            participants=[(a, "actor")],
            changes=changes + _missing_flag(conn, obj["id"], 0.0) + _emotion(conn, a, "relieved"),
            memories=[MemorySpec(a, describe_claim(found, names), 1.0, claim=found)]
            + cleared_suspicions(conn, a, obj["id"], names),
            claims=[ClaimSpec(found)],
        )
    took = Claim(a, "take", obj["id"])
    seen = noticers(conn, here, now, f"take:{a}:{obj['id']}", QUIET, a)
    deltas = RelDeltas()
    for w in seen:
        deltas.add(w, a, "trust", -0.15 if owner else 0.0)
    return EventSpec(
        timestamp=now, type="take", trigger_type=trigger, location_id=here, importance=0.7 if owner else 0.4,
        truth={"actor": a, "object": obj["id"], "rightful_owner": owner, "value_cents": obj["value_cents"],
               "witnessed": bool(seen), "reason": it.reason, "source": it.source},
        participants=[(a, "actor")] + ([(owner, "victim")] if owner else []) + [(w, "witness") for w in seen],
        changes=changes + deltas.changes(conn),
        memories=[MemorySpec(a, describe_claim(took, names), 1.0, claim=took)]
        + [MemorySpec(w, describe_claim(took, names), 0.75, claim=took) for w in seen],
        claims=[ClaimSpec(took), ClaimSpec(Claim(a, "find", obj["id"]))],
    )


def resolve_give(conn: sqlite3.Connection, it: Intent, now: int, trigger: str) -> EventSpec:
    obj = item(conn, it.target)
    a, owner = it.actor, obj["rightful_owner_id"]
    here = person(conn, a)["location_id"]
    names = labels(conn)
    gave = Claim(a, "give", obj["id"])
    seen = noticers(conn, here, now, f"give:{a}:{obj['id']}", NORMAL, a, owner)
    deltas = RelDeltas()
    deltas.add(owner, a, "trust", 0.2)
    deltas.add(owner, a, "affection", 0.15)
    for w in seen:
        deltas.add(w, a, "trust", 0.05)
    return EventSpec(
        timestamp=now, type="give", trigger_type=trigger, location_id=here, importance=0.6,
        parent_event_id=_last_event_about(conn, obj["id"]),
        truth={"actor": a, "target": owner, "object": obj["id"], "reason": it.reason, "source": it.source},
        participants=[(a, "actor"), (owner, "target")] + [(w, "witness") for w in seen],
        changes=[Change("object", obj["id"], "owner_person_id", value=owner)] + deltas.changes(conn)
        + _missing_flag(conn, obj["id"], 0.0) + _emotion(conn, owner, "relieved"),
        memories=[MemorySpec(p, describe_claim(gave, names), 1.0, claim=gave) for p in (a, owner)]
        + cleared_suspicions(conn, owner, obj["id"], names, keep=a)
        + [MemorySpec(w, describe_claim(gave, names), 0.7, claim=gave) for w in seen],
        claims=[ClaimSpec(gave)],
    )


def cleared_suspicions(conn: sqlite3.Connection, owner: str, oid: str, names: dict, keep: str | None = None) -> list[MemorySpec]:
    """Getting a thing back settles who the owner thought had taken it: those guesses are now believed false.

    keep: the person who handed it back (they did have it, so that suspicion stands).
    """
    out = []
    for r in conn.execute(
        "SELECT DISTINCT c.subject FROM memories m JOIN claims c USING (claim_id) WHERE m.observer_id = ? "
        "AND c.object = ? AND c.act IN ('take', 'steal') AND c.polarity = 'affirm' AND m.source_type <> 'direct_observation' "
        "ORDER BY c.subject", (owner, oid)):
        if r[0] in (owner, keep):
            continue
        cleared = Claim(r[0], "take", oid, DENY)
        out.append(MemorySpec(owner, describe_claim(cleared, names), 0.95, claim=cleared, source_type="inference",
                              about_self=True))
    return out


def _last_event_about(conn: sqlite3.Connection, oid: str) -> int | None:
    return conn.execute(
        "SELECT MAX(event_id) FROM events WHERE json_extract(truth, '$.object') = ?", (oid,)).fetchone()[0]


# -- the owner misses it (overnight) ------------------------------------------------------------------------------------
def missing_items(conn: sqlite3.Connection, owner: str) -> list[sqlite3.Row]:
    """Items this person owns, does not hold, and has not yet missed."""
    return conn.execute(
        "SELECT o.* FROM objects o JOIN world_vars v ON v.key = 'missing.' || o.id "
        "WHERE o.rightful_owner_id = ? AND COALESCE(o.owner_person_id, '') <> ? AND o.status = 'normal' AND v.value = 0 "
        "ORDER BY o.id", (owner, owner)).fetchall()


def _how_it_went(conn: sqlite3.Connection, oid: str) -> sqlite3.Row | None:
    """The last event that separated the item from its rightful owner (misplace or an unnoticed steal)."""
    return conn.execute(
        "SELECT * FROM events WHERE type IN ('misplace', 'steal', 'take') AND json_extract(truth, '$.object') = ? "
        "ORDER BY event_id DESC LIMIT 1", (oid,)).fetchone()


def suspect_for(conn: sqlite3.Connection, owner: str, loss: sqlite3.Row | None) -> tuple[str, float] | None:
    """Who the owner guesses: of the people they remember being around when it went, the one they trust least."""
    if loss is None:
        return None
    truth = json.loads(loss["truth"])
    if loss["type"] == "misplace":
        around = truth.get("present", [])
    else:  # the owner was there when it was stolen, but did not see it happen
        around = [p for p, in conn.execute(
            "SELECT person_id FROM event_participants WHERE event_id = ? AND person_id <> ? ORDER BY person_id",
            (loss["event_id"], owner))]
        around = sorted(set(around) | {truth.get("actor")} - {None, owner})
    around = [p for p in around if p != owner]
    if not around:
        return None
    scored = sorted((rel(conn, owner, p, "trust") - 0.5 * rel(conn, owner, p, "rivalry"), p) for p in around)
    score, suspect = scored[0]
    confidence = round(min(0.75, max(0.3, 0.35 - 0.4 * score)), 2)
    return suspect, confidence


def notice_missing(conn: sqlite3.Connection, owner: str, oid: str, now: int) -> EventSpec:
    names = labels(conn)
    lost = Claim(owner, "lose", oid)
    loss = _how_it_went(conn, oid)
    guess = suspect_for(conn, owner, loss)
    memories = [MemorySpec(owner, describe_claim(lost, names), 1.0, claim=lost)]
    deltas = RelDeltas()
    truth = {"actor": owner, "object": oid, "loss_event": loss["event_id"] if loss else None, "suspect": None}
    if guess:
        suspect, confidence = guess
        guessed = Claim(suspect, "take", oid)
        memories.append(MemorySpec(owner, describe_claim(guessed, names), confidence, claim=guessed,
                                   source_type="inference"))
        deltas.add(owner, suspect, "trust", -0.15 * confidence)
        truth.update(suspect=suspect, confidence=confidence,
                     suspect_guilty=evaluate(conn, guessed) in (TRUE, PARTIAL))
    return EventSpec(
        timestamp=now, type="notice_missing", trigger_type="rule", location_id=person(conn, owner)["location_id"],
        importance=0.5, parent_event_id=loss["event_id"] if loss else None, truth=truth,
        participants=[(owner, "actor")] + ([(guess[0], "suspect")] if guess else []),
        changes=_missing_flag(conn, oid, 1.0) + deltas.changes(conn) + _emotion(conn, owner, "uneasy"),
        memories=memories, claims=[ClaimSpec(lost)],
    )


# -- accuse -------------------------------------------------------------------------------------------------------------
def resolve_accuse(conn: sqlite3.Connection, it: Intent, now: int, trigger: str) -> EventSpec:
    """Say it to their face. The world decides what comes of it:

    caught  it is true and the accuser has strong grounds (saw it, or is quite sure): the item goes back.
    denied  it is true but the grounds are weak: the guilty one lies their way out, the doubt stays.
    false   it is not true: the accused is wronged and bears a grudge; onlookers think less of the accuser.
    """
    a, b = it.actor, it.target
    m = accusation_claim(conn, it.memory_id)
    claim = Claim(m["subject"], m["act"], m["object"], m["polarity"])
    verdict = evaluate(conn, claim)
    true = verdict == TRUE or (verdict == PARTIAL and claim.family == "acquire")
    strong = m["source_type"] == "direct_observation" or m["confidence"] >= 0.7
    outcome = ("caught" if strong else "denied") if true else "false"
    here = person(conn, a)["location_id"]
    names = labels(conn)
    watchers = noticers(conn, here, now, f"accuse:{a}:{b}", LOUD, a, b)
    accused = Claim(a, "accuse", b)
    deltas = RelDeltas()
    changes: list[Change] = []
    claims = [ClaimSpec(accused), ClaimSpec(claim, "asserted")]
    memories = [MemorySpec(p, describe_claim(accused, names) + "：" + describe_claim(claim, names), 1.0, claim=accused)
                for p in (a, b)]
    memories += [MemorySpec(w, describe_claim(accused, names) + "：" + describe_claim(claim, names), 0.9, claim=accused)
                 for w in watchers]
    oid = claim.object if claim.object in {r[0] for r in conn.execute("SELECT id FROM objects")} else None

    if outcome == "caught":
        deltas.add(a, b, "trust", -0.4)
        deltas.add(a, b, "affection", -0.2)
        for w in watchers:
            deltas.add(w, b, "trust", -0.3)
            memories.append(MemorySpec(w, describe_claim(claim, names), 0.9, claim=claim, about_self=False,
                                       source_type="inference", derived_from_events=[m["event_id"]]))
        memories.append(MemorySpec(a, describe_claim(claim, names), 1.0, claim=claim, about_self=False,
                                   source_type="told_by", source_id=b, derived_from_memories=[m["memory_id"]]))
        changes += _emotion(conn, a, "angry") + _emotion(conn, b, "ashamed")
        if oid:
            obj = item(conn, oid)
            if obj["owner_person_id"] == b and obj["rightful_owner_id"] and obj["rightful_owner_id"] != b:
                changes += [Change("object", oid, "owner_person_id", value=obj["rightful_owner_id"])]
                changes += _missing_flag(conn, oid, 0.0)
    elif outcome == "denied":
        denial = Claim(claim.subject, claim.act, claim.object, DENY)
        claims += [ClaimSpec(Claim(b, "deceive", a)), ClaimSpec(denial, "asserted")]
        deltas.add(a, b, "trust", -0.2)
        deltas.add(b, a, "fear", 0.2)
        for w in watchers:
            deltas.add(w, b, "trust", -0.05)
        memories.append(MemorySpec(a, describe_claim(denial, names), 0.4, claim=denial, about_self=False,
                                   source_type="told_by", source_id=b, derived_from_memories=[m["memory_id"]]))
        memories.append(MemorySpec(b, describe_claim(Claim(b, "deceive", a), names), 1.0, claim=Claim(b, "deceive", a)))
        changes += _emotion(conn, a, "angry") + _emotion(conn, b, "uneasy")
    else:
        denial = Claim(claim.subject, claim.act, claim.object, DENY)
        deltas.add(b, a, "trust", -0.4)
        deltas.add(b, a, "affection", -0.2)
        deltas.add(b, a, "rivalry", 0.4)
        for w in watchers:
            deltas.add(w, a, "trust", -0.1)
        memories.append(MemorySpec(a, describe_claim(denial, names), 0.6, claim=denial, about_self=False,
                                   source_type="told_by", source_id=b, derived_from_memories=[m["memory_id"]]))
        changes += _emotion(conn, a, "embarrassed") + _emotion(conn, b, "hurt")

    return EventSpec(
        timestamp=now, type="accuse", trigger_type=trigger, location_id=here, importance={"caught": 0.95, "denied": 0.8, "false": 0.85}[outcome],
        parent_event_id=m["event_id"],
        truth={"actor": a, "target": b, "memory_id": m["memory_id"], "claim_id": m["claim_id"],
               "claim": {"subject": claim.subject, "act": claim.act, "object": claim.object, "polarity": claim.polarity},
               "verdict": verdict, "outcome": outcome, "object": oid, "text": describe_claim(claim, names),
               "depends_on": [m["event_id"]], "reason": it.reason, "source": it.source},
        participants=[(a, "actor"), (b, "target")] + [(w, "witness") for w in watchers],
        changes=deltas.changes(conn) + changes, memories=memories, claims=claims,
    )
