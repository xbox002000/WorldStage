"""DirectorPlan: how the audience experiences a scene. SceneSpec says what happened; this says what the audience
should know, through whose eyes, what each beat is for, what the camera does, why each cut, and what is heard.

It sits between SceneSpec and the ProductionPacket, and never changes the story: every beat it plans points at an
event of the scene, and a focalizer can only show what they took part in or noticed. Backends (a video model, a
spatial backend, a camera-trajectory DSL such as LAMP's) read it; none of them is part of it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from contracts.base import hash_without

DIRECTOR_VERSION = 1

Strategy = Literal["irony", "mystery", "plain"]  # audience knows more / less / the same as the characters
FocalMode = Literal["omniscient", "limited", "subjective", "witness"]
FocalKind = Literal["person", "animal", "device", "none"]
Function = Literal["orient", "escalate", "reveal", "hide", "reaction", "payoff", "misdirect", "foreshadow",
                   "isolate", "connect", "contrast", "observe"]
Scale = Literal["EWS", "WS", "MS", "MCU", "CU", "ECU", "INSERT"]
Angle = Literal["eye_level", "high", "low", "overhead", "ground"]
Relation = Literal["frontal", "profile", "rear", "over_shoulder", "two_shot", "subjective"]
Motion = Literal["static", "pan", "tilt", "truck", "dolly", "push_in", "pull_out", "arc", "tracking", "handheld"]
# why cut to a shot: always something it adds (narrative/economy.py). A change of angle alone is never a reason, so
# there is no "attention_shift", "angle_change" or "more_cinematic" (FORBIDDEN_CUTS)
CutReason = Literal["open", "reaction", "information_reveal", "hide", "action", "new_relation", "pov_change",
                    "time_jump", "location_change", "causal_continuity", "emotional_break", "contrast", "payoff",
                    "hold"]
FORBIDDEN_CUTS = ("attention_shift", "angle_change", "camera_needed", "more_cinematic")
Transition = Literal["cut", "match_cut", "smash_cut", "dissolve", "hold"]


@dataclass(frozen=True)
class KnowledgeState:
    question: str  # the thread's open question
    truth: list[str]  # claim triples
    knows: list[str]
    wrong: list[str]
    unaware: list[str]
    audience_knew_before: bool  # shown in an earlier episode


@dataclass(frozen=True)
class AudienceKnowledgePlan:
    strategy: Strategy
    reason: str
    state: KnowledgeState | None
    reveal_beat: int | None  # the beat where the truth reaches the audience (irony: early; mystery: late or never)
    withheld_beats: list[int]  # beats the audience does not see directly (mystery keeps the culprit off screen)


@dataclass(frozen=True)
class POVTransition:
    at_beat: int
    from_focalizer: str
    to_focalizer: str
    kind: Literal["cut", "look", "drop"]  # a cut, following a glance, or the camera dropping to a lower viewpoint
    reason: str


@dataclass(frozen=True)
class FocalizationPlan:
    focalizer: str  # entity id, or "" for omniscient
    kind: FocalKind
    mode: FocalMode
    reason: str
    in_scope: list[int]  # beats the focalizer took part in or noticed
    audience_only: list[int]  # beats shown although the focalizer does not know them (limited mode, irony)
    transitions: list[POVTransition] = field(default_factory=list)


@dataclass(frozen=True)
class DramaticBeat:
    beat_index: int
    event_id: int
    functions: list[Function]
    inner: str  # whose inner state this beat is about
    note: str  # plain words: what the audience should feel or learn here


@dataclass(frozen=True)
class CameraShot:
    shot_index: int
    beat_index: int
    function: Function
    scale: Scale
    angle: Angle
    relation: Relation
    motion: Motion
    speed: Literal["slow", "medium", "fast"]
    subject: str  # entity id in frame (or a prop id for an insert)
    attention: Literal["face", "eyes", "hands", "object", "space", "body"]
    seconds: float
    spatial_camera: str  # which SpatialPlan camera stages it: wide | two_shot | over_shoulder | insert | pov
    reason: str
    information_function: str = ""  # orients | shows_truth | withholds | misleads | hints | confirms | none
    grammar_step: str = ""  # <cinematic grammar>:<step>, e.g. conceal_reaction_reveal:reaction


@dataclass(frozen=True)
class Cut:
    to_shot: int
    reason: CutReason
    transition: Transition


@dataclass(frozen=True)
class ShotValue:
    """What a shot adds, against everything the audience has seen before it (narrative/economy.py)."""
    shot_index: int
    information: float  # share of the facts it shows that are new
    emotion: float  # a face in a feeling not yet seen on it
    relation: float  # a new place, two people together for the first time (1), a change of whose eyes (0.5)
    state: float  # a thing changes hands in view
    action: float  # someone seen doing something not yet seen
    redundancy: float  # looks like the shot before it (1: same subject, framing and side in the same beat)
    score: float  # the gains minus the redundancy
    why: str


@dataclass(frozen=True)
class DroppedShot:
    """A shot the director planned and cut, and why: the edit's paper trail."""
    beat_index: int
    function: str
    subject: str
    scale: str
    relation: str
    reason: str


@dataclass(frozen=True)
class SoundCue:
    shot_index: int
    music: Literal["none", "tension", "release", "sting", "silence"]
    dialogue: Literal["full", "muffled", "none"]
    ambience: str
    reason: str


@dataclass(frozen=True)
class AttentionMark:
    shot_index: int
    primary: str  # what the audience should look at (entity or prop id)
    secondary: str  # what is there to be noticed only by those who look
    hidden: str  # what is in the world here but kept out of sight
    why: str


@dataclass(frozen=True)
class AttentionPlan:
    """Where the audience looks, shot by shot, and when what was kept back is finally let in."""
    marks: list[AttentionMark]
    reveal_shot: int | None  # the shot where a withheld truth is let in (controlled release), if any
    reveal_how: str  # e.g. "the camera finds the dog watching, after the wallet is back"
    reveal_subject: str = ""  # who or what the camera finds there


@dataclass(frozen=True)
class DirectorPlan:
    version: int
    scene_id: str
    scene_hash: str
    thread_id: str
    compiler_version: str
    dramatic_goal: str  # what the audience should come away with
    knowledge: AudienceKnowledgePlan
    focalization: FocalizationPlan
    beats: list[DramaticBeat]
    shots: list[CameraShot]
    cuts: list[Cut]
    sound: list[SoundCue]
    attention: AttentionPlan | None = None
    grammar: str = ""  # the cinematic grammar the scene is built on (narrative/grammar.py)
    # choices a benchmark forced instead of the director making them (focalizer, strategy, grammar); empty normally
    forced: dict[str, str] = field(default_factory=dict)
    values: list[ShotValue] = field(default_factory=list)  # one per shot: what it adds
    dropped: list[DroppedShot] = field(default_factory=list)  # planned, and cut for adding nothing
    plan_hash: str = ""


def finalize(plan: DirectorPlan) -> DirectorPlan:
    import dataclasses
    return dataclasses.replace(plan, plan_hash=hash_without(plan, "plan_hash"))


def verify(plan: DirectorPlan) -> bool:
    return plan.plan_hash == hash_without(plan, "plan_hash")
