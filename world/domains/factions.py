"""Circles, factions and the fight for a seat, as a domain pack (primitive social.factions).

People who like each other keep company. That is a *circle*, and nobody declares it: it is read, a night at a time, from how
people stand with each other (liking, trust, knowing each other, minus grudges), and it is world truth (`circle.<person>`, a var
the nightly event moves), because it decides things: whom one stands by in a quarrel (Domain.solidarity), whom one believes,
whom one seeks out. A circle that grows large enough around somebody who matters becomes a *faction* when its members say so: an
event founds it (relationships stay what they are; the faction is a fact on top of them), it has a leader, and membership can be
a secret, since it is only what its members know.

What happens between factions and inside them is done by people:

  recruit    ask somebody to join. They say yes or no by how they feel about you and what they owe their own side
  defect     leave one's faction, with the grudges that follow (the leader's, the members')
  campaign   when a seat the faction holds falls vacant (the producer may open one; so may the content), a member asks
             another for their support. They give it by how they feel, and what they gave is remembered (vote.<person>)

and by the rules, on the day a seat is to be decided, a succession: each member of the faction votes (for whom they promised, or
for whom they rate most), the leader counts double, and the one with most holds the seat. Everything is recorded in the event
(candidates, every vote, the tally), so anyone can see why. The losers feel it (failure), the winner too (success), and the
losing side holds it against the winner.

Nothing here knows a genre. The jianghu calls it a sect and a chief disciple; a town would call it a clique and a promotion.
"""
from __future__ import annotations

import math
import sqlite3

from contracts.claim import Claim
from contracts.recipe import MechanicPrimitive as P
from world.attention import QUIET, noticers, var, world_seed
from world.domains.base import ActionSpec, ClaimAct, Domain, EventStyle, Scored, situation
from world.events import Change, ClaimSpec, EventSpec, MemorySpec
from world.helpers import RelDeltas, person, rel
from world.intent import Intent
from world.rng import rng as make_rng
from world.state import WorldError

CIRCLE_AT = 0.22         # how strongly two people must be tied to be in one circle
FOUND_MIN = 3            # how many unaffiliated people in a circle it takes to found a faction
SAME_FACTION = 0.25      # solidarity: one of our faction
SAME_CIRCLE = 0.15       # ... one of our circle
RIVAL_FACTION = -0.10    # ... one of a rival faction
LEADER_VOTES = 2.0       # the leader's vote counts this much
EXTEND_DAYS = 2          # a seat nobody stands for is put off by this many days


def humans(conn: sqlite3.Connection) -> list[str]:
    from world.seeds import humans as all_humans
    return [p for p in all_humans(conn) if conn.execute("SELECT status FROM people WHERE id = ?", (p,)).fetchone()[0] == "active"]


# -- circles ---------------------------------------------------------------------------------------------------------
def tie(conn: sqlite3.Connection, a: str, b: str, rows: dict) -> float:
    """How strongly a and b are tied, both ways together."""
    s = 0.0
    for x, y in ((a, b), (b, a)):
        r = rows[(x, y)]
        s += 0.6 * r["affection"] + 0.3 * r["trust"] + 0.4 * max(0.0, r["familiarity"]) - 0.8 * max(0.0, r["resentment"])
    return s / 2.0


def circles(conn: sqlite3.Connection) -> list[list[str]]:
    """The groups of people who keep company, found by label propagation over the ties (deterministic: fixed order, ties go to
    the smaller label). Only groups of two or more."""
    people = humans(conn)
    rows = {(r["actor_id"], r["target_id"]): r for r in conn.execute(
        "SELECT actor_id, target_id, affection, trust, familiarity, resentment FROM relationships")}
    weight = {}
    for i, a in enumerate(people):
        for b in people[i + 1:]:
            s = tie(conn, a, b, rows)
            if s >= CIRCLE_AT:
                weight[(a, b)] = weight[(b, a)] = s
    label = {p: p for p in people}
    for _ in range(12):
        moved = False
        for p in people:
            score: dict[str, float] = {}
            for q in people:
                if (p, q) in weight:
                    score[label[q]] = score.get(label[q], 0.0) + weight[(p, q)]
            if score:
                best = min(score, key=lambda k: (-round(score[k], 9), k))
                if score[best] > score.get(label[p], 0.0) + 1e-9 and best != label[p]:
                    label[p], moved = best, True
        if not moved:
            break
    groups: dict[str, list[str]] = {}
    for p in people:
        groups.setdefault(label[p], []).append(p)
    return sorted((sorted(g) for g in groups.values() if len(g) >= 2), key=lambda g: g[0])


