"""Tell and confront: how information moves between people, and what happens when someone is caught out.

The model only ever picks *which* claim to pass on and *how* (a mode) or *whom* to confront. Every number, every
asserted proposition and every verdict below comes from rules and from comparing claims with world truth.
"""
from __future__ import annotations

import json
import sqlite3

from contracts.claim import AFFIRM, DENY, FALSE, PARTIAL, TRUE, UNKNOWN, Claim
from contracts.tell import TellIntent
from world.claims import claim_dict, describe_claim, evaluate, labels, load_claim, truth_claims
from world.confront import find_grounds
from world.events import Change, ClaimSpec, EventSpec, MemorySpec
from world.attention import LOUD, QUIET, noticers
from world.helpers import RelDeltas, person, rel
from world.intent import Intent
from world.tell import asserted_claim, best_memory

# Trust change toward a claim's subject per unit of confidence, for someone who comes to believe the claim.
BELIEF_EFFECT: dict[tuple[str, str], float] = {
    ("steal", AFFIRM): -0.40, ("steal", DENY): 0.15,
    ("take", AFFIRM): -0.20, ("take", DENY): 0.08,
    ("borrow", AFFIRM): -0.03,
    ("speak_hostile", AFFIRM): -0.15, ("speak_hostile", DENY): 0.05,
    ("speak_cold", AFFIRM): -0.06,
    ("speak_warm", AFFIRM): 0.05, ("speak_warm", DENY): -0.03,
    ("deceive", AFFIRM): -0.45, ("deceive", DENY): 0.10,
    ("conceal", AFFIRM): -0.25, ("conceal", DENY): 0.05,
}
TELL_IMPORTANCE = {"truth": 0.30, "omission": 0.35, "distortion": 0.45, "lie": 0.50}
WITNESS_CONFIDENCE = 0.6

# outcome -> (accuser trust in accused, accuser affection, accused trust in accuser, accused fear of accuser,
#             accuser emotion, accused emotion, importance)
OUTCOME_EFFECT: dict[str, tuple[float, float, float, float, str, str, float]] = {
    "lie_exposed": (-0.60, -0.30, -0.10, 0.10, "angry", "ashamed", 0.95),
    "distortion_exposed": (-0.35, -0.15, -0.05, 0.05, "hurt", "uneasy", 0.85),
    "concealment_exposed": (-0.25, -0.10, -0.05, 0.0, "hurt", "uneasy", 0.70),
    "misinformed": (-0.05, 0.0, 0.0, 0.0, "uneasy", "uneasy", 0.50),
    "unfounded": (0.10, 0.0, -0.30, 0.0, "embarrassed", "hurt", 0.70),
    "inconclusive": (-0.05, 0.0, -0.05, 0.0, "uneasy", "uneasy", 0.40),
}
EXPOSED_DECEPTION = {"lie_exposed": "deceive", "distortion_exposed": "deceive", "concealment_exposed": "conceal"}


def belief_effect(claim: Claim) -> float:
    return BELIEF_EFFECT.get((claim.act, claim.polarity), 0.0)


def listener_confidence(trust_in_speaker: float) -> float:
    """How much a listener believes what they are told: more if they trust the speaker, never certain."""
    return round(min(0.95, max(0.10, 0.55 + 0.40 * trust_in_speaker)), 2)


def incident_of(conn: sqlite3.Connection, event_id: int) -> int:
    """The original event a chain of telling and confronting is about (an event is its own incident by default)."""
    row = conn.execute("SELECT json_extract(truth, '$.incident') FROM events WHERE event_id = ?", (event_id,)).fetchone()
    return int(row[0]) if row and row[0] is not None else event_id


def _emotion_change(conn: sqlite3.Connection, pid: str, emotion: str) -> list[Change]:
    return [Change("person", pid, "emotion", value=emotion)] if person(conn, pid)["emotion"] != emotion else []


