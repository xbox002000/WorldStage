"""Jianghu primitives: martial_arts (skill that training raises), reputation (public standing), duel (settled by skill
and luck), sect_factions (loyalty and grudges between sects). Each runs only when the world's recipe enables it.

Reputation is public: everyone can read `rep.<person>`, so it needs no claims. It moves when the world makes a
spectacle of someone: caught red-handed, a lie exposed, a false accusation, a duel. A duel between known fighters
moves it most. Sect loyalty is a reflex: a sect-mate beaten or wrongly accused in front of you makes you bristle at
whoever did it.
"""
from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import replace

from contracts.claim import Claim
from world.attention import LOUD, noticers, var
from world.claims import describe_claim, labels
from world.events import Change, ClaimSpec, EventSpec, MemorySpec
from world.helpers import RelDeltas, clamp_delta, last_event_between, person, rel
from world.intent import Intent
from world.rng import rng as make_rng
from world.state import WorldError

TRAIN_ENERGY = 15
DUEL_ENERGY = 30
DUEL_SHARPNESS = 8.0  # how much a skill gap decides a duel (logistic slope)
DUEL_COOLDOWN_DAYS = 3
INJURY_DAYS = 2  # the loser of a duel is hurt: nobody fights them, and they fight nobody, until it heals
FIGHTER = 0.2  # below this skill someone is not a fighter: nobody honourable duels them
BULLY_GAP = 0.25  # beating someone this much weaker is no glory, it is shame


def skill(conn: sqlite3.Connection, pid: str) -> float:
    return var(conn, f"skill.{pid}", 0.0)


def rep(conn: sqlite3.Connection, pid: str) -> float:
    return var(conn, f"rep.{pid}", 0.5)


def sect(conn: sqlite3.Connection, pid: str) -> str:
    row = conn.execute("SELECT json_extract(traits, '$.sect') FROM personas WHERE person_id = ?", (pid,)).fetchone()
    return row[0] or "" if row else ""


def sect_mates(conn: sqlite3.Connection, pid: str, among: list[str]) -> list[str]:
    s = sect(conn, pid)
    return [p for p in among if s and p != pid and sect(conn, p) == s]


def _var_change(conn: sqlite3.Connection, key: str, delta: float, lo: float = 0.0, hi: float = 1.0) -> Change | None:
    cur = var(conn, key, None)
    if cur is None:
        return None
    d = round(min(hi, max(lo, cur + delta)) - cur, 6)
    return Change("var", key, "value", delta=d) if d else None


# -- validation -----------------------------------------------------------------------------------------------------
def validate_train(conn: sqlite3.Connection, actor: sqlite3.Row, here_tags: list[str]) -> None:
    from world.recipes import enabled
    if not enabled(conn, "martial_arts"):
        raise WorldError("this world has no martial arts")
    if "training" not in here_tags:
        raise WorldError("nowhere to train here")
    if actor["energy"] < TRAIN_ENERGY:
        raise WorldError("too tired to train")


def validate_challenge(conn: sqlite3.Connection, it: Intent, actor: sqlite3.Row) -> None:
    from world.recipes import enabled
    if not enabled(conn, "duel"):
        raise WorldError("this world has no duels")
    other = person(conn, it.target) if it.target else None
    if other is None or other["id"] == it.actor or other["location_id"] != actor["location_id"]:
        raise WorldError("nobody here to challenge")
    if actor["energy"] < DUEL_ENERGY or other["energy"] < DUEL_ENERGY:
        raise WorldError("too tired for a duel")
    if skill(conn, it.actor) < FIGHTER or skill(conn, it.target) < FIGHTER:
        raise WorldError("one of them is no fighter")
    now = conn.execute("SELECT COALESCE(MAX(timestamp), 0) FROM events").fetchone()[0]
    if recent_duel(conn, it.actor, it.target, now):
        raise WorldError("they fought too recently")
    if injured(conn, it.actor, now) or injured(conn, it.target, now):
        raise WorldError("still hurt from a duel")


def injured(conn: sqlite3.Connection, pid: str, now: int) -> bool:
    return conn.execute("SELECT 1 FROM events WHERE type = 'duel' AND json_extract(truth, '$.loser') = ? AND timestamp > ?",
                        (pid, now - INJURY_DAYS * 1440)).fetchone() is not None


def recent_duel(conn: sqlite3.Connection, a: str, b: str, now: int) -> bool:
    return conn.execute(
        "SELECT 1 FROM events WHERE type = 'duel' AND timestamp > ? AND ((json_extract(truth, '$.actor') = ? AND "
        "json_extract(truth, '$.target') = ?) OR (json_extract(truth, '$.actor') = ? AND json_extract(truth, '$.target') = ?))",
        (now - DUEL_COOLDOWN_DAYS * 1440, a, b, b, a)).fetchone() is not None


# -- resolution -----------------------------------------------------------------------------------------------------
def resolve_train(conn: sqlite3.Connection, it: Intent, now: int, trigger: str) -> EventSpec:
    a = it.actor
    manual = conn.execute("SELECT id FROM objects WHERE owner_person_id = ? AND tags LIKE '%\"manual\"%'", (a,)).fetchone()
    cur = skill(conn, a)
    gain = round(0.006 * (1 - cur) * (2.0 if manual else 1.0), 6)  # slow and diminishing; a manual doubles it
    changes = [Change("person", a, "energy", delta=-min(person(conn, a)["energy"], TRAIN_ENERGY))]
    c = _var_change(conn, f"skill.{a}", gain)
    if c:
        changes.append(c)
    return EventSpec(timestamp=now, type="train", trigger_type=trigger, location_id=person(conn, a)["location_id"],
                     importance=0.1, truth={"actor": a, "gain": gain, "with_manual": bool(manual), "reason": it.reason},
                     participants=[(a, "actor")], changes=changes)


