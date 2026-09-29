from __future__ import annotations

import sqlite3

from contracts.claim import Claim
from world.events import Change, ClaimSpec, EventSpec, MemorySpec
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


def clamp_delta(current: float, delta: float, lo: float, hi: float) -> float:
    return round(min(hi, max(lo, current + delta)) - current, 6)


def _person(conn: sqlite3.Connection, pid: str) -> sqlite3.Row:
    return conn.execute("SELECT * FROM people WHERE id = ?", (pid,)).fetchone()


def _rel(conn: sqlite3.Connection, actor: str, target: str, field: str) -> float:
    return conn.execute(
        f"SELECT {field} FROM relationships WHERE actor_id = ? AND target_id = ?", (actor, target)
    ).fetchone()[0]


def last_event_between(conn: sqlite3.Connection, a: str, b: str) -> int | None:
    """Most recent social event where both were principals (not mere witnesses): the causal parent."""
    return conn.execute(
        "SELECT MAX(e.event_id) FROM events e "
        "JOIN event_participants p1 ON p1.event_id = e.event_id AND p1.person_id = ? "
        "  AND p1.role IN ('actor', 'target', 'victim') "
        "JOIN event_participants p2 ON p2.event_id = e.event_id AND p2.person_id = ? "
        "  AND p2.role IN ('actor', 'target', 'victim') "
        "WHERE e.type IN ('talk', 'steal')",
        (a, b),
    ).fetchone()[0]


def _trust_change(conn: sqlite3.Connection, observer: str, subject: str, delta: float) -> Change | None:
    d = clamp_delta(_rel(conn, observer, subject, "trust"), delta, -1.0, 1.0)
    return Change("relationship", f"{observer}:{subject}", "trust", delta=d) if d else None


def resolve(conn: sqlite3.Connection, it: Intent, now: int, trigger: str) -> EventSpec:
    """Deterministic consequences of a validated intent. The model never chooses any numbers."""
    actor = _person(conn, it.actor)
    here = actor["location_id"]
    base = dict(timestamp=now, trigger_type=trigger, location_id=here)

    if it.action == "move":
        return EventSpec(
            **{**base, "location_id": it.target}, type="move", importance=0.05,
            truth={"actor": it.actor, "from": here, "to": it.target},
            participants=[(it.actor, "actor")],
            changes=[
                Change("person", it.actor, "location_id", value=it.target),
                Change("person", it.actor, "energy", delta=-clamp_neg(actor["energy"], 2)),
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
    return _steal(conn, it, base)


def clamp_neg(current: int, amount: int) -> int:
    return min(current, amount)


def _bystanders(conn: sqlite3.Connection, here: str, *exclude: str) -> list[str]:
    rows = conn.execute("SELECT id FROM people WHERE location_id = ? ORDER BY id", (here,)).fetchall()
    return [r["id"] for r in rows if r["id"] not in exclude]


def _talk(conn: sqlite3.Connection, it: Intent, base: dict) -> EventSpec:
    a, b, tone = it.actor, it.target, it.tone
    d_trust, d_aff, d_aff_self = TONE_EFFECT[tone]
    old_trust = _rel(conn, b, a, "trust")
    trust_delta = clamp_delta(old_trust, d_trust, -1.0, 1.0)
    flipped = old_trust * (old_trust + trust_delta) < 0

    changes: list[Change] = []
    if trust_delta:
        changes.append(Change("relationship", f"{b}:{a}", "trust", delta=trust_delta))
    for who, other, delta in ((b, a, d_aff), (a, b, d_aff_self)):
        d = clamp_delta(_rel(conn, who, other, "affection"), delta, -1.0, 1.0)
        if d:
            changes.append(Change("relationship", f"{who}:{other}", "affection", delta=d))
    if tone in TONE_EMOTION and _person(conn, b)["emotion"] != TONE_EMOTION[tone]:
        changes.append(Change("person", b, "emotion", value=TONE_EMOTION[tone]))

    claim = Claim(a, f"speak_{tone}", b)
    memories = [
        MemorySpec(b, f"{a} spoke {tone}ly to me", 0.9, claim=claim),
        MemorySpec(a, f"I spoke {tone}ly to {b}", 1.0, claim=claim),
    ] + [MemorySpec(w, f"{a} spoke {tone}ly to {b}", 0.6, claim=claim)
         for w in _bystanders(conn, base["location_id"], a, b)]

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
    witnesses = _bystanders(conn, base["location_id"], thief, owner)

    changes = [Change("object", obj["id"], "owner_person_id", value=thief)]
    for observer, delta in [(owner, STEAL_TRUST_OWNER)] + [(w, STEAL_TRUST_WITNESS) for w in witnesses]:
        ch = _trust_change(conn, observer, thief, delta)
        if ch:
            changes.append(ch)
    claim = Claim(thief, "steal", obj["id"])
    memories = [
        MemorySpec(owner, f"{thief} took my {obj['name']}", 0.95, claim=claim),
        MemorySpec(thief, f"I took {owner}'s {obj['name']}", 1.0, claim=claim),
    ] + [MemorySpec(w, f"{thief} took {owner}'s {obj['name']}", 0.8, claim=claim) for w in witnesses]

    return EventSpec(
        **base, type="steal", parent_event_id=last_event_between(conn, thief, owner), importance=0.8,
        truth={"actor": thief, "victim": owner, "object": obj["id"], "reason": it.reason, "source": it.source},
        participants=[(thief, "actor"), (owner, "victim")] + [(w, "witness") for w in witnesses],
        changes=changes, memories=memories,
        claims=[ClaimSpec(claim)],
    )
