"""PerformancePlan: how each character embodies their state in each shot. It sits between the DirectorPlan (what the
audience should notice) and the camera (how it is captured), and is derived from the character's state in the world
(emotion, beliefs, relationships, goals, traits, what they perceive), never chosen freely.

Provider-neutral: no prompt text, rig names or keyframes. A 2D renderer, a 3D rig or a video model each compile it
their own way. A PerformanceProfile says which channels a kind of body has: a dog has ears and a tail, not speech.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from contracts.base import hash_without

PERFORMANCE_VERSION = 1


@dataclass(frozen=True)
class Cause:
    kind: str  # emotion | relationship | belief | goal | trait | perception | holding | event | counterfactual
    ref: str  # what in the world it points at, e.g. "trust:ming->kai=-0.42", "memory:812", "goal:ming:1"
    weight: float


@dataclass(frozen=True)
class Drive:
    """One inner pressure behind the performance, with what in the world makes it so."""
    name: str  # fear | resentment | suspicion | guilt | distress | relief | attachment | curiosity | self_protection
    value: float  # 0..1
    causes: list[Cause]


@dataclass(frozen=True)
class Gaze:
    target: str  # an entity or prop id, or "" (inward / nowhere)
    mode: str  # hold | avoid | scan | down | glance | follow
    seconds: float


@dataclass(frozen=True)
class Posture:
    tension: float  # 0..1
    openness: float  # 0..1 (arms crossed, turned away = low)
    lean: float  # -1 back .. +1 forward


@dataclass(frozen=True)
class Hands:
    action: str  # idle | grip | fidget | search | hold | point | reach | none
    tension: float
    holding: str = ""  # prop id held after this shot ("" = empty hands / mouth)


@dataclass(frozen=True)
class Face:
    brows: str  # neutral | narrow | raised | knit
    jaw: str  # loose | tight
    mouth: str  # neutral | pressed | open | smile | down
    eyes: str  # neutral | wide | narrow | soft | lowered


@dataclass(frozen=True)
class AnimalBody:
    ears: str  # neutral | up | back
    tail: str  # neutral | wag | high | low | still
    head_tilt: float  # degrees
    pace: str  # still | trot | slow | dart


@dataclass(frozen=True)
class Speech:
    delivery: str  # none | soft | restrained | short | sharp | warm
    pace: str  # slow | normal | fast
    pause_before: float  # seconds of silence before answering


@dataclass(frozen=True)
class MicroAction:
    name: str  # glance_away | swallow | jaw_clench | pat_pockets | look_around | exhale | touch_object | sniff ...
    at: float  # 0..1 through the shot


@dataclass(frozen=True)
class BodyState:
    """What must carry over to the next shot (performance continuity)."""
    holding: str
    hand: str  # right | mouth | none
    gesture: str  # idle | hold | grip | search | point | crossed
    gaze: str  # the target being looked at
    emotion: str


@dataclass(frozen=True)
class PerformanceBeat:
    shot_index: int
    actor: str
    profile: str  # human | dog (see narrative/performance.PROFILES)
    intent: str  # go_on | search | conceal | recover | confront | defend | watch | avoid | reach_out | investigate ...
    primary: str  # calm | afraid | suspicious | guilty | distressed | relieved | defensive | restrained_anger | curious ...
    intensity: float
    drives: list[Drive]
    gaze: Gaze
    posture: Posture
    hands: Hands | None  # None for a body without hands
    face: Face | None  # None for a body without a human face
    animal: AnimalBody | None  # None for a person
    micro: list[MicroAction]
    movement: str  # still | approach | retreat | walk_away | pace
    speech: Speech | None  # None for a body that does not speak
    before: BodyState
    after: BodyState
    changes: list[str] = field(default_factory=list)  # continuity changes and their cause, e.g. "holding: -> wallet (take)"


@dataclass(frozen=True)
class PerformancePlan:
    version: int
    scene_hash: str
    direction_hash: str
    beats: list[PerformanceBeat]
    # a benchmark's hypothetical state ("what if Ming trusted Kai less"): the input changes, the derivation does not
    counterfactual: dict[str, dict[str, float | str]] = field(default_factory=dict)
    plan_hash: str = ""


def finalize(plan: PerformancePlan) -> PerformancePlan:
    import dataclasses
    return dataclasses.replace(plan, plan_hash=hash_without(plan, "plan_hash"))
