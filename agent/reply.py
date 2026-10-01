"""A word gets an answer. When someone is spoken to, accused or confronted, they answer at once, and the exchange
goes on until one of them lets it go, walks out, or it has gone on long enough.

Nothing here writes the world. Each answer is an ordinary Intent (talk with a tone, or move away) that the validator
may refuse and the rules resolve; its reason says how it was meant ("reply:retort", "reply:apologize", ...), so the
event can be read back as a line in a scene. What someone answers comes from what was just done to them, who they are
(temper, honesty, generosity; aggression and withdrawal from their history), how they feel about the other, and
whether they are in the wrong.

Stances:
  chat       warm or neutral words back after warm or neutral words
  soothe     warm words back after cold ones or an attack: calming it down
  apologize  warm words back from someone who is in the wrong (caught, exposed)
  explain    neutral words back after an attack
  deny       cold words back from someone accused
  rebuff     cold words back
  retort     hostile words back: it escalates
  storm_off  walking out
A bystander may step in once when it turns ugly: comfort the one attacked, or side with them against the attacker.
"""
from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import replace

from world.intent import Intent
from world.rng import rng as make_rng

MAX_TURNS = 8
TEMPERATURE = 0.3
TONE_HEAT = {"warm": 0, "neutral": 1, "cold": 2, "hostile": 3}
# what being on the receiving end of an accusation or a confrontation feels like, by its outcome, for the one
# answering: (heat, in the wrong)
OUTCOME_HEAT = {
    "caught": (2, True), "denied": (2, False), "false": (3, False),                   # accuse
    "lie_exposed": (2, True), "distortion_exposed": (2, True), "concealment_exposed": (2, True),  # confront
    "misinformed": (1, False), "unfounded": (3, False), "inconclusive": (2, False),
}
ANSWERED = ("talk", "accuse", "confront")


def stimulus(row: sqlite3.Row) -> tuple[str, str, int, bool, bool] | None:
    """(who answers, to whom, heat 0..3, is the one answering in the wrong, was it an accusation) for an event that
    calls for an answer, else None."""
    if row["type"] not in ANSWERED:
        from world.domains import style
        st = style(row["type"])  # a domain's event that calls for an answer (a master's demand, ...)
        if st is None or not st.opens_scene:
            return None
        t = json.loads(row["truth"])
        a, b = t.get("actor"), t.get("target")
        return (b, a, st.heat, False, False) if a and b and a != b else None
    t = json.loads(row["truth"])
    a, b = t.get("actor"), t.get("target")
    if not a or not b or a == b:
        return None
    if row["type"] == "talk":
        return b, a, TONE_HEAT.get(t.get("tone"), 1), False, False
    heat, wrong = OUTCOME_HEAT.get(t.get("outcome"), (2, False))
    return b, a, heat, wrong, True


def heat_of(row: sqlite3.Row) -> int:
    s = stimulus(row)
    return s[2] if s else 0


def _together(conn: sqlite3.Connection, a: str, b: str) -> bool:
    rows = conn.execute("SELECT id, location_id, status FROM people WHERE id IN (?, ?)", (a, b)).fetchall()
    return len(rows) == 2 and rows[0]["location_id"] == rows[1]["location_id"] and all(r["status"] == "active" for r in rows)


def _away(conn: sqlite3.Connection, me: str) -> str | None:
    """Where one walks out to: home if one can get there from here, else the first place one can reach."""
    from world.content import home_of
    here = conn.execute("SELECT location_id FROM people WHERE id = ?", (me,)).fetchone()[0]
    nxt = [r[0] for r in conn.execute("SELECT to_location_id FROM location_edges WHERE from_location_id = ? "
                                      "ORDER BY to_location_id", (here,))]
    home = home_of(conn, me)
    return home if home in nxt and home != here else (nxt[0] if nxt else None)


