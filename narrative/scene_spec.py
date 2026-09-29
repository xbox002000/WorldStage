"""World -> SceneSpec. Works on a read-only connection: the production side never writes to the world."""
from __future__ import annotations

import sqlite3

from contracts.base import to_dict
from contracts.scene_spec import (
    SCENE_SPEC_VERSION, Beat, Participant, Person, Place, Prop, SceneSpec, Source, Thought, WorldMap, finalize, verify)
from narrative.arcs import Ev
from narrative.selector import Candidate
from world.rng import rng as make_rng
from world.ruleset import ruleset_hash
from world.snapshot import history_hash, snapshot_hash, world_revision
from world.toolchain import simulation_toolchain_hash

WEATHER = ("clear", "cloudy", "rain", "fog")


def asset_id(person_id: str) -> str:
    """Stable per-person asset id: the same character always maps to the same face, costume and voice."""
    return f"char_{person_id}"


def _clock(ts: int) -> str:
    m = ts % 1440
    return f"{m // 60:02d}:{m % 60:02d}"


def _weather(world_seed: str, day: int) -> str:
    return make_rng(world_seed, day, "world", "weather").choice(WEATHER)


def _place(conn: sqlite3.Connection, location_id: str | None) -> Place:
    if location_id is None:  # something from outside the town (a seed): told over the whole town
        return Place("town", "小鎮", 3.0, 2.0)
    r = conn.execute("SELECT id, name, x, y FROM locations WHERE id = ?", (location_id,)).fetchone()
    return Place(r["id"], r["name"], float(r["x"]), float(r["y"]))


def _beat(conn: sqlite3.Connection, ev: Ev, seed: str) -> Beat:
    prop = None
    if ev.truth.get("object"):
        name = conn.execute("SELECT name FROM objects WHERE id = ?", (ev.truth["object"],)).fetchone()[0]
        prop = Prop(ev.truth["object"], name, f"prop_{ev.truth['object']}")
    thoughts = [
        Thought(r["observer_id"], r["belief"], float(r["confidence"]))
        for r in conn.execute(
            "SELECT observer_id, belief, confidence FROM memories WHERE event_id = ? AND confidence >= 0.9 "
            "ORDER BY memory_id", (ev.id,))
    ]
    variant = {"talk": ev.truth.get("tone"), "tell": ev.mode, "confront": ev.outcome}.get(ev.type)
    withheld = ev.truth.get("withheld_text") or []
    return Beat(
        event_id=ev.id, event_type=ev.type, variant=variant,
        location=_place(conn, ev.location_id), day=ev.day + 1, clock=_clock(ev.ts), weather=_weather(seed, ev.day),
        participants=[Participant(p, role) for p, role in ev.participants], prop=prop, thoughts=thoughts,
        motivation=ev.truth.get("reason") if ev.truth.get("source") else None,
        trust_flipped=ev.flipped, importance=float(ev.importance),
        detail=ev.truth.get("text") if ev.type in ("tell", "confront") else None,
        detail2="、".join(withheld) or None, incident=ev.incident,
    )


def _world_map(conn: sqlite3.Connection) -> WorldMap:
    return WorldMap(
        locations=[Place(r["id"], r["name"], float(r["x"]), float(r["y"]))
                   for r in conn.execute("SELECT id, name, x, y FROM locations ORDER BY id")],
        edges=[[r[0], r[1]] for r in conn.execute(
            "SELECT from_location_id, to_location_id FROM location_edges WHERE from_location_id < to_location_id "
            "ORDER BY 1, 2")],
    )


def build_scene_specs(conn: sqlite3.Connection, chosen: list[Candidate], scene_ids: list[str] | None = None) -> list[SceneSpec]:
    seed = conn.execute("SELECT value FROM meta WHERE key = 'world_seed'").fetchone()[0]
    revision, snap = world_revision(conn), snapshot_hash(conn)
    history = history_hash(conn, revision)
    cast = [r for r in conn.execute("SELECT id, name FROM people ORDER BY id")]
    people = {r["id"]: (r["name"], (conn.execute("SELECT text FROM personas WHERE person_id = ?", (r["id"],)).fetchone() or [""])[0])
              for r in cast}
    slots = {r["id"]: i for i, r in enumerate(cast)}
    world_map = _world_map(conn)
    specs = []
    for number, cand in enumerate(chosen, start=1):
        beats = [_beat(conn, e, seed) for e in cand.arc.events]
        involved = list(dict.fromkeys(p.id for b in beats for p in b.participants))
        peak = cand.arc.peak
        a = peak.people[0]
        b = peak.people[1] if len(peak.people) > 1 else a
        spec = SceneSpec(
            version=SCENE_SPEC_VERSION, scene_id=scene_ids[number - 1] if scene_ids else f"scene_{number:02d}",
            title=f"{people[a][0]} 與 {people[b][0]}" if a != b else people[a][0],
            score=float(cand.score), score_breakdown={k: float(v) for k, v in cand.breakdown.items()},
            peak_event_id=peak.id,
            source=Source(revision, snap, history, ruleset_hash(), simulation_toolchain_hash(), list(cand.arc.ids)),
            characters={p: Person(p, people[p][0], asset_id(p), people[p][1], slots[p]) for p in involved},
            map=world_map, beats=beats,
        )
        specs.append(finalize(spec))
    return specs


def validate_spec(conn: sqlite3.Connection, spec: SceneSpec) -> None:
    """Every id must exist in the world, each person maps to exactly one asset id, and the hash must match."""
    if not verify(spec):
        raise ValueError("scene_hash does not match content")
    people = {r["id"] for r in conn.execute("SELECT id FROM people")}
    locations = {r["id"] for r in conn.execute("SELECT id FROM locations")}
    event_ids = {r["event_id"] for r in conn.execute("SELECT event_id FROM events")}
    if set(spec.source.source_event_ids) - event_ids:
        raise ValueError("source_event_ids reference unknown events")
    for beat in spec.beats:
        if beat.event_id not in event_ids:
            raise ValueError(f"unknown event {beat.event_id}")
        if beat.location.id not in locations:
            raise ValueError(f"unknown location {beat.location.id}")
        for p in beat.participants:
            if p.id not in people:
                raise ValueError(f"unknown person {p.id}")
            if spec.characters[p.id].asset_id != asset_id(p.id):
                raise ValueError(f"{p.id} maps to the wrong asset")


def dumps(spec: SceneSpec) -> dict:
    return to_dict(spec)