def resolve_tell(conn: sqlite3.Connection, it: Intent, now: int, trigger: str) -> EventSpec:
    a, b = it.actor, it.target
    t = TellIntent(a, b, it.mode, it.claim_id, list(it.withheld))
    src = best_memory(conn, a, t.source_claim_id)
    asserted = asserted_claim(conn, t)
    about = src["about_event_id"] if src["about_event_id"] is not None else src["event_id"]
    names = labels(conn)
    here = person(conn, a)["location_id"]
    confidence = listener_confidence(rel(conn, b, a, "trust"))

    verdict = evaluate(conn, asserted, about)
    deceived = t.mode in ("lie", "distortion") and verdict in (FALSE, PARTIAL)
    concealed = t.mode == "omission"

    deltas = RelDeltas()
    deltas.add(b, a, "trust", 0.02)  # being confided in builds a little trust and warmth
    deltas.add(b, a, "affection", 0.03)
    flipped = False
    subject = asserted.subject
    if subject != b and conn.execute("SELECT 1 FROM people WHERE id = ?", (subject,)).fetchone():
        effect = belief_effect(asserted) * confidence
        if effect:
            before = rel(conn, b, subject, "trust")
            deltas.add(b, subject, "trust", effect)
            flipped = before * (before + effect) < 0 and abs(effect) > 0.05
    changes = deltas.changes(conn)

    tell_claim = Claim(a, "tell", b)
    memories = [
        MemorySpec(b, describe_claim(tell_claim, names), 1.0, claim=tell_claim),
        MemorySpec(b, describe_claim(asserted, names), confidence, claim=asserted, about_self=False,
                   about_event_id=about, source_type="told_by", source_id=a, derived_from_memories=[src["memory_id"]]),
        MemorySpec(a, describe_claim(tell_claim, names), 1.0, claim=tell_claim),
    ]
    claims = [ClaimSpec(tell_claim, "truth")]
    if deceived:
        own = Claim(a, "deceive", b)
        claims.append(ClaimSpec(own, "truth"))
        memories.append(MemorySpec(a, describe_claim(own, names), 1.0, claim=own))
    elif concealed:
        own = Claim(a, "conceal", b)
        claims.append(ClaimSpec(own, "truth"))
        memories.append(MemorySpec(a, describe_claim(own, names), 1.0, claim=own))
    claims.append(ClaimSpec(asserted, "asserted"))
    for cid in t.withheld_claim_ids:
        claims.append(ClaimSpec(load_claim(conn, cid), "withheld"))
    overheard = noticers(conn, here, now, f"tell:{a}:{b}:{t.source_claim_id}", QUIET, a, b)
    memories += [MemorySpec(w, describe_claim(tell_claim, names), WITNESS_CONFIDENCE, claim=tell_claim)
                 for w in overheard]

    return EventSpec(
        timestamp=now, trigger_type=trigger, location_id=here, type="tell", parent_event_id=src["event_id"],
        importance=min(0.95, TELL_IMPORTANCE[t.mode] + (0.30 if flipped else 0.0)),
        truth={
            "actor": a, "target": b, "mode": t.mode, "reason": it.reason, "source": it.source,
            "source_claim": t.source_claim_id, "asserted_claim": claim_dict(asserted), "verdict": verdict,
            "incident": incident_of(conn, about), "depends_on": sorted({src["event_id"], about}),
            "listener_confidence": confidence, "trust_flipped": flipped,
            "text": describe_claim(asserted, names),
            "withheld_text": [describe_claim(load_claim(conn, cid), names) for cid in t.withheld_claim_ids],
        },
        participants=[(a, "actor"), (b, "target")] + [(w, "witness") for w in overheard],
        changes=changes, memories=memories, claims=claims,
    )


def classify_confrontation(verdict: str, tell_mode: str | None, withheld: list[int]) -> str:
    if verdict in (FALSE, PARTIAL):
        if tell_mode in ("lie", "distortion"):
            return "lie_exposed" if verdict == FALSE else "distortion_exposed"
        return "misinformed"  # they passed on something false without meaning to
    if verdict == TRUE:
        return "concealment_exposed" if withheld else "unfounded"
    return "inconclusive"


