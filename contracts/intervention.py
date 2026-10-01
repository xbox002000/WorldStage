"""Producer interventions: the showrunner's one way into the world.

    Producer -> InterventionProposal -> closed vocabulary + legality + budget -> apply_event -> world

The producer controls the topology of *opportunity*: who might meet, what is announced, what arrives, what position falls
vacant. The world controls outcomes, the characters their intentions, the rules the consequences. So a proposal has two
halves, and only one of them can reach the world:

  what the world sees   (WorldIntervention)  type, target, a few closed parameters, an opaque id
  what the producer keeps (the rest)         the season and arc it serves, why (`purpose`), what it cost, who proposed it

`purpose` and the arc never become world truth: the town sees "a master has come", never "a master has come so that the
hero can be proved right". See producer/intervention.py (the ledger) and world/interventions.py (the closed vocabulary).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from contracts.base import hash_without

INTERVENTION_VERSION = 1

# what the producer may do, and nothing else. Each is an opportunity; none names an outcome, a feeling or a relationship.
InterventionType = Literal["announce_gathering", "deliver_parcel", "open_seat", "announce_visitor", "cast_role"]


@dataclass(frozen=True)
class WorldIntervention:
    """The part of a proposal the world is told. Nothing in it says why."""

    intervention_id: str
    type: InterventionType
    target: str = ""                                      # a person, a place or a seat, by what the type says
    params: dict[str, str] = field(default_factory=dict)  # the type's own closed parameters (a day, a kind, a place)
    source: str = "producer"


@dataclass(frozen=True)
class InterventionProposal:
    intervention_id: str
    season_id: str
    arc_id: str
    type: InterventionType
    target: str = ""
    params: dict[str, str] = field(default_factory=dict)
    day: int = 0
    budget_cost: int = 1
    purpose: str = ""                                     # why, in the producer's words: kept in the producer's log only
    source: str = "showrunner"
    version: int = INTERVENTION_VERSION

    def hash(self) -> str:
        return hash_without(self)

    def world_view(self) -> WorldIntervention:
        return WorldIntervention(self.intervention_id, self.type, self.target, dict(self.params))
