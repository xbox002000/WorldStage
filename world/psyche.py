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
    "world_is_hostile": ("大家都對我有敵意", "hostility", 4.0),
}
# How each held self-model leans what someone does (self_bias): read by the rule agent, the replies and belief.
SELF_BIAS = {
    "cannot_trust": {"belief": -0.15, "accuse": 0.3, "tell": -0.2},
    "always_blamed": {"defend": 0.3, "apologize": -0.3},
    "on_my_own": {"withdraw": 0.2, "lend": -0.3},
    "some_are_kind": {"soothe": 0.2, "warm": 0.15},
    "world_is_hostile": {"retort": 0.3, "warm": -0.2},
}
PROVOKED = 0.3   # hostility one provoked oneself still stings, a little
DECAY = 0.85  # experiences fade by this factor every night
REPEAT = 1.5  # an accumulated weight this high means "it keeps happening"
STEP_DOWN, STEP_UP = 0.06, 0.03  # harm moves a trait twice as fast as healing moves it back
VALUE_STEP = 0.02


# a trait harmed past its resting value remembers how far it went; healing stops short of rest by a quarter of that
HARM_DIRECTION = {"vigilance": 1, "cynicism": 1, "aggression": 1, "withdrawal": 1, "trust_default": -1}
SCAR = 0.25


# What a formative experience (contracts/persona.py Formative.experience) leaves in someone before the world starts: how far
# it moves each adaptive trait at weight 1, and the self-model it forms outright when it was strong. The marks are scars
# like any lived harm: healing stops short of rest.
SHAPING = {
    "betrayal": ({"vigilance": 0.25, "trust_default": -0.25, "cynicism": 0.15}, "cannot_trust"),
    "wronged": ({"vigilance": 0.10, "cynicism": 0.10}, "always_blamed"),
    "shame": ({"withdrawal": 0.15}, None),
    "kindness": ({"vigilance": -0.10, "trust_default": 0.20, "withdrawal": -0.05}, "some_are_kind"),
    "hostility": ({"aggression": 0.20, "vigilance": 0.10}, "world_is_hostile"),
    "failure": ({"withdrawal": 0.20}, "on_my_own"),
    "success": ({"withdrawal": -0.10, "trust_default": 0.10}, None),
}
SHAPING_SELF_MODEL_AT = 0.7


def shaping_changes(conn: sqlite3.Connection, pid: str, experience: str, weight: float) -> tuple[list[Change], dict]:
    """The changes to someone's adaptive state from a formative experience, and what they were: {key: delta}."""
    if experience not in SHAPING or var(conn, f"psy.{pid}.vigilance", None) is None:
        return [], {}
    moves, model = SHAPING[experience]
    changes, shifted = [], {}
    for key, step in moves.items():
        cur = var(conn, f"psy.{pid}.{key}", ADAPTIVE[key])
        value = round(min(1.0, max(0.0, cur + step * weight)), 6)
        if value == cur:
            continue
        changes.append(Change("var", f"psy.{pid}.{key}", "value", delta=round(value - cur, 6)))
        shifted[key] = round(value - cur, 6)
        sign = HARM_DIRECTION[key]
        worst = var(conn, f"psy.{pid}.worst.{key}", ADAPTIVE[key])
        if (value - worst) * sign > 0:
            changes.append(Change("var", f"psy.{pid}.worst.{key}", "value", delta=round(value - worst, 6)))
    if model and weight >= SHAPING_SELF_MODEL_AT and var(conn, f"psy.{pid}.self.{model}", None) is not None:
        cur = var(conn, f"psy.{pid}.self.{model}", 0.0)
        if cur < 1.0:
            changes.append(Change("var", f"psy.{pid}.self.{model}", "value", delta=round(1.0 - cur, 6)))
            shifted[f"self.{model}"] = round(1.0 - cur, 6)
    return changes, shifted


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


def self_models(conn: sqlite3.Connection, pid: str) -> dict[str, float]:
    """The self-models someone holds: key -> strength (1 held, 0.5 softened)."""
    out = {}
    for key in SELF_MODEL:
        v = var(conn, f"psy.{pid}.self.{key}", 0.0)
        if v >= 0.5:
            out[key] = v
    return out


def self_bias(conn: sqlite3.Connection, pid: str) -> dict[str, float]:
    """How who someone has come to think they are leans what they do: summed over held self-models, each by its
    strength. Keys: belief, accuse, tell, defend, apologize, withdraw, lend, soothe, warm, retort."""
    out: dict[str, float] = {}
    for key, strength in self_models(conn, pid).items():
        for k, v in SELF_BIAS.get(key, {}).items():
            out[k] = round(out.get(k, 0.0) + v * strength, 3)
    return out


def _home(conn: sqlite3.Connection, pid: str) -> str:
    from world.content import home_of
    return home_of(conn, pid)


# -- appraisal: what a day meant to someone, from what they know ----------------------------------------------------
def appraise(conn: sqlite3.Connection, pid: str, day: int) -> tuple[dict[str, float], list[int]]:
    """Experiences of `pid` on `day`, only from events they took part in or noticed."""
    exp, cited, _ = appraise_detail(conn, pid, day)
    return exp, cited


