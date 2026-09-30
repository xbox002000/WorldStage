"""World Runtime ABI: the world's events played out in space and time. world.db says *that* Ming picked up the wallet;
the runtime says he walked 2.1 m to it, reached down, touched it at 12.76 s and had it in his right hand at 13.10 s.

Deterministic and derived: a pure function of the world's history (read-only), the white-box layouts and the runtime
version. Renderers, engines (Godot, Blender) and video models only *play* a trace; they never decide what happens.
Nothing here writes the world.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from contracts.base import hash_without

RUNTIME_VERSION = "runtime-0.1"


@dataclass(frozen=True)
class RuntimeTransform:
    entity: str  # person or object id
    place: str  # location id ("" = not in any place: offstage, or carried)
    x: float  # metres, the place's white-box floor plan (narrative/layouts.py)
    y: float
    yaw: float  # degrees
    pose: str  # stand | sit | crouch | walk | carried | on_floor | offstage


@dataclass(frozen=True)
class RuntimeAction:
    event_id: int
    actor: str
    kind: str  # enter | exit | walk_to | reach | attach | detach | drop | look_at | face | sit | strike | idle
    target: str  # a person, an object or an anchor
    start: float  # world seconds (event timestamp * 60 + offset)
    end: float
    place: str
    frm: list[float] = field(default_factory=list)  # [x, y]
    to: list[float] = field(default_factory=list)


@dataclass(frozen=True)
class RuntimeInteraction:
    """A body and a thing (or two bodies) meeting: when the reach starts, when contact is made, when it is done."""
    event_id: int
    actor: str
    action: str  # pickup | drop | hand_over | receive | grab | strike
    target: str
    start: float
    contact: float
    complete: float
    hand: str  # right | left | mouth | none


@dataclass(frozen=True)
class RuntimeSnapshot:
    version: str
    revision: int  # the last world event applied
    world_time: int  # minutes
    ruleset_hash: str
    transforms: list[RuntimeTransform]
    holders: dict[str, str]  # object -> who holds it ("" = nobody)
    attached: dict[str, str]  # object -> the part it is attached to (right | mouth | ""), for whoever holds it
    state_hash: str = ""


@dataclass(frozen=True)
class RuntimeTrace:
    version: str
    event_ids: list[int]
    actions: list[RuntimeAction]
    interactions: list[RuntimeInteraction]
    keyframes: list[tuple[float, RuntimeTransform]]  # (world seconds, where an entity is from then on)
    initial: list[RuntimeTransform] = field(default_factory=list)  # everyone and everything just before the first event
    initial_holders: dict[str, str] = field(default_factory=dict)
    trace_hash: str = ""


def stamp_snapshot(s: RuntimeSnapshot) -> RuntimeSnapshot:
    import dataclasses
    return dataclasses.replace(s, state_hash=hash_without(s, "state_hash"))


def stamp_trace(t: RuntimeTrace) -> RuntimeTrace:
    import dataclasses
    return dataclasses.replace(t, trace_hash=hash_without(t, "trace_hash"))