def circle_of(conn: sqlite3.Connection, pid: str) -> int:
    return int(var(conn, f"circle.{pid}", 0.0))


def circle_id(conn: sqlite3.Connection, members: list[str]) -> int:
    """A circle's number: one more than the place of its first member among everybody (so it stays when the circle does)."""
    return 1 + sorted(humans(conn)).index(members[0])


# -- factions --------------------------------------------------------------------------------------------------------
def faction_of(conn: sqlite3.Connection, pid: str) -> str | None:
    r = conn.execute("SELECT faction_id FROM affiliations WHERE person_id = ?", (pid,)).fetchone()
    return r[0] if r else None


def members(conn: sqlite3.Connection, fid: str) -> list[str]:
    return [r[0] for r in conn.execute("SELECT person_id FROM affiliations WHERE faction_id = ? ORDER BY person_id", (fid,))]


def leader_of(conn: sqlite3.Connection, fid: str) -> str | None:
    r = conn.execute("SELECT leader_id FROM factions WHERE faction_id = ? AND status = 'active'", (fid,)).fetchone()
    return r[0] if r else None


def influence(conn: sqlite3.Connection, pid: str) -> float:
    """How much weight somebody carries: the regard of the others, the size of the side they lead, and the seats they hold."""
    r = conn.execute("SELECT AVG(respect) FROM relationships WHERE target_id = ? AND actor_id != ?", (pid, pid)).fetchone()[0] or 0.0
    led = conn.execute("SELECT faction_id FROM factions WHERE leader_id = ? AND status = 'active'", (pid,)).fetchall()
    size = sum(len(members(conn, f[0])) for f in led) / max(1, len(humans(conn)))
    seats = conn.execute("SELECT COUNT(*) FROM seats WHERE holder_id = ?", (pid,)).fetchone()[0]
    return round(r + 0.5 * size + 0.1 * seats, 4)


def solidarity(conn: sqlite3.Connection, a: str, b: str) -> float:
    s = 0.0
    fa, fb = faction_of(conn, a), faction_of(conn, b)
    if fa and fa == fb:
        s += SAME_FACTION
    elif fa and fb and fa != fb:
        s += RIVAL_FACTION
    ca = circle_of(conn, a)
    if ca and ca == circle_of(conn, b):
        s += SAME_CIRCLE
    return s


def _free_slot(conn: sqlite3.Connection) -> str | None:
    r = conn.execute("SELECT faction_id FROM factions WHERE status = 'dormant' ORDER BY faction_id LIMIT 1").fetchone()
    return r[0] if r else None


def _idx(conn: sqlite3.Connection, pid: str) -> int:
    return 1 + sorted(humans(conn)).index(pid)


def _pid(conn: sqlite3.Connection, idx: float) -> str | None:
    people = sorted(humans(conn))
    return people[int(idx) - 1] if 1 <= int(idx) <= len(people) else None


def _open_seat(conn: sqlite3.Connection, fid: str | None) -> sqlite3.Row | None:
    if not fid:
        return None
    return conn.execute("SELECT * FROM seats WHERE faction_id = ? AND status = 'vacant' ORDER BY seat_id LIMIT 1", (fid,)).fetchone()


def _loyalty(conn: sqlite3.Connection, pid: str) -> float:
    from world.profiles import profile
    p = profile(conn, pid)
    return p.values.get("loyalty", 0.5) if p else 0.5


def _ambition(conn: sqlite3.Connection, pid: str) -> float:
    from world.profiles import profile
    p = profile(conn, pid)
    return p.values.get("ambition", 0.4) if p else 0.4


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


# -- validation ----------------------------------------------------------------------------------------------------
def _present(conn: sqlite3.Connection, it: Intent, actor: sqlite3.Row) -> sqlite3.Row:
    other = person(conn, it.target) if it.target else None
    if other is None or other["id"] == it.actor or other["location_id"] != actor["location_id"] or it.target not in humans(conn):
        raise WorldError("they are not here")
    return other


