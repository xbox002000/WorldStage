"""The body, as a domain pack (primitive body.arousal): getting worked up, holding it in, and losing it.

Arousal is fast. Being shouted at, wrongly accused, called a liar or shamed in front of others winds someone up; a
kind word from someone they like takes a little off; it ebbs with time (half-life HALF_LIFE minutes) and sleep
clears it. Self-control is slower: temper and aggression lower it, and so do being exhausted, hungry or under
pressure at work. When arousal exceeds self-control, and only then, losing it becomes possible: a shove, a blow,
smashing something, breaking down in tears. Even then it is a choice the scores make likely, not a reflex.

What follows is the world's: the one hit is hurt and afraid, everyone there saw it and will tell it, and the next
night the one who lost control appraises it (shame) and, if they care for the other, sets out to make amends.
Tired or hungry people are also shorter-tempered in words (Domain.irritability).

With martial arts in the world, a blow between fighters is settled by skill: the weaker one may be the one hurt.
"""
from __future__ import annotations

import json
import math
import sqlite3

from contracts.claim import Claim
from contracts.recipe import MechanicPrimitive as P
from world.attention import LOUD, noticers, var, world_seed
from world.domains.base import ActionSpec, ClaimAct, Domain, EventStyle, add_changes
from world.events import Change, ClaimSpec, EventSpec, MemorySpec
from world.helpers import RelDeltas, person
from world.intent import Intent
from world.rng import rng as make_rng
from world.state import WorldError

HALF_LIFE = 90.0          # minutes for arousal to halve
AROUSE = {"hostile": 0.15, "accused_false": 0.3, "caught": 0.25, "called_liar": 0.3, "exposed": 0.25, "robbed": 0.3,
          "hit": 0.35}  # (first tuning: hostile 0.25 piled four lines of a quarrel up to 1.0; outbursts came 10-14 a month)
SOOTHE = -0.1             # a kind word from someone one likes
VENT = {"shove": -0.3, "strike": -0.45, "smash": -0.4, "break_down": -0.5}
HURT_DAYS = 2
SHOVE_AT, STRIKE_AT = 0.05, 0.2   # how far past self-control a shove, and a blow, become possible (tuned: a 10-day
                                  # trial at 0 / 0.15 had six shoves in one world)
ALONE_AT = 0.1                   # smashing something, breaking down
LOSE = 2.5                        # chance of losing it = LOSE x how far past self-control (at most 0.85)
REMORSE = 0.1                     # self-control gained per outburst in the last week (up to three): without it, a
                                  # 30-day world spiralled to 35 outbursts as aggression rose to 1.0
OUTBURSTS = ("shove", "strike", "smash", "break_down")


def _traits(conn: sqlite3.Connection, pid: str) -> dict:
    row = conn.execute("SELECT traits FROM personas WHERE person_id = ?", (pid,)).fetchone()
    return json.loads(row[0]) if row else {}


def has_body(conn: sqlite3.Connection, pid: str) -> bool:
    return var(conn, f"body.arousal.{pid}", None) is not None


def arousal(conn: sqlite3.Connection, pid: str, now: int) -> float:
    a, at = var(conn, f"body.arousal.{pid}", 0.0), var(conn, f"body.arousal_at.{pid}", 0.0)
    return round(a * 0.5 ** (max(0.0, now - at) / HALF_LIFE), 4)


def control(conn: sqlite3.Connection, pid: str) -> float:
    """Self-control now: temper and a history of aggression lower it; so do exhaustion, hunger, pressure."""
    from world.psyche import trait
    p = person(conn, pid)
    c = 0.65 - 0.4 * _traits(conn, pid).get("temper", 0.4) - 0.3 * (trait(conn, pid, "aggression") - 0.2)
    c -= 0.15 * (p["energy"] < 30) + 0.15 * (p["hunger"] > 70) + 0.1 * (var(conn, f"work.stress.{pid}", 0.0) > 0.7)
    c += REMORSE * min(3, _lost_lately(conn, pid))  # having lost it lately, one holds it in harder
    return round(min(0.95, max(0.05, c)), 4)


def _lost_lately(conn: sqlite3.Connection, pid: str) -> int:
    now = conn.execute("SELECT COALESCE(MAX(timestamp), 0) FROM events").fetchone()[0]
    marks = ",".join("?" * len(OUTBURSTS))
    return conn.execute(f"SELECT COUNT(*) FROM events WHERE type IN ({marks}) AND json_extract(truth, '$.actor') = ? "
                        "AND timestamp >= ?", (*OUTBURSTS, pid, now - 7 * 1440)).fetchone()[0]