def resolve_confront(conn: sqlite3.Connection, it: Intent, now: int, trigger: str) -> EventSpec:
    a, b = it.actor, it.target
    m1 = conn.execute("SELECT * FROM memories WHERE memory_id = ?", (it.memory_id,)).fetchone()
    c1 = load_claim(conn, m1["claim_id"])
    tell_event, e0 = m1["event_id"], m1["about_event_id"]
    tell_truth = json.loads(conn.execute("SELECT truth FROM events WHERE event_id = ?", (tell_event,)).fetchone()[0])
    withheld = [r[0] for r in conn.execute(
        "SELECT claim_id FROM event_claims WHERE event_id = ? AND role = 'withheld' ORDER BY claim_id", (tell_event,))]
    grounds = find_grounds(conn, a, c1, it.memory_id)
    verdict = evaluate(conn, c1, e0)
    outcome = classify_confrontation(verdict, tell_truth.get("mode"), withheld)
    a_trust, a_aff, b_trust, b_fear, emo_a, emo_b, importance = OUTCOME_EFFECT[outcome]

    names = labels(conn)
    here = person(conn, a)["location_id"]
    watchers = noticers(conn, here, now, f"confront:{a}:{b}", LOUD, a, b)
    deceit = EXPOSED_DECEPTION.get(outcome)

    deltas = RelDeltas()
    deltas.add(a, b, "trust", a_trust)
    deltas.add(a, b, "affection", a_aff)
    deltas.add(b, a, "trust", b_trust)
    deltas.add(b, a, "fear", b_fear)
    if deceit:
        for w in watchers:  # onlookers draw their own conclusion about the one who was caught
            deltas.add(w, b, "trust", belief_effect(Claim(b, deceit, a)) * WITNESS_CONFIDENCE)
    before = rel(conn, a, b, "trust")
    changes = deltas.changes(conn) + _emotion_change(conn, a, emo_a) + _emotion_change(conn, b, emo_b)
    flipped = before * (before + a_trust) < 0

    confront_claim = Claim(a, "confront", b)
    memories = [MemorySpec(a, describe_claim(confront_claim, names), 1.0, claim=confront_claim),
                MemorySpec(b, describe_claim(confront_claim, names), 1.0, claim=confront_claim)]
    claims = [ClaimSpec(confront_claim, "truth")]
    incident = incident_of(conn, e0 if e0 is not None else tell_event)

    def learn(pid: str, claim: Claim, conf: float, source_type: str, source: str | None, about: int | None,
              memory_ids: list[int], event_ids: list[int]) -> MemorySpec:
        return MemorySpec(pid, describe_claim(claim, names), conf, claim=claim, about_self=False, about_event_id=about,
                          source_type=source_type, source_id=source, derived_from_memories=memory_ids,
                          derived_from_events=event_ids)

    src_events = [e for e in (tell_event, e0) if e is not None]
    truths = truth_claims(conn, e0) if e0 is not None else []  # only ever the events this belief is about
    if outcome in ("lie_exposed", "distortion_exposed"):
        for tc in truths:  # the caught one comes clean about what really happened
            memories.append(learn(a, tc, 0.9, "told_by", b, e0, [it.memory_id], src_events))
        memories.append(learn(a, Claim(b, "deceive", a), 0.95, "inference", None, None,
                              [it.memory_id, grounds["memory_id"]], []))
    elif outcome == "concealment_exposed":
        for cid in withheld:
            wm = best_memory(conn, b, cid)
            memories.append(learn(a, load_claim(conn, cid), 0.85, "told_by", b,
                                  wm["about_event_id"] if wm and wm["about_event_id"] is not None else tell_event,
                                  [it.memory_id], [tell_event]))
        memories.append(learn(a, Claim(b, "conceal", a), 0.9, "inference", None, None, [it.memory_id], []))
    elif outcome == "unfounded":
        memories.append(learn(a, c1, 0.85, "told_by", b, e0, [it.memory_id], src_events))
    elif outcome == "misinformed":
        for tc in truths:
            memories.append(learn(a, tc, 0.85, "inference", None, e0, [it.memory_id, grounds["memory_id"]], src_events))
            memories.append(learn(b, tc, 0.8, "told_by", a, e0, [], src_events))

    if deceit:
        claims.append(ClaimSpec(Claim(b, deceit, a), "truth"))
        for w in watchers:
            memories.append(MemorySpec(w, describe_claim(Claim(b, deceit, a), names), WITNESS_CONFIDENCE,
                                       claim=Claim(b, deceit, a), source_type="inference",
                                       derived_from_events=[tell_event]))
    memories += [MemorySpec(w, describe_claim(confront_claim, names), 0.9, claim=confront_claim) for w in watchers]

    return EventSpec(
        timestamp=now, trigger_type=trigger, location_id=here, type="confront", parent_event_id=tell_event,
        importance=importance,
        truth={
            "actor": a, "target": b, "memory_id": it.memory_id, "claim_id": m1["claim_id"], "claim": claim_dict(c1),
            "outcome": outcome,
            "verdict": verdict, "tell_event": tell_event, "grounds_memory_id": grounds["memory_id"],
            "incident": incident, "depends_on": sorted({e for e in (tell_event, e0, grounds["event_id"]) if e is not None}),
            "reason": it.reason, "source": it.source, "trust_flipped": flipped, "text": describe_claim(c1, names),
        },
        participants=[(a, "actor"), (b, "target")] + [(w, "witness") for w in watchers],
        changes=changes, memories=memories, claims=claims,
    )
