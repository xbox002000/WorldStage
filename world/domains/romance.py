"""Attraction, courtship, couples, jealousy and heartbreak, as a domain pack (primitive romance.attraction).

Who draws whom is not a dice roll, and it is not equal. Each person is born with a *charm* (their genome); who they can fall for
is in the genome too (`attracted_to`); and the rest is a life: how well two people know each other, what they have in common
(tastes and values), whether one has wronged the other, what one has seen the other do. That settles, a night at a time, how
strongly each is drawn to each (relationships.attraction: a to b, and b to a need not match).

What people do about it are actions, like any other, which the rules judge:

  flirt      show interest. If it lands, the other is drawn a little more; if the other is not (or is spoken for), it does not
  confess    say it. Whether it is accepted is decided by how the other feels, the other's attachment, who else is in the
             picture, and the world's seed. Accepted: they are together (relationships.bond = 'dating', both ways). Declined:
             the one who confessed carries it ('rejected') and may not ask again
  date       time together; draws a couple closer
  break_up   ends it ('ex'), and hurts the one left

Being together is a fact the world holds, and the fact can be a secret: only the two and whoever saw it know it, and the rest of
what they know is gossip like any other claim. Somebody who sees someone they love flirt with, or be taken by, a third person
feels it: a grudge against the third, and against the loved one if they were together. A person who leaves their partner for
somebody else leaves a betrayed ex behind, and two enemies. None of that is scripted: it falls out of the rules.

Only adults (18 and over) can be in any of this, whatever their genome says: a minor is not drawn to anyone, nobody is drawn to them
that way, and none of these actions is open to them. Nothing here is more explicit than a courtship: the stage shows a look, a
word, a hand held.
"""
from __future__ import annotations

import math
import sqlite3

from contracts.claim import Claim
from contracts.recipe import MechanicPrimitive as P
from world.attention import QUIET, noticers, world_seed
from world.domains.base import ActionSpec, ClaimAct, Domain, EventStyle, Scored, add_changes, situation
from world.events import Change, ClaimSpec, EventSpec, MemorySpec
from world.helpers import RelDeltas, person, rel
from world.intent import Intent
from world.rng import rng as make_rng
from world.state import WorldError

ADULT = 18
DRAWN = 0.22            # attraction from which one flirts
READY = 0.45            # ... from which one can confess
JEALOUS = 0.35          # attraction from which seeing the other with somebody else hurts
RATE_MET = 0.20         # share of the distance to what one is drawn to that closes on a day they met
RATE_APART = 0.03       # ... and on a day they did not
FLIRT_GAIN = 0.04       # what a flirt that lands adds (and up to 0.10 more with charm and compatibility)
DATE_GAIN = 0.03
WITNESS_GLORY = 0.04    # seeing somebody win is attractive
ACCEPT_SHARP = 6.0      # how sharply a confession turns on how the other feels
ACCEPT_AT = 0.30        # the other's attraction at which it is a coin toss
DISCOURAGED_DAYS = 5     # after being turned down, how long before one dares again
TAKEN = 0.35            # share of the chance left when the other already has a partner (before they prefer the newcomer)


def profile(conn: sqlite3.Connection, pid: str):
    from world.profiles import profile as get
    return get(conn, pid)


def adult(conn: sqlite3.Connection, pid: str) -> bool:
    p = profile(conn, pid)
    return p is not None and p.age >= ADULT


def charm(conn: sqlite3.Connection, pid: str) -> float:
    """How easily somebody draws others in: the genome's charm; in a world with social.impression, how they look (the genome's
    `looks`, which is the charm when it does not say), kept apart from how warm they are."""
    from world.personas import genome
    from world.recipes import enabled
    if enabled(conn, "social.impression"):
        from world.domains.impression import looks
        return looks(conn, pid)
    g = genome(conn, pid)
    return g.charm if g is not None else 0.5


def drawn_to(conn: sqlite3.Connection, a: str, b: str) -> bool:
    """Can a be drawn to b: both grown, a's genome says people like b, and b is a person, not an animal."""
    from world.personas import genome
    from world.animals import is_animal
    if a == b or is_animal(conn, a) or is_animal(conn, b) or not (adult(conn, a) and adult(conn, b)):
        return False
    g, pb = genome(conn, a), profile(conn, b)
    return g is not None and pb is not None and pb.gender in g.attracted_to


