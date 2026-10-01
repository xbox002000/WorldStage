"""Story director: which thread is worth following today. It picks what to film, never what happens.

The score is deterministic and made of parts (no model judges):
momentum   what moved in the last two days;
tension    how open the thread's question still is;
stakes     what is at risk;
asymmetry  the knowledge gap (narrative/knowledge.py): someone believes the wrong thing, or it concerns someone who
           does not know; more if the audience has already seen the truth (dramatic irony);
crossing   how many other threads it touches;
novelty    not shown in the last episodes;
payoff     somebody holds grounds to accuse or confront, so the question may be settled soon;
change     what the thread did to people: goals it formed, turned or broke, reflections that shifted a trait or a
           self-image, trust that reversed, beliefs that flipped. A lost duel is an event; the loser deciding to train
           in secret is a story.
inner      the internal conflict of what was chosen (world/values.py): someone doing what serves one value they
           hold dear while it betrays another. A person making a choice they do not want to make is worth more than
           two people shouting again.

A thread qualifies only if its new material contains at least one event a character chose. A thread made only of
rules, props and seeds is weather, not story (this is what `seed_direct_plot_rate` measures).
"""
from __future__ import annotations

import sqlite3

from contracts.thread import StoryThread, ThreadScore
from narrative.arcs import Arc, Ev, load_events
from narrative.selector import Candidate
from narrative.threads import derive_threads

WEIGHTS = {"momentum": 0.20, "tension": 0.20, "stakes": 0.10, "asymmetry": 0.15, "crossing": 0.10,
           "novelty": 0.10, "payoff": 0.05, "change": 0.10, "inner": 0.15}
TURN = {"formed": 1.0, "transformed": 1.5, "abandoned": 1.5, "completed": 1.0, "blocked": 0.8, "revised": 0.8}
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


def _change(conn: sqlite3.Connection, t: StoryThread, shown: set[int]) -> float:
    """How much the thread's new events changed people (read-only: goal changes and reflections cite their causes)."""
    new = [e for e in t.event_ids if e not in shown]
    if not new:
        return 0.0
    marks = ",".join("?" * len(new))
    total = 0.0
    for (to,) in conn.execute(f"SELECT json_extract(truth, '$.to') FROM events WHERE type = 'goal_change' "
                              f"AND json_extract(truth, '$.cause_event') IN ({marks})", new):
        total += TURN.get(to, 0.5)
    for (truth,) in conn.execute("SELECT truth FROM events WHERE type = 'reflection' AND EXISTS (SELECT 1 FROM "
                                 f"json_each(json_extract(truth, '$.cites')) WHERE value IN ({marks}))", new):
        import json
        d = json.loads(truth)
        total += 1.0 if d.get("shifted") or d.get("self_model") else 0.2
    total += 0.5 * conn.execute(f"SELECT COUNT(*) FROM events WHERE event_id IN ({marks}) "
                                "AND json_extract(truth, '$.trust_flipped') = 1", new).fetchone()[0]
    return min(1.0, total / 3)


def _inner(conn: sqlite3.Connection, events: list[int]) -> float:
    """The highest internal conflict among these events (0 when nobody chose against themselves)."""
    if not events:
        return 0.0
    marks = ",".join("?" * len(events))
    row = conn.execute(f"SELECT MAX(json_extract(truth, '$.dilemma.tension')) FROM events WHERE event_id IN ({marks})",
                       events).fetchone()
    return float(row[0] or 0.0)


def score_thread(conn: sqlite3.Connection, t: StoryThread, shown: set[int]) -> ThreadScore:
    from narrative.knowledge import knowledge_of
    new = [e for e in t.event_ids if e not in shown]
    k = knowledge_of(conn, t, shown)
    parts = {
        "momentum": t.momentum,
        "tension": t.tension,
        "stakes": t.stakes,
        "asymmetry": k.gap if k is not None else min(1.0, t.information_asymmetry / 3),
        "crossing": min(1.0, len(t.cross_threads) / 3),
        "novelty": len(new) / len(t.event_ids) if t.event_ids else 0.0,
        "payoff": _payoff(conn, t),
        "change": _change(conn, t, shown),
        "inner": _inner(conn, new),
    }
    from world.recipes import load_recipe, recipe_of
    bonus = load_recipe(recipe_of(conn)).director_prefers.get(t.kind, 0.0)
    return ThreadScore(t.thread_id, round(sum(WEIGHTS[k] * v for k, v in parts.items()) + bonus, 4),
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
