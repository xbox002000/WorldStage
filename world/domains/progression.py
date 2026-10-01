"""Growth and what others think of it, as a domain pack (primitive growth.progression).

A hidden talent is the oldest engine of a good story: somebody is underestimated, works in secret, and one day, in front of
the people who looked down on them, it shows. Nothing here scripts that. It gives the world the two things it was
missing, and lets it happen:

  growth     practice builds *tempering* (a defeat builds a lot of it); once there is enough, a breakthrough: the ability
             jumps, in one event that records what earned it. The ability never falls back (an injury is a different thing).
  estimate   what each person believes each other person can do (relationships.estimate). It is kept per pair, in the
             ability's own units. Practice is private, so the truth runs ahead of it; only what is seen (a duel, in front of
             witnesses) or heard (the news of one, by night) moves it.

When a duel shows somebody to be more (or less) than they were taken for, the world records the gap in the event (`slap`
and `gaps`): who was surprised and by how much, who had looked down on the winner. It costs the ones who were wrong their
standing (respect flips towards the winner: the more they underestimated, the more) and it is felt (shame for the loser
and for the ones who sneered, success for the winner). Whether it was *earned* is read later from the events: the
breakthrough lists every practice and every defeat behind it.

The pack declares and returns changes and events; the core applies them. It reads the ability from the martial pack's
`skill.<person>`; another genre gives its own ability the same way (a rank, a score) and keeps the rest.
"""
from __future__ import annotations

import sqlite3

from contracts.recipe import MechanicPrimitive as P
from world.attention import var
from world.domains.base import Domain, Scored, add_changes, situation
from world.events import Change, EventSpec, MemorySpec
from world.helpers import person

REALMS = (("入門", 0.0), ("小成", 0.25), ("精熟", 0.45), ("高手", 0.65), ("宗師", 0.85))  # name, ability from which
TEMPER_TRAIN = 0.05      # tempering one practice builds (a manual doubles it)
TEMPER_DEFEAT = 0.5      # a defeat in front of others builds a lot
TEMPER_NEED = 1.0        # tempering a breakthrough takes at the start; the higher the ability, the more (x 1 + 1.5 ability)
JUMP = (0.04, 0.12)      # how far an ability jumps (more when there is more room)
SEEN = 0.7               # how much of the gap to what is shown a witness closes at once
OPPONENT = 0.8           # ... and the one who fought
RUMOUR = 0.35            # ... and everyone else, by night
GAP_SHOWN = 0.10         # an estimate off by this much has been surprised
SLAP_MARGIN = 0.08       # the winner was rated this much below the loser, on average, before the duel: an underdog's win
FLIP = 1.5               # respect flips by this times how far the winner was underestimated (at most 0.5)
MANUAL = '"manual"'


def realm(ability: float) -> tuple[int, str]:
    idx = max(i for i, (_n, lo) in enumerate(REALMS) if ability >= lo)
    return idx, REALMS[idx][0]


def ability(conn: sqlite3.Connection, pid: str) -> float:
    return var(conn, f"skill.{pid}", 0.0)


def estimate(conn: sqlite3.Connection, observer: str, subject: str) -> float:
    r = conn.execute("SELECT estimate FROM relationships WHERE actor_id = ? AND target_id = ?", (observer, subject)).fetchone()
    return r[0] if r else 0.5


def _toward(cur: float, goal: float, share: float) -> float:
    """The change that closes `share` of the gap, kept inside 0..1."""
    return round(min(1.0, max(0.0, cur + share * (goal - cur))) - cur, 6)


def _var(conn: sqlite3.Connection, key: str, delta: float, lo: float = 0.0, hi: float = 1.0) -> Change | None:
    cur = var(conn, key, None)
    if cur is None:
        return None
    d = round(min(hi, max(lo, cur + delta)) - cur, 6)
    return Change("var", key, "value", delta=d) if d else None


