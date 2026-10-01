"""Narrative state: what stories the world has formed so far, in one place (read model, never truth).

The episode planner, the producer and the control room all ask the same questions of the same world: which stories are running and which have
stopped moving, who is carrying something unanswered, where the audience is ahead of the crowd, what has been told too often, where a story is
a step from happening. Each used to read the events itself. This compiles them once, as of a day:

  arcs           the story threads, each with whether anything *really* happened in it lately (a feeling, a relationship moved by a real
                 amount, a seat or a goal) and for how many days nothing has: a thread that exists is not a thread that moves
  expectations   people the audience knows to be more than the crowd takes them for (narrative/audience.py), and for how long
  patterns       what has been told, by mechanic and by pair (narrative/novelty.py), and the pairs of the last days
  debts          who is carrying most unanswered (narrative/debt.py; a read model that does not predict better than the opportunity
                 list, so it is shown, not decided on)
  opportunities  the stories the world is half-making and what each lacks (narrative/opportunity.py)
  payoffs        what has been paid off in the last days

It only reads. `narrative_state_v0.1`: a draft.
"""
from __future__ import annotations

import sqlite3

STATE_VERSION = "narrative_state_v0.1"
RECENT_DAYS = 7
STALLED_AFTER = 4        # days of nothing real after which a running thread is called stalled


def _arcs(conn: sqlite3.Connection, day: int) -> list[dict]:
    from narrative.arcs import load_events
    from narrative.director import LIVE
    from narrative.episode_planner import _is_story, _names, real_progress
    from narrative.threads import derive_threads
    events = load_events(conn)
    names = _names(conn)
    out = []
    for t in derive_threads(conn, today=day):
        moved = [events[i].day for i in t.event_ids if i in events and _is_story(events[i]) and real_progress(conn, events[i], names)]
        last = max(moved) if moved else None
        stagnation = (day - last) if last is not None else (day - t.first_day)
        running = t.status in LIVE
        out.append({"id": t.thread_id, "kind": t.kind, "question": t.central_question, "status": t.status, "first_day": t.first_day, "last_day": t.last_day,
                    "people": [names.get(p, p) for p in t.participants], "events": len(t.event_ids), "tension": round(t.tension, 3),
                    "last_progress_day": last, "stagnation": stagnation, "moved_recently": sum(1 for d in moved if day - d < RECENT_DAYS),
                    "stalled": running and stagnation >= STALLED_AFTER})
    return sorted(out, key=lambda a: (a["stalled"], -a["tension"], a["id"]))


def _expectations(conn: sqlite3.Connection, day: int) -> list[dict]:
    from narrative import audience as A
    from narrative.episode_planner import _names
    from world.domains.factions import humans
    names = _names(conn)
    last_event = conn.execute("SELECT COALESCE(MAX(event_id), 0) FROM events").fetchone()[0]
    out = []
    for pid in humans(conn):
        exp = A.expectation_of(conn, pid, last_event)
        if exp is not None and exp.knows - exp.expected >= A.GAP:
            out.append({"person": pid, "name": names.get(pid, pid), "knows": round(exp.knows, 2), "expected": round(exp.expected, 2),
                        "gap": round(exp.knows - exp.expected, 2), "since_day": exp.since_day, "waited": max(0, day - exp.since_day)})
    return sorted(out, key=lambda x: -x["gap"])


def compile_state(conn: sqlite3.Connection, day: int, recent_pairs: list[list[str]] | None = None) -> dict:
    """The narrative state of the world as of the start of `day` (what the episode planner and the control room read)."""
    from narrative import debt, novelty, opportunity, payoff
    from narrative.episode_planner import _names
    names = _names(conn)
    found = payoff.payoffs(conn)
    mem = novelty.PatternMemory.of(found)
    ledger = debt.ledger(conn)
    return {
        "version": STATE_VERSION, "day": day,
        "arcs": _arcs(conn, day),
        "expectations": _expectations(conn, day),
        "patterns": {"mechanics": dict(mem.mechanics), "pairs": dict(sorted(mem.pairs.items(), key=lambda kv: -kv[1])[:6]),
                     "recent_pairs": [[names.get(p, p) for p in pair] for pair in (recent_pairs or [])]},
        "debts": [{"person": r["person"], "name": names.get(r["person"], r["person"]), "debt": r["debt"], "parts": r["parts"]} for r in ledger[:5]],
        "opportunities": [{"kind": o.kind, "protagonist": o.protagonist, "name": names.get(o.protagonist, o.protagonist),
                           "others": [names.get(x, x) for x in o.others], "potential": o.potential, "p_success": o.p_success,
                           "missing": [m.lack for m in o.missing]} for o in opportunity.detect(conn, day)[:5]],
        "payoffs": [{"kind": p["kind"], "name": names.get(p["protagonist"], p["protagonist"]), "day": p["day"], "earned": p["earned"]}
                    for p in found if day - p["day"] < RECENT_DAYS],
    }
