"""The night before a vote (primitive social.succession_process), for the seats of world/domains/factions.py.

A seat that falls vacant is decided at dawn by the faction's vote. Without this primitive that is all there is: the result arrives with nothing before
it. A recipe that switches the primitive on gets, on the night before the vote, for each seat somebody stands for:

  pledge    each one standing says in front of the others what they stand for: one of a closed list of stances (STANCES), the one that speaks to the
            values they hold dearest. A member who holds what it speaks to thinks the better of them; one who holds what it is said against, the worse.
  asking    each member who is not standing is asked for their support by the one most likely to win them over, and may change their word: the ordinary
            campaign (factions._resolve_campaign), resolved by the ordinary rule, so the answer is the world's and not this module's
  council   the elders meet over the seat and say whom they favour, if somebody is clear of the others: from what the candidates can really do and
            how they are known (the world's skill and reputation) and how the sect holds them. Their favour is respect from every member, and a rival who
            was passed over holds it against the favoured one.

None of it decides. The vote at dawn counts what each member says (their word, their own name if they stand, else whom they respect most, which is
what the pledges and the council moved a little), and its result event names the council as its cause, and lists the night's events, so the way
to the result can be read. Each step is validated (who may stand, what is vacant) and has its cost in respect or resentment, as the other
actions of the pack. A world without the primitive never calls any of this.
"""
from __future__ import annotations

import sqlite3
from dataclasses import replace

from world.attention import present, var
from world.domains.factions import (_name, _pid, _resolve_campaign, _validate_campaign, faction_of, members)
from world.events import EventSpec, MemorySpec
from world.helpers import RelDeltas, person, rel
from world.intent import Intent
from world.state import WorldError

LOBBY_MAX = 6            # the night before the vote: most members who are asked for their support again (those standing vote for themselves)
PLEDGE_GAIN = 0.07       # a pledge that speaks to what a member values raises their respect for the speaker (per unit of match above NEUTRAL)
PLEDGE_NEUTRAL = 0.45
PLEDGE_COST = 0.02       # ... and one that goes against what they hold dearest costs the speaker this much with them
COUNCIL_FAVOUR = 0.05    # the elders' favour: the respect it brings the favoured one from every member
COUNCIL_MARGIN = 0.05    # how far ahead of the others somebody has to be for the elders to name them
COUNCIL_RIVAL = 0.03     # what a rival holds against the one the elders favoured
# what one can stand for (a closed list): label, the line they say, the values it speaks to (the first one is what it is about). The sect's name is filled in.
STANCES = {
    "merit": ("論功", "位子該給功夫最好的人。", {"fairness": 1.0, "truth": 0.5}),
    "loyalty": ("守成", "我會守住門規，守住{faction}的名聲。", {"loyalty": 1.0, "belonging": 0.3, "security": 0.3}),
    "ambition": ("進取", "我要帶{faction}更上一層樓。", {"ambition": 1.0, "freedom": 0.4}),
    "heart": ("人望", "我與師兄弟同進退，不會丟下任何人。", {"belonging": 1.0, "family": 0.3}),
    "steady": ("安穩", "我只求{faction}平平安安，師兄弟都有口飯吃。", {"security": 1.0, "family": 0.6}),
}
OPPOSED = {"merit": ("heart",), "heart": ("merit",), "loyalty": ("ambition",), "ambition": ("loyalty", "steady"), "steady": ("ambition",)}  # what each is said against


def process_on(conn: sqlite3.Connection) -> bool:
    from world.recipes import enabled
    return enabled(conn, "social.succession_process")


def _stance_of(conn: sqlite3.Connection, pid: str) -> str:
    """What somebody stands for: the stance that speaks to the values they hold most (a tie goes to the list order)."""
    from world.profiles import profile
    p = profile(conn, pid)
    held = p.values if p else {}

    def speaks(k: str) -> float:  # what it is about, held that dear; what else it speaks to only breaks a tie
        (first, _), *rest = STANCES[k][2].items()
        return held.get(first, 0.0) + 0.1 * sum(held.get(v, 0.0) * w for v, w in rest)
    return max(STANCES, key=lambda k: (round(speaks(k), 6), -list(STANCES).index(k)))


