"""Opportunities: where is a story close to happening, and what does it lack? (read model, never truth)

`detect(conn, day)` reads the world as it is and lists the stories it is half-making, each with who, how much it would be worth,
how open the outcome still is, and the conditions it lacks. It never writes, and it never decides anything about a person: it
looks only at what the world's own state says (what people can really do and what the others take them for, who is drawn to
whom, which seat is held), so the audience's knowledge (the irony: the truth is ahead of what the crowd believes) is the
raw material, and the producer's job (producer/shaper.py) is only to supply what is lacking.

  reversal    somebody the crowd rates below another, who would in fact have a fair chance against them, and who is looked down on
              (so the other would take up a challenge). Worth: how much the crowd would be surprised x what the hero has been
              through x how open the result is. It is NOT worth arranging when the hero is bound to win (nothing is open), nor when
              they are bound to lose
  triangle    two people drawn to the same third, about equally
  succession  a seat held, and somebody of the same side who could hold it

`opportunity_model_v0.1`: a draft; the numbers are first guesses that the producer lab will say something about.
"""
from __future__ import annotations

import hashlib
import sqlite3

from contracts.opportunity import MissingCondition, Opportunity

MODEL_VERSION = "opportunity_model_v0.1"
SURE_WIN = 0.85         # above this the protagonist is bound to win: no suspense, not worth arranging
SURE_LOSS = 0.30        # below this they are bound to lose
SHORT = 0.45            # between SURE_LOSS and this the hero is a little short of strength
LOOKS_DOWN = 0.15       # the other believes they beat the hero by at least this much (and so would take the challenge)
CRUSH = 0.30            # attraction at which a feeling is worth watching
PURSUIT_DAYS = 7


def _oid(kind: str, protagonist: str, others: list[str]) -> str:
    return "op-" + hashlib.sha256(f"{kind}:{protagonist}:{','.join(sorted(others))}".encode()).hexdigest()[:10]


def _suspense(p: float) -> float:
    return round(max(0.0, 1.0 - abs(2.0 * p - 1.0)), 4)


def _ability(conn: sqlite3.Connection, pid: str) -> float:
    from world.attention import var
    return var(conn, f"skill.{pid}", 0.0)


def _crowd(conn: sqlite3.Connection, pid: str) -> float:
    r = conn.execute("SELECT AVG(estimate) FROM relationships WHERE target_id = ? AND actor_id != ?", (pid, pid)).fetchone()[0]
    return 0.5 if r is None else r


def gathering_ahead(conn: sqlite3.Connection, day: int) -> int | None:
    """The day of the next announced tournament that has not happened yet, or None."""
    import json
    best = None
    for (t,) in conn.execute("SELECT truth FROM events WHERE type = 'intervention' AND json_extract(truth, '$.kind') = 'announce_gathering'"):
        p = json.loads(t)["params"]
        if p["kind"] == "tournament" and int(p["day"]) >= day and (best is None or int(p["day"]) < best):
            best = int(p["day"])
    return best


def _reversals(conn: sqlite3.Connection, day: int, unfiltered: bool = False) -> list[Opportunity]:
    from narrative.payoff import _pressure
    from world.domains.factions import humans
    from world.domains.progression import SLAP_MARGIN
    from world.jianghu import FIGHTER, injured, recent_duel, win_chance
    now = day * 1440
    ahead = gathering_ahead(conn, day)
    fighters = [p for p in humans(conn) if _ability(conn, p) >= FIGHTER]
    out = []
    for h in fighters:
        for o in fighters:
            if o == h:
                continue
            surprise = _crowd(conn, o) - _crowd(conn, h)   # how far the crowd is from expecting this pair's result
            p = win_chance(conn, h, o)
            if not unfiltered and (surprise < SLAP_MARGIN or not SURE_LOSS <= p <= SURE_WIN):
                continue  # (unfiltered is only for the control that ignores what a story is: producer/director.py `blind`)
            view = conn.execute("SELECT estimate FROM relationships WHERE actor_id = ? AND target_id = ?", (o, h)).fetchone()
            believed_gap = _ability(conn, o) - (view[0] if view else 0.5)
            pressure = _pressure(conn, h, day)
            potential = round(max(0.0, min(1.0, surprise / 0.4)) * (0.6 + 0.4 * pressure) * _suspense(p), 4)
            missing = []
            if injured(conn, h, now) or injured(conn, o, now) or recent_duel(conn, h, o, now):
                missing.append(MissingCondition("recovery", "somebody is hurt or they fought lately"))
            if ahead is None:
                missing.append(MissingCondition("occasion", "no tournament is announced"))
            if believed_gap < LOOKS_DOWN:
                missing.append(MissingCondition("challenger", f"{o} does not think they would win"))
            if SURE_LOSS <= p < SHORT:
                missing.append(MissingCondition("strength", "a little short of what it takes"))
            out.append(Opportunity(_oid("reversal", h, [o]), "reversal", h, [o], day, potential, _suspense(p), round(p, 4), missing,
                                   {"surprise": round(surprise, 3), "pressure": round(pressure, 3), "believed_gap": round(believed_gap, 3),
                                    "tournament_day": ahead}))
    return out