def edge(conn: sqlite3.Connection, pid: str, now: int) -> float:
    """How far past their self-control someone is (> 0: they could lose it)."""
    return round(arousal(conn, pid, now) - control(conn, pid), 4) if has_body(conn, pid) else -1.0


def hurt(conn: sqlite3.Connection, pid: str, now: int) -> bool:
    return var(conn, f"body.hurt.{pid}", -1.0) >= now // 1440


def _set_arousal(conn: sqlite3.Connection, pid: str, now: int, delta: float) -> list[Change]:
    if not has_body(conn, pid):
        return []
    cur = arousal(conn, pid, now)
    new = min(1.0, max(0.0, cur + (delta * (1.0 - cur) if delta > 0 else delta)))  # the more worked up, the less more
    out = []
    for key, target in ((f"body.arousal.{pid}", round(new, 4)), (f"body.arousal_at.{pid}", float(now))):
        d = round(target - var(conn, key, 0.0), 6)
        if d:
            out.append(Change("var", key, "value", delta=d))
    return out


# -- outbursts ------------------------------------------------------------------------------------------------------
def _present(conn: sqlite3.Connection, it: Intent, actor: sqlite3.Row) -> None:
    from world.animals import is_animal
    other = person(conn, it.target) if it.target else None
    if other is None or other["id"] == it.actor or other["location_id"] != actor["location_id"] or is_animal(conn, it.target):
        raise WorldError("nobody here to lay hands on")


def _validate_hands(conn: sqlite3.Connection, it: Intent, actor: sqlite3.Row) -> None:
    _present(conn, it, actor)
    now = conn.execute("SELECT COALESCE(MAX(timestamp), 0) FROM events").fetchone()[0]
    if hurt(conn, it.actor, now):
        raise WorldError("too hurt")


def _validate_alone(conn: sqlite3.Connection, it: Intent, actor: sqlite3.Row) -> None:
    if not has_body(conn, it.actor):
        raise WorldError("no body state")


