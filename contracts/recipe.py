"""WorldRecipe: which executable primitives a world is made of. Configuration and composition, not code.

Genre is not an engine and a franchise is not a plugin. "Jianghu", "cultivation" or "a small town with a parrot" are
recipes: a choice of primitives from one library, compiled against a budget, a compatibility table and a fixed
precedence of layers. All recipes share the same world core (events, claims, goals, threads, director, SceneSpec).

Budget: 1 core, at most 3 pillars, at most 3 accents, at most 2 narrative mechanics. The library can grow without
limit; one world keeps its interaction surface small (n primitives have n(n-1)/2 pairs).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from contracts.base import hash_without

RECIPE_VERSION = 1

# Precedence, outermost first: a later layer may read what an earlier layer set up, never the reverse.
Layer = Literal["physics", "power", "progression", "social", "economy", "information", "adventure", "narrative"]
LAYERS = ("physics", "power", "progression", "social", "economy", "information", "adventure", "narrative")
Role = Literal["core", "pillar", "accent", "narrative"]
Compatibility = Literal["compatible", "conditional", "exclusive", "requires_adapter"]


@dataclass(frozen=True)
class MechanicPrimitive:
    id: str  # e.g. money.rent, items.ownership, gossip.drift, goals, duel
    layer: Layer
    summary: str
    requires: list[str] = field(default_factory=list)
    implemented: bool = True  # False: named in the library, no code yet (a recipe using it will not compile)
    cost: int = 1  # share of the complexity budget


@dataclass(frozen=True)
class Pairing:
    a: str
    b: str
    relation: Compatibility
    note: str = ""


@dataclass(frozen=True)
class WorldRecipe:
    recipe_id: str
    title: str
    content: str  # the cast/places/things (world/content), separate from the rules
    core: str  # one primitive: what the world is about
    pillars: list[str]  # what keeps producing stories
    accents: list[str] = field(default_factory=list)  # flavour, never a rewrite of the simulation
    narrative: list[str] = field(default_factory=list)  # narrative mechanics (rebirth, system, ...)
    style: str = ""  # the StylePack id: how it is shown, never a world rule
    signature_hook: str = ""  # what a viewer should notice first; steers the director's preferences
    director_prefers: dict[str, float] = field(default_factory=dict)  # thread kind -> weight bonus
    base: list[str] = field(default_factory=list)  # always-on core primitives (events, claims, attention ...)
    version: int = RECIPE_VERSION

    def hash(self) -> str:
        return hash_without(self)


@dataclass(frozen=True)
class CompiledRecipe:
    recipe_id: str
    recipe_hash: str
    order: list[str]  # every enabled primitive, in precedence order (hooks run in this order)
    budget_used: int
    budget_limit: int
    warnings: list[str]  # conditional pairings that were accepted
    compiled_hash: str = ""