def _validate_recruit(conn: sqlite3.Connection, it: Intent, actor: sqlite3.Row) -> None:
    _present(conn, it, actor)
    mine = faction_of(conn, it.actor)
    if mine is None and _free_slot(conn) is None:
        raise WorldError("no room for another faction")
    if mine is not None and leader_of(conn, mine) != it.actor:
        raise WorldError("only a leader recruits")
    if mine is not None and faction_of(conn, it.target) == mine:
        raise WorldError("already one of ours")


def _validate_defect(conn: sqlite3.Connection, it: Intent, actor: sqlite3.Row) -> None:
    if faction_of(conn, it.actor) is None:
        raise WorldError("in no faction")


def _validate_campaign(conn: sqlite3.Connection, it: Intent, actor: sqlite3.Row) -> None:
    _present(conn, it, actor)
    mine = faction_of(conn, it.actor)
    if _open_seat(conn, mine) is None:
        raise WorldError("no seat to stand for")
    if faction_of(conn, it.target) != mine:
        raise WorldError("they have no say in it")


# -- resolution ------------------------------------------------------------------------------------------------------
def _name(conn: sqlite3.Connection, pid: str) -> str:
    return person(conn, pid)["name"]


def _resolve_recruit(conn: sqlite3.Connection, it: Intent, now: int, trigger: str) -> EventSpec:
    a, b = it.actor, it.target
    here = person(conn, a)["location_id"]
    seen = noticers(conn, here, now, f"recruit:{a}:{b}", QUIET, a, b)
    fid = faction_of(conn, a)
    founding = fid is None
    fid = fid or _free_slot(conn)
    theirs = faction_of(conn, b)
    r = conn.execute("SELECT respect, affection, trust, resentment FROM relationships WHERE actor_id = ? AND target_id = ?", (b, a)).fetchone()
    pull = 0.5 * r["respect"] + 0.5 * r["affection"] + 0.3 * r["trust"] - 0.4 * r["resentment"] - 0.25 + 0.2 * solidarity(conn, b, a)
    if theirs:
        pull -= 0.5 * _loyalty(conn, b)  # what one owes the side one is on
    p = _sigmoid(4.0 * pull)
    yes = make_rng(world_seed(conn), now, f"recruit:{a}:{b}", "recruit").random() < p
    changes: list[Change] = []
    d = RelDeltas()
    truth = {"actor": a, "target": b, "outcome": "joined" if yes else "declined", "p": round(p, 3), "faction": fid,
             "reason": it.reason, "source": it.source}
    memories = []
    claims = []
    if yes:
        if founding:
            changes += [Change("faction", fid, "status", value="active"), Change("faction", fid, "leader_id", value=a),
                        Change("faction", fid, "name", value=f"{_name(conn, a)}一派"),
                        Change("affiliation", a, "faction_id", value=fid), Change("affiliation", a, "role", value="leader")]
            truth["founded"] = True
        changes += [Change("affiliation", b, "faction_id", value=fid), Change("affiliation", b, "role", value="member")]
        if theirs and theirs != fid:  # leaving one side for another: its leader and members hold it against both of them
            truth["left_faction"] = theirs
            lead = leader_of(conn, theirs)
            for m in members(conn, theirs):
                if m != b:
                    d.add(m, b, "resentment", 0.25 if m == lead else 0.08)
            if lead and lead != a:
                d.add(lead, a, "resentment", 0.2)
        claim = Claim(b, "member_of", fid)
        claims = [ClaimSpec(claim)]
        text = f"{_name(conn, b)}加入了{_name(conn, a)}這一邊"
        memories = [MemorySpec(x, text, 1.0, claim=claim) for x in (a, b)] + [MemorySpec(w, text, 0.8, claim=claim) for w in seen]
        d.add(b, a, "trust", 0.05)
    else:
        text = f"{_name(conn, b)}婉拒了{_name(conn, a)}的邀請"
        memories = [MemorySpec(x, text, 0.9) for x in (a, b)]
    truth["text"] = text
    return EventSpec(timestamp=now, type="recruit", trigger_type=trigger, location_id=here, importance=0.6 if yes else 0.3, truth=truth,
                     participants=[(a, "actor"), (b, "target")] + [(w, "witness") for w in seen],
                     changes=changes + d.changes(conn), memories=memories, claims=claims)