def _hands(kind: str):
    """A shove or a blow: the target is hurt or shaken, everyone there sees it."""
    def resolve(conn: sqlite3.Connection, it: Intent, now: int, trigger: str) -> EventSpec:
        a, b = it.actor, it.target
        here = person(conn, a)["location_id"]
        seen = noticers(conn, here, now, f"{kind}:{a}:{b}", LOUD, a, b)
        hit, hitter = b, a
        from world.recipes import enabled
        if kind == "strike" and enabled(conn, "martial_arts"):  # between fighters, skill decides who gets hurt
            from world import jianghu
            sa, sb = jianghu.skill(conn, a), jianghu.skill(conn, b)
            if sa >= 0.2 and sb >= 0.2:
                p = 1 / (1 + math.exp(-8 * (sa - sb)))
                if make_rng(world_seed(conn), now, f"{a}:{b}", "brawl").random() >= p:
                    hit, hitter = a, b
        d = RelDeltas()
        strength = 1.0 if kind == "strike" else 0.5
        d.add(b, a, "trust", -0.35 * strength)
        d.add(b, a, "affection", -0.3 * strength)
        d.add(b, a, "fear", 0.3 * strength)
        for w in seen:
            d.add(w, a, "trust", -0.1 * strength)
            d.add(w, a, "fear", 0.05)
        c = Claim(a, kind, b)
        from world.claims import describe_claim, labels
        text = describe_claim(c, labels(conn))
        changes = d.changes(conn) + _set_arousal(conn, a, now, VENT[kind]) + _set_arousal(conn, b, now, AROUSE["hit"])
        temper = _traits(conn, b).get("temper", 0.4)
        changes.append(Change("person", b, "emotion", value="angry" if temper >= 0.6 else "scared"))
        if kind == "strike":
            cur = var(conn, f"body.hurt.{hit}", -1.0)
            until = float(now // 1440 + HURT_DAYS)
            if until > cur:
                changes.append(Change("var", f"body.hurt.{hit}", "value", delta=until - cur))
        return EventSpec(
            timestamp=now, type=kind, trigger_type=trigger, location_id=here, importance=0.9 if kind == "strike" else 0.75,
            truth={"actor": a, "target": b, "text": text, "reason": it.reason, "source": it.source,
                   **({"hurt": hit, "won": hitter} if kind == "strike" else {}),
                   "edge": edge(conn, a, now), "provoked_by_target": _provoked_by(conn, b, a, now)},
            participants=[(a, "actor"), (b, "target")] + [(w, "witness") for w in seen], changes=changes,
            memories=[MemorySpec(p, text, 1.0, claim=c) for p in (a, b)] + [MemorySpec(w, text, 0.9, claim=c) for w in seen],
            claims=[ClaimSpec(c)])
    return resolve


def _alone(kind: str, text: str):
    def resolve(conn: sqlite3.Connection, it: Intent, now: int, trigger: str) -> EventSpec:
        a = it.actor
        here = person(conn, a)["location_id"]
        seen = noticers(conn, here, now, f"{kind}:{a}", LOUD, a)
        changes = _set_arousal(conn, a, now, VENT[kind])
        if kind == "break_down" and person(conn, a)["emotion"] != "hurt":
            changes.append(Change("person", a, "emotion", value="hurt"))
        d = RelDeltas()
        for w in seen:
            if kind == "smash":
                d.add(w, a, "fear", 0.05)
        return EventSpec(timestamp=now, type=kind, trigger_type=trigger, location_id=here, importance=0.55,
                         truth={"actor": a, "target": it.target or "", "text": text, "reason": it.reason, "source": it.source,
                                "edge": edge(conn, a, now)},
                         participants=[(a, "actor")] + [(w, "witness") for w in seen], changes=changes + d.changes(conn),
                         memories=[MemorySpec(p, f"{person(conn, a)['name']}{text}", 0.9) for p in [a] + seen])
    return resolve


def _provoked_by(conn: sqlite3.Connection, b: str, a: str, now: int) -> bool:
    """Had `b` just gone for `a` (hostile words, an accusation, a confrontation, a shove or a blow, within 5 minutes)?"""
    row = conn.execute(
        "SELECT 1 FROM events WHERE json_extract(truth, '$.actor') = ? AND json_extract(truth, '$.target') = ? AND timestamp >= ? "
        "AND (type IN ('accuse', 'confront', 'shove', 'strike') OR (type = 'talk' AND json_extract(truth, '$.tone') = 'hostile')) "
        "LIMIT 1", (b, a, now - 5)).fetchone()
    return row is not None


def _stakes_hands(conn: sqlite3.Connection, it: Intent) -> dict[str, float]:
    row = conn.execute("SELECT affection FROM relationships WHERE actor_id = ? AND target_id = ?", (it.actor, it.target)).fetchone()
    fond = max(0.0, row[0]) if row else 0.0
    return {"revenge": 0.5, "belonging": -0.3 - 0.6 * fond, "fairness": -0.3, "security": -0.3}


class Body(Domain):
    id = "body"
    title = "身體"
    primitives = (P("body.arousal", "physics", "getting worked up and holding it in: arousal against self-control; past "
                    "it, a shove, a blow, smashing something, breaking down", ["volition"], cost=0),)
    actions = {
        "shove": ActionSpec("shove", _validate_hands, _hands("shove"), targets_person=True, conflict=True,
                            label="推{t}一把", stakes=_stakes_hands),
        "strike": ActionSpec("strike", _validate_hands, _hands("strike"), targets_person=True, conflict=True,
                             label="對{t}動手", stakes=_stakes_hands),
        "smash": ActionSpec("smash", _validate_alone, _alone("smash", "氣得摔東西"), label="摔東西"),
        "break_down": ActionSpec("break_down", _validate_alone, _alone("break_down", "崩潰大哭"), label="崩潰大哭"),
    }
    acts = {"shove": ClaimAct("violence", "person", "推了{o}", "沒有推{o}", belief_effect=-0.3),
            "strike": ClaimAct("violence", "person", "動手打了{o}", "沒有動手打{o}", belief_effect=-0.5)}
    styles = {
        "shove": EventStyle(caption="推了{t}一把", lines=("走開！", "你給我滾！", "別碰我！"), social=True, say=1.5, heat=3,
                            opens_scene=True, first_time=True, functions=("escalate",)),
        "strike": EventStyle(caption="動手打了{t}", lines=("你找死！", "……！"), social=True, say=1.0, strikes=1, heat=3,
                             opens_scene=True, first_time=True, functions=("escalate", "payoff")),
        "smash": EventStyle(caption="氣得摔東西", lines=("夠了！", "我受夠了！"), heat=2, functions=("escalate",)),
        "break_down": EventStyle(caption="崩潰大哭", lines=("我受不了了……", "為什麼都是我……"), heat=1, functions=("reveal",)),
        "regret": EventStyle(caption="{text}", functions=("reflect",)),
    }
    situation_kinds = {"lost_control": "失控"}

    def initial_vars(self, pid: str, profile) -> dict[str, float]:
        if profile is None:
            return {}
        return {f"body.arousal.{pid}": 0.0, f"body.arousal_at.{pid}": 0.0, f"body.hurt.{pid}": -1.0}

    # -- the rule agent: outbursts only past self-control ------------------------------------------------------------
    def _outbursts(self, conn: sqlite3.Connection, me: str, targets: list[str], now: int) -> list:
        over = edge(conn, me, now)
        if over <= 0 or self._spent(conn, me, now):
            return []
        from world.psyche import trait
        t = _traits(conn, me)
        out = []
        for other in targets:
            r = conn.execute("SELECT affection, fear, rivalry FROM relationships WHERE actor_id = ? AND target_id = ?",
                             (me, other)).fetchone()
            if r is None or not has_body(conn, other):
                continue
            if over > SHOVE_AT:
                out.append((0.4 + 3.0 * over + 0.3 * t.get("temper", 0.4) - 0.5 * max(0.0, r[0]) + 0.3 * max(0.0, r[2])
                            - 0.8 * max(0.0, r[1]), Intent(me, "shove", other, reason="body:lost_control")))
            if over > STRIKE_AT and not hurt(conn, me, now):
                out.append((0.1 + 3.0 * over + 0.5 * (trait(conn, me, "aggression") - 0.2) - 0.8 * max(0.0, r[0])
                            - 0.8 * max(0.0, r[1]), Intent(me, "strike", other, reason="body:lost_control")))
        if over > ALONE_AT:
            out.append((0.1 + 2.0 * over, Intent(me, "smash", reason="body:lost_control")))
            out.append((0.1 + 2.0 * over * (1 - t.get("temper", 0.4)) + 0.5 * trait(conn, me, "withdrawal"),
                        Intent(me, "break_down", reason="body:lost_control")))
        return out

    @staticmethod
    def _spent(conn: sqlite3.Connection, me: str, now: int) -> bool:
        """One loses it once in a day: after that, one is spent (and ashamed)."""
        marks = ",".join("?" * len(OUTBURSTS))
        return conn.execute(f"SELECT 1 FROM events WHERE type IN ({marks}) AND json_extract(truth, '$.actor') = ? "
                            "AND timestamp >= ? LIMIT 1", (*OUTBURSTS, me, now // 1440 * 1440)).fetchone() is not None

    def seize(self, conn: sqlite3.Connection, me: str, targets: list[str], now: int) -> Intent | None:
        """Losing control is not one choice among others (as an option it never won against a retort): past
        self-control, there is a chance it takes over, the larger the further past; then what it becomes is weighed
        among the outbursts. Deterministic: the world's seed decides."""
        over = edge(conn, me, now)
        if over <= SHOVE_AT or self._spent(conn, me, now):
            return None
        if make_rng(world_seed(conn), now, me, "lose_control").random() >= min(0.85, LOSE * over):
            return None
        options = self._outbursts(conn, me, targets, now)
        if not options:
            return None
        rng = make_rng(world_seed(conn), now, me, "outburst")
        return rng.choices([it for _, it in options], [math.exp(s / 0.3) for s, _ in options])[0]

    def irritability(self, conn: sqlite3.Connection, pid: str, now: int) -> float:
        if not has_body(conn, pid):
            return 0.0
        p = person(conn, pid)
        return round(0.25 * (p["energy"] < 30) + 0.25 * (p["hunger"] > 70) + 0.4 * arousal(conn, pid, now), 3)

    def influences(self, conn: sqlite3.Connection, pid: str, now: int) -> list[dict]:
        if not has_body(conn, pid):
            return []
        a, p = arousal(conn, pid, now), person(conn, pid)
        if a < 0.05 and p["energy"] >= 30 and p["hunger"] <= 70:
            return []
        return [{"kind": "body", "arousal": round(a, 3), "control": control(conn, pid), "tired": p["energy"] < 30,
                 "hungry": p["hunger"] > 70}]

    # -- the world -----------------------------------------------------------------------------------------------------
    def effects(self, conn: sqlite3.Connection, spec: EventSpec, primitives: set[str]) -> EventSpec:
        """What winds people up and what calms them, on the events that do it."""
        t, now = spec.truth, spec.timestamp
        a, b = t.get("actor"), t.get("target") or t.get("victim")
        extra: list[Change] = []
        if spec.type == "talk" and b:
            if t.get("tone") == "hostile":
                extra += _set_arousal(conn, b, now, AROUSE["hostile"])
            elif t.get("tone") == "warm":
                row = conn.execute("SELECT affection FROM relationships WHERE actor_id = ? AND target_id = ?", (b, a)).fetchone()
                if row and row[0] > 0.2:
                    extra += _set_arousal(conn, b, now, SOOTHE)
        elif spec.type == "accuse" and b:
            extra += _set_arousal(conn, b, now, AROUSE["accused_false" if t.get("outcome") == "false" else "caught"])
        elif spec.type == "confront" and b:
            if t.get("outcome") == "unfounded":
                extra += _set_arousal(conn, b, now, AROUSE["called_liar"])
            elif t.get("outcome") in ("lie_exposed", "distortion_exposed"):
                extra += _set_arousal(conn, b, now, AROUSE["exposed"])
        elif spec.type == "steal" and t.get("owner_noticed") and b:
            extra += _set_arousal(conn, b, now, AROUSE["robbed"])
        return add_changes(conn, spec, extra) if extra else spec

    def appraise(self, conn: sqlite3.Connection, pid: str, kind: str, t: dict) -> list[tuple[str, float]]:
        """What its events mean to those in them (world/psyche.py): lashing out is shame, being hit is hostility."""
        if kind in ("shove", "strike"):
            if t.get("actor") == pid:
                return [("shame", 0.8 if kind == "strike" else 0.5)]
            if t.get("target") == pid:
                if t.get("provoked_by_target"):  # I had just gone for them: it stings, but it is not injustice
                    return [("hostility", 0.3)]
                return [("hostility", 1.0), ("wronged", 0.4)]
        if kind == "break_down" and t.get("actor") == pid:
            return [("failure", 0.5)]
        return []

    def overnight(self, conn: sqlite3.Connection, pid: str, now: int) -> list[Change]:
        """Sleep clears it."""
        if not has_body(conn, pid) or var(conn, f"body.arousal.{pid}", 0.0) == 0.0:
            return []
        return [Change("var", f"body.arousal.{pid}", "value", delta=-var(conn, f"body.arousal.{pid}", 0.0))]

    def nightly(self, conn: sqlite3.Connection, day: int, now: int) -> list[EventSpec]:
        """The night after: regret, and wanting to make it right with someone one cares about."""
        from world.goals import GoalWriter
        out = []
        w = GoalWriter(conn, now, None)
        names = {r[0]: r[1] for r in conn.execute("SELECT id, name FROM people")}
        for eid, etype, truth in conn.execute("SELECT event_id, type, truth FROM events WHERE type IN ('shove', 'strike') "
                                              "AND timestamp >= ? AND timestamp < ? ORDER BY event_id", (day * 1440, now)).fetchall():
            t = json.loads(truth)
            a, b = t["actor"], t["target"]
            row = conn.execute("SELECT affection FROM relationships WHERE actor_id = ? AND target_id = ?", (a, b)).fetchone()
            fond = row[0] if row else 0.0
            text = f"後悔對{names.get(b, b)}{'動手' if etype == 'strike' else '動粗'}"
            out.append(EventSpec(timestamp=now, type="regret", trigger_type="rule", location_id=None, importance=0.45,
                                 parent_event_id=eid, truth={"actor": a, "target": b, "text": text, "cause_event": eid},
                                 participants=[(a, "actor")], memories=[MemorySpec(a, f"我{text}", 1.0)]))
            if fond > 0.1:
                w.cause = eid
                w.form(a, "make_amends", b, "", 0.7, day, text)
        return out + w.out

    def situations(self, conn: sqlite3.Connection, names: dict) -> list[dict]:
        from world.domains.base import situation
        out = []
        for eid, ts, etype, truth in conn.execute("SELECT event_id, timestamp, type, truth FROM events WHERE type IN "
                                                   "('shove', 'strike', 'smash', 'break_down') ORDER BY event_id"):
            t = json.loads(truth)
            who = t["actor"]
            out.append(situation("lost_control", 0.6, ts // 1440, [who] + ([t["target"]] if t.get("target") else []),
                                 f"{names.get(who, who)}{t.get('text', '')}（失控 {t.get('edge', 0):+.2f}）",
                                 f"{names.get(who, who)}之後要怎麼面對？", [eid], stakes=0.9 if etype == "strike" else 0.6, lasts=3))
        return out

    def describe(self, conn: sqlite3.Connection, pid: str) -> dict:
        if not has_body(conn, pid):
            return {}
        now = conn.execute("SELECT COALESCE(MAX(timestamp), 0) FROM events").fetchone()[0]
        return {"激動": round(arousal(conn, pid, now), 2), "自制": round(control(conn, pid), 2),
                "受傷": "是" if hurt(conn, pid, now) else "—"}
