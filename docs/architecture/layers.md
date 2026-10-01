# Layers: who may import whom, and how a new video model plugs in

Written 2026-10-01 (plan v0.4, section C2). The rule is enforced by `tests/test_layers.py`: it reads every import in every
package and fails on an edge that is not in its table, on a table entry nothing uses, and on a new edge that points the
wrong way.

```text
contracts   plain data and schemas
world       what happens (events, rules, domain packs); the only writer of world.db
agent       who wants what: proposes Intents, never writes
runtime     where and when, in space: plays events, never writes
narrative   reads the world: drama analysis, director, observatory, causal audit
producer    the showrunner: reads the story, and changes the world through the seed layer only
production  turns a chosen story into a model-neutral shot list (ProductionPacket, ShotRequest, PerformancePlan)
capability  provider registry: asks for "visual.generate", never for a tool
render      one adapter per renderer or model
channel     the daily run that ties it all together (may import anything)
```

## The four sentences (plan v0.5)

> The producer controls the topology of opportunity. The world decides the outcome. The characters decide their intentions.
> The rules decide the consequences.

Only one arrow writes: `Producer / Agent / System -> Intent -> World rules -> apply_event() -> world.db`. The producer's intent is an
`InterventionProposal` that has to pass a closed vocabulary, the world's rules and a budget (docs/producer.md).

Said once more for Producer 2 (plan v0.6): **the producer does not write a story; it manages the distribution of what could
happen.** It changes which things have a chance of happening (an occasion, a part, a parcel, a vacancy); the characters decide
whether to; the rules decide how it ends.

## The edges that point the wrong way

They exist, and they are listed so that they stay the only ones (`KNOWN_UPWARD` in the test):

| edge | why |
|---|---|
| world -> agent | the simulation calls the deciders and the replier it is given; intent.py asks what an agent perceives |
| world -> runtime | the simulation can play the runtime along (optional) |
| contracts -> world | `contracts/world_api.py` re-exports the kernel types |
| runtime -> narrative | the white-box layouts and the spatial plan are in `narrative/` |

## The producer

`producer/` is the one package that reads the story and then makes things happen. Everything else either reads
(`narrative/`) or acts as a character (`agent/`). It is separate so that the rule that matters can be tested:

- only `channel/` may import it;
- it has no `apply_event`, no `EventSpec`, no SQL that writes: its only door into the world is the seed layer
  (`world/seeds.py`, `contracts/seed.py`), whose vocabulary is closed (a test pins the word list);
- a seed names no person's action, feeling, relationship or verdict: the town decides what to do about it;
- it may *imagine* (producer/forecast.py) only through `world/rollout.py`: a copy of the world, run under another luck, thrown
  away. The real seed is refused as imagined luck, because the world is deterministic and a producer that ran the real future
  would be reading the answer, not weighing a chance (tests/test_rollout.py, test_layers.py: the producer never imports
  `Simulation`).

## Plugging in a video model

Nothing above `production/` knows a model exists. A new model is:

1. a provider (`manifest`, `available`, `toolchain`, `generate`) and its own compiler in `render/`: ShotRequest, the
   character and scene bible, the control images in; its prompt or workflow out;
2. registered in `capability/defaults.py`;
3. run against the conformance set (`tests/provider_conformance/`, phase 8) with `production/shot_qa.py`.

What makes this cheap is what the upstream layers keep in neutral data and never in model words:

- **who looks like what**: the genome's `appearance` and `voice`, and the world's casting `costume`; the compiler makes
  the CharacterLock from them, so a face is the same in every shot, scene and model;
- **what the shot means**: `Shot.intent` (a closed vocabulary from the director's grammar: reveal, payoff, reaction,
  bystander shock, longing glance, rival standoff, confession, ...), translated by each provider, never written as
  "cinematic, 8k" upstream;
- **where bodies are and how they move**: the runtime trace and the PerformancePlan.
