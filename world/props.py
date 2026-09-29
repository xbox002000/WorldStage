"""What props do on their own, once an outside event has brought them in. These are world rules, not plot:

parrot  repeats, once, the last quiet claim spoken where it lives, to everyone there;
dog     eats: whoever keeps it pays for its food each night;
ticket  a holder of a winning ticket cashes it overnight.
"""
from __future__ import annotations

import sqlite3

from contracts.claim import Claim
from world.attention import LOUD, noticers, present
from world.claims import describe_claim, labels
from world.events import Change, ClaimSpec, EventSpec, MemorySpec

DOG_FOOD_CENTS = 300


def _home(conn: sqlite3.Connection, pid: str) -> str:
    from world.content import home_of
    return home_of(conn, pid)


def parrot_events(conn: sqlite3.Connection, now: int) -> list[EventSpec]:
    out = []
    for obj in conn.execute("SELECT * FROM objects WHERE status = 'normal' AND location_id IS NOT NULL "
                            "AND tags LIKE '%\"repeater\"%' ORDER BY id").fetchall():
        here = obj["location_id"]
        if not present(conn, here):
            continue
        said = conn.execute(
            "SELECT e.event_id, c.subject, c.act, c.object, c.polarity FROM events e "
            "JOIN event_claims ec ON ec.event_id = e.event_id AND ec.role = 'asserted' JOIN claims c USING (claim_id) "
            "WHERE e.type = 'tell' AND e.location_id = ? AND e.timestamp >= ? "
            "AND NOT EXISTS (SELECT 1 FROM events p WHERE p.type = 'parrot_speaks' "
            "  AND json_extract(p.truth, '$.repeats') = e.event_id) ORDER BY e.event_id DESC LIMIT 1",
            (here, now - 2 * 1440)).fetchone()
        if said is None:
            continue
        claim = Claim(said["subject"], said["act"], said["object"], said["polarity"])
        names = labels(conn)
        text = describe_claim(claim, names)
        heard = noticers(conn, here, now, f"parrot:{said['event_id']}", LOUD)
        out.append(EventSpec(
            timestamp=now, type="parrot_speaks", trigger_type="rule", location_id=here, importance=0.55,
            parent_event_id=said["event_id"],
            truth={"object": obj["id"], "repeats": said["event_id"], "text": f"鸚鵡大聲學舌：「{text}」",
                   "claim": {"subject": claim.subject, "act": claim.act, "object": claim.object, "polarity": claim.polarity},
                   "depends_on": [said["event_id"]]},
            participants=[(p, "witness") for p in heard],
            memories=[MemorySpec(p, text, 0.4, claim=claim, about_self=False, about_event_id=said["event_id"],
                                 source_type="external_rumor", source_id=obj["id"]) for p in heard],
        ))
    return out


def feed_animals(conn: sqlite3.Connection, now: int) -> list[EventSpec]:
    """An animal that has attached itself to someone is fed by them: it costs them, and binds it closer."""
    from world.animals import animal_ids, keeper
    out = []
    for a in sorted(animal_ids(conn)):
        if conn.execute("SELECT status FROM people WHERE id = ?", (a,)).fetchone()[0] == "inactive":
            continue
        k = keeper(conn, a)
        if k is None:
            continue
        money = conn.execute("SELECT money_cents FROM people WHERE id = ?", (k,)).fetchone()[0]
        cost = min(money, DOG_FOOD_CENTS)
        aff = conn.execute("SELECT affection FROM relationships WHERE actor_id = ? AND target_id = ?", (a, k)).fetchone()[0]
        changes = [Change("relationship", f"{a}:{k}", "affection", delta=round(min(1.0, aff + 0.05) - aff, 6))]
        if cost:
            changes.append(Change("person", k, "money_cents", delta=-cost))
        out.append(EventSpec(timestamp=now, type="feed_pet", trigger_type="rule", location_id=None, importance=0.05,
                             truth={"actor": k, "object": a, "cost_cents": cost}, participants=[(k, "actor"), (a, "target")],
                             changes=[c for c in changes if c.delta]))
    return out


def overnight(conn: sqlite3.Connection, pid: str, now: int) -> list[EventSpec]:
    """Props a person holds that do something overnight."""
    out = []
    names = labels(conn)
    for obj in conn.execute("SELECT * FROM objects WHERE owner_person_id = ? AND status = 'normal' ORDER BY id", (pid,)):
        money = conn.execute("SELECT money_cents FROM people WHERE id = ?", (pid,)).fetchone()[0]
        if obj["id"] == "dog" and money > 0:
            out.append(EventSpec(
                timestamp=now, type="feed_pet", trigger_type="rule", location_id=_home(conn, pid), importance=0.05,
                truth={"actor": pid, "object": "dog", "cost_cents": min(money, DOG_FOOD_CENTS)},
                participants=[(pid, "actor")],
                changes=[Change("person", pid, "money_cents", delta=-min(money, DOG_FOOD_CENTS))]))
        elif obj["id"] == "ticket" and obj["value_cents"] > 0:
            won = Claim(pid, "win", "ticket")
            out.append(EventSpec(
                timestamp=now, type="cash_prize", trigger_type="rule", location_id=_home(conn, pid), importance=0.8,
                parent_event_id=conn.execute("SELECT MAX(event_id) FROM events WHERE json_extract(truth, '$.object') = 'ticket'").fetchone()[0],
                truth={"actor": pid, "object": "ticket", "amount_cents": obj["value_cents"]},
                participants=[(pid, "actor")],
                changes=[Change("person", pid, "money_cents", delta=obj["value_cents"]),
                         Change("object", "ticket", "status", value="spent"),
                         Change("object", "ticket", "owner_person_id", value=None),
                         Change("person", pid, "emotion", value="happy")],
                memories=[MemorySpec(pid, describe_claim(won, names), 1.0, claim=won)],
                claims=[ClaimSpec(won)]))
    return out
