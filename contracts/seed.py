"""External seeds: how something from outside the town gets in, without ever writing the plot.

ExternalEvent   a fact about the outside world (synthetic for now; real news later). Never enters world.db as such.
SeedCandidate   that fact adapted to this world: which domains it touches and what it could change here.
SeedEffect      one change from a closed vocabulary. No effect names a person's action, a feeling, a relationship
                or a verdict; the town decides what to do about it.

The provenance chain is ExternalEvent -> SeedCandidate -> the `seed` event in world.db, whose truth carries the
external event id, the candidate hash and the feed hash.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from contracts.base import hash_without

SEED_VERSION = 1

SeedType = Literal["stimulus", "pressure", "opportunity", "disruption", "information"]
EffectOp = Literal["set_var", "place_object", "deliver_object", "set_object_value", "news", "animal_arrives"]
# The only world variables an outside event may move.
SEED_VARS = ("price_food", "visibility", "job_security")
AUDIENCES = ("everyone", "workers", "at_cafe", "at_office", "at_park", "at_station")


@dataclass(frozen=True)
class ExternalEvent:
    external_event_id: str
    source: str  # "synthetic" for fixtures; a feed name later
    day: int  # simulated day it becomes observable in the town
    title: str
    topic: str  # a key into the adapter table (world/seeds.py TOPICS)
    magnitude: float = 1.0  # 0..2: how strong it is out there
    salience: float = 0.5  # 0..1: how much people would hear about it
    confidence: float = 1.0  # 0..1: how sure the source is that it happened
    expires_after_days: int = 3  # if the town cannot take it in by then, it is dropped
    version: int = SEED_VERSION

    def hash(self) -> str:
        return hash_without(self)


@dataclass(frozen=True)
class SeedEffect:
    op: EffectOp
    key: str = ""  # set_var: variable; *_object: object id
    value: float = 0.0  # set_var: new value; set_object_value: cents
    at: str = ""  # place_object: location id
    audience: str = ""  # news: who hears it
    text: str = ""  # news: what they hear
    revert_after_days: int = 0  # set_var: 0 = permanent


@dataclass(frozen=True)
class SeedCandidate:
    seed_id: str
    external_event_id: str
    seed_type: SeedType
    world_relevance: float  # 0..1: how much of what the event touches exists in this town
    affected_domains: list[str]
    effects: list[SeedEffect]
    status: Literal["adopted", "rejected", "expired"] = "adopted"
    reason: str = ""
    version: int = SEED_VERSION
    candidate_hash: str = ""

    def compute_hash(self) -> str:
        return hash_without(self, "candidate_hash")


@dataclass(frozen=True)
class SeedFeed:
    feed_id: str
    events: list[ExternalEvent] = field(default_factory=list)