def bond(conn: sqlite3.Connection, a: str, b: str) -> str:
    r = conn.execute("SELECT bond FROM relationships WHERE actor_id = ? AND target_id = ?", (a, b)).fetchone()
    return r[0] if r else ""


def partners(conn: sqlite3.Connection, a: str) -> list[str]:
    return [r[0] for r in conn.execute("SELECT target_id FROM relationships WHERE actor_id = ? AND bond = 'dating' "
                                       "ORDER BY target_id", (a,))]


def compat(conn: sqlite3.Connection, a: str, b: str) -> float:
    """0..1: what two people have in common, in tastes and in what they hold dear."""
    pa, pb = profile(conn, a), profile(conn, b)
    if pa is None or pb is None:
        return 0.5
    topics = set(pa.interests) | set(pb.interests)
    like = (sum(min(pa.interests.get(t, 0.0), pb.interests.get(t, 0.0)) for t in topics) /
            max(1e-9, sum(max(pa.interests.get(t, 0.0), pb.interests.get(t, 0.0)) for t in topics))) if topics else 0.5
    keys = set(pa.values) & set(pb.values)
    values = 1.0 - sum(abs(pa.values[k] - pb.values[k]) for k in keys) / len(keys) if keys else 0.5
    return round(0.5 * like + 0.5 * values, 3)


def drawn_level(conn: sqlite3.Connection, a: str, b: str) -> float:
    """What a would settle at, drawn to b, given how well they know each other and what lies between them (0 when a cannot
    be drawn to b at all)."""
    if not drawn_to(conn, a, b):
        return 0.0
    r = conn.execute("SELECT resentment, respect, familiarity FROM relationships WHERE actor_id = ? AND target_id = ?", (a, b)).fetchone()
    pull = 0.15 + 0.55 * charm(conn, b) + 0.30 * compat(conn, a, b) - 0.5 * max(0.0, r["resentment"]) + 0.15 * max(0.0, r["respect"])
    return round(max(0.0, min(1.0, pull)) * min(1.0, 0.4 + 2.0 * max(0.0, r["familiarity"])), 4)


def attachment(conn: sqlite3.Connection, pid: str) -> str:
    from world.personas import genome
    g = genome(conn, pid)
    return g.attachment if g is not None else "secure"


def loyalty(conn: sqlite3.Connection, pid: str) -> float:
    p = profile(conn, pid)
    return p.values.get("loyalty", 0.5) if p else 0.5