def resolve_challenge(conn: sqlite3.Connection, it: Intent, now: int, trigger: str) -> EventSpec:
    """A duel. The world decides who wins (skill gap and luck); what it costs and proves follows from that."""
    a, b = it.actor, it.target
    here = person(conn, a)["location_id"]
    seed = conn.execute("SELECT value FROM meta WHERE key = 'world_seed'").fetchone()[0]
    p_a = 1.0 / (1.0 + math.exp(-DUEL_SHARPNESS * (skill(conn, a) - skill(conn, b))))
    a_wins = make_rng(seed, now, f"duel:{a}:{b}", "duel").random() < p_a
    winner, loser = (a, b) if a_wins else (b, a)
    names = labels(conn)
    watchers = noticers(conn, here, now, f"duel:{a}:{b}", LOUD, a, b)
    upset = rep(conn, loser) - rep(conn, winner)  # beating someone better known proves more
    bully = winner == a and skill(conn, a) - skill(conn, b) > BULLY_GAP  # picking on the weak is shameful
    expected = loser == a and skill(conn, b) - skill(conn, a) > BULLY_GAP  # losing to a master costs little
    changes: list[Change] = []
    for key, d in ((f"rep.{winner}", (-0.04 if bully else 0.02 + 0.08 * max(0.0, upset))),
                   (f"rep.{loser}", (0.0 if expected else -0.02 - 0.04 * max(0.0, -upset)))):
        c = _var_change(conn, key, d)
        if c:
            changes.append(c)
    changes.append(Change("person", loser, "energy", delta=-min(person(conn, loser)["energy"], 40)))
    changes.append(Change("person", winner, "energy", delta=-min(person(conn, winner)["energy"], 15)))
    for pid, emo in ((winner, "happy"), (loser, "ashamed")):
        if person(conn, pid)["emotion"] != emo:
            changes.append(Change("person", pid, "emotion", value=emo))
    deltas = RelDeltas()
    deltas.add(loser, winner, "rivalry", 0.3)
    deltas.add(winner, loser, "rivalry", -0.1)  # the winner has nothing left to prove against them
    for w in sect_mates(conn, loser, watchers):  # a sect-mate beaten in front of you
        deltas.add(w, winner, "rivalry", 0.15)
    # settling it by the sword: if the winner is the rightful owner of something the loser holds, it goes back
    returned = None
    for o in conn.execute("SELECT id FROM objects WHERE owner_person_id = ? AND rightful_owner_id = ? ORDER BY id",
                          (loser, winner)):
        returned = o["id"]
        changes += [Change("object", o["id"], "owner_person_id", value=winner)]
        miss = _var_change(conn, f"missing.{o['id']}", -1.0)
        if miss:
            changes.append(miss)
        break
    beat = Claim(winner, "defeat", loser)
    text = describe_claim(beat, names)
    memories = [MemorySpec(p, text, 1.0, claim=beat) for p in (a, b)] + [MemorySpec(w, text, 0.95, claim=beat) for w in watchers]
    return EventSpec(
        timestamp=now, type="duel", trigger_type=trigger, location_id=here, importance=0.85 if returned else 0.75,
        parent_event_id=last_event_between(conn, a, b),
        truth={"actor": a, "target": b, "winner": winner, "loser": loser, "p_challenger": round(p_a, 3), "bully": bully,
               "returned": returned, "reason": it.reason, "source": it.source, "text": text},
        participants=[(a, "actor"), (b, "target")] + [(w, "witness") for w in watchers],
        changes=changes + deltas.changes(conn), memories=memories, claims=[ClaimSpec(beat)])


# -- what a spectacle does to reputation and sects (added to events other rules resolved) --------------------------
def with_jianghu_effects(conn: sqlite3.Connection, spec: EventSpec, primitives: set[str]) -> EventSpec:
    t, extra = spec.truth, []
    if "reputation" in primitives:
        hits = []
        if spec.type == "accuse" and t.get("outcome") == "caught":
            hits.append((t["target"], -0.15))
        elif spec.type == "accuse" and t.get("outcome") == "false":
            hits.append((t["actor"], -0.05))
        elif spec.type == "confront" and t.get("outcome") in ("lie_exposed", "distortion_exposed"):
            hits.append((t["target"], -0.1))
        elif spec.type == "give":
            hits.append((t["actor"], 0.03))
        for pid, d in hits:
            c = _var_change(conn, f"rep.{pid}", d)
            if c:
                extra.append(c)
    if "sect_factions" in primitives and spec.type == "accuse" and t.get("outcome") == "false":
        watchers = [p for p, role in spec.participants if role == "witness"]
        deltas = RelDeltas()
        for w in sect_mates(conn, t["target"], watchers):  # a sect-mate wrongly accused in front of you
            deltas.add(w, t["actor"], "rivalry", 0.1)
        extra += deltas.changes(conn)
    if not extra:
        return spec
    taken = {(c.entity_type, c.entity_id, c.field) for c in spec.changes}
    return replace(spec, changes=list(spec.changes) + [c for c in extra if (c.entity_type, c.entity_id, c.field) not in taken])
