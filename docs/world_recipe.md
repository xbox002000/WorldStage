# World recipes

Written 2026-09-30, from the user's proposal to support wuxia, cultivation, western magic, ninja-style and
great-voyage worlds without building five engines. Code: `contracts/recipe.py`, `world/recipes/` (library,
compiler, `town_v1.json`), tests `tests/test_recipe.py`.

## The rule

A genre is not an engine, a franchise is not a plugin, a style is not a world rule, and a narrative mechanic is not
world truth.

A **WorldRecipe** is configuration: a choice of executable primitives from one library. It is compiled against:
- a budget;
- a compatibility table;
- a fixed precedence of layers.

Every recipe shares the same core: events, claims, attention, rule motives, goals, threads, the director, SceneSpec,
the spatial plan and production.

## What is adopted

- **The layers**: physics → power → progression → social → economy → information → adventure → narrative.
  - They are the precedence: a later layer reads what an earlier one set up, never the reverse.
  - Style is outside the world: it is the StylePack.
- **The role budget**: 1 core, at most 3 pillars, at most 3 accents, at most 2 narrative mechanics.
  - There is also a complexity budget (the sum of primitive costs, limit 12). That limits the interaction surface:
    n primitives have n(n-1)/2 pairs.
- **Compatibility**: compatible, conditional (accepted with a warning), exclusive (refused), requires_adapter (refused
  until someone writes the adapter). Examples:
  - rebirth + time loop: exclusive, because whose memory wins is undefined;
  - cultivation + magic: needs an adapter;
  - rebirth + system: conditional.
- **The signature hook**: what a viewer should notice first. It steers the director's preferences
  (`director_prefers`), never the world.
- **Proof before breadth**: the library may name primitives that have no code yet (`implemented = false`). A
  recipe using one does not compile. Nothing pretends to exist.

## What is adjusted

- **Fewer contracts.** The proposal listed eleven new concepts. Three carry them:
  - `MechanicPrimitive`: id, layer, requirements, cost, implemented;
  - `WorldRecipe`: core, pillars, accents, narrative, style, signature hook, director preferences, content;
  - `CompiledRecipe`: order, budget and warnings.
- **Most of the eleven are fields or layers, not types:**
  - world archetype, power system, progression system: layers;
  - signature hook, director preferences: fields;
  - story-world pattern ("ninja-type", "great voyage"): a recipe plus its director preferences;
  - genre compiler: `compile_recipe`.
- **Content is separate from rules.** Cast, places and things are the recipe's `content`. Today that is the small
  town in `world/seed.py`. A second recipe needs its own content file.
- **The first recipe is the town itself (`town_v1`).**
  - Core: everyday_life.
  - Pillars: ownership, rent, drift in retelling.
  - Accents: the parrot, animals, outside events.
- **The simulation now runs only the primitives the recipe enables.** A test turns off rent, the parrot and outside
  events and shows that their rules stop while everything else keeps running.

## Next: the second recipe proves the abstraction

"Jianghu" needs three new primitives:
- **reputation**: public standing that acts raise or ruin, readable by everyone;
- **duel**: a challenge settled by skill and luck, with stakes in reputation or a thing;
- **sect_factions**: membership, rank and loyalty.

It also needs its own content: an inn, a sect hall, a road, a secret manual, a master and disciples.

The test of the architecture is whether threads, the director, SceneSpec, the spatial plan and production run for
jianghu without changes. Cultivation and magic come after that, one at a time. Each needs a power primitive and an
adapter if they are mixed.

Narrative mechanics still come from the world's recorded `NarrativeMechanicPack`. The next step is to build that
pack from the recipe's `narrative` list, so there is one source.