def _pick(scored: list[tuple[float, Intent | None]], rng) -> Intent | None:
    weights = [math.exp(s / TEMPERATURE) for s, _ in scored]
    return rng.choices(scored, weights)[0][1]


def _grudge(conn: sqlite3.Connection, me: str, other: str) -> float:
    from world.goals import goals_of, has_goals
    if not has_goals(conn):
        return 0.0
    return max((g["priority"] for g in goals_of(conn, me) if g["status"] == "active" and g["target"] == other
                and g["kind"] in ("revenge", "expose", "outshine")), default=0.0)


class Replier:
    """Rule answers for anyone. Same world, same seed, same moment: same answer."""

    def __init__(self, world_seed: int | str) -> None:
        self.world_seed = world_seed

    def reply(self, conn: sqlite3.Connection, row: sqlite3.Row, turn: int, now: int) -> Intent | None:
        s = stimulus(row)
        if s is None:
            return None
        me, other, heat, wrong, accused = s
        if not _together(conn, me, other):
            return None
        if heat >= 2:  # mid-quarrel, past self-control, it may take over
            from agent.volition import seizure
            seized = seizure(conn, me, now, [other])
            if seized is not None:
                return seized
        scored = self.scored(conn, row, turn, now)
        if not scored:
            return None
        choice = _pick(scored, make_rng(self.world_seed, now, f"{me}:{row['event_id']}", "reply"))
        if choice is None:
            return None
        from agent.trace import build
        return replace(choice, trace=build(conn, me, scored, choice, TEMPERATURE, now, {
            "kind": "reply", "to": row["event_id"], "heat": heat, "wrong": wrong, "accused": accused}))

    def scored(self, conn: sqlite3.Connection, row: sqlite3.Row, turn: int, now: int) -> list | None:
        """Every answer `row` could get now, with how much it is wanted (before the pick; a seizure aside). The
        persona probe (persona_probe.py) reads these to know what someone would do in a given circumstance."""
        s = stimulus(row)
        if s is None:
            return None
        me, other, heat, wrong, accused = s
        if not _together(conn, me, other):
            return None
        from agent.volition import rel, traits
        from world.psyche import trait
        t = traits(conn, me)
        r = rel(conn, me, other)
        emotion = conn.execute("SELECT emotion FROM people WHERE id = ?", (me,)).fetchone()[0]
        aggression, withdrawal = trait(conn, me, "aggression"), trait(conn, me, "withdrawal")
        affection, fear = r["affection"], max(0.0, r["fear"])
        tired = 0.18 * (turn - 1)  # every exchange runs out of steam
        sore = 0.3 if emotion in ("angry", "hurt", "embarrassed", "ashamed") else 0.0
        from agent.volition import STRAIN_WEIGHT, strain
        from world.psyche import self_bias
        sb = self_bias(conn, me)  # who they have come to think they are
        from agent.volition import irritability
        short = irritability(conn, me, now)  # tired, hungry, worked up
        worn = STRAIN_WEIGHT * strain(conn, me, now) * (1.0 - 0.6 * aggression)  # recent clashes: less fight left

        def say(tone: str, stance: str) -> Intent:
            return Intent(me, "talk", other, tone, reason=f"reply:{stance}")

        if heat <= 1:  # pleasant or plain words: a little small talk, then it ends
            scored = [(0.45 + tired + 0.3 * withdrawal, None),
                      (0.25 + 0.3 * affection + 0.2 * t["curiosity"] - 0.15 * heat, say("warm", "chat")),
                      (0.2, say("neutral", "chat"))]
            if heat == 1 and r["rivalry"] > 0.2:
                scored.append((0.1 + 0.4 * r["rivalry"] + 0.3 * t["temper"], say("cold", "rebuff")))
        else:
            wronged = heat >= 3 and not wrong
            retort = (t["temper"] * (0.35 + 0.2 * heat) + 0.8 * (aggression - 0.2) + sore + 0.5 * wronged
                      + 0.5 * _grudge(conn, me, other) - 0.7 * fear - 0.3 * max(0.0, affection) - 0.4 * wrong
                      - worn - 0.12 * (turn - 1) + sb.get("retort", 0.0) + (sb.get("defend", 0.0) if accused else 0.0)
                      + short)
            scored = [
                (0.15 + tired + 0.5 * fear + 0.3 * withdrawal + 0.5 * worn + sb.get("withdraw", 0.0), None),  # swallows it
                (retort, say("hostile", "retort")),
                (0.3 + 0.2 * (heat >= 2) + 0.2 * t["temper"] + (sb.get("defend", 0.0) if accused else 0.0),
                 say("cold", "deny" if accused else "rebuff")),
                (0.1 + 0.4 * t["generosity"] + 0.4 * max(0.0, affection) - 0.3 * t["temper"] - 0.2 * wronged
                 + (sb.get("apologize", 0.0) if wrong else sb.get("soothe", 0.0)), say("warm", "apologize" if wrong else "soothe")),
                (0.2 + 0.3 * (1 - t["temper"]) - 0.1 * heat, say("neutral", "explain")),
            ]
            if wrong:  # in the wrong: owning up, or getting out of there
                scored.append((-0.1 + 1.1 * t["honesty"] + 0.4 * t["generosity"] - 0.3 * (aggression - 0.2)
                               + sb.get("apologize", 0.0), say("warm", "apologize")))
            from world.domains import active
            for dom in active(conn):  # what a domain lets an answer be (past self-control: a shove, a blow)
                scored += dom.reply_options(conn, me, other, heat, now)
            away = _away(conn, me)
            if away:
                scored.append((-0.1 + 0.9 * withdrawal + 0.5 * fear + 0.4 * wrong + 0.3 * wronged * (1 - t["temper"])
                               + 0.1 * turn, Intent(me, "move", away, reason="reply:storm_off")))
        return scored

    def intervene(self, conn: sqlite3.Connection, row: sqlite3.Row, now: int) -> Intent | None:
        """Someone else there steps in when it turns ugly: comforts the one attacked, or turns on the attacker."""
        s = stimulus(row)
        if s is None or s[2] < 3:
            return None
        victim, attacker = s[0], s[1]
        from agent.volition import rel, traits
        here = conn.execute("SELECT location_id FROM people WHERE id = ?", (victim,)).fetchone()[0]
        from world.animals import animal_ids
        animals = animal_ids(conn)
        present = [r[0] for r in conn.execute("SELECT id FROM people WHERE location_id = ? AND status = 'active' "
                                              "AND id NOT IN (?, ?) ORDER BY id", (here, victim, attacker))
                   if r[0] not in animals]
        if not present:
            return None
        noticed = set()
        for (pid,) in conn.execute("SELECT person_id FROM event_participants WHERE event_id = ? AND role = 'witness'",
                                   (row["event_id"],)):
            noticed.add(pid)
        rows = conn.execute("SELECT observer_id FROM memories WHERE event_id = ?", (row["event_id"],)).fetchall()
        noticed |= {r[0] for r in rows}
        scored: list[tuple[float, Intent | None]] = [(0.9, None)]
        for w in present:
            if w not in noticed:
                continue  # one steps in only if one noticed
            t = traits(conn, w)
            to_v, to_a = rel(conn, w, victim), rel(conn, w, attacker)
            scored.append((0.1 + 0.8 * max(0.0, to_v["affection"]) + 0.4 * t["generosity"],
                           Intent(w, "talk", victim, "warm", reason="intervene:comfort")))
            scored.append((0.1 + 0.8 * (to_v["affection"] - to_a["affection"]) + 0.4 * t["temper"] - 0.5 * max(0.0, to_a["fear"]),
                           Intent(w, "talk", attacker, "cold", reason="intervene:side")))
        if len(scored) == 1:
            return None
        return _pick(scored, make_rng(self.world_seed, now, f"{row['event_id']}", "intervene"))
