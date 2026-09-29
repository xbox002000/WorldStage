from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field

SOCIAL = ("talk", "steal")
MAX_BEFORE = 4  # causes kept ahead of the peak event
MAX_AFTER = 2  # aftermath kept behind it


@dataclass(frozen=True)
class Ev:
    id: int
    ts: int
    type: str
    location_id: str | None
    parent: int | None
    importance: float
    truth: dict
    participants: tuple[tuple[str, str], ...]  # (person_id, role)
    trust_shift: float  # sum of |trust delta| caused by this event
    flipped: bool

    @property
    def day(self) -> int:
        return self.ts // 1440

    @property
    def people(self) -> tuple[str, ...]:
        return tuple(p for p, _ in self.participants)

    @property
    def pair(self) -> frozenset[str]:
        """The two principals (actor + target/victim); witnesses come after them."""
        return frozenset(self.people[:2])


@dataclass(frozen=True)
class Arc:
    """A causal arc: the chain of events that led to a peak event, plus its aftermath."""

    events: tuple[Ev, ...]
    peak: Ev

    @property
    def ids(self) -> tuple[int, ...]:
        return tuple(e.id for e in self.events)


def load_events(conn: sqlite3.Connection) -> dict[int, Ev]:
    parts: dict[int, list[tuple[str, str]]] = {}
    for r in conn.execute("SELECT event_id, person_id, role FROM event_participants ORDER BY rowid"):
        parts.setdefault(r["event_id"], []).append((r["person_id"], r["role"]))
    shifts: dict[int, float] = {}
    for r in conn.execute(
        "SELECT event_id, SUM(ABS(delta_value)) s FROM event_deltas "
        "WHERE entity_type = 'relationship' AND field = 'trust' GROUP BY event_id"
    ):
        shifts[r["event_id"]] = r["s"]
    out: dict[int, Ev] = {}
    for r in conn.execute("SELECT * FROM events ORDER BY event_id"):
        truth = json.loads(r["truth"])
        out[r["event_id"]] = Ev(
            r["event_id"], r["timestamp"], r["type"], r["location_id"], r["parent_event_id"], r["importance"],
            truth, tuple(parts.get(r["event_id"], [])), shifts.get(r["event_id"], 0.0),
            bool(truth.get("trust_flipped")),
        )
    return out


def build_arcs(events: dict[int, Ev], anchors: int = 20) -> list[Arc]:
    """One arc per high-importance social event: its cause chain, itself, and its strongest aftermath."""
    children: dict[int, list[Ev]] = {}
    for e in events.values():
        if e.parent is not None:
            children.setdefault(e.parent, []).append(e)

    peaks = sorted((e for e in events.values() if e.type in SOCIAL), key=lambda e: (-e.importance, e.id))[:anchors]
    arcs = []
    for peak in peaks:
        before: list[Ev] = []
        cur = peak
        while cur.parent is not None and len(before) < MAX_BEFORE and cur.parent in events:
            if events[cur.parent].pair != peak.pair:
                break
            cur = events[cur.parent]
            before.append(cur)
        after: list[Ev] = []
        cur = peak
        while len(after) < MAX_AFTER:
            same_pair = [c for c in children.get(cur.id, []) if c.pair == peak.pair]
            if not same_pair:
                break
            cur = max(same_pair, key=lambda c: (c.importance, -c.id))
            after.append(cur)
        arcs.append(Arc(tuple(reversed(before)) + (peak,) + tuple(after), peak))
    return arcs
