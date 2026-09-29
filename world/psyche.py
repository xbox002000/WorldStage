"""Characters over time: what someone lives through slowly changes who they are.

Three speeds. Emotion is fast: one event can change it (people.emotion). Relationships, beliefs and goals move at
medium speed: events change them directly. Adaptive traits, values and the self-model are slow: they move only in
the nightly reflection, only when an experience repeats, and a step back towards health is smaller than the step
away from it. So people recover, but not to where they started. The core disposition (personas.traits) never
changes.

Nothing here is a personality switch. "Suspicious", "withdrawn" or "vengeful" are where the numbers end up after a
history, and each number can be traced to the reflection events that moved it and the experiences they cite.

State lives in world_vars under psy.<person>.<key>; every change is a `reflection` event with deltas.
"""
from __future__ import annotations

import json
import sqlite3

from world.attention import var
from world.events import Change, EventSpec, MemorySpec

# adaptive traits and values start here; recovery never quite gets back
ADAPTIVE = {"vigilance": 0.2, "cynicism": 0.2, "aggression": 0.2, "withdrawal": 0.1, "trust_default": 0.5}
VALUES = {"security": 0.4, "truth": 0.5, "belonging": 0.5, "revenge": 0.1}
EXPERIENCES = ("betrayal", "wronged", "shame", "kindness", "hostility", "failure", "success")
SELF_MODEL = {
    "cannot_trust": ("我不能相信別人", "betrayal", 3.0),
    "always_blamed": ("我總是被冤枉的那個", "wronged", 2.0),
    "on_my_own": ("只能靠自己", "failure", 3.0),
    "some_are_kind": ("還是有人對我好", "kindness", 3.0),
}
DECAY = 0.85  # experiences fade by this factor every night
REPEAT = 1.5  # an accumulated weight this high means "it keeps happening"
STEP_DOWN, STEP_UP = 0.06, 0.03  # harm moves a trait twice as fast as healing moves it back
VALUE_STEP = 0.02


# a trait harmed past its resting value remembers how far it went; healing stops short of rest by a quarter of that
HARM_DIRECTION = {"vigilance": 1, "cynicism": 1, "aggression": 1, "withdrawal": 1, "trust_default": -1}
SCAR = 0.25


def keys_for(pid: str) -> dict[str, float]:
    out = {f"psy.{pid}.{k}": v for k, v in ADAPTIVE.items()}
    out.update({f"psy.{pid}.worst.{k}": v for k, v in ADAPTIVE.items()})
    out.update({f"psy.{pid}.value.{k}": v for k, v in VALUES.items()})
    out.update({f"psy.{pid}.exp.{k}": 0.0 for k in EXPERIENCES})
    out.update({f"psy.{pid}.self.{k}": 0.0 for k in SELF_MODEL})
    return out


def trait(conn: sqlite3.Connection, pid: str, key: str) -> float:
    default = ADAPTIVE.get(key, VALUES.get(key.removeprefix("value."), 0.0))
    return var(conn, f"psy.{pid}.{key}", default)


# -- appraisal: what a day meant to someone, from what they know ----------------------------------------------------
def appraise(conn: sqlite3.Connection, pid: str, day: int) -> tuple[dict[str, float], list[int]]:
    """Experiences of `pid` on `day`, only from events they took part in or noticed."""
    rows = conn.execute(
        "SELECT e.event_id, e.type, e.truth, p.role FROM events e JOIN event_participants p ON p.event_id = e.event_id "
        "WHERE p.person_id = ? AND e.timestamp >= ? AND e.timestamp < ? ORDER BY e.event_id",
        (pid, day * 1440, (day + 1) * 1440)).fetchall()
    exp = {k: 0.0 for k in EXPERIENCES}
    cited: list[int] = []

    def add(kind: str, w: float, eid: int) -> None:
        exp[kind] += w
        cited.append(eid)

    for r in rows:
        t, kind, role = json.loads(r["truth"]), r["type"], r["role"]
        me_actor, me_target = t.get("actor") == pid, t.get("target") == pid or t.get("victim") == pid
        outcome = t.get("outcome")
        if kind == "confront" and me_actor and outcome in ("lie_exposed", "distortion_exposed", "concealment_exposed"):
            add("betrayal", 1.0, r["event_id"])  # I found out I had been lied to
        elif kind == "confront" and me_target and outcome in ("lie_exposed", "distortion_exposed"):
            add("shame", 1.0, r["event_id"])
        elif kind == "accuse" and me_target and outcome == "false":
            add("wronged", 1.0, r["event_id"])
        elif kind == "accuse" and me_target and outcome == "caught":
            add("shame", 1.2, r["event_id"])
        elif kind == "accuse" and me_actor and outcome == "denied":
            add("betrayal", 0.5, r["event_id"])  # I am sure they are lying to my face
        elif kind == "accuse" and me_actor and outcome == "false":
            add("failure", 0.5, r["event_id"])
        elif kind == "steal" and me_target and t.get("owner_noticed"):
            add("betrayal", 1.0, r["event_id"])
        elif kind == "notice_missing" and me_actor:
            add("failure", 0.3, r["event_id"])
        elif kind in ("lend", "give") and me_target:
            add("kindness", 1.0, r["event_id"])
        elif kind == "talk" and me_target and t.get("tone") == "warm" and _unexpected(conn, pid, t.get("actor")):
            add("kindness", 0.5, r["event_id"])  # warmth counts when I was hurting, or from someone I distrust
        elif kind == "talk" and me_target and t.get("tone") == "hostile":
            add("hostility", 1.0, r["event_id"])
        elif kind == "goal_change" and me_actor and t.get("to") in ("abandoned", "blocked"):
            add("failure", 1.0, r["event_id"])
        elif kind == "goal_change" and me_actor and t.get("to") == "completed":
            add("success", 1.0, r["event_id"])
    return exp, cited


