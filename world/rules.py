from __future__ import annotations

import sqlite3
from dataclasses import replace

from contracts.claim import Claim
from world.claims import describe_claim, labels
from world.events import Change, ClaimSpec, EventSpec, MemorySpec
from world.attention import LOUD, NORMAL, noticers, var, world_seed
from world.helpers import clamp_delta, last_event_between, person, rel, trust_change, trust_reversed
from world.intent import WORK_ENERGY, Intent, food_price
from world.rng import rng as make_rng

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
OWNER_NOTICES_THEFT = 0.7  # a pickpocket can go unnoticed; the loss is then found at night


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
                Change("person", it.actor, "money_cents", delta=-food_price(conn)),
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
    if it.action == "drop":
        from world.items import misplace
        return replace(misplace(conn, it.actor, it.target, now), trigger_type=trigger,
                       truth={**misplace(conn, it.actor, it.target, now).truth, "reason": it.reason, "dropped": True})
    if it.action == "bark":
        return _bark(conn, it, base)
    if it.action in ("train", "challenge"):
        from world import jianghu
        return (jianghu.resolve_train if it.action == "train" else jianghu.resolve_challenge)(conn, it, now, trigger)
    if it.action in ("take", "give", "accuse"):
        from world import items
        return {"take": items.resolve_take, "give": items.resolve_give, "accuse": items.resolve_accuse}[it.action](
            conn, it, now, trigger)
    if it.action in ("lend", "repay"):
        from world import money
        return (money.resolve_lend if it.action == "lend" else money.resolve_repay)(conn, it, now, trigger)
    return _steal(conn, it, base)


def _talk(conn: sqlite3.Connection, it: Intent, base: dict) -> EventSpec:
    a, b, tone = it.actor, it.target, it.tone
    d_trust, d_aff, d_aff_self = TONE_EFFECT[tone]
    old_trust = rel(conn, b, a, "trust")
    trust_delta = clamp_delta(old_trust, d_trust, -1.0, 1.0)
    flipped = trust_reversed(conn, b, a, trust_delta)

    changes: list[Change] = []
    if trust_delta:
        changes.append(Change("relationship", f"{b}:{a}", "trust", delta=trust_delta))
    for who, other, delta in ((b, a, d_aff), (a, b, d_aff_self)):
        d = clamp_delta(rel(conn, who, other, "affection"), delta, -1.0, 1.0)
        if d:
            changes.append(Change("relationship", f"{who}:{other}", "affection", delta=d))
    owed = conn.execute("SELECT debt_cents FROM relationships WHERE actor_id = ? AND target_id = ?", (b, a)).fetchone()
    if owed and owed[0] > 0 and tone in ("cold", "hostile"):
        d = clamp_delta(rel(conn, b, a, "fear"), 0.1 if tone == "cold" else 0.2, -1.0, 1.0)
        if d:
            changes.append(Change("relationship", f"{b}:{a}", "fear", delta=d))
    if tone in TONE_EMOTION and person(conn, b)["emotion"] != TONE_EMOTION[tone]:
        changes.append(Change("person", b, "emotion", value=TONE_EMOTION[tone]))

    claim = Claim(a, f"speak_{tone}", b)
    text = describe_claim(claim, labels(conn))
    watchers = noticers(conn, base["location_id"], base["timestamp"], f"talk:{a}:{b}",
                        LOUD if tone == "hostile" else NORMAL, a, b)
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


def _bark(conn: sqlite3.Connection, it: Intent, base: dict) -> EventSpec:
    """Loud: everyone there hears a dog barking at someone. People make of it what they will (no claim)."""
    names = labels(conn)
    heard = noticers(conn, base["location_id"], base["timestamp"], f"bark:{it.actor}:{it.target}", LOUD, it.actor, it.target)
    text = f"{names.get(it.actor, it.actor)}對著{names.get(it.target, it.target)}狂吠"
    ch = [c for c in [clamp_delta(rel(conn, it.target, it.actor, "fear"), 0.05, -1.0, 1.0)] if c]
    return EventSpec(
        **base, type="bark", importance=0.3, parent_event_id=last_event_between(conn, it.actor, it.target),
        truth={"actor": it.actor, "target": it.target, "reason": it.reason, "text": text},
        participants=[(it.actor, "actor"), (it.target, "target")] + [(w, "witness") for w in heard],
        changes=[Change("relationship", f"{it.target}:{it.actor}", "fear", delta=ch[0])] if ch else [],
        memories=[MemorySpec(p, text, 0.9) for p in [it.target] + heard],
    )


def _steal(conn: sqlite3.Connection, it: Intent, base: dict) -> EventSpec:
    obj = conn.execute("SELECT * FROM objects WHERE id = ?", (it.target,)).fetchone()
    owner, thief = obj["owner_person_id"], it.actor
    key = f"steal:{thief}:{obj['id']}"
    owner_noticed = make_rng(world_seed(conn), base["timestamp"], key, "owner_notices").random() < (
        OWNER_NOTICES_THEFT * var(conn, "visibility", 1.0))
    witnesses = noticers(conn, base["location_id"], base["timestamp"], key, NORMAL, thief, owner)

    changes = [Change("object", obj["id"], "owner_person_id", value=thief)]
    observers = ([(owner, STEAL_TRUST_OWNER)] if owner_noticed else []) + [(w, STEAL_TRUST_WITNESS) for w in witnesses]
    for observer, delta in observers:
        ch = trust_change(conn, observer, thief, delta)
        if ch:
            changes.append(ch)
    claim = Claim(thief, "steal", obj["id"])
    text = describe_claim(claim, labels(conn))
    memories = ([MemorySpec(owner, text, 0.95, claim=claim)] if owner_noticed else []) + [
        MemorySpec(thief, text, 1.0, claim=claim),
    ] + [MemorySpec(w, text, 0.8, claim=claim) for w in witnesses]

    return EventSpec(
        **base, type="steal", parent_event_id=last_event_between(conn, thief, owner), importance=0.8,
        truth={"actor": thief, "victim": owner, "object": obj["id"], "reason": it.reason, "source": it.source,
               "owner_noticed": owner_noticed, "witnessed": bool(witnesses) or owner_noticed},
        participants=[(thief, "actor"), (owner, "victim")] + [(w, "witness") for w in witnesses],
        changes=changes, memories=memories,
        claims=[ClaimSpec(claim)],
    )
