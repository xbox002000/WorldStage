"""A season's plan: the producer's own document, never part of the world.

    SeasonPlan -> Arc -> Beat -> InterventionProposal (contracts/intervention.py)

A season is a stretch of days with a few protagonists, each with one arc, and an arc is a handful of opportunities placed on
days (a rival is cast, a parcel arrives, a gathering is announced). The plan says *why* (the arc's kind, the beat's purpose); the
world only ever hears the interventions it becomes, with an opaque id. The plan is revised every morning from what has really
happened, and what happens to the hero is theirs: a plan can end in a triumph or in a failure, and both are a season.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from contracts.base import hash_without
from contracts.intervention import InterventionType

SEASON_VERSION = 1
ArcKind = Literal["underdog", "succession", "romance"]


@dataclass(frozen=True)
class Beat:
    day: int                                  # days after the season began
    type: InterventionType
    target: str = ""
    params: dict[str, str] = field(default_factory=dict)   # a "+N" value means N days after the beat's own day
    purpose: str = ""                          # in the producer's words; never leaves the producer


@dataclass(frozen=True)
class Arc:
    arc_id: str
    kind: ArcKind
    protagonist: str
    beats: list[Beat] = field(default_factory=list)
    reason: str = ""                           # why this person, why this kind of story


@dataclass(frozen=True)
class SeasonPlan:
    season_id: str
    start_day: int
    days: int
    arcs: list[Arc] = field(default_factory=list)
    strategy: str = "full"
    version: int = SEASON_VERSION

    def hash(self) -> str:
        return hash_without(self)