class Progression(Domain):
    id = "progression"
    title = "成長"
    primitives = (P("growth.progression", "power", "practice builds tempering, tempering becomes a breakthrough that never "
                    "falls back, and what others believe of one's ability lags the truth until it is shown",
                    ["martial_arts", "social.depth"], cost=0),)
    situation_kinds = {"hidden_strength": "被低估的實力", "face_slap": "打臉"}

    def initial_vars(self, pid: str, profile: dict | None) -> dict[str, float]:
        return {f"tempering.{pid}": 0.0}

    # -- what events do ----------------------------------------------------------------------------------------------
    def effects(self, conn: sqlite3.Connection, spec: EventSpec, primitives: set[str]) -> EventSpec:
        t = spec.truth
        if spec.type == "train" and t.get("actor"):
            a = t["actor"]
            c = _var(conn, f"tempering.{a}", TEMPER_TRAIN * (2.0 if t.get("with_manual") else 1.0), 0.0, 3.0)
            return add_changes(conn, spec, [c] if c else [])
        if spec.type == "duel" and t.get("winner") and t.get("loser"):
            return self._duel(conn, spec)
        return spec

    def _duel(self, conn: sqlite3.Connection, spec: EventSpec) -> EventSpec:
        t = spec.truth
        w, l = t["winner"], t["loser"]
        watchers = [p for p, role in spec.participants if role == "witness" and p not in (w, l)]
        sw, sl = ability(conn, w), ability(conn, l)
        shown = {w: sw, l: sl}
        extra: list[Change] = []
        gaps: dict[str, float] = {}
        sneered: list[str] = []
        views = {o: (estimate(conn, o, w), estimate(conn, o, l)) for o in watchers + [w, l]}
        for o in watchers + [w, l]:
            for subject, truth in ((w, sw), (l, sl)):
                if o == subject:
                    continue
                share = OPPONENT if (o in (w, l)) else SEEN
                cur = estimate(conn, o, subject)
                d = _toward(cur, truth, share)
                if d:
                    extra.append(Change("relationship", f"{o}:{subject}", "estimate", delta=d))
                gap = truth - cur
                if subject == w and abs(gap) >= GAP_SHOWN:
                    gaps[o] = round(gap, 3)
                    if gap >= GAP_SHOWN:  # they had taken the winner for less than they are
                        r = conn.execute("SELECT respect FROM relationships WHERE actor_id = ? AND target_id = ?", (o, w)).fetchone()
                        if r is not None and r[0] <= 0.05:
                            sneered.append(o)
                        extra.append(Change("relationship", f"{o}:{w}", "respect", delta=round(min(0.5, FLIP * gap), 6)))
        mean_w = sum(v[0] for o, v in views.items() if o != w) / max(1, len([o for o in views if o != w]))
        mean_l = sum(v[1] for o, v in views.items() if o != l) / max(1, len([o for o in views if o != l]))
        slap = None
        if mean_l - mean_w >= SLAP_MARGIN:
            slap = {"underdog": w, "surprise": round(mean_l - mean_w, 3), "witnesses": len(watchers), "sneered": sorted(sneered)}
        c = _var(conn, f"tempering.{l}", TEMPER_DEFEAT, 0.0, 3.0)  # a defeat in front of others burns
        if c:
            extra.append(c)
        truth = {"estimates": {"winner": round(mean_w, 3), "loser": round(mean_l, 3)}, "gaps": gaps}
        if slap:
            truth["slap"] = slap
        return add_changes(conn, spec, extra, truth=truth)

    def after_event(self, conn: sqlite3.Connection, event_id: int) -> list[EventSpec]:
        """Enough tempering is a breakthrough: the ability jumps, and the event lists what earned it."""
        row = conn.execute("SELECT type, timestamp, truth FROM events WHERE event_id = ?", (event_id,)).fetchone()
        if row["type"] not in ("train", "duel"):
            return []
        import json
        t = json.loads(row["truth"])
        pid = t.get("actor") if row["type"] == "train" else t.get("loser")
        if not pid or var(conn, f"tempering.{pid}", None) is None:
            return []
        cur = ability(conn, pid)
        if var(conn, f"tempering.{pid}", 0.0) < TEMPER_NEED * (1.0 + 1.5 * cur):
            return []
        jump = round(min(JUMP[1], max(JUMP[0], 0.2 * (1.0 - cur))), 6)
        c_skill = _var(conn, f"skill.{pid}", jump)
        if c_skill is None:
            return []
        before, after = realm(cur), realm(cur + c_skill.delta)
        last = conn.execute("SELECT COALESCE(MAX(event_id), 0) FROM events WHERE type = 'breakthrough' AND "
                            "json_extract(truth, '$.actor') = ?", (pid,)).fetchone()[0]
        earned = [r[0] for r in conn.execute(
            "SELECT event_id FROM events WHERE event_id > ? AND ((type = 'train' AND json_extract(truth, '$.actor') = ?) OR "
            "(type = 'duel' AND json_extract(truth, '$.loser') = ?)) ORDER BY event_id", (last, pid, pid))]
        defeats = [r[0] for r in conn.execute("SELECT event_id FROM events WHERE event_id > ? AND type = 'duel' AND "
                                              "json_extract(truth, '$.loser') = ? ORDER BY event_id", (last, pid))]
        name = person(conn, pid)["name"]
        text = f"{name}突破了，武功到了「{after[1]}」" if after[0] > before[0] else f"{name}有所領悟，武功更進一步"
        changes = [c_skill, Change("var", f"tempering.{pid}", "value", delta=round(-var(conn, f"tempering.{pid}", 0.0), 6))]
        return [EventSpec(
            timestamp=row["timestamp"], type="breakthrough", trigger_type="rule", location_id=person(conn, pid)["location_id"],
            parent_event_id=event_id, importance=0.7 if after[0] > before[0] else 0.5,
            truth={"actor": pid, "text": text, "jump": c_skill.delta, "realm_before": before[1], "realm_after": after[1],
                   "ranked_up": after[0] > before[0], "earned_by": earned, "defeats": defeats},
            participants=[(pid, "actor")], changes=changes, memories=[MemorySpec(pid, text, 1.0)])]

    def overnight(self, conn: sqlite3.Connection, pid: str, now: int) -> list[Change]:
        """By night everyone hears of the day's duels: what one believes of the two who fought moves a little, whether or
        not one was there (the ones who were there already know)."""
        import json
        day = (now // 1440) * 1440
        out, wanted = [], {}
        for r in conn.execute("SELECT event_id, truth FROM events WHERE type = 'duel' AND timestamp >= ? ORDER BY event_id", (day,)):
            t = json.loads(r["truth"])
            at = {p for (p,) in conn.execute("SELECT person_id FROM event_participants WHERE event_id = ?", (r["event_id"],))}
            if pid in at:
                continue
            for who in (t.get("winner"), t.get("loser")):
                if who and who != pid:
                    wanted[who] = ability(conn, who)  # what the news says of them: what they showed
        for who, truth in sorted(wanted.items()):
            d = _toward(estimate(conn, pid, who), truth, RUMOUR)
            if d:
                out.append(Change("relationship", f"{pid}:{who}", "estimate", delta=d))
        return out

    def appraise(self, conn: sqlite3.Connection, pid: str, kind: str, t: dict) -> list[tuple[str, float]]:
        """What it means to be surprised: the loser and the ones who sneered feel shame, the winner success."""
        if kind == "duel":
            gap = (t.get("gaps") or {}).get(pid, 0.0)
            if t.get("winner") == pid and t.get("slap"):
                return [("success", 0.6 + min(0.6, t["slap"]["surprise"]))]
            if gap >= GAP_SHOWN and pid in (t.get("slap") or {}).get("sneered", []):
                return [("shame", min(1.0, 3.0 * gap))]
            if t.get("loser") == pid and t.get("slap"):
                return [("shame", 0.4 + min(0.6, 2.0 * t["slap"]["surprise"]))]
        if kind == "breakthrough" and t.get("actor") == pid:
            return [("success", 0.8 if t.get("ranked_up") else 0.4)]
        return []

    # -- what it decides ---------------------------------------------------------------------------------------------
    def shape(self, conn: sqlite3.Connection, actor: str, now: int, scored: Scored) -> Scored:
        """One does not fight the opponent one cannot see: the risk and the bullying of a challenge are weighed against what
        one *believes* of the other, not the truth (the martial pack's own scoring knew the truth). Who has looked down on
        someone is therefore the likelier to challenge them, and the likelier to be wrong."""
        from world.jianghu import BULLY_GAP
        out = []
        me = ability(conn, actor)
        for score, it in scored:
            if it is not None and it.action == "challenge" and it.target:
                true_gap = me - ability(conn, it.target)
                believed_gap = me - estimate(conn, actor, it.target)
                score += (1.5 * max(0.0, true_gap - BULLY_GAP + 0.05) + 1.2 * max(0.0, -true_gap - 0.1)
                          - 1.5 * max(0.0, believed_gap - 0.2) - 1.2 * max(0.0, -believed_gap - 0.1))
                contempt = max(0.0, -conn.execute("SELECT respect FROM relationships WHERE actor_id = ? AND target_id = ?",
                                                  (actor, it.target)).fetchone()[0])
                score += 0.5 * contempt  # a sneer wants to be proved right
            out.append((score, it))
        return out

    # -- read models -------------------------------------------------------------------------------------------------
    def describe(self, conn: sqlite3.Connection, pid: str) -> dict:
        if var(conn, f"skill.{pid}", None) is None:
            return {}
        a = ability(conn, pid)
        views = [r[0] for r in conn.execute("SELECT estimate FROM relationships WHERE target_id = ? AND actor_id != ?", (pid, pid))]
        return {"境界": realm(a)[1], "別人眼中的武功": round(sum(views) / len(views), 2) if views else None,
                "真實武功": round(a, 2), "歷練": round(var(conn, f"tempering.{pid}", 0.0), 2)}

    def situations(self, conn: sqlite3.Connection, names: dict) -> list[dict]:
        """Somebody much stronger than they are taken for (the irony the audience can see), and duels that surprised."""
        import json
        out = []
        people = [r[0] for r in conn.execute("SELECT person_id FROM character_profiles ORDER BY person_id")]
        day = (conn.execute("SELECT COALESCE(MAX(timestamp), 0) FROM events").fetchone()[0]) // 1440
        for pid in people:
            if var(conn, f"skill.{pid}", None) is None:
                continue
            views = [r[0] for r in conn.execute("SELECT estimate FROM relationships WHERE target_id = ? AND actor_id != ?", (pid, pid))]
            if views and ability(conn, pid) - sum(views) / len(views) >= 0.15:
                ev = [r[0] for r in conn.execute("SELECT event_id FROM events WHERE type IN ('train', 'breakthrough') AND "
                                                 "json_extract(truth, '$.actor') = ? ORDER BY event_id DESC LIMIT 5", (pid,))]
                out.append(situation("hidden_strength", 0.55, day, [pid],
                                     f"{names.get(pid, pid)}比大家以為的強", "他的實力什麼時候會被看見？", ev, build=0.5, lasts=7))
        for r in conn.execute("SELECT event_id, timestamp, truth FROM events WHERE type = 'duel' ORDER BY event_id"):
            t = json.loads(r["truth"])
            if t.get("slap"):
                s = t["slap"]
                out.append(situation("face_slap", 0.8, r["timestamp"] // 1440, [s["underdog"]] + s["sneered"],
                                     f"{names.get(s['underdog'], s['underdog'])}在眾人面前贏了看輕他的人",
                                     "看輕他的人怎麼收場？", [r["event_id"]], build=min(1.0, s["surprise"] * 2), stakes=0.5))
        return out
