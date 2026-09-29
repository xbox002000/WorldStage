"""SpatialPlan: how a scene happens in space. Where everyone stands, what blocks the view, where the cameras are.

SceneSpec says what happened; the SpatialPlan only says how it is staged. Changing a plan changes how a scene is
filmed, never its story. The plan is backend-neutral: a Blender, three.js or 2D backend reads the same file.
Units are metres; x to the right, y into the room, z up. Angles in degrees.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from contracts.base import hash_without

SPATIAL_VERSION = 1

ObjectKind = Literal["wall", "table", "chair", "counter", "door", "window", "bench", "tree", "desk", "sofa",
                     "platform", "prop", "perch"]
Pose = Literal["stand", "sit"]
CameraMove = Literal["static", "push_in", "pan", "follow"]


@dataclass(frozen=True)
class SpatialObject:
    id: str
    kind: ObjectKind
    position: list[float]  # centre of the base
    size: list[float]  # width (x), depth (y), height (z)
    yaw: float = 0.0
    blocks_sight: bool = True  # walls, trees; a window does not
    label: str = ""


@dataclass(frozen=True)
class Placement:
    id: str  # person id or prop id
    anchor: str  # the layout anchor used, e.g. cafe.table1.seat_a
    position: list[float]
    yaw: float  # which way they face
    pose: Pose = "stand"
    height: float = 1.7


@dataclass(frozen=True)
class CameraShot:
    shot: str  # wide | two_shot | single | over_shoulder | insert | pov
    position: list[float]
    target: list[float]
    lens_mm: float = 35.0
    move: CameraMove = "static"
    end_position: list[float] | None = None
    subjects: list[str] = field(default_factory=list)  # who must be in frame


@dataclass(frozen=True)
class SightCheck:
    observer: str  # a person id, or a camera as camera:<index>
    subject: str
    required: bool
    visible: bool
    blocked_by: str = ""  # the first object in the way


@dataclass(frozen=True)
class BeatStaging:
    beat_index: int
    event_id: int
    location: str
    layout_id: str
    placements: list[Placement]
    cameras: list[CameraShot]
    checks: list[SightCheck]


@dataclass(frozen=True)
class LayoutRef:
    layout_id: str
    location: str
    objects: list[SpatialObject]
    layout_hash: str


@dataclass(frozen=True)
class SpatialPlan:
    version: int
    scene_id: str
    scene_hash: str  # the SceneSpec this plan stages
    compiler_version: str
    layouts: list[LayoutRef]
    beats: list[BeatStaging]
    valid: bool  # every required sight line holds
    problems: list[str]
    plan_hash: str = ""


def finalize(plan: SpatialPlan) -> SpatialPlan:
    import dataclasses
    return dataclasses.replace(plan, plan_hash=hash_without(plan, "plan_hash"))


def verify(plan: SpatialPlan) -> bool:
    return plan.plan_hash == hash_without(plan, "plan_hash")
