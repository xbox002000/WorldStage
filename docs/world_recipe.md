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

## The second recipe: jianghu (built 2026-09-30)

`world/recipes/jianghu_v1.json`, content `world/content/jianghu_v1.py`, rules `world/jianghu.py`, tests
`tests/test_jianghu.py`.

- **Recipe**: core martial_arts; pillars reputation, duel and sect_factions; accent gossip drift. It has no rent, no
  outside feed and no props.
- **Content**:
  - Two rival sects (青雲門, 鐵劍山莊), an inn, a market and a mountain road.
  - Ten people: a master and his disciples, a manor lord and his son, a retainer, an innkeeper, a storyteller and a
    wanderer.
  - The starting secret: years ago the senior disciple 陸青 stole the sect's 《青雲劍譜》.
- **Primitives** (each runs only when the recipe enables it):
  - **martial_arts**: skill that training raises, slowly and with diminishing returns. A manual doubles the gain.
  - **reputation**: public standing. It moves with spectacles: caught, a lie exposed, a false accusation, a duel.
    Beating someone better known proves more; bullying the weak costs standing. It colours belief: a respected
    teller is believed more, and a disreputable person is suspected more.
  - **duel**: settled by the skill gap plus luck. Non-fighters are never involved, and the same pair cannot fight
    again within three days. The loser forms "surpass" (or "revenge", if hot-tempered). If the winner is the
    rightful owner of something the loser holds, it goes back: settled by the sword.
  - **sect_factions**: warmer within a sect, sharper across rival sects. A sect-mate beaten or wrongly accused in
    front of you breeds a grudge against whoever did it.
- **Thirty days, seed 1:**
  - 26 duels, and a recurring rivalry between the two sect heads that goes back and forth.
  - The manor lord's son keeps losing to the senior disciple he wants to beat.
  - A retainer steals the young lord's sword and is caught the next day.
  - On day 4 the manor lord picked up the lost manual unseen, and on day 6 lost a duel to its rightful owner, so it
    went back. Nobody wrote that.
  - 38 threads (25 long), cross-thread rate 0.74, no flat days, clean audit, exact replay.
  - Three rendered episodes through the same daily job (`daily.py --world-c --feed none --recipe jianghu_v1`).

### The red line: what the shared core had to change for a second world

| Change | Why |
|---|---|
| Night-time home from the content (`world/content.home_of`) instead of the literal `apartment` in five places | the town's home was hardcoded |
| Initial goals passed in by the content | they were the town's dict |
| A layout alias per place (`LAYOUTS` in the content) | the spatial plan only knew the town's five places |
| `build_world` dispatches to a content builder | the town was the only builder |
| The narrative vocabulary learned `duel` and `train` (shot table, event summaries, beat functions, a claim act `defeat`) | new events need words and shots |

Nothing else changed: story threads, the story director, knowledge, the DirectorPlan, SceneSpec, the SpatialPlan,
the packet compiler, the render pipeline, goals, psyche and mechanics. The first four rows were town assumptions
leaking into the core, and they are fixed for every future recipe. The last row is the expected cost of a new
primitive.

## Next

- Cultivation and magic, one at a time. Each needs a power primitive, and an adapter if the two are mixed.
- Build the NarrativeMechanicPack from the recipe's `narrative` list, so there is one source.
- The town's content still lives in `world/seed.py`. Moving it into `world/content/town_v1.py` would make the two
  recipes symmetric. That needs care, because the town's snapshot hashes must not change.

## Before jianghu: the plan that was tested

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
