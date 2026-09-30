"""ProductionPacket: how to shoot a SceneSpec. Compiled deterministically (no LLM) from a spec + a style pack."""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass

from contracts.base import hash_without
from contracts.scene_spec import Place, Prop, WorldMap

PACKET_VERSION = 4


@dataclass(frozen=True)
class StylePackRef:
    id: str
    version: int
    hash: str


@dataclass(frozen=True)
class CompilerRef:
    version: str
    hash: str


@dataclass(frozen=True)
class Episode:
    title: str
    recap: str
    hook: str
    title_seconds: float
    end_seconds: float


@dataclass(frozen=True)
class CharacterLock:
    asset_id: str
    identity_lock: list[str]  # facts about appearance that must not change between shots
    wardrobe_lock: list[str]
    voice_asset_id: str | None = None


@dataclass(frozen=True)
class LocationLock:
    asset_id: str
    description: str


@dataclass(frozen=True)
class ContinuityLocks:
    characters: dict[str, CharacterLock]
    locations: dict[str, LocationLock]


@dataclass(frozen=True)
class Camera:
    shot_type: str
    movement: str
    focal_mm: int


@dataclass(frozen=True)
class Lighting:
    time_of_day: str
    weather: str


@dataclass(frozen=True)
class ShotCharacter:
    id: str
    name: str
    asset_id: str
    role: str
    position: str  # left | right | background
    action: str
    emotion: str


@dataclass(frozen=True)
class Shot:
    shot_id: str
    event_id: int
    intent: str
    subject: str
    action: str
    environment: str
    camera: Camera
    lighting: Lighting
    start_seconds: float
    duration_seconds: int
    caption: str
    thought: str | None
    characters: list[ShotCharacter]
    props: list[Prop]
    location: Place
    day: int
    clock: str
    render_backend: str  # procedural | stock | ai_clip
    route_reason: str
    continuity_refs: list[str]
    continuity_note: str | None
    trust_flipped: bool
    # v3, from the DirectorPlan (empty when a packet is compiled without one)
    function: str = ""  # reveal | hide | escalate | misdirect ...
    direction_note: str = ""  # why this shot exists, in plain words
    relation: str = ""  # frontal | over_shoulder | two_shot | subjective ...
    angle: str = ""  # eye_level | high | low | ground ...
    focalizer: str = ""  # whose view the scene is told through
    spatial_camera: str = ""  # which SpatialPlan camera stages it: wide | two_shot | over_shoulder | insert | pov
    music: str = ""  # none | tension | release | sting | silence
    dialogue: str = "full"  # full | muffled | none
    # v4, so a renderer can film the director's intent from the packet alone
    scale: str = ""  # EWS | WS | MS | MCU | CU | ECU | INSERT
    subject_id: str = ""  # the entity or prop id the camera is on
    attention: str = ""  # face | eyes | hands | object | space | body
    event_type: str = ""
    thought_by: str = ""  # whose inner text `thought` is
    thought_kind: str = ""  # belief (a person's) | sense (an animal's percept: no words, no names of acts)
    suspect_id: str = ""  # someone who is only in a character's head: the one they suspect
    transition: str = ""  # how the cut into this shot is made: cut | dissolve | smash_cut | match_cut | hold


@dataclass(frozen=True)
class AudioCue:
    t: float
    kind: str  # music | sfx | voice
    name: str
    duration: float = 0.0
    intensity: float = 0.5


@dataclass(frozen=True)
class AudioPlan:
    cues: list[AudioCue]


@dataclass(frozen=True)
class SubtitleCue:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class Canvas:
    width: int
    height: int
    fps: int


@dataclass(frozen=True)
class QARequirements:
    width: int
    height: int
    fps: int
    total_seconds: float
    required_asset_ids: list[str]
    require_audio: bool


@dataclass(frozen=True)
class ProductionPacket:
    version: int
    scene_hash: str
    stylepack: StylePackRef
    compiler: CompilerRef
    episode: Episode
    canvas: Canvas
    map: WorldMap
    continuity_locks: ContinuityLocks
    shots: list[Shot]
    audio_plan: AudioPlan
    subtitle_plan: list[SubtitleCue]
    qa: QARequirements
    packet_hash: str = ""
    direction_hash: str = ""  # the DirectorPlan it was compiled from (v3); empty without one


def finalize(packet: ProductionPacket) -> ProductionPacket:
    return dataclasses.replace(packet, packet_hash=hash_without(packet, "packet_hash"))


def verify(packet: ProductionPacket) -> bool:
    return packet.packet_hash == hash_without(packet, "packet_hash")
