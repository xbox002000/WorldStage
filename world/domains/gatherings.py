"""Gatherings: what happens to a town when a tournament or an assessment has been announced (primitive event.gatherings).

An announcement (world/interventions.py `announce_gathering`) is only words: a place, a day, a kind, said to everybody. This pack is the
town's answer to it, by its own rules and with nothing decided for anyone:

  - on the day, in the afternoon, each person who heard of it goes, or does not: how likely depends on who they are (their curiosity
    and ambition, whether they are a fighter, if it is a tournament), settled by the world's seed. Their routine step is replaced by a
    walk to the place; nothing else about their day is touched. The hero may well not come;
  - at a tournament, those who are there are readier to challenge (it is what the day is for), and everybody there sees what happens:
    nothing makes anyone win, or be the one challenged;
  - at an assessment, they are simply there together.

So an announced gathering changes *who is where, when, and watching*: the opportunity. What is done with it is the people's.
"""
from __future__ import annotations

import json
import sqlite3

from contracts.recipe import MechanicPrimitive as P
from world.attention import var, world_seed
from world.domains.base import Domain, Scored
from world.intent import Intent
from world.rng import rng as make_rng

START, END = 780, 1080       # minute of the day from which the afternoon routine is replaced, and until
TOURNAMENT_PUSH = 2.5        # how much readier to challenge those at a tournament are (0.7 was measured to start no duel at all: 0 in 8 tournaments; 2.5 gives about 1.5 bouts)


def today(conn: sqlite3.Connection, now: int) -> dict | None:
    """The gathering announced for this day (the latest announcement for it), or None."""
    day = now // 1440
    got = None
    for r in conn.execute("SELECT event_id, truth FROM events WHERE type = 'intervention' AND json_extract(truth, '$.kind') = 'announce_gathering' "
                          "AND timestamp < ? ORDER BY event_id", ((day + 1) * 1440,)):
        t = json.loads(r[1])
        if int(t["params"]["day"]) == day:
            got = {"event_id": r[0], **t["params"]}
    return got


def attends(conn: sqlite3.Connection, pid: str, g: dict) -> bool:
    """Whether somebody who has heard of it goes (a seeded draw, weighted by who they are)."""
    from world.profiles import profile
    if conn.execute("SELECT 1 FROM memories WHERE observer_id = ? AND source_id = (SELECT json_extract(truth, '$.intervention_id') FROM events "
                    "WHERE event_id = ?)", (pid, g["event_id"])).fetchone() is None:
        return False  # never heard of it
    row = conn.execute("SELECT traits FROM personas WHERE person_id = ?", (pid,)).fetchone()
    t = json.loads(row[0]) if row else {}
    p = profile(conn, pid)
    ambition = p.values.get("ambition", 0.4) if p else 0.4
    fighter = var(conn, f"skill.{pid}", 0.0) >= 0.2
    chance = 0.25 + 0.3 * t.get("curiosity", 0.4) + 0.3 * ambition + (0.25 if g["kind"] == "tournament" and fighter else 0.0)
    return make_rng(world_seed(conn), g["event_id"], pid, "attend").random() < max(0.1, min(0.95, chance))


class Gatherings(Domain):
    id = "gatherings"
    title = "聚會"
    primitives = (P("event.gatherings", "social", "an announced tournament or assessment: who goes is up to them, and those there see "
                    "what happens", ["social.exchange"], cost=0),)

    def scripted(self, conn: sqlite3.Connection, it: Intent, now: int) -> Intent | None:
        g = today(conn, now)
        if g is None or not START <= now % 1440 < END or it.action not in ("move", "work", "eat"):
            return it
        if not attends(conn, it.actor, g):
            return it
        here = conn.execute("SELECT location_id FROM people WHERE id = ?", (it.actor,)).fetchone()[0]
        if here == g["place"]:
            return None  # already there: they stay
        return Intent(it.actor, "move", g["place"], reason="gathering")

    def shape(self, conn: sqlite3.Connection, actor: str, now: int, scored: Scored) -> Scored:
        g = today(conn, now)
        if g is None or g["kind"] != "tournament" or not START <= now % 1440 < END:
            return scored
        if conn.execute("SELECT location_id FROM people WHERE id = ?", (actor,)).fetchone()[0] != g["place"]:
            return scored
        return [(s + (TOURNAMENT_PUSH if it is not None and it.action == "challenge" else 0.0), it) for s, it in scored]

    def influences(self, conn: sqlite3.Connection, pid: str, now: int) -> list[dict]:
        g = today(conn, now)
        if g is None or not START <= now % 1440 < END:
            return []
        here = conn.execute("SELECT location_id FROM people WHERE id = ?", (pid,)).fetchone()[0]
        return [{"kind": "gathering", "what": g["kind"], "there": here == g["place"]}] if here == g["place"] else []
