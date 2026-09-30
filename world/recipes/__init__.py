"""The primitive library and the recipe compiler (see docs/world_recipe.md).

The library names every primitive once with its layer, what it needs and what it costs. A recipe picks from it; the
compiler refuses a recipe that is over budget, uses an unimplemented or exclusive pair, or misses a requirement, and
otherwise returns the primitives in precedence order. The simulation asks the compiled recipe whether a primitive is on.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from functools import lru_cache
from pathlib import Path

from contracts.base import from_dict, hash_without
from contracts.recipe import LAYERS, CompiledRecipe, MechanicPrimitive, Pairing, WorldRecipe

HERE = Path(__file__).parent
DEFAULT_RECIPE = "town_v1"
LIMITS = {"core": 1, "pillar": 3, "accent": 3, "narrative": 2}
BUDGET = 12

P = MechanicPrimitive
LIBRARY: dict[str, MechanicPrimitive] = {p.id: p for p in [
    # always-on core of every world
    P("events", "physics", "one transaction = one event; the only way anything changes", cost=0),
    P("claims", "information", "propositions; truth vs belief vs what was said", ["events"], cost=0),
    P("attention", "physics", "being present is not noticing; loud and quiet acts", ["events"], cost=0),
    P("space.perception", "physics", "the world is simulated in its space: witnesses must see or hear, finders must see",
      ["attention"], cost=0),
    P("schedule", "physics", "daily routines move people between places", ["events"], cost=0),
    P("volition", "social", "rule motives from traits, needs, feelings, beliefs", ["claims"], cost=0),
    P("goals", "social", "goals form, get blocked, transform, are abandoned or completed", ["volition"], cost=0),
    P("psyche", "social", "repeated experience slowly moves traits, values and the self-model", ["volition"], cost=0),
    # the small town's primitives (World C)
    P("everyday_life", "physics", "ordinary life in a small town: work, meals, gossip", ["schedule"]),
    P("items.ownership", "economy", "rightful owner vs holder; things go astray, are taken, missed, found", ["attention"]),
    P("items.accusation", "social", "suspicion by inference; accusations judged by world truth", ["items.ownership", "claims"]),
    P("money.rent", "economy", "rent, arrears, odd jobs, prices", ["everyday_life"]),
    P("money.debt", "economy", "lending and repaying; a demand has weight", ["money.rent"]),
    P("gossip.drift", "information", "passing things on; unsure retellings drift", ["claims"]),
    P("props.parrot", "information", "a repeater that repeats quiet claims loudly", ["claims"]),
    P("props.animals", "economy", "a pet costs its keeper every night", ["items.ownership"]),
    P("seeds.external", "adventure", "outside events adapted into closed-vocabulary effects", ["events"]),
    # narrative mechanics
    P("rebirth", "narrative", "a timeline fork; one person remembers the first run", ["claims"], cost=2),
    P("system", "narrative", "hidden quests with true hints and rewards", ["goals"], cost=2),
    # named for recipes still to come; they do not compile until they have code
    P("reputation", "social", "public standing that acts raise or ruin", ["claims"]),
    P("duel", "adventure", "a challenge settled by skill and luck, with stakes", ["reputation", "martial_arts"]),
    P("sect_factions", "social", "membership, rank and loyalty in groups", ["reputation"]),
    P("martial_arts", "power", "skills that training raises; a manual doubles it", ["schedule"], cost=2),
    P("cultivation", "power", "realms, spiritual resources, breakthroughs", [], implemented=False, cost=2),
    P("magic", "power", "spells with costs, schools and guilds", [], implemented=False, cost=2),
    P("time_loop", "narrative", "the world forks every N days", ["claims"], implemented=False, cost=2),
]}
BASE = ["events", "claims", "attention", "schedule", "volition", "goals"]

PAIRINGS = [
    Pairing("rebirth", "time_loop", "exclusive", "two ways of repeating time: whose memory wins is undefined"),
    Pairing("cultivation", "magic", "requires_adapter", "two power systems need a rule for how they compare"),
    Pairing("rebirth", "system", "conditional", "allowed: the system does not know about the first life"),
]


def pairing(a: str, b: str) -> Pairing | None:
    for p in PAIRINGS:
        if {p.a, p.b} == {a, b}:
            return p
    return None


class RecipeError(ValueError):
    pass


def compile_recipe(r: WorldRecipe) -> CompiledRecipe:
    chosen = {"core": [r.core], "pillar": r.pillars, "accent": r.accents, "narrative": r.narrative}
    for role, items in chosen.items():
        if len(items) > LIMITS[role]:
            raise RecipeError(f"{role}: {len(items)} chosen, the budget allows {LIMITS[role]}")
    enabled = list(dict.fromkeys((r.base or BASE) + [x for items in chosen.values() for x in items]))
    for pid in enabled:
        if pid not in LIBRARY:
            raise RecipeError(f"unknown primitive {pid!r}")
        if not LIBRARY[pid].implemented:
            raise RecipeError(f"{pid} is in the library but has no code yet")
    for pid in r.narrative:
        if LIBRARY[pid].layer != "narrative":
            raise RecipeError(f"{pid} is not a narrative mechanic")
    for pid in enabled:
        for need in LIBRARY[pid].requires:
            if need not in enabled:
                raise RecipeError(f"{pid} needs {need}, which the recipe does not enable")
    warnings = []
    for i, a in enumerate(enabled):
        for b in enabled[i + 1:]:
            p = pairing(a, b)
            if p is None:
                continue
            if p.relation in ("exclusive", "requires_adapter"):
                raise RecipeError(f"{a} + {b}: {p.relation} ({p.note})")
            warnings.append(f"{a} + {b}: {p.note}")
    used = sum(LIBRARY[p].cost for p in enabled)
    if used > BUDGET:
        raise RecipeError(f"complexity {used} is over the budget of {BUDGET}")
    order = sorted(enabled, key=lambda p: (LAYERS.index(LIBRARY[p].layer), enabled.index(p)))
    c = CompiledRecipe(r.recipe_id, r.hash(), order, used, BUDGET, warnings)
    return replace(c, compiled_hash=hash_without(c, "compiled_hash"))


@lru_cache(maxsize=None)
def load_recipe(recipe_id: str = DEFAULT_RECIPE) -> WorldRecipe:
    return from_dict(WorldRecipe, json.loads((HERE / f"{recipe_id}.json").read_text(encoding="utf-8")))


@lru_cache(maxsize=None)
def compiled(recipe_id: str = DEFAULT_RECIPE) -> CompiledRecipe:
    return compile_recipe(load_recipe(recipe_id))


def recipe_of(conn: sqlite3.Connection) -> str:
    row = conn.execute("SELECT value FROM meta WHERE key = 'recipe'").fetchone()
    return row[0] if row else DEFAULT_RECIPE


def enabled(conn: sqlite3.Connection, primitive: str) -> bool:
    """Is this primitive part of the world's recipe? Worlds made before recipes run the default one."""
    return primitive in compiled(recipe_of(conn)).order
