from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from narrative.arcs import Arc, Ev, build_arcs, load_events
from narrative.scorer import score_arc

DEFAULT_PROTAGONISTS = {"ming", "mei", "jun", "lan"}


@dataclass(frozen=True)
class Candidate:
    arc: Arc
    score: float
    breakdown: dict


def rank_arcs(conn: sqlite3.Connection, protagonists: set[str] = frozenset(DEFAULT_PROTAGONISTS)) -> tuple[list[Candidate], dict[int, Ev]]:
    events = load_events(conn)
    ranked = []
    for arc in build_arcs(events):
        score, breakdown = score_arc(conn, arc, events, set(protagonists))
        ranked.append(Candidate(arc, score, breakdown))
    ranked.sort(key=lambda c: (-c.score, c.arc.peak.id))
    return ranked, events


def select_top(conn: sqlite3.Connection, n: int = 3, protagonists: set[str] = frozenset(DEFAULT_PROTAGONISTS),
               min_shots: int = 3) -> tuple[list[Candidate], dict[int, Ev]]:
    """Greedy pick: no shared events, each pair in at most one arc. Arcs with at least `min_shots`
    events go first; shorter ones only fill remaining slots."""
    ranked, events = rank_arcs(conn, protagonists)
    chosen: list[Candidate] = []
    used: set[int] = set()
    pairs: set[frozenset] = set()
    for long_only in (True, False):
        for c in ranked:
            if len(chosen) == n:
                break
            if long_only and len(c.arc.events) < min_shots:
                continue
            if used & set(c.arc.ids) or c.arc.peak.pair in pairs:
                continue
            chosen.append(c)
            used |= set(c.arc.ids)
            pairs.add(c.arc.peak.pair)
    chosen.sort(key=lambda c: (-c.score, c.arc.peak.id))
    return chosen, events
