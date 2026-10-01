"""Depth in relationships, as a domain pack (primitive social.depth).

Trust and affection say how a person stands with another; they do not say what the two have been through. Three more
things are kept for each pair, from one to the other (world/schema.sql, relationships):

  familiarity  how well they know each other: it grows with every exchange and fades slowly when they stop meeting
  resentment   what has been done to them, and not forgiven: it comes from being wronged, accused falsely, robbed, hit,
               and fades only slowly, an apology takes some of it away
  respect      what they have seen the other do: it falls when somebody is caught in a lie or a theft or loses control in
               public, and rises when they win fairly or keep their word. Everybody who saw it feels it, not only the pair

They are world truth like any other relationship value: events change them, and they decide things. A grudge makes the
next words colder and an argument worse; knowing someone makes small talk likelier; respect decides who may talk down to
whom. The pack declares and returns changes; the core applies them.
"""
from __future__ import annotations

import sqlite3

from contracts.recipe import MechanicPrimitive as P
from world.domains.base import Domain, Scored, add_changes
from world.events import Change, EventSpec
from world.helpers import RelDeltas, rel
from world.intent import Intent

FAMILIAR = 0.02          # per exchange, times how much room is left
FORGET = 0.004           # familiarity lost on a day the pair did not meet
GRUDGE_FADE = 0.03       # share of a resentment that fades each night
RESPECT_FADE = 0.01      # respect drifts back to nothing, slowly
APOLOGY = -0.15          # what an apology takes off the resentment of the one apologised to
GRUDGE_AT = 0.25         # a resentment this deep makes an argument worse
# what resentment (target -> actor) an event leaves, and what respect (those who saw -> the actor or the target)
RESENT = {"hostile": 0.06, "cold": 0.02, "accuse_false": 0.25, "unfounded": 0.20, "caught": 0.15, "steal": 0.35,
          "shove": 0.30, "strike": 0.40, "provoked": 0.10, "beaten": 0.05}
RESPECT = {"caught": -0.25, "exposed": -0.25, "steal": -0.30, "shove": -0.15, "strike": -0.25, "duel_loser": 0.15,
           "duel_watcher": 0.12, "bully": -0.10, "repay": 0.08}


