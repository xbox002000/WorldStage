from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from contracts.stylepack import SCORE_WEIGHTS_V1
from narrative.arcs import Arc, Ev, build_arcs, load_events, without
from narrative.continuity import connects
from narrative.scorer import score_arc

DEFAULT_PROTAGONISTS = frozenset({"ming", "mei", "jun", "lan"})
CONTINUITY_BONUS = 0.25  # a follow-up beats an equally good but unrelated arc


@dataclass(frozen=True)
class Candidate:
    arc: Arc
    score: float  # final ranking score, including any continuity bonus
    breakdown: dict
    base_score: float = 0.0
    continuity: dict | None = field(default=None)  # evidence that this arc continues earlier episodes


def rank_arcs(conn: sqlite3.Connection, protagonists: set[str] | frozenset[str] = DEFAULT_PROTAGONISTS,
              weights: dict[str, float] = SCORE_WEIGHTS_V1, exclude: frozenset[int] | set[int] = frozenset(),
              min_events: int = 2) -> tuple[list[Candidate], dict[int, Ev]]:
    """Score every arc on the material not yet shown. `exclude` = events already told in earlier episodes."""
    events = load_events(conn)
    ranked = []
    for arc in build_arcs(events):
        arc = without(arc, exclude, min_events) if exclude else arc
        if arc is None:
            continue
        base, breakdown = score_arc(conn, arc, events, set(protagonists), weights)
        evidence = connects(conn, events, arc, exclude) if exclude else None
        ranked.append(Candidate(arc, round(base + (CONTINUITY_BONUS if evidence else 0.0), 4), breakdown, base, evidence))
    ranked.sort(key=lambda c: (-c.score, c.arc.peak.id))
    return ranked, events


def select_top(conn: sqlite3.Connection, n: int = 3, protagonists: set[str] | frozenset[str] = DEFAULT_PROTAGONISTS,
               min_shots: int = 3, weights: dict[str, float] = SCORE_WEIGHTS_V1,
               exclude: frozenset[int] | set[int] = frozenset()) -> tuple[list[Candidate], dict[int, Ev]]:
    """Greedy pick: no shared events, one arc per story (per incident, per pair of people). Arcs with at least
    `min_shots` events go first; shorter ones only fill remaining slots."""
    ranked, events = rank_arcs(conn, protagonists, weights, exclude)
    chosen: list[Candidate] = []
    used: set[int] = set()
    keys: set[tuple] = set()
    for long_only in (True, False):
        for c in ranked:
            if len(chosen) == n:
                break
            if long_only and len(c.arc.events) < min_shots:
                continue
            if used & set(c.arc.ids) or c.arc.key in keys:
                continue
            chosen.append(c)
            used |= set(c.arc.ids)
            keys.add(c.arc.key)
    chosen.sort(key=lambda c: (-c.score, c.arc.peak.id))
    return chosen, events


def select_daily(conn: sqlite3.Connection, day: int, protagonists: set[str] | frozenset[str] = DEFAULT_PROTAGONISTS,
                 weights: dict[str, float] = SCORE_WEIGHTS_V1, exclude: frozenset[int] | set[int] = frozenset(),
                 min_shots: int = 3, lookback_days: int = 1) -> tuple[Candidate | None, dict[int, Ev]]:
    """The one story for today: the best arc whose peak happened in the last `lookback_days + 1` days.

    Falls back to the best arc overall when the recent days were quiet, so the channel never skips a day.
    """
    ranked, events = rank_arcs(conn, protagonists, weights, exclude)
    if not ranked:
        return None, events
    recent = [c for c in ranked if c.arc.peak.day >= day - lookback_days]
    for pool in (recent, ranked):
        long = [c for c in pool if len(c.arc.events) >= min_shots]
        if long or pool:
            return (long or pool)[0], events
    return None, events
