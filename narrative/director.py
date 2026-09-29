"""Story director: which thread is worth following today. It picks what to film, never what happens.

The score is deterministic and made of parts (no model judges):
momentum   what moved in the last two days;
tension    how open the thread's question still is;
stakes     what is at risk;
asymmetry  how many beliefs about it are wrong (someone knows something others do not);
crossing   how many other threads it touches;
novelty    not shown in the last episodes;
payoff     somebody holds grounds to accuse or confront, so the question may be settled soon.

A thread qualifies only if its new material contains at least one event a character chose. A thread made only of
rules, props and seeds is weather, not story (this is what `seed_direct_plot_rate` measures).
"""
from __future__ import annotations

import sqlite3

from contracts.thread import StoryThread, ThreadScore
from narrative.arcs import Arc, Ev, load_events
from narrative.selector import Candidate
from narrative.threads import derive_threads

WEIGHTS = {"momentum": 0.25, "tension": 0.20, "stakes": 0.15, "asymmetry": 0.15, "crossing": 0.10,
           "novelty": 0.10, "payoff": 0.05}
LIVE = ("forming", "active", "escalating", "climax")
MAX_EVENTS = 6


def _payoff(conn: sqlite3.Connection, t: StoryThread) -> float:
    if t.kind != "item":
        return 0.0
    obj = t.thread_id.split(":", 1)[1]
    row = conn.execute(
        "SELECT 1 FROM memories m JOIN claims c USING (claim_id) JOIN objects o ON o.id = c.object "
        "WHERE c.object = ? AND c.act IN ('take', 'steal') AND m.observer_id = o.rightful_owner_id "
        "AND m.confidence >= 0.3 LIMIT 1", (obj,)).fetchone()
    return 1.0 if row else 0.0


def score_thread(conn: sqlite3.Connection, t: StoryThread, shown: set[int]) -> ThreadScore:
    new = [e for e in t.event_ids if e not in shown]
    parts = {
        "momentum": t.momentum,
        "tension": t.tension,
        "stakes": t.stakes,
        "asymmetry": min(1.0, t.information_asymmetry / 3),
        "crossing": min(1.0, len(t.cross_threads) / 3),
        "novelty": len(new) / len(t.event_ids) if t.event_ids else 0.0,
        "payoff": _payoff(conn, t),
    }
    return ThreadScore(t.thread_id, round(sum(WEIGHTS[k] * v for k, v in parts.items()), 4),
                       {k: round(v, 3) for k, v in parts.items()})


def rank_threads(conn: sqlite3.Connection, day: int, shown: set[int] | frozenset[int] = frozenset(),
                 lookback_days: int = 1) -> list[tuple[ThreadScore, StoryThread]]:
    """Threads with new, chosen material in the last `lookback_days + 1` days, best first."""
    ranked = []
    for t in derive_threads(conn, today=day):
        if t.status not in LIVE or t.last_day < day - lookback_days:
            continue
        if not [e for e in t.decision_event_ids if e not in shown]:
            continue
        ranked.append((score_thread(conn, t, set(shown)), t))
    ranked.sort(key=lambda st: (-st[0].score, st[1].thread_id))
    return ranked


def thread_arc(t: StoryThread, events: dict[int, Ev], shown: set[int]) -> Arc:
    """The episode material: the thread's newest events not yet shown, plus its origin for context."""
    fresh = [events[i] for i in t.event_ids if i not in shown and i in events][-MAX_EVENTS:]
    origin = events.get(t.event_ids[0])
    if origin is not None and origin not in fresh and len(fresh) < MAX_EVENTS and origin.id not in shown:
        fresh = [origin] + fresh
    chosen = [e for e in fresh if e.id in set(t.decision_event_ids) and e.people] or [e for e in fresh if e.people] or fresh
    peak = max(chosen, key=lambda e: (e.importance, e.id))  # the peak is something a person did
    return Arc(tuple(sorted(fresh, key=lambda e: e.id)), peak, "thread")


def select_thread(conn: sqlite3.Connection, day: int, shown: set[int] | frozenset[int] = frozenset()
                  ) -> tuple[Candidate | None, StoryThread | None, dict[int, Ev]]:
    ranked = rank_threads(conn, day, shown)
    events = load_events(conn)
    if not ranked:
        return None, None, events
    score, thread = ranked[0]
    arc = thread_arc(thread, events, set(shown))
    return Candidate(arc, score.score, dict(score.parts), score.score), thread, events