def _resolve_defect(conn: sqlite3.Connection, it: Intent, now: int, trigger: str) -> EventSpec:
    a = it.actor
    here = person(conn, a)["location_id"]
    fid = faction_of(conn, a)
    lead = leader_of(conn, fid)
    changes = [Change("affiliation", a, "faction_id", value=None), Change("affiliation", a, "role", value="")]
    d = RelDeltas()
    leaving_leader = lead == a
    if leaving_leader:
        changes.append(Change("faction", fid, "leader_id", value=None))
    for m in members(conn, fid):
        if m != a:
            d.add(m, a, "resentment", 0.3 if leaving_leader else (0.2 if m == lead else 0.08))
    text = f"{_name(conn, a)}離開了{conn.execute('SELECT name FROM factions WHERE faction_id = ?', (fid,)).fetchone()[0]}"
    return EventSpec(timestamp=now, type="defect", trigger_type=trigger, location_id=here, importance=0.65,
                     truth={"actor": a, "target": lead or "", "faction": fid, "was_leader": leaving_leader, "text": text, "reason": it.reason,
                            "source": it.source},
                     participants=[(a, "actor")] + ([(lead, "target")] if lead and lead != a else []),
                     changes=changes + d.changes(conn), memories=[MemorySpec(m, text, 0.9) for m in members(conn, fid)])


def _resolve_campaign(conn: sqlite3.Connection, it: Intent, now: int, trigger: str) -> EventSpec:
    a, b = it.actor, it.target
    here = person(conn, a)["location_id"]
    seat = _open_seat(conn, faction_of(conn, a))
    seen = noticers(conn, here, now, f"campaign:{a}:{b}", QUIET, a, b)
    r = conn.execute("SELECT respect, affection, trust, resentment FROM relationships WHERE actor_id = ? AND target_id = ?", (b, a)).fetchone()
    pull = 0.6 * r["respect"] + 0.4 * r["affection"] + 0.3 * r["trust"] - 0.4 * r["resentment"] - 0.2 + 0.3 * solidarity(conn, b, a)
    promised = int(var(conn, f"vote.{b}", 0.0))
    if promised and promised != _idx(conn, a):
        pull -= 0.6  # already given their word to somebody else
    p = _sigmoid(5.0 * pull)
    if int(var(conn, f"cand.{b}", 0.0)) == 1:
        p = 0.0  # one who is standing does not back a rival
    yes = make_rng(world_seed(conn), now, f"campaign:{a}:{b}", "campaign").random() < p
    changes: list[Change] = []
    if int(var(conn, f"cand.{a}", 0.0)) == 0:
        changes.append(Change("var", f"cand.{a}", "value", delta=1.0))  # standing for it
    if yes and promised != _idx(conn, a):
        changes.append(Change("var", f"vote.{b}", "value", delta=float(_idx(conn, a) - promised)))
    d = RelDeltas()
    d.add(b, a, "respect", 0.02 if yes else 0.0)
    text = f"{_name(conn, a)}向{_name(conn, b)}請求支持{seat['title']}，{'得到了承諾' if yes else '沒有得到承諾'}"
    return EventSpec(timestamp=now, type="campaign", trigger_type=trigger, location_id=here, importance=0.45,
                     truth={"actor": a, "target": b, "seat": seat["seat_id"], "endorsed": yes, "p": round(p, 3), "text": text,
                            "reason": it.reason, "source": it.source},
                     participants=[(a, "actor"), (b, "target")] + [(w, "witness") for w in seen],
                     changes=changes + d.changes(conn), memories=[MemorySpec(x, text, 0.9) for x in (a, b)])