def _triangles(conn: sqlite3.Connection, day: int) -> list[Opportunity]:
    from narrative.payoff import _pressure
    from world.domains import romance as R
    from world.domains.factions import humans
    people = [p for p in humans(conn) if R.adult(conn, p)]
    att = {(a, c): conn.execute("SELECT attraction FROM relationships WHERE actor_id = ? AND target_id = ?", (a, c)).fetchone()[0]
           for a in people for c in people if a != c}
    out = []
    for c in people:
        wanting = sorted((a for a in people if a != c and att[(a, c)] >= CRUSH and R.drawn_to(conn, a, c)), key=lambda a: (-att[(a, c)], a))
        for i, a in enumerate(wanting):
            for b in wanting[i + 1:]:
                p = att[(a, c)] / (att[(a, c)] + att[(b, c)])
                missing = []
                chased = conn.execute("SELECT 1 FROM events WHERE type IN ('flirt', 'confession') AND json_extract(truth, '$.actor') = ? AND "
                                      "json_extract(truth, '$.target') = ? AND timestamp >= ? LIMIT 1", (b, c, (day - PURSUIT_DAYS) * 1440)).fetchone()
                if chased is None:
                    missing.append(MissingCondition("challenger", f"{b} has not been courting {c}"))
                potential = round(min(att[(a, c)], att[(b, c)]) * _suspense(p) * (0.6 + 0.4 * _pressure(conn, a, day)), 4)
                out.append(Opportunity(_oid("triangle", a, [b, c]), "triangle", a, [b, c], day, potential, _suspense(p), round(p, 4), missing,
                                       {"object": c, "attraction": [round(att[(a, c)], 3), round(att[(b, c)], 3)]}))
    return out


def _successions(conn: sqlite3.Connection, day: int) -> list[Opportunity]:
    from narrative.payoff import _pressure
    from world.domains import factions as F
    out = []
    for s in conn.execute("SELECT seat_id, faction_id, holder_id, status FROM seats WHERE status IN ('held', 'vacant') ORDER BY seat_id"):
        rivals = [m for m in F.members(conn, s["faction_id"]) if m != s["holder_id"]] if s["faction_id"] else []
        if not rivals or not s["holder_id"]:
            continue
        hero = max(rivals, key=lambda m: (F.influence(conn, m), m))
        w_h, w_o = max(0.05, 0.5 + F.influence(conn, hero)), max(0.05, 0.5 + F.influence(conn, s["holder_id"]))
        p = w_h / (w_h + w_o)
        missing = [MissingCondition("vacancy", "the seat is held")] if s["status"] == "held" else []
        out.append(Opportunity(_oid("succession", hero, [s["holder_id"], s["seat_id"]]), "succession", hero, [s["holder_id"]], day,
                               round(_suspense(p) * (0.6 + 0.4 * _pressure(conn, hero, day)), 4), _suspense(p), round(p, 4), missing,
                               {"seat": s["seat_id"], "status": s["status"]}))
    return out


def detect(conn: sqlite3.Connection, day: int, unfiltered: bool = False) -> list[Opportunity]:
    """Every story the world is half-making as of `day`, the most worth having first (ties by id, so the list is deterministic)."""
    found = _reversals(conn, day, unfiltered) + _triangles(conn, day) + _successions(conn, day)
    return sorted(found, key=lambda o: (-o.potential, o.opportunity_id))