def _day_start(now: int) -> int:
    return (now // 1440) * 1440


def _done_today(conn: sqlite3.Connection, kind: str, a: str, b: str, now: int) -> bool:
    return conn.execute("SELECT 1 FROM events WHERE type = ? AND timestamp >= ? AND json_extract(truth, '$.actor') = ? AND "
                        "json_extract(truth, '$.target') = ? LIMIT 1", (kind, _day_start(now), a, b)).fetchone() is not None


def _here(conn: sqlite3.Connection, it: Intent, actor: sqlite3.Row) -> sqlite3.Row:
    other = person(conn, it.target) if it.target else None
    if other is None or other["id"] == it.actor or other["location_id"] != actor["location_id"]:
        raise WorldError("they are not here")
    return other


# -- validation ------------------------------------------------------------------------------------------------------
def _validate_flirt(conn: sqlite3.Connection, it: Intent, actor: sqlite3.Row) -> None:
    _here(conn, it, actor)
    if not drawn_to(conn, it.actor, it.target):
        raise WorldError("not somebody they can be drawn to")
    if bond(conn, it.actor, it.target) == "dating":
        raise WorldError("they are together already")


def _validate_confess(conn: sqlite3.Connection, it: Intent, actor: sqlite3.Row) -> None:
    _here(conn, it, actor)
    if not drawn_to(conn, it.actor, it.target):
        raise WorldError("not somebody they can be drawn to")
    if bond(conn, it.actor, it.target) in ("dating", "rejected"):
        raise WorldError("there is nothing to confess")
    if rel(conn, it.actor, it.target, "attraction") < DRAWN:
        raise WorldError("they do not feel enough to say it")


def _validate_together(conn: sqlite3.Connection, it: Intent, actor: sqlite3.Row) -> None:
    _here(conn, it, actor)
    if bond(conn, it.actor, it.target) != "dating" or not (adult(conn, it.actor) and adult(conn, it.target)):
        raise WorldError("they are not together")


# -- resolution ------------------------------------------------------------------------------------------------------
def _claim_memories(conn: sqlite3.Connection, claim: Claim, people: list[str], seen: list[str], strength: float = 0.9):
    from world.claims import describe_claim, labels
    text = describe_claim(claim, labels(conn))
    return text, [MemorySpec(p, text, 1.0, claim=claim) for p in people] + [MemorySpec(w, text, strength, claim=claim) for w in seen]


def _resolve_flirt(conn: sqlite3.Connection, it: Intent, now: int, trigger: str) -> EventSpec:
    a, b = it.actor, it.target
    here = person(conn, a)["location_id"]
    seen = noticers(conn, here, now, f"flirt:{a}:{b}", QUIET, a, b)
    lands = drawn_to(conn, b, a)
    d = RelDeltas()
    if lands:
        d.add(b, a, "attraction", FLIRT_GAIN + 0.10 * charm(conn, a) * compat(conn, a, b))
    else:
        d.add(b, a, "resentment", 0.02)  # unwelcome
    taken = [c for c in partners(conn, b) if c != a]
    claim = Claim(a, "flirt", b)
    text, memories = _claim_memories(conn, claim, [a, b], seen, 0.85)
    return EventSpec(
        timestamp=now, type="flirt", trigger_type=trigger, location_id=here, importance=0.35 + (0.15 if taken else 0.0),
        truth={"actor": a, "target": b, "landed": lands, "text": text, "reason": it.reason, "source": it.source,
               **({"poaching": taken[0]} if taken else {})},
        participants=[(a, "actor"), (b, "target")] + [(w, "witness") for w in seen],
        changes=d.changes(conn), memories=memories, claims=[ClaimSpec(claim)])


def _leave(conn: sqlite3.Connection, who: str, partner: str) -> list[Change]:
    return [Change("relationship", f"{who}:{partner}", "bond", value="ex"), Change("relationship", f"{partner}:{who}", "bond", value="ex")]


def _resolve_confess(conn: sqlite3.Connection, it: Intent, now: int, trigger: str) -> EventSpec:
    a, b = it.actor, it.target
    here = person(conn, a)["location_id"]
    seen = noticers(conn, here, now, f"confess:{a}:{b}", QUIET, a, b)
    feel = rel(conn, b, a, "attraction")
    p = 1.0 / (1.0 + math.exp(-ACCEPT_SHARP * (feel - ACCEPT_AT))) if drawn_to(conn, b, a) else 0.0  # not who they are drawn to
    if attachment(conn, b) == "avoidant":
        p *= 0.8  # keeps people at arm's length
    their = [c for c in partners(conn, b) if c != a]
    if their:  # somebody is already there: only a newcomer who matters more is heard
        best = max(rel(conn, b, c, "attraction") for c in their)
        p *= 0.85 if feel > best + 0.15 else TAKEN * (1.0 - loyalty(conn, b))
    accepted = make_rng(world_seed(conn), now, f"confess:{a}:{b}", "confess").random() < p
    d = RelDeltas()
    changes: list[Change] = []
    truth = {"actor": a, "target": b, "outcome": "accepted" if accepted else "declined", "p": round(p, 3), "secret": not seen,
             "reason": it.reason, "source": it.source}
    claims, memories = [], []
    if accepted:
        changes += [Change("relationship", f"{a}:{b}", "bond", value="dating"), Change("relationship", f"{b}:{a}", "bond", value="dating")]
        d.add(a, b, "attraction", 0.10)
        d.add(b, a, "attraction", 0.10)
        d.add(a, b, "affection", 0.15)
        d.add(b, a, "affection", 0.15)
        left = []
        for who, others in ((b, their), (a, [c for c in partners(conn, a) if c != b])):
            for c in others:  # leaving somebody for somebody: a betrayed ex, and two enemies
                changes += _leave(conn, who, c)
                d.add(c, who, "resentment", 0.4)
                d.add(c, a if who == b else b, "resentment", 0.5)
                left.append(c)
        if left:
            truth["left"] = left
        claim = Claim(a, "dating", b)
        claims = [ClaimSpec(claim)]
        text, memories = _claim_memories(conn, claim, [a, b], seen)
        changes += [Change("person", a, "emotion", value="happy"), Change("person", b, "emotion", value="happy")]
    else:
        changes.append(Change("relationship", f"{a}:{b}", "bond", value="rejected"))
        d.add(a, b, "attraction", -0.15)
        changes.append(Change("person", a, "emotion", value="ashamed"))
        text = f"{person(conn, a)['name']}向{person(conn, b)['name']}告白，被婉拒了"
        memories = [MemorySpec(x, text, 1.0) for x in (a, b)] + [MemorySpec(w, text, 0.8) for w in seen]
    truth["text"] = text
    return EventSpec(
        timestamp=now, type="confession", trigger_type=trigger, location_id=here, importance=0.8 if accepted else 0.65,
        truth=truth, participants=[(a, "actor"), (b, "target")] + [(w, "witness") for w in seen],
        changes=changes + d.changes(conn), memories=memories, claims=claims)


def _resolve_date(conn: sqlite3.Connection, it: Intent, now: int, trigger: str) -> EventSpec:
    a, b = it.actor, it.target
    here = person(conn, a)["location_id"]
    seen = noticers(conn, here, now, f"date:{a}:{b}", QUIET, a, b)
    d = RelDeltas()
    for x, y in ((a, b), (b, a)):
        d.add(x, y, "attraction", DATE_GAIN)
        d.add(x, y, "affection", 0.04)
    claim = Claim(a, "dating", b)
    text, memories = _claim_memories(conn, claim, [a, b], seen, 0.8)
    return EventSpec(timestamp=now, type="date", trigger_type=trigger, location_id=here, importance=0.3,
                     truth={"actor": a, "target": b, "text": text, "reason": it.reason, "source": it.source},
                     participants=[(a, "actor"), (b, "target")] + [(w, "witness") for w in seen],
                     changes=d.changes(conn), memories=memories, claims=[ClaimSpec(claim)])


def _resolve_break_up(conn: sqlite3.Connection, it: Intent, now: int, trigger: str) -> EventSpec:
    a, b = it.actor, it.target
    here = person(conn, a)["location_id"]
    seen = noticers(conn, here, now, f"break_up:{a}:{b}", QUIET, a, b)
    d = RelDeltas()
    for x, y in ((a, b), (b, a)):
        d.add(x, y, "attraction", -0.3)
    d.add(b, a, "resentment", 0.25)
    changes = _leave(conn, a, b) + [Change("person", b, "emotion", value="hurt"), Change("person", a, "emotion", value="calm")]
    text = f"{person(conn, a)['name']}和{person(conn, b)['name']}分手了"
    return EventSpec(timestamp=now, type="break_up", trigger_type=trigger, location_id=here, importance=0.75,
                     truth={"actor": a, "target": b, "text": text, "reason": it.reason, "source": it.source},
                     participants=[(a, "actor"), (b, "target")] + [(w, "witness") for w in seen],
                     changes=changes + d.changes(conn), memories=[MemorySpec(x, text, 1.0) for x in (a, b)] + [MemorySpec(w, text, 0.9) for w in seen])


def _stakes_flirt(conn: sqlite3.Connection, it: Intent) -> dict[str, float]:
    spoken_for = [c for c in partners(conn, it.target) if c != it.actor] or [c for c in partners(conn, it.actor) if c != it.target]
    return {"belonging": 0.3, "loyalty": -0.6} if spoken_for else {"belonging": 0.3}


class Romance(Domain):
    id = "romance"
    title = "感情"
    primitives = (P("romance.attraction", "social", "who is drawn to whom (charm, compatibility, time together), courtship, couples, "
                    "jealousy and heartbreak; adults only", ["social.depth"], cost=0),)
    situation_kinds = {"crush": "曖昧", "love_triangle": "三角關係", "secret_couple": "地下戀情", "heartbreak": "感情變故"}
    acts = {"dating": ClaimAct("romance", "person", "和{o}在一起", "沒有和{o}在一起"),
            "flirt": ClaimAct("romance", "person", "對{o}示好", "沒有對{o}示好")}
    actions = {
        "flirt": ActionSpec("flirt", _validate_flirt, _resolve_flirt, targets_person=True, label="對{t}示好", stakes=_stakes_flirt),
        "confess": ActionSpec("confess", _validate_confess, _resolve_confess, targets_person=True, label="向{t}告白",
                              stakes=_stakes_flirt),
        "date": ActionSpec("date", _validate_together, _resolve_date, targets_person=True, label="和{t}相處"),
        "break_up": ActionSpec("break_up", _validate_together, _resolve_break_up, targets_person=True, label="向{t}提分手",
                               stakes=lambda conn, it: {"loyalty": -0.3, "belonging": -0.4}),
    }
    styles = {
        "flirt": EventStyle(caption="對{t}示好", lines=("今天……有空嗎？", "你笑起來很好看。", "我請你喝一杯？"), social=True, say=2.5,
                            beat=("talk", "listen", "warm", "shy", "medium", "static", 4), describe="{a} 對 {b} 示好", heat=0),
        "confession": EventStyle(caption="向{t}告白", lines=("我……喜歡你。", "我想和你在一起。"), social=True, say=3.5,
                                 beat=("talk", "listen", "nervous", "surprised", "close", "slow_push_in", 6),
                                 describe="{a} 向 {b} 告白", functions=("escalate", "payoff"), first_time=True, heat=1),
        "date": EventStyle(caption="和{t}相處", lines=("和你在一起，很安心。",), social=True, say=2.0,
                           beat=("talk", "listen", "warm", "warm", "medium", "static", 4), describe="{a} 和 {b} 相處", heat=0),
        "break_up": EventStyle(caption="向{t}提分手", lines=("我們……到這裡吧。",), social=True, say=3.0,
                               beat=("talk", "listen", "cold", "hurt", "close", "slow_push_in", 5), describe="{a} 向 {b} 提分手",
                               functions=("escalate", "turn"), first_time=True, heat=2),
    }

    # -- the rule agent ------------------------------------------------------------------------------------------------
    def options(self, conn: sqlite3.Connection, actor: str, now: int, ctx: dict) -> Scored:
        if not adult(conn, actor):
            return []
        out: Scored = []
        att = attachment(conn, actor)
        mine = partners(conn, actor)
        lonely = 0.0 if mine else 1.0  # nobody to come home to: the wish to be with somebody is part of what moves one
        stung = conn.execute("SELECT 1 FROM events WHERE type = 'confession' AND json_extract(truth, '$.actor') = ? AND "
                             "json_extract(truth, '$.outcome') = 'declined' AND timestamp >= ? LIMIT 1",
                             (actor, now - DISCOURAGED_DAYS * 1440)).fetchone() is not None  # turned down lately: not again yet
        for p in ctx["here"]:
            r = conn.execute("SELECT attraction, resentment, familiarity FROM relationships WHERE actor_id = ? AND target_id = ?",
                             (actor, p)).fetchone()
            if r is None or not adult(conn, p):
                continue
            state = bond(conn, actor, p)
            if state == "dating":
                if not _done_today(conn, "date", actor, p, now):
                    out.append((0.5 + 0.5 * max(0.0, r["attraction"]), Intent(actor, "date", p, reason="volition")))
                if (r["attraction"] < 0.15 or r["resentment"] > 0.45) and loyalty(conn, actor) < 0.9:
                    out.append((1.2 * (0.2 - r["attraction"]) + 0.9 * r["resentment"] - 0.3, Intent(actor, "break_up", p, reason="volition")))
                continue
            if not drawn_to(conn, actor, p) or r["attraction"] < DRAWN:
                continue
            their = [c for c in partners(conn, p) if c != actor]
            guilt = loyalty(conn, actor) * (1.0 if [c for c in mine if c != p] else 0.0) + 0.5 * loyalty(conn, actor) * bool(their)
            shy = {"anxious": 0.15, "avoidant": -0.2}.get(att, 0.0)
            if not _done_today(conn, "flirt", actor, p, now):
                out.append((1.1 * (r["attraction"] - DRAWN) + 0.25 * max(0.0, r["familiarity"]) + 0.25 * lonely + shy - 0.8 * guilt,
                            Intent(actor, "flirt", p, reason="volition")))
            if r["attraction"] >= READY and state not in ("rejected", "dating") and not stung:
                out.append((1.6 * (r["attraction"] - READY) + 0.3 * max(0.0, r["familiarity"]) + 0.3 * lonely + shy - 1.0 * guilt,
                            Intent(actor, "confess", p, reason="volition")))
        return out

    # -- the world -------------------------------------------------------------------------------------------------
    def effects(self, conn: sqlite3.Connection, spec: EventSpec, primitives: set[str]) -> EventSpec:
        t = spec.truth
        if spec.type == "duel" and t.get("winner"):  # seeing somebody win is attractive
            d = RelDeltas()
            for w, role in spec.participants:
                if role == "witness" and drawn_to(conn, w, t["winner"]):
                    d.add(w, t["winner"], "attraction", WITNESS_GLORY)
            return add_changes(conn, spec, d.changes(conn)) if d._sum else spec
        if spec.type not in ("flirt", "date", "confession") or (spec.type == "confession" and t.get("outcome") != "accepted"):
            return spec
        a, b = t["actor"], t["target"]
        d = RelDeltas()
        jealous: dict[str, dict] = {}
        for y, role in spec.participants:
            if role != "witness":
                continue
            for x, z in ((a, b), (b, a)):  # y loves x, and has just seen x with z
                together = bond(conn, y, x) == "dating"
                if together or (drawn_to(conn, y, x) and rel(conn, y, x, "attraction") >= JEALOUS):
                    jealous[y] = {"of": z, "over": x, "kind": "partner" if together else "crush"}
                    d.add(y, z, "resentment", 0.15)
                    if together:
                        d.add(y, x, "resentment", 0.10)
                        d.add(y, x, "trust", -0.15)
                    break
        # a partner who was not there learns of it only by hearing: gossip, like any claim (the flirt and the couple are claims)
        return add_changes(conn, spec, d.changes(conn), truth={"jealous": jealous} if jealous else None) if (d._sum or jealous) else spec

    def overnight(self, conn: sqlite3.Connection, pid: str, now: int) -> list[Change]:
        """In one's sleep: who one is drawn to moves towards what one would settle at, faster the days they met."""
        if not adult(conn, pid):
            return []
        today = _day_start(now)
        met = {r[0] for r in conn.execute(
            "SELECT DISTINCT p2.person_id FROM event_participants p1 JOIN event_participants p2 ON p2.event_id = p1.event_id "
            "JOIN events e ON e.event_id = p1.event_id WHERE p1.person_id = ? AND p2.person_id != ? AND e.timestamp >= ?",
            (pid, pid, today))}
        out = []
        for r in conn.execute("SELECT target_id, attraction, bond FROM relationships WHERE actor_id = ? ORDER BY target_id", (pid,)):
            other = r["target_id"]
            goal = drawn_level(conn, pid, other)
            if r["bond"] == "dating":
                goal = max(goal, 0.55)  # a couple stays drawn, unless something breaks it
            elif r["bond"] == "ex":
                goal *= 0.5
            rate = RATE_MET if other in met else RATE_APART
            d = round(rate * (goal - r["attraction"]), 6)
            if abs(d) >= 0.001:
                out.append(Change("relationship", f"{pid}:{other}", "attraction", delta=d))
        return out

    def appraise(self, conn: sqlite3.Connection, pid: str, kind: str, t: dict) -> list[tuple[str, float]]:
        """What it was to be in it: chosen or turned down, left, or watching somebody else be chosen."""
        out: list[tuple[str, float]] = []
        if kind == "confession":
            if t.get("actor") == pid:
                out += [("success", 0.8)] if t.get("outcome") == "accepted" else [("shame", 0.7)]
            elif t.get("target") == pid and t.get("outcome") == "accepted":
                out += [("kindness", 0.6)]
            if pid in (t.get("left") or []):
                out += [("betrayal", 1.0), ("wronged", 0.4)]
        elif kind == "break_up":
            if t.get("target") == pid:
                out += [("failure", 0.8), ("shame", 0.3)]
            elif t.get("actor") == pid:
                out += [("shame", 0.2)]
        elif kind == "date" and pid in (t.get("actor"), t.get("target")):
            out += [("kindness", 0.4)]
        if kind in ("flirt", "date", "confession") and pid not in (t.get("left") or []):  # (the one left was told in full above)
            j = (t.get("jealous") or {}).get(pid)
            if j:
                out += [("betrayal", 0.7)] if j["kind"] == "partner" else [("failure", 0.4)]
        return out

    # -- read models -----------------------------------------------------------------------------------------------
    def describe(self, conn: sqlite3.Connection, pid: str) -> dict:
        if not adult(conn, pid):
            return {}
        rows = conn.execute("SELECT target_id, attraction, bond FROM relationships WHERE actor_id = ? AND attraction >= 0.2 "
                            "ORDER BY attraction DESC, target_id LIMIT 3", (pid,)).fetchall()
        return {"魅力": round(charm(conn, pid), 2), "對象": [(r["target_id"], round(r["attraction"], 2)) for r in rows],
                "戀人": partners(conn, pid)}

    def situations(self, conn: sqlite3.Connection, names: dict) -> list[dict]:
        out = []
        people = [r[0] for r in conn.execute("SELECT person_id FROM character_profiles ORDER BY person_id")]
        day = conn.execute("SELECT COALESCE(MAX(timestamp), 0) FROM events").fetchone()[0] // 1440
        att = {(r["actor_id"], r["target_id"]): r["attraction"] for r in conn.execute("SELECT actor_id, target_id, attraction FROM relationships")}
        state = {(r["actor_id"], r["target_id"]): r["bond"] for r in conn.execute("SELECT actor_id, target_id, bond FROM relationships")}
        for i, a in enumerate(people):
            for b in people[i + 1:]:
                if att.get((a, b), 0) >= READY and att.get((b, a), 0) >= READY and not state.get((a, b)):
                    out.append(situation("crush", 0.55, day, [a, b], f"{names.get(a, a)}和{names.get(b, b)}互相有好感，誰也沒說破",
                                         "誰會先開口？", [], build=min(1.0, (att[(a, b)] + att[(b, a)]) / 2), lasts=5))
        for c in people:  # two people drawn to the same third: a triangle
            fans = [x for x in people if x != c and att.get((x, c), 0) >= READY]
            if len(fans) >= 2:
                out.append(situation("love_triangle", 0.75, day, fans[:2] + [c], f"{names.get(fans[0], fans[0])}和{names.get(fans[1], fans[1])}都喜歡{names.get(c, c)}",
                                     f"{names.get(c, c)}會選誰？", [], build=0.6, stakes=0.5, lasts=5))
        for r in conn.execute("SELECT event_id, timestamp, type, truth FROM events WHERE type IN ('confession', 'break_up') ORDER BY event_id"):
            import json
            t = json.loads(r["truth"])
            if t.get("secret") and t.get("outcome") == "accepted":
                out.append(situation("secret_couple", 0.7, r["timestamp"] // 1440, [t["actor"], t["target"]],
                                     "他們在一起了，沒有人知道", "能瞞多久？", [r["event_id"]], build=0.5, lasts=7))
            if t.get("left") or r["type"] == "break_up":
                who = [t["actor"], t["target"]] + list(t.get("left") or [])
                out.append(situation("heartbreak", 0.8 if t.get("left") else 0.6, r["timestamp"] // 1440, who, t.get("text", "感情有了變故"),
                                     "被留下的人怎麼辦？", [r["event_id"]], build=0.4, stakes=0.6))
        return out