def _appeal(conn: sqlite3.Connection, voter: str, stance: str) -> float:
    """How strongly a stance speaks to what a member holds, 0..1 (a value they do not list counts as a middling 0.4)."""
    from world.profiles import profile
    p = profile(conn, voter)
    held = p.values if p else {}
    appeal = STANCES[stance][2]
    return sum(held.get(v, 0.4) * w for v, w in appeal.items()) / sum(appeal.values())


def _validate_pledge(conn: sqlite3.Connection, cand: str, seat: sqlite3.Row) -> None:
    if seat["status"] != "vacant":
        raise WorldError("no seat to stand for")
    if faction_of(conn, cand) != seat["faction_id"] or int(var(conn, f"cand.{cand}", 0.0)) != 1:
        raise WorldError("not one of those standing")


def _resolve_pledge(conn: sqlite3.Connection, cand: str, seat: sqlite3.Row, now: int, day: int) -> EventSpec:
    """One of those standing says, in front of the others, what they stand for. A member who holds what it speaks to thinks the better of them, one
    who holds the opposite thinks the worse (their respect: the vote reads it for those who have promised nobody)."""
    here = person(conn, cand)["location_id"]
    faction = conn.execute("SELECT name FROM factions WHERE faction_id = ?", (seat["faction_id"],)).fetchone()[0]
    stance = _stance_of(conn, cand)
    label, line, _ = STANCES[stance]
    line = line.format(faction=faction)
    d = RelDeltas()
    reaction: dict[str, float] = {}
    for v in members(conn, seat["faction_id"]):
        if v == cand:
            continue
        gain = PLEDGE_GAIN * (_appeal(conn, v, stance) - PLEDGE_NEUTRAL)
        if max(_appeal(conn, v, o) for o in OPPOSED[stance]) >= 0.7 and _appeal(conn, v, stance) < PLEDGE_NEUTRAL:
            gain -= PLEDGE_COST  # the speaker has said what this member holds against
        gain = round(max(-0.04, min(0.05, gain)), 4)
        if gain:
            d.add(v, cand, "respect", gain)
            reaction[v] = gain
    heard = present(conn, here, cand)
    text = f"{_name(conn, cand)}在眾人面前表態，主張「{label}」：{line}"
    return EventSpec(timestamp=now, type="succession_pledge", trigger_type="rule", location_id=here, importance=0.5,
                     truth={"actor": cand, "seat": seat["seat_id"], "title": seat["title"], "faction": seat["faction_id"], "stance": stance,
                            "stance_label": label, "line": line, "reaction": reaction, "eve_of": day + 1, "text": text},
                     participants=[(cand, "actor")] + [(w, "witness") for w in heard],
                     changes=d.changes(conn), memories=[MemorySpec(w, text, 0.9) for w in heard + [cand]])


def _standing(conn: sqlite3.Connection, cand: str, voters: list[str]) -> float:
    """What the elders see in somebody: what they can really do and how they are known (the world's own numbers), and how the sect holds them."""
    skill, rep = var(conn, f"skill.{cand}", None), var(conn, f"rep.{cand}", None)
    others = [v for v in voters if v != cand]
    regard = sum(rel(conn, v, cand, "respect") for v in others) / len(others) if others else 0.0
    known = [(w, x) for w, x in ((0.5, skill), (0.3, rep)) if x is not None]
    base = sum(w * x for w, x in known) / sum(w for w, _ in known) if known else 0.4
    return round(0.8 * base + 0.2 * (0.5 + regard), 4)