def _unexpected(conn: sqlite3.Connection, pid: str, other: str | None) -> bool:
    if other is None:
        return False
    trust = conn.execute("SELECT trust FROM relationships WHERE actor_id = ? AND target_id = ?", (pid, other)).fetchone()
    hurting = var(conn, f"psy.{pid}.vigilance", 0.2) > ADAPTIVE["vigilance"] + 0.05 or \
        var(conn, f"psy.{pid}.withdrawal", 0.1) > ADAPTIVE["withdrawal"] + 0.05
    return bool(trust and trust[0] < 0) or hurting


# -- reflection: the slow layers move ---------------------------------------------------------------------------------
def reflect(conn: sqlite3.Connection, pid: str, day: int, now: int) -> EventSpec | None:
    if var(conn, f"psy.{pid}.vigilance", None) is None:
        return None
    today, cited = appraise(conn, pid, day)
    acc = {k: round(var(conn, f"psy.{pid}.exp.{k}", 0.0) * DECAY + today[k], 6) for k in EXPERIENCES}
    new: dict[str, float] = {}

    def move(key: str, delta: float, lo: float = 0.0, hi: float = 1.0) -> None:
        cur = new.get(key, var(conn, f"psy.{pid}.{key}", 0.0))
        value = min(hi, max(lo, cur + delta))
        sign = HARM_DIRECTION.get(key)
        if sign is not None:
            rest, worst = ADAPTIVE[key], var(conn, f"psy.{pid}.worst.{key}", ADAPTIVE[key])
            if delta * sign < 0:  # healing: towards rest, never past the scar
                floor = rest + SCAR * (worst - rest)
                value = max(value, floor) if sign > 0 else min(value, floor)
                if (cur - floor) * sign <= 0:
                    value = cur  # already as healed as this history allows
            elif (value - worst) * sign > 0:
                new[f"worst.{key}"] = round(value, 6)
        new[key] = round(value, 6)

    hurt = acc["betrayal"] + acc["wronged"]
    if today["betrayal"] + today["wronged"] and hurt >= REPEAT:  # it keeps happening
        move("vigilance", STEP_DOWN * min(2.0, hurt / REPEAT))
        move("trust_default", -STEP_DOWN)
        move("cynicism", STEP_DOWN * 0.7)
    if today["hostility"] and acc["hostility"] >= REPEAT:
        move("aggression", STEP_DOWN)
    if today["failure"] and acc["failure"] + acc["hostility"] >= 2 * REPEAT:
        move("withdrawal", STEP_DOWN)
    if today["kindness"]:  # healing: half the speed of harm
        move("vigilance", -STEP_UP * min(2.0, today["kindness"]))
        move("trust_default", STEP_UP * min(2.0, today["kindness"]))
        move("withdrawal", -STEP_UP)
        move("cynicism", -STEP_UP * 0.5)
        move("aggression", -STEP_UP)
    if today["success"]:
        move("withdrawal", -STEP_UP)
    # values: only a long run of the same experience shifts what someone cares about
    if acc["betrayal"] + acc["wronged"] >= 2 * REPEAT and today["betrayal"] + today["wronged"]:
        move("value.security", VALUE_STEP)
        move("value.truth", VALUE_STEP)
    if acc["hostility"] + acc["wronged"] >= 2 * REPEAT and today["hostility"] + today["wronged"]:
        move("value.revenge", VALUE_STEP)
    if acc["kindness"] >= 2 * REPEAT and today["kindness"]:
        move("value.belonging", VALUE_STEP)
    formed = []
    for key, (text, source, threshold) in SELF_MODEL.items():
        if acc[source] >= threshold and var(conn, f"psy.{pid}.self.{key}", 0.0) < 0.5:
            new[f"self.{key}"] = 1.0
            formed.append(text)
        elif acc[source] < threshold / 3 and var(conn, f"psy.{pid}.self.{key}", 0.0) >= 0.5:
            new[f"self.{key}"] = 0.5  # the belief softens, it does not vanish
    changes = [Change("var", f"psy.{pid}.exp.{k}", "value", delta=round(acc[k] - var(conn, f"psy.{pid}.exp.{k}", 0.0), 6))
               for k in EXPERIENCES if abs(acc[k] - var(conn, f"psy.{pid}.exp.{k}", 0.0)) > 1e-6]
    shifted = {}
    for key, value in new.items():
        d = round(value - var(conn, f"psy.{pid}.{key}", 0.0), 6)
        if d:
            changes.append(Change("var", f"psy.{pid}.{key}", "value", delta=d))
            shifted[key] = d
    if not changes:
        return None
    return EventSpec(
        timestamp=now, type="reflection", trigger_type="rule", location_id="apartment",
        importance=0.2 + (0.4 if formed else 0.0) + min(0.3, sum(abs(v) for v in shifted.values())),
        truth={"actor": pid, "day": day, "experiences": {k: round(v, 3) for k, v in today.items() if v},
               "shifted": shifted, "self_model": formed, "cites": sorted(set(cited)), "depends_on": sorted(set(cited))},
        participants=[(pid, "actor")], changes=changes,
        memories=[MemorySpec(pid, f"我開始覺得：{t}", 1.0) for t in formed])