def appraise_detail(conn: sqlite3.Connection, pid: str, day: int) -> tuple[dict[str, float], list[int], dict[str, list]]:
    """As `appraise`, and which event gave how much of each experience: {kind: [[event_id, weight], ...]}."""
    rows = conn.execute(
        "SELECT e.event_id, e.type, e.truth, e.parent_event_id, e.timestamp, p.role FROM events e JOIN event_participants p "
        "ON p.event_id = e.event_id WHERE p.person_id = ? AND e.timestamp >= ? AND e.timestamp < ? ORDER BY e.event_id",
        (pid, day * 1440, (day + 1) * 1440)).fetchall()
    exp = {k: 0.0 for k in EXPERIENCES}
    cited: list[int] = []
    by_kind: dict[str, list] = {}

    def add(kind: str, w: float, eid: int) -> None:
        exp[kind] += w
        cited.append(eid)
        by_kind.setdefault(kind, []).append([eid, w])

    for r in rows:
        t, kind, role = json.loads(r["truth"]), r["type"], r["role"]
        me_actor, me_target = t.get("actor") == pid, t.get("target") == pid or t.get("victim") == pid
        outcome = t.get("outcome")
        if kind == "confront" and me_actor and outcome in ("lie_exposed", "distortion_exposed", "concealment_exposed"):
            add("betrayal", 1.0, r["event_id"])  # I found out I had been lied to
        elif kind == "confront" and me_target and outcome in ("lie_exposed", "distortion_exposed"):
            add("shame", 1.0, r["event_id"])
        elif kind == "confront" and me_target and outcome == "unfounded":
            add("wronged", 0.8, r["event_id"])  # I told the truth and was called a liar to my face
        elif kind == "confront" and me_target and outcome == "misinformed":
            add("wronged", 0.3, r["event_id"])  # doubted for what someone else got wrong
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
            add("hostility", PROVOKED if _provoked(conn, pid, r) else 1.0, r["event_id"])
        elif kind == "goal_change" and me_actor and t.get("to") in ("abandoned", "blocked"):
            add("failure", 1.0, r["event_id"])
        elif kind == "goal_change" and me_actor and t.get("to") == "completed":
            add("success", 1.0, r["event_id"])
        else:
            from world.domains import style
            if style(kind) is not None:  # a domain pack's event: the pack says what it meant
                from world.domains import active
                for dom in active(conn):
                    for exp_kind, w in dom.appraise(conn, pid, kind, t):
                        if exp_kind in exp:
                            add(exp_kind, w, r["event_id"])
    return exp, cited, by_kind


def _provoked(conn: sqlite3.Connection, pid: str, row: sqlite3.Row) -> bool:
    """Was this hostile word an answer to my own cold or hostile word, accusation or confrontation, just before?"""
    if row["parent_event_id"] is None:
        return False
    p = conn.execute("SELECT type, timestamp, truth FROM events WHERE event_id = ?", (row["parent_event_id"],)).fetchone()
    if p is None or row["timestamp"] - p["timestamp"] > 5:
        return False
    t = json.loads(p["truth"])
    return t.get("actor") == pid and (p["type"] in ("accuse", "confront") or
                                      (p["type"] == "talk" and t.get("tone") in ("cold", "hostile")))


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
    today, cited, by_kind = appraise_detail(conn, pid, day)
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
    if today["hostility"] >= 1.0 and acc["hostility"] >= REPEAT:
        # the harder someone already is, the less more hostility hardens them (linear steps took a quarrelsome world
        # to aggression 0.99 in a month, and with it 38 hostile words a day)
        move("aggression", STEP_DOWN * (1.0 - var(conn, f"psy.{pid}.aggression", 0.2)))
    elif today["hostility"] < 1.0:  # a day without much attack: the edge wears off, slowly (never past the scar)
        move("aggression", -STEP_UP * 0.5)
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
    formed, formed_keys, softened = [], [], []
    for key, (text, source, threshold) in SELF_MODEL.items():
        if var(conn, f"psy.{pid}.self.{key}", None) is None:
            continue  # a world made before this self-model existed has no place for it
        if acc[source] >= threshold and var(conn, f"psy.{pid}.self.{key}", 0.0) < 0.5:
            new[f"self.{key}"] = 1.0
            formed.append(text)
            formed_keys.append(key)
        elif acc[source] < threshold / 3 and var(conn, f"psy.{pid}.self.{key}", 0.0) >= 0.5:
            new[f"self.{key}"] = 0.5  # the belief softens, it does not vanish
            softened.append(key)
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
    truth = {"actor": pid, "day": day, "experiences": {k: round(v, 3) for k, v in today.items() if v},
             "shifted": shifted, "self_model": formed, "cites": sorted(set(cited)), "depends_on": sorted(set(cited))}
    from world.recipes import enabled
    if enabled(conn, "social.exchange"):
        # the three memories (narrative/causal_audit.py): what happened to me (which event gave how much of each
        # experience), and how I came to see myself (which self-models formed or softened tonight)
        truth.update(experienced={k: [[e, round(w, 3)] for e, w in v] for k, v in sorted(by_kind.items())},
                     formed=formed_keys, softened=softened)
    return EventSpec(
        timestamp=now, type="reflection", trigger_type="rule", location_id=_home(conn, pid),
        importance=0.2 + (0.4 if formed else 0.0) + min(0.3, sum(abs(v) for v in shifted.values())),
        truth=truth,
        participants=[(pid, "actor")], changes=changes,
        memories=[MemorySpec(pid, f"我開始覺得：{t}", 1.0) for t in formed])