def _resolve_council(conn: sqlite3.Connection, seat: sqlite3.Row, cands: list[str], voters: list[str], now: int, day: int) -> EventSpec:
    """The sect's elders meet over the seat and say whom they favour, if anybody is clear of the others. Favour is respect from the members;
    a rival who was passed over holds it against the favoured one. Whom they name never is the result: only the vote is."""
    from world.domains.work import words
    elder = words(conn, cands[0]).get("superior") or "長老"
    view = {c: _standing(conn, c, voters) for c in cands}
    ranked = sorted(cands, key=lambda c: (-view[c], c))
    favoured = ""
    if len(ranked) == 1:
        favoured = ranked[0] if view[ranked[0]] >= 0.45 else ""
    elif view[ranked[0]] - view[ranked[1]] >= COUNCIL_MARGIN:
        favoured = ranked[0]
    d = RelDeltas()
    if favoured:
        for v in voters:
            d.add(v, favoured, "respect", COUNCIL_FAVOUR)
        for c in cands:
            if c != favoured:
                d.add(c, favoured, "resentment", COUNCIL_RIVAL)
    here = person(conn, cands[0])["location_id"]
    who = "、".join(_name(conn, c) for c in cands)
    text = (f"{elder}召集長老議事，商量{seat['title']}由誰來接（{who}）：" +
            (f"看好{_name(conn, favoured)}" if favoured else "沒有人明說看好誰，交給眾人表決"))
    return EventSpec(timestamp=now, type="succession_council", trigger_type="rule", location_id=here, importance=0.6,
                     truth={"seat": seat["seat_id"], "title": seat["title"], "faction": seat["faction_id"], "elder": elder, "candidates": cands,
                            "view": view, "favoured": favoured, "eve_of": day + 1, "text": text},
                     participants=[(c, "candidate") for c in cands], changes=d.changes(conn),
                     memories=[MemorySpec(c, text, 0.9) for c in cands])


def eve(conn: sqlite3.Connection, day: int, now: int) -> list[EventSpec]:
    """Tonight's events for every seat that the next dawn decides and somebody stands for: pledges, a round of asking for support, the council."""
    out: list[EventSpec] = []
    for seat in conn.execute("SELECT * FROM seats WHERE status = 'vacant' AND decide_by <= ? ORDER BY seat_id", (day + 1,)).fetchall():
        voters = members(conn, seat["faction_id"]) if seat["faction_id"] else []
        cands = [p for p in voters if int(var(conn, f"cand.{p}", 0.0)) == 1]
        if not cands:
            continue
        for c in cands:
            try:
                _validate_pledge(conn, c, seat)
            except WorldError:
                continue
            out.append(_resolve_pledge(conn, c, seat, now, day))
        # the last round of asking: each member who is not standing is asked by the one who would most likely win them over (not the one they
        # already gave their word to), and may change their word. One asking each, so that a word is set once a night.
        asks = []
        for v in (v for v in voters if v not in cands):
            given = _pid(conn, var(conn, f"vote.{v}", 0.0))
            best = max((c for c in cands if c != given),
                       key=lambda c: (round(0.6 * rel(conn, v, c, "respect") + 0.4 * rel(conn, v, c, "affection") + 0.3 * rel(conn, v, c, "trust"), 6), c),
                       default=None)
            if best is not None:
                asks.append((best, v))
        for c, v in sorted(asks, key=lambda a: (-round(0.6 * rel(conn, a[1], a[0], "respect") + 0.4 * rel(conn, a[1], a[0], "affection"), 6), a))[:LOBBY_MAX]:
            it = Intent(c, "campaign", v, reason="succession_eve", source="rule")
            try:
                _validate_campaign(conn, it, person(conn, c))
            except WorldError:
                continue
            spec = _resolve_campaign(conn, it, now, "rule")
            out.append(replace(spec, truth={**spec.truth, "eve_of": day + 1}))
        out.append(_resolve_council(conn, seat, cands, voters, now, day))
    return out


def eve_events(conn: sqlite3.Connection, seat_id: str, day: int) -> list[tuple[int, str]]:
    """(event id, type) of the night before the vote on this seat: its pledges, its asking for support, its council, in order."""
    rows = conn.execute("SELECT event_id, type FROM events WHERE json_extract(truth, '$.eve_of') = ? AND json_extract(truth, '$.seat') = ? "
                        "AND type IN ('succession_pledge', 'campaign', 'succession_council') ORDER BY event_id", (day, seat_id)).fetchall()
    return [(r[0], r[1]) for r in rows]
