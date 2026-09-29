"""Causal arcs: the stretches of world history worth telling as a story.

Two kinds:
  pair      a chain of events between the same two people, followed along parent_event_id;
  incident  everything that grew out of one original event: the lies told about it, the rumours, the exposure.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, replace

SOCIAL = ("talk", "steal", "tell", "confront")
DECEPTIVE_MODES = ("lie", "distortion")
EXPOSED = ("lie_exposed", "distortion_exposed", "concealment_exposed")
MAX_BEFORE = 4  # causes kept ahead of the peak event in a pair arc
MAX_AFTER = 2  # aftermath kept behind it
MAX_INCIDENT_EVENTS = 6
MIN_INCIDENT_EVENTS = 3


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

    @property
    def mode(self) -> str | None:
        return self.truth.get("mode") if self.type == "tell" else None

    @property
    def outcome(self) -> str | None:
        return self.truth.get("outcome") if self.type == "confront" else None

    @property
    def incident(self) -> int | None:
        value = self.truth.get("incident")
        return int(value) if value is not None else None

    @property
    def depends_on(self) -> tuple[int, ...]:
        deps = {int(d) for d in self.truth.get("depends_on", ())}
        if self.parent is not None:
            deps.add(self.parent)
        return tuple(sorted(deps))

    @property
    def deceptive(self) -> bool:
        """A tell whose content was actually false or bent (the world knows; the listener does not)."""
        return self.type == "tell" and self.mode in DECEPTIVE_MODES and self.truth.get("verdict") in ("FALSE", "PARTIAL")


@dataclass(frozen=True)
class Arc:
    """A causal arc: a set of events told in order, with the one that carries it."""

    events: tuple[Ev, ...]
    peak: Ev
    kind: str = "pair"

    @property
    def ids(self) -> tuple[int, ...]:
        return tuple(e.id for e in self.events)

    @property
    def key(self) -> tuple:
        """What makes two arcs 'the same story' for selection: one per incident, one per pair of people."""
        if self.kind == "incident":
            return ("incident", self.peak.incident if self.peak.incident is not None else self.peak.id)
        return ("pair", self.peak.pair)


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


def _pair_arcs(events: dict[int, Ev], anchors: int) -> list[Arc]:
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


def _incident_arcs(events: dict[int, Ev], anchors: int) -> list[Arc]:
    groups: dict[int, dict[int, Ev]] = {}
    for e in events.values():
        if e.incident is not None:
            groups.setdefault(e.incident, {})[e.id] = e
    arcs = []
    for incident, members in groups.items():
        root = events.get(incident)
        if root is not None and root.type in SOCIAL:
            members = {**members, root.id: root}
        if len(members) < MIN_INCIDENT_EVENTS or not any(e.type in ("tell", "confront") for e in members.values()):
            continue
        kept = list(members.values())
        if len(kept) > MAX_INCIDENT_EVENTS:  # keep the root, then the weightiest, then restore time order
            rest = sorted((e for e in kept if e.id != incident), key=lambda e: (-e.importance, e.id))
            kept = ([members[incident]] if incident in members else []) + rest[: MAX_INCIDENT_EVENTS - (incident in members)]
        kept.sort(key=lambda e: e.id)
        peak = max(kept, key=lambda e: (e.importance, e.id))
        arcs.append(Arc(tuple(kept), peak, "incident"))
    arcs.sort(key=lambda a: (-a.peak.importance, a.peak.id))
    return arcs[:anchors]


def build_arcs(events: dict[int, Ev], anchors: int = 20) -> list[Arc]:
    return _pair_arcs(events, anchors) + _incident_arcs(events, anchors)


def without(arc: Arc, excluded: frozenset[int] | set[int], min_events: int = 2) -> Arc | None:
    """The arc minus events already told in earlier episodes. None if too little new material remains.

    The peak becomes the weightiest remaining event, so a follow-up is about what is new (the exposure),
    while the earlier episodes' events stay behind as its recap.
    """
    kept = tuple(e for e in arc.events if e.id not in excluded)
    if len(kept) < min_events:
        return None
    peak = arc.peak if arc.peak.id not in excluded else max(kept, key=lambda e: (e.importance, e.id))
    return replace(arc, events=kept, peak=peak)