class Relations(Domain):
    id = "relations"
    title = "人際深度"
    primitives = (P("social.depth", "social", "what a pair has been through: familiarity, resentment, respect; they are "
                    "world truth and they decide how the next words are said", ["social.exchange"], cost=0),)

    # -- what events do to a pair ----------------------------------------------------------------------------------
    def effects(self, conn: sqlite3.Connection, spec: EventSpec, primitives: set[str]) -> EventSpec:
        t = spec.truth
        a, b = t.get("actor"), t.get("target") or t.get("victim")
        if not a or not b or a == b:
            return spec
        seen = [p for p, role in spec.participants if role == "witness" and p not in (a, b)]
        d = RelDeltas()
        if spec.type in ("talk", "tell", "confront", "accuse", "lend", "repay", "give", "flirt", "date", "confession"):
            for x, y in ((a, b), (b, a)):  # an exchange: they know each other a little better
                d.add(x, y, "familiarity", FAMILIAR * (1.0 - max(0.0, rel(conn, x, y, "familiarity"))))
        if spec.type == "talk":
            tone = t.get("tone")
            if tone in ("hostile", "cold"):
                d.add(b, a, "resentment", RESENT[tone])
            elif t.get("reason", "").endswith("apologize") and rel(conn, b, a, "resentment") > 0:
                d.add(b, a, "resentment", APOLOGY)  # an apology is heard
        elif spec.type == "accuse":
            if t.get("outcome") == "false":
                d.add(b, a, "resentment", RESENT["accuse_false"])
            elif t.get("outcome") == "caught":
                d.add(a, b, "resentment", RESENT["caught"])
                for w in [a] + seen:
                    d.add(w, b, "respect", RESPECT["caught"])
        elif spec.type == "confront":
            if t.get("outcome") == "unfounded":
                d.add(b, a, "resentment", RESENT["unfounded"])
            elif t.get("outcome") in ("lie_exposed", "distortion_exposed", "concealment_exposed"):
                for w in [a] + seen:
                    d.add(w, b, "respect", RESPECT["exposed"])
        elif spec.type == "steal" and t.get("owner_noticed"):
            d.add(b, a, "resentment", RESENT["steal"])
            for w in [b] + seen:
                d.add(w, a, "respect", RESPECT["steal"])
        elif spec.type in ("shove", "strike"):
            provoked = bool(t.get("provoked_by_target"))
            d.add(b, a, "resentment", RESENT["provoked" if provoked else spec.type])
            if not provoked:
                for w in [b] + seen:
                    d.add(w, a, "respect", RESPECT[spec.type])
        elif spec.type == "duel":
            winner, loser = t.get("winner"), t.get("loser")
            if winner and loser:
                d.add(loser, winner, "respect", RESPECT["duel_loser"])
                d.add(loser, winner, "resentment", RESENT["beaten"])
                for w in seen:
                    d.add(w, winner, "respect", RESPECT["bully" if t.get("bully") else "duel_watcher"])
        elif spec.type == "repay":
            d.add(b, a, "respect", RESPECT["repay"])
        return add_changes(conn, spec, d.changes(conn)) if d._sum else spec

    def overnight(self, conn: sqlite3.Connection, pid: str, now: int) -> list[Change]:
        """In one's sleep: grudges fade a little, respect drifts back, people not met today are known a little less."""
        today = (now // 1440) * 1440
        met = {r[0] for r in conn.execute(
            "SELECT DISTINCT p2.person_id FROM event_participants p1 JOIN event_participants p2 ON p2.event_id = p1.event_id "
            "JOIN events e ON e.event_id = p1.event_id WHERE p1.person_id = ? AND p2.person_id != ? AND e.timestamp >= ? "
            "AND e.type IN ('talk', 'tell', 'confront', 'accuse', 'lend', 'repay', 'give', 'flirt', 'date', 'confession')",
            (pid, pid, today))}
        out = []
        for r in conn.execute("SELECT target_id, resentment, respect, familiarity FROM relationships WHERE actor_id = ? "
                              "ORDER BY target_id", (pid,)):
            for field, cur, delta in (("resentment", r["resentment"], -GRUDGE_FADE * r["resentment"]),
                                      ("respect", r["respect"], -RESPECT_FADE * r["respect"]),
                                      ("familiarity", r["familiarity"],
                                       0.0 if r["target_id"] in met else -min(FORGET, max(0.0, r["familiarity"])))):
                d = round(delta, 6)
                if d and abs(cur + d) <= 1.0:
                    out.append(Change("relationship", f"{pid}:{r['target_id']}", field, delta=d))
        return out

    # -- what it decides -------------------------------------------------------------------------------------------
    def shape(self, conn: sqlite3.Connection, actor: str, now: int, scored: Scored) -> Scored:
        """A grudge cools or sharpens the words one is about to say; knowing someone makes talking likelier; low respect
        makes one curt, high respect makes one warm."""
        out = []
        cache: dict[str, sqlite3.Row] = {}
        for score, it in scored:
            if it is not None and it.action == "talk" and it.target:
                r = cache.get(it.target)
                if r is None:
                    r = cache[it.target] = conn.execute(
                        "SELECT resentment, respect, familiarity FROM relationships WHERE actor_id = ? AND target_id = ?",
                        (actor, it.target)).fetchone()
                if r is not None:
                    grudge, respect, known = max(0.0, r["resentment"]), r["respect"], max(0.0, r["familiarity"])
                    if it.tone == "warm":
                        score += 0.2 * max(0.0, respect) + 0.3 * known - 0.6 * grudge - 0.2 * max(0.0, -respect)
                    elif it.tone == "neutral":
                        score += 0.2 * known - 0.2 * grudge
                    elif it.tone == "cold":
                        score += 0.5 * grudge + 0.3 * max(0.0, -respect)
                    elif it.tone == "hostile":
                        score += 0.7 * grudge
            out.append((score, it))
        return out

    def reply_options(self, conn: sqlite3.Connection, me: str, other: str, heat: int, now: int) -> Scored:
        """In an argument, an old grudge is one more reason to say it: a harder answer, weighed by how deep it goes."""
        if heat < 2:
            return []
        r = conn.execute("SELECT resentment FROM relationships WHERE actor_id = ? AND target_id = ?", (me, other)).fetchone()
        grudge = r["resentment"] if r else 0.0
        if grudge < GRUDGE_AT:
            return []
        return [(0.9 * (grudge - GRUDGE_AT) + 0.1, Intent(me, "talk", other, "hostile", reason="reply:grudge"))]

    def influences(self, conn: sqlite3.Connection, pid: str, now: int) -> list[dict]:
        """The deepest grudge someone carries, when it is deep enough to lean what they say."""
        r = conn.execute("SELECT target_id, resentment FROM relationships WHERE actor_id = ? ORDER BY resentment DESC, "
                         "target_id LIMIT 1", (pid,)).fetchone()
        return [{"kind": "grudge", "against": r["target_id"], "resentment": round(r["resentment"], 3)}] \
            if r is not None and r["resentment"] >= GRUDGE_AT else []

    # -- read model --------------------------------------------------------------------------------------------------
    def describe(self, conn: sqlite3.Connection, pid: str) -> dict:
        rows = conn.execute("SELECT target_id, resentment, respect, familiarity FROM relationships WHERE actor_id = ?", (pid,)).fetchall()
        return {"grudges": sorted(((r["target_id"], round(r["resentment"], 2)) for r in rows if r["resentment"] >= 0.1),
                                  key=lambda x: -x[1])[:3],
                "respects": sorted(((r["target_id"], round(r["respect"], 2)) for r in rows if r["respect"] >= 0.15),
                                   key=lambda x: -x[1])[:3],
                "knows_best": sorted(((r["target_id"], round(r["familiarity"], 2)) for r in rows if r["familiarity"] >= 0.1),
                                     key=lambda x: -x[1])[:3]}