class Factions(Domain):
    id = "factions"
    title = "圈子與派系"
    primitives = (P("social.factions", "social", "circles that form from how people stand with each other, factions that are founded "
                    "and split, and the fight for a seat that falls vacant", ["social.depth"], cost=0),)
    situation_kinds = {"power_struggle": "權力之爭", "faction_rivalry": "派系對立", "defection": "倒戈"}
    acts = {"member_of": ClaimAct("faction", "topic", "是{o}的人", "不是{o}的人")}
    actions = {
        "recruit": ActionSpec("recruit", _validate_recruit, _resolve_recruit, targets_person=True, label="拉攏{t}",
                              stakes=lambda conn, it: {"ambition": 0.4, "belonging": 0.3}),
        "defect": ActionSpec("defect", _validate_defect, _resolve_defect, conflict=True, label="離開自己的派系",
                             stakes=lambda conn, it: {"loyalty": -0.8, "freedom": 0.4}),
        "campaign": ActionSpec("campaign", _validate_campaign, _resolve_campaign, targets_person=True, label="向{t}拉票",
                               stakes=lambda conn, it: {"ambition": 0.6}),
    }
    styles = {
        "recruit": EventStyle(caption="拉攏{t}", lines=("跟著我，不會虧待你。", "我們這邊需要你。"), social=True, say=3.0,
                              beat=("talk", "listen", "calm", "uneasy", "medium", "static", 4), describe="{a} 拉攏 {b}", heat=0),
        "defect": EventStyle(caption="離開派系", lines=("這裡，我待不下去了。",), say=3.0,
                             beat=("walk_away", "watch", "cold", "shocked", "wide", "static", 4), describe="{a} 離開了自己的派系",
                             functions=("escalate", "turn"), first_time=True, heat=2),
        "campaign": EventStyle(caption="向{t}拉票", lines=("這次，請支持我。", "我需要你的一票。"), social=True, say=3.0,
                               beat=("talk", "listen", "focused", "calm", "medium", "static", 4), describe="{a} 向 {b} 拉票", heat=0),
        "succession": EventStyle(caption="位子有了新主人", lines=("從今天起，由他來擔任。",), say=0.0,
                                 describe="{who}接下了位子", functions=("payoff", "turn"), first_time=True, heat=1),
        "found_faction": EventStyle(caption="成立派系", describe="{who}拉起了自己的一派", functions=("escalate",), heat=0),
        "circles": EventStyle(caption="", describe="", heat=0),
    }

    def initial_vars(self, pid: str, profile: dict | None) -> dict[str, float]:
        return {f"circle.{pid}": 0.0, f"vote.{pid}": 0.0, f"cand.{pid}": 0.0}

    # -- the rule agent --------------------------------------------------------------------------------------------------
    def options(self, conn: sqlite3.Connection, actor: str, now: int, ctx: dict) -> Scored:
        out: Scored = []
        if actor not in humans(conn):
            return out
        mine = faction_of(conn, actor)
        amb = _ambition(conn, actor)
        seat = _open_seat(conn, mine)
        lead = leader_of(conn, mine) if mine else None
        for p in ctx["here"]:
            if p not in humans(conn):
                continue
            r = conn.execute("SELECT affection, respect, trust, resentment FROM relationships WHERE actor_id = ? AND target_id = ?",
                             (actor, p)).fetchone()
            if r is None:
                continue
            if seat is not None and faction_of(conn, p) == mine and p != actor:
                backed = int(var(conn, f"vote.{p}", 0.0)) == _idx(conn, actor)
                out.append((0.9 * (amb - 0.3) + 0.3 * max(0.0, r["respect"]) - 0.5 * backed - 0.1, Intent(actor, "campaign", p, reason="volition")))
            if (mine is None or lead == actor) and faction_of(conn, p) != mine:
                strong = 0.6 * max(0.0, r["affection"]) + 0.4 * max(0.0, r["respect"]) + 0.3 * max(0.0, r["trust"])
                if strong >= 0.3:
                    out.append((0.5 * strong + 0.3 * amb - 0.45 + (0.15 if lead == actor else 0.0), Intent(actor, "recruit", p, reason="volition")))
        if mine is not None and lead and lead != actor:
            rl = conn.execute("SELECT resentment, respect FROM relationships WHERE actor_id = ? AND target_id = ?", (actor, lead)).fetchone()
            leave = 0.8 * rl["resentment"] + 0.4 * max(0.0, -rl["respect"]) - 0.5 - 0.5 * _loyalty(conn, actor)
            if leave > -0.3:
                out.append((leave, Intent(actor, "defect", reason="volition")))
        return out

    def solidarity(self, conn: sqlite3.Connection, a: str, b: str) -> float:
        return solidarity(conn, a, b)

    def shape(self, conn: sqlite3.Connection, actor: str, now: int, scored: Scored) -> Scored:
        """One keeps company with one's own: a word to somebody of the same faction or circle is likelier, and warmer."""
        out = []
        for score, it in scored:
            if it is not None and it.action == "talk" and it.target:
                s = solidarity(conn, actor, it.target)
                if s:
                    score += 0.25 * s if it.tone in ("warm", "neutral") else -0.1 * max(0.0, s)
            out.append((score, it))
        return out

    # -- the world -------------------------------------------------------------------------------------------------------
    def nightly(self, conn: sqlite3.Connection, day: int, now: int) -> list[EventSpec]:
        out: list[EventSpec] = []
        groups = circles(conn)
        change: list[Change] = []
        assigned = {}
        for g in groups:
            cid = circle_id(conn, g)
            for p in g:
                assigned[p] = cid
        for p in humans(conn):
            want = float(assigned.get(p, 0))
            have = var(conn, f"circle.{p}", None)
            if have is not None and have != want:
                change.append(Change("var", f"circle.{p}", "value", delta=want - have))
        if change:
            out.append(EventSpec(timestamp=now, type="circles", trigger_type="rule", importance=0.15,
                                 truth={"circles": [list(g) for g in groups]}, changes=change))
        return out

    def dawn(self, conn: sqlite3.Connection, day: int, now: int) -> list[EventSpec]:
        """The day a seat is to be decided: the faction votes. And a circle that has grown into a following may found a faction."""
        out: list[EventSpec] = []
        for seat in conn.execute("SELECT * FROM seats WHERE status = 'vacant' AND decide_by <= ? ORDER BY seat_id", (day,)).fetchall():
            spec = self._succession(conn, seat, day, now)
            if spec is not None:
                out.append(spec)
        out += self._founding(conn, now)
        return out

    def _succession(self, conn: sqlite3.Connection, seat: sqlite3.Row, day: int, now: int) -> EventSpec | None:
        fid = seat["faction_id"]
        voters = members(conn, fid) if fid else []
        candidates = [p for p in voters if int(var(conn, f"cand.{p}", 0.0)) == 1]
        if not candidates:
            return EventSpec(timestamp=now, type="seat_put_off", trigger_type="rule", importance=0.2,
                             truth={"seat": seat["seat_id"], "text": f"沒有人出來爭「{seat['title']}」，延後決定"},
                             changes=[Change("seat", seat["seat_id"], "decide_by", delta=EXTEND_DAYS)])
        lead = leader_of(conn, fid)
        votes: dict[str, str] = {}
        tally: dict[str, float] = {c: 0.0 for c in candidates}
        for v in voters:
            promised = _pid(conn, var(conn, f"vote.{v}", 0.0))
            if v in candidates:
                pick = v  # one who stands votes for oneself
            elif promised in candidates:
                pick = promised
            else:
                pick = max(candidates, key=lambda c: (round(0.6 * rel(conn, v, c, "respect") + 0.4 * rel(conn, v, c, "affection")
                                                              + 0.2 * solidarity(conn, v, c), 6), c))
            votes[v] = pick
            tally[pick] += LEADER_VOTES if v == lead else 1.0
        winner = max(candidates, key=lambda c: (tally[c], sum(rel(conn, v, c, "respect") for v in voters if v != c), c))
        text = f"{_name(conn, winner)}成為了{seat['title']}"
        changes = [Change("seat", seat["seat_id"], "holder_id", value=winner), Change("seat", seat["seat_id"], "status", value="held")]
        for p in voters:  # what was promised and who stood are spent
            for key in (f"vote.{p}", f"cand.{p}"):
                cur = var(conn, key, 0.0)
                if cur:
                    changes.append(Change("var", key, "value", delta=-cur))
        d = RelDeltas()
        for c in candidates:
            if c != winner:
                d.add(c, winner, "resentment", 0.12)
        for v, pick in votes.items():
            if pick != winner and v != winner:
                d.add(v, winner, "resentment", 0.04)
        return EventSpec(
            timestamp=now, type="succession", trigger_type="rule", importance=0.85,
            truth={"seat": seat["seat_id"], "title": seat["title"], "faction": fid, "winner": winner, "actor": winner, "candidates": candidates,
                   "votes": votes, "tally": tally, "previous": seat["holder_id"], "text": text},
            participants=[(winner, "actor")] + [(c, "rival") for c in candidates if c != winner],
            changes=changes + d.changes(conn), memories=[MemorySpec(p, text, 1.0) for p in voters])

    def _founding(self, conn: sqlite3.Connection, now: int) -> list[EventSpec]:
        out = []
        free = [r[0] for r in conn.execute("SELECT faction_id FROM factions WHERE status = 'dormant' ORDER BY faction_id")]
        taken = set()
        for g in circles(conn):
            loose = [p for p in g if faction_of(conn, p) is None and p not in taken]
            if len(loose) < FOUND_MIN or not free:
                continue
            leader = max(loose, key=lambda p: (influence(conn, p), p))
            fid = free.pop(0)
            taken |= set(loose)
            text = f"{_name(conn, leader)}和身邊的人成立了自己的一派"
            changes = [Change("faction", fid, "status", value="active"), Change("faction", fid, "leader_id", value=leader),
                       Change("faction", fid, "name", value=f"{_name(conn, leader)}一派")]
            for p in loose:
                changes += [Change("affiliation", p, "faction_id", value=fid), Change("affiliation", p, "role", value="leader" if p == leader else "member")]
            out.append(EventSpec(timestamp=now, type="found_faction", trigger_type="rule", importance=0.6,
                                 truth={"actor": leader, "faction": fid, "members": loose, "text": text},
                                 participants=[(p, "actor" if p == leader else "member") for p in loose],
                                 changes=changes, memories=[MemorySpec(p, text, 1.0) for p in loose]))
            now += 1
        return out

    def appraise(self, conn: sqlite3.Connection, pid: str, kind: str, t: dict) -> list[tuple[str, float]]:
        if kind == "succession":
            if t.get("winner") == pid:
                return [("success", 0.9)]
            if pid in t.get("candidates", []):
                return [("failure", 0.7), ("shame", 0.2)]
        if kind == "defect" and t.get("target") == pid:
            return [("betrayal", 0.8 if t.get("was_leader") is False else 0.4)]
        if kind == "recruit" and t.get("left_faction") and t.get("target") != pid and conn.execute(
                "SELECT 1 FROM factions WHERE faction_id = ? AND leader_id = ?", (t["left_faction"], pid)).fetchone():
            return [("betrayal", 0.8)]
        return []

    # -- read models -----------------------------------------------------------------------------------------------------
    def describe(self, conn: sqlite3.Connection, pid: str) -> dict:
        fid = faction_of(conn, pid)
        if fid is None and not circle_of(conn, pid):
            return {}
        name = conn.execute("SELECT name FROM factions WHERE faction_id = ?", (fid,)).fetchone()[0] if fid else "—"
        mates = [p for p in humans(conn) if p != pid and circle_of(conn, pid) and circle_of(conn, p) == circle_of(conn, pid)]
        return {"派系": name, "圈子": mates, "影響力": influence(conn, pid)}

    def situations(self, conn: sqlite3.Connection, names: dict) -> list[dict]:
        import json
        out = []
        day = conn.execute("SELECT COALESCE(MAX(timestamp), 0) FROM events").fetchone()[0] // 1440
        for seat in conn.execute("SELECT * FROM seats WHERE status = 'vacant'").fetchall():
            cands = [p for p in members(conn, seat["faction_id"]) if int(var(conn, f"cand.{p}", 0.0)) == 1]
            if len(cands) >= 2:
                out.append(situation("power_struggle", 0.85, day, cands, f"{'、'.join(names.get(c, c) for c in cands)}都想要「{seat['title']}」",
                                     "誰能贏得這個位子？", [], build=0.6, stakes=0.8, until=seat["decide_by"]))
        live = [r["faction_id"] for r in conn.execute("SELECT faction_id FROM factions WHERE status = 'active' ORDER BY faction_id")]
        for i, f1 in enumerate(live):
            for f2 in live[i + 1:]:
                a, b = members(conn, f1), members(conn, f2)
                if a and b:
                    mean = sum(rel(conn, x, y, "resentment") + rel(conn, y, x, "resentment") for x in a for y in b) / (2 * len(a) * len(b))
                    if mean >= 0.12:
                        out.append(situation("faction_rivalry", 0.7, day, a[:2] + b[:2], "兩派人互相積怨", "他們會不會走到公開衝突？",
                                             [], build=min(1.0, mean * 3), stakes=0.5, lasts=7))
        for r in conn.execute("SELECT event_id, timestamp, type, truth FROM events WHERE type IN ('defect', 'recruit', 'succession') ORDER BY event_id"):
            t = json.loads(r["truth"])
            if r["type"] == "defect" or t.get("left_faction"):
                out.append(situation("defection", 0.75, r["timestamp"] // 1440, [t.get("actor", ""), t.get("target", "")], t.get("text", "有人倒戈"),
                                     "被留下的人怎麼辦？", [r["event_id"]], build=0.4, stakes=0.5))
        return out
