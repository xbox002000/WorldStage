"""Is this arc a continuation of what viewers have already seen?

Two ways an arc can build on earlier episodes, both checkable from the world alone:
  causal   an event in the arc depends (directly or through a chain) on an event already shown;
  state    a relationship or feeling the arc changes was last changed by an event already shown.
"""
from __future__ import annotations

import sqlite3

from narrative.arcs import Arc, Ev

DEPTH = 12
LINEAGE_STEPS = 3  # how many earlier changes of the same field are looked at
LINEAGE_FIELDS = ("trust", "affection", "fear", "rivalry", "debt_cents", "emotion", "owner_person_id")


def closure(events: dict[int, Ev], start: set[int] | tuple[int, ...], depth: int = DEPTH) -> set[int]:
    """Everything the given events depend on, following parent links and belief provenance."""
    seen: set[int] = set()
    frontier = set(start)
    for _ in range(depth):
        nxt: set[int] = set()
        for eid in frontier:
            e = events.get(eid)
            if e is None:
                continue
            for d in e.depends_on:
                if d not in seen and d not in start:
                    nxt.add(d)
        seen |= nxt
        frontier = nxt
        if not frontier:
            break
    return seen


def connects(conn: sqlite3.Connection, events: dict[int, Ev], arc: Arc, prior_event_ids: set[int] | frozenset[int]) -> dict | None:
    """Evidence that `arc` continues the story told by `prior_event_ids`, or None."""
    if not prior_event_ids:
        return None
    own = set(arc.ids)
    hit = sorted((closure(events, own) | own) & set(prior_event_ids) - own)
    if hit:
        return {"kind": "causal", "via": hit[:3]}
    for eid in arc.ids:
        for d in conn.execute(
            "SELECT delta_id, entity_type, entity_id, field FROM event_deltas WHERE event_id = ? "
            "AND field IN (%s) ORDER BY delta_id" % ",".join("?" * len(LINEAGE_FIELDS)), (eid, *LINEAGE_FIELDS)):
            previous = [r[0] for r in conn.execute(
                "SELECT event_id FROM event_deltas WHERE entity_type = ? AND entity_id = ? AND field = ? AND delta_id < ? "
                "ORDER BY delta_id DESC LIMIT ?", (d["entity_type"], d["entity_id"], d["field"], d["delta_id"], LINEAGE_STEPS))]
            shown = [p for p in previous if p in prior_event_ids and p not in own]
            if shown:
                return {"kind": "state", "via": shown[:3], "field": f"{d['entity_id']}.{d['field']}"}
    return None
