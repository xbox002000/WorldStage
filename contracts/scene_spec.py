"""SceneSpec: what happened in the world, cut into beats. No camera, no style, no prompts.

Derived read-only from world.db at a known revision; every scene carries the hashes that pin it there.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field

from contracts.base import hash_without

SCENE_SPEC_VERSION = 2


@dataclass(frozen=True)
class Source:
    world_revision: int
    world_snapshot_hash: str
    history_hash: str  # immutable history up to world_revision; recomputable after the world moves on
    ruleset_hash: str
    simulation_toolchain_hash: str
    source_event_ids: list[int]


@dataclass(frozen=True)
class Place:
    id: str
    name: str
    x: float
    y: float


@dataclass(frozen=True)
class Person:
    id: str
    name: str
    asset_id: str  # stable: char_<id>
    persona: str = ""


@dataclass(frozen=True)
class Prop:
    id: str
    name: str
    asset_id: str  # stable: prop_<id>


@dataclass(frozen=True)
class Participant:
    id: str
    role: str  # actor | target | victim | witness


@dataclass(frozen=True)
class Thought:
    person: str
    belief: str
    confidence: float


@dataclass(frozen=True)
class Beat:
    event_id: int
    event_type: str
    tone: str | None
    location: Place
    day: int
    clock: str
    weather: str
    participants: list[Participant]
    prop: Prop | None
    thoughts: list[Thought]
    motivation: str | None
    trust_flipped: bool
    importance: float


@dataclass(frozen=True)
class WorldMap:
    locations: list[Place]
    edges: list[list[str]]


@dataclass(frozen=True)
class SceneSpec:
    version: int
    scene_id: str
    title: str
    score: float
    score_breakdown: dict[str, float]
    peak_event_id: int
    source: Source
    characters: dict[str, Person]
    map: WorldMap
    beats: list[Beat]
    scene_hash: str = ""


def finalize(spec: SceneSpec) -> SceneSpec:
    """Stamp the content hash (computed without the hash field itself)."""
    return dataclasses.replace(spec, scene_hash=hash_without(spec, "scene_hash"))


def verify(spec: SceneSpec) -> bool:
    return spec.scene_hash == hash_without(spec, "scene_hash")
