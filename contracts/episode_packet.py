"""EpisodePacketMap: which beat and which story line each shot of a packet belongs to (a record beside the packet, never inside it).

A ProductionPacket is compiled from one SceneSpec. When the episode planner's A/B option is on (docs/episode_planner.md, "Into the
packet"), that spec holds the A story's scenes, the B story's scenes and an ordinary moment (texture), in the plan's order. The packet
itself stays the same shape it always had (so a packet made without a plan is byte for byte what it was); this map says, for every shot
in it, which plan beat it belongs to, which story line (A, B or texture) and which intent (the closed `ShotIntent` vocabulary), so that
QA and a provider's compiler can read the structure without re-deriving it. It names the packet by hash and the plan by hash.

It also records what did *not* go into the packet and why: a beat the shot economy elided, and the scenes cut to keep the episode within
its length budget (texture first, then B; the A story is never cut).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from contracts.base import hash_without
from contracts.episode_plan import ShotIntent

EPISODE_PACKET_VERSION = 1

Story = Literal["A", "B", "texture"]


@dataclass(frozen=True)
class ShotBeat:
    shot_id: str                      # the packet shot's id
    shot_index: int
    beat_index: int                   # EpisodeBeat.index in the plan named by plan_hash
    story: Story
    intent: ShotIntent                # what the shot is for (the packet shot's `function`)
    event_id: int
    derived: bool = False             # the shot belongs to a reaction beat added for the same event (bystander_shock)


@dataclass(frozen=True)
class BeatCoverage:
    beat_index: int
    story: Story
    intent: ShotIntent
    event_id: int
    shots: int                        # how many packet shots carry this beat (0: the director's shot economy elided it)
    note: str = ""


@dataclass(frozen=True)
class TrimmedScenes:
    story: Story                      # texture or B: the A story is never trimmed
    event_ids: list[int]
    reason: str


@dataclass(frozen=True)
class EpisodePacketMap:
    version: int
    packet_hash: str
    plan_hash: str                    # the plan the packet follows (after trimming)
    source_plan_hash: str             # the plan before trimming (the same when nothing was trimmed)
    shots: list[ShotBeat]
    beats: list[BeatCoverage]
    trimmed: list[TrimmedScenes]
    body_seconds: float               # the shots' seconds (the title card and the ending are the style's, not counted)
    budget_seconds: float
    over_budget: bool                 # the A story alone is longer than the budget (it is never cut, so this is reported)
    map_hash: str = ""


def finalize(m: EpisodePacketMap) -> EpisodePacketMap:
    import dataclasses
    return dataclasses.replace(m, map_hash=hash_without(m, "map_hash"))


def verify(m: EpisodePacketMap) -> bool:
    return m.map_hash == hash_without(m, "map_hash")
