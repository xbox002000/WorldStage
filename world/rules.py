from __future__ import annotations

import sqlite3

from contracts.claim import Claim
from world.claims import describe_claim, labels
from world.events import Change, ClaimSpec, EventSpec, MemorySpec
from world.helpers import bystanders, clamp_delta, last_event_between, person, rel, trust_change  # noqa: F401
from world.intent import EAT_COST_CENTS, WORK_ENERGY, Intent

# tone -> (target's trust in actor, target's affection for actor, actor's affection for target)
TONE_EFFECT = {
    "warm": (0.15, 0.10, 0.05),
    "neutral": (0.02, 0.0, 0.0),
    "cold": (-0.12, -0.05, -0.02),
    "hostile": (-0.35, -0.15, -0.05),
}
TONE_IMPORTANCE = {"warm": 0.3, "neutral": 0.15, "cold": 0.4, "hostile": 0.6}
TONE_EMOTION = {"warm": "happy", "cold": "hurt", "hostile": "angry"}

STEAL_TRUST_OWNER = -0.5
STEAL_TRUST_WITNESS = -0.2


def resolve(conn: sqlite3.Connection, it: Intent, now: int, trigger: str) -> EventSpec:
    """Deterministic consequences of a validated intent. The model never chooses any numbers."""
    actor = person(conn, it.actor)
    here = actor["location_id"]
    base = dict(timestamp=now, trigger_type=trigger, location_id=here)

    if it.action == "move":
        return EventSpec(
            **{**base, "location_id": it.target}, type="move", importance=0.05,
            truth={"actor": it.actor, "from": here, "to": it.target},
            participants=[(it.actor, "actor")],
            changes=[
                Change("person", it.actor, "location_id", value=it.target),
                Change("person", it.actor, "energy", delta=-min(actor["energy"], 2)),
            ],
        )
    if it.action == "eat":
        return EventSpec(
            **base, type="eat", importance=0.1, truth={"actor": it.actor},
            participants=[(it.actor, "actor")],
            changes=[
                Change("person", it.actor, "money_cents", delta=-EAT_COST_CENTS),
                Change("person", it.actor, "hunger", delta=-min(40, actor["hunger"])),
            ],
        )
    if it.action == "work":
        return EventSpec(
            **base, type="work", importance=0.1, truth={"actor": it.actor},
            participants=[(it.actor, "actor")],
            changes=[
                Change("person", it.actor, "money_cents", delta=1500),
                Change("person", it.actor, "energy", delta=-WORK_ENERGY),
            ],
        )
    if it.action == "rest":
        gain = min(25, 100 - actor["energy"])
        return EventSpec(
            **base, type="rest", importance=0.05, truth={"actor": it.actor},
            participants=[(it.actor, "actor")],
            changes=[Change("person", it.actor, "energy", delta=gain)] if gain else [],
        )
    if it.action == "talk":
        return _talk(conn, it, base)
    if it.action == "tell":
        from world.social import resolve_tell
        return resolve_tell(conn, it, now, trigger)
    if it.action == "confront":
        from world.social import resolve_confront
        return resolve_confront(conn, it, now, trigger)
    return _steal(conn, it, base)


def _talk(conn: sqlite3.Connection, it: Intent, base: dict) -> EventSpec:
    a, b, tone = it.actor, it.target, it.tone
    d_trust, d_aff, d_aff_self = TONE_EFFECT[tone]
    old_trust = rel(conn, b, a, "trust")
    trust_delta = clamp_delta(old_trust, d_trust, -1.0, 1.0)
    flipped = old_trust * (old_trust + trust_delta) < 0

    changes: list[Change] = []
    if trust_delta:
        changes.append(Change("relationship", f"{b}:{a}", "trust", delta=trust_delta))
    for who, other, delta in ((b, a, d_aff), (a, b, d_aff_self)):
        d = clamp_delta(rel(conn, who, other, "affection"), delta, -1.0, 1.0)
        if d:
            changes.append(Change("relationship", f"{who}:{other}", "affection", delta=d))
    if tone in TONE_EMOTION and person(conn, b)["emotion"] != TONE_EMOTION[tone]:
        changes.append(Change("person", b, "emotion", value=TONE_EMOTION[tone]))

    claim = Claim(a, f"speak_{tone}", b)
    text = describe_claim(claim, labels(conn))
    watchers = bystanders(conn, base["location_id"], a, b)
    memories = [
        MemorySpec(b, text, 0.9, claim=claim),
        MemorySpec(a, text, 1.0, claim=claim),
    ] + [MemorySpec(w, text, 0.6, claim=claim) for w in watchers]

    return EventSpec(
        **base, type="talk", parent_event_id=last_event_between(conn, a, b),
        importance=0.85 if flipped else TONE_IMPORTANCE[tone],
        truth={"actor": a, "target": b, "tone": tone, "reason": it.reason, "source": it.source, "trust_flipped": flipped},
        participants=[(a, "actor"), (b, "target")], changes=changes, memories=memories,
        claims=[ClaimSpec(claim)],
    )


def _steal(conn: sqlite3.Connection, it: Intent, base: dict) -> EventSpec:
    obj = conn.execute("SELECT * FROM objects WHERE id = ?", (it.target,)).fetchone()
    owner, thief = obj["owner_person_id"], it.actor
    witnesses = bystanders(conn, base["location_id"], thief, owner)

    changes = [Change("object", obj["id"], "owner_person_id", value=thief)]
    for observer, delta in [(owner, STEAL_TRUST_OWNER)] + [(w, STEAL_TRUST_WITNESS) for w in witnesses]:
        ch = trust_change(conn, observer, thief, delta)
        if ch:
            changes.append(ch)
    claim = Claim(thief, "steal", obj["id"])
    text = describe_claim(claim, labels(conn))
    memories = [
        MemorySpec(owner, text, 0.95, claim=claim),
        MemorySpec(thief, text, 1.0, claim=claim),
    ] + [MemorySpec(w, text, 0.8, claim=claim) for w in witnesses]

    return EventSpec(
        **base, type="steal", parent_event_id=last_event_between(conn, thief, owner), importance=0.8,
        truth={"actor": thief, "victim": owner, "object": obj["id"], "reason": it.reason, "source": it.source},
        participants=[(thief, "actor"), (owner, "victim")] + [(w, "witness") for w in witnesses],
        changes=changes, memories=memories,
        claims=[ClaimSpec(claim)],
    )
