# Provider conformance: how to attach a new video model

Code: `contracts/bible.py`, `production/bible.py`, `tests/provider_conformance/` (`samples.json`, `bible.json`, `runner.py`,
`builder.py`), `production/shot_qa.py`. Plan: C2 in the roadmap ("what is needed to attach any video model").

**Problem.** Every video model wants its own prompt format, its own controls and its own idea of a reference picture. If the
upstream layers learn any of that, each new model costs a change in the director, the packet and the world. If nothing checks a
new model, "it renders" is the only evidence that it can carry this story.

**Decision.** A model is one provider plus its own compiler. Two neutral things sit upstream for the compiler to read, and one
fixed test set decides whether the provider can go live.

## The two neutral inputs

| Input | What it is | Where |
|---|---|---|
| `ShotRequest` | one shot, self-contained: plain description, seconds, size, seed, camera, each body's performance | `contracts/backends.py` |
| `Bible` | who is filmed and where, per world: the look, wardrobe and voice of each person, the layout and features of each place | `contracts/bible.py`, `production/bible.py` |

**The Bible.**
- A character asset is keyed by genome and casting: `char:<genome>:<costume hash>`. The same person keeps the same face in
  every world (the genome's appearance and voice), and each world dresses them (the casting's costume). The key moves when the
  genome or the costume does, and not otherwise.
- A scene asset is keyed by the world's place id (`scene:inn`) and described from the white-box layout that stages it
  (`narrative/layouts.py`): size, window, what stands in it.
- Every asset carries structured fields (a `Look`, an `identity_lock`, a `wardrobe_lock`) and one model-neutral sentence. A
  compiler uses whichever it needs.
- `references` is empty and reserved. The first time a provider works on a world it may make a face sheet or a voice sample,
  keep it there by content hash, and the Bible is cached with it. Nothing in this repository generates one yet.
- What the genome or casting does not say is listed in `gaps`, not invented.
- `check_bible` is the gate: no model words (`cinematic`, `8k`, a sampler, a lens, a model's name) and no banned name (the
  publish gate's list, `world/personas.py` `scan`) anywhere in it. `build_bible` refuses a world that holds a real person who
  was not fictionalized.
- `build_bible(conn)` is read-only and deterministic: the same world gives the same hash. `cache=True` keeps it under
  `out/bible/` by a cheap key (cast, costumes, places, layouts) and reads it back, checked against its own hash.
- Production code may not build or run worlds (`tests/test_production.py`), so a Bible is made from a connection or the path of
  a `world.db`. From a recipe: `tests/provider_conformance/worlds.py` `bible_for_recipe`.

## Attaching a model

1. **Manifest.** Write a provider class (`render/<model>.py` or a `capability/` adapter) with `manifest()`, `available()`,
   `toolchain()` and `generate(request, shot, dest) -> Take`. The manifest says what it can do: capability `visual.generate`,
   features (`t2v`, `i2v`, `reference_image`, `depth`, ...), limits, cost per second, whether it is deterministic. See
   `render/mock_clip.py` for the smallest one.
2. **Compiler.** Inside the provider, turn `ShotRequest` (and, if it uses references, the `Bible` assets named by
   `reference_asset_ids`) into the model's own input: a prompt, a workflow, control images. This is the only place a model's
   vocabulary may appear. `generate` returns a `Take` with status `failed` for a failure, never an exception for a bad take
   (the runner and `production/shots.py` both treat a raise as a failed take).
3. **Register.** Add it in `capability/defaults.py` (the composition root). Nothing else imports it.
4. **Run the suite.**

   ```
   python -m tests.provider_conformance.runner --provider <id> [--scale 0.25] [--json report.json]
   ```

   or from a test: `run_conformance(provider)`. The default policy allows only free providers, so a paid model is *skipped with
   its reason and never called*. A paid model is dry-run only until the budget is approved: write its compiler, check its request
   with `production/dryrun.py`, and run the suite when it is allowed to spend.
5. **Read the report.** Per sample: pass, fail (with the codes) or skipped (with the reason). The provider passes when every
   sample is made, none has a failure, and the determinism check holds. A model that is only meant for some shots may be run
   with `--allow-skipped`; at least one sample must still pass.
6. **Go live** by listing it in a policy's `order`. No upstream file changes.

## The samples

Seven shots of real events of `jianghu_story_v1` (seed 17, eight days), compiled as the pipeline does: SceneSpec, DirectorPlan,
PerformancePlan, ProductionPacket, ShotRequest. Each has the closed-vocabulary intent the episode plan gives that beat
(`contracts/episode_plan.py`), the packet it came from, and the Bible assets it uses.

| Sample | Real event | Shot |
|---|---|---|
| `two_person_dialogue` | a warm talk | two-shot, medium |
| `duel` | a bout, three watching | escalate, MCU |
| `hand_over` | a take, then a give, through the world's rules | payoff, CU |
| `public_face_slap` | a duel that showed somebody to be more than they were taken for | escalate, MCU |
| `ambiguous_closeup` | a flirt | longing glance, CU |
| `crowd_reaction` | the same duel, the bystanders | reaction, CU |
| `confrontation` | a public confrontation, nine others present | reveal, CU |

The fixtures are committed so that the suite does not depend on the simulation staying the same.
`python -m tests.provider_conformance.builder --check` (or `PROVIDER_CONFORMANCE_REBUILD=1` with the tests) replays the world and
says whether they have drifted; `--write` replaces them.

## What it judges, and what it does not

`production/shot_qa.diagnose` measures: format (size and frame rate), duration, frozen frames, black frames, provider error.
The runner adds a rerun for a provider that claims to be deterministic.

It does **not** judge whether the face is the right face, whether the slap reads as a slap, or whether the hands are right.
Those failure codes exist (`IDENTITY_DRIFT`, `POSE_ERROR`, `OBJECT_CONTINUITY_ERROR` in `contracts/repair.py`) but there is no
detector for them; a vision inspector, and a person looking, come with the first real model. Passing here means the provider
is mechanically sound on this story's shots, not that it is good.

## Tests

`tests/provider_conformance/test_runner.py` shows the runner telling providers apart, using the local mock and small fakes
(one that freezes, one that raises, one with the wrong size, one that lies about determinism, one that costs money, one that
lacks a feature). `tests/test_bible.py` covers the contract, the schema, determinism, read-only access, the two rules and the
cache.
