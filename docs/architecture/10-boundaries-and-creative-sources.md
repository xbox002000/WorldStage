# 10 Boundaries, MCP placement and creative sources

Written 2026-09-30, from the user's survey of 2026 short-drama tools:
- script-first: Jellyfish, Moyin, drama-skills;
- director and technical storyboard layers: AI-real-person-short-drama-workflow, short-drama-production;
- agentic studios: OpenMontage;
- canvas studios: Toonflow;
- MCP-first factories: StarReel MCP, remotion-video, mcp-video.

The survey's MCP facts come from its sources (spec 2026-07-28, Tasks extension); they were not re-checked here.

## Audit: where the repo already stands

| Boundary | Status | Where |
|---|---|---|
| World core (events, deltas, claims, memory, relationships, goals, psyche, recipes, mechanics) is plain Python, deterministic, the only writer of `world.db` | in place, enforced by tests | `world/`, `tests/test_series.py` (write path), `tests/test_determinism.py` |
| Story engine (threads, knowledge, story director) is read-only on the world | in place | `narrative/threads.py`, `narrative/knowledge.py`, `narrative/director.py` |
| Director engine (knowledge, focalization, beats, grammar, attention, performance, camera, edit, sound) is read-only, deterministic, not a provider | in place | `narrative/direction.py`, `narrative/grammar.py`, `narrative/performance.py` |
| Production IR (SceneSpec, SpatialPlan, ProductionPacket, RenderRequest) is compiled deterministically | in place | `narrative/compiler.py`, `narrative/spatial.py`, `contracts/` |
| Capability runtime (registry, manifests, $0 policy, fallback, cache by request hash) | in place | `capability/registry.py`, `capability/defaults.py` |
| MCP only as an adapter, with tools named by capability (`visual_generate`), never by tool | in place | `capability/mcp_adapter.py`, `docs/architecture/06-mcp.md` |
| Production never imports a renderer, and never writes the world | in place, enforced by tests | `tests/test_capability.py`, `world/reader.py` |
| ActionGraph, ContinuityState | partial | Body continuity is now in the PerformancePlan (`BodyState`: holding, hand, gesture, gaze, emotion). There is no separate ActionGraph yet. |
| Creative sources other than the world | missing | see below |
| MCP long-running tasks | missing | the adapter is request/response against the 2025-06-18 revision |

## Decisions

**1. Never MCP: world, character, story, director, performance and the compilers.**
- This agrees with the survey. It is already true and is tested.
- A model may *propose* (an Intent, and later a DirectorPlan proposal). The rules and compilers decide.
- A future `world` MCP server could only offer `propose_intent` or `submit_external_signal`, both of which go
  through the validator.

**2. A script or novel enters through the world, not beside it.**
- This adjusts the survey's proposal. The survey suggested `CreativeSource -> Narrative IR -> SceneSpec`, which
  skips the world. That would break everything the director and performance layers now derive from the world:
  - who knows what (claims and memories);
  - how someone feels about someone (relationship history);
  - what they hold;
  - why they act.

  A scripted scene with no world behind it has no beliefs to play.
- So the plan is a `ScriptSource` that compiles a screenplay into a world: a recipe, a cast, places and things, and
  the scripted events *applied through `apply_event`* with their truth claims and memories.
- From there the path is the same as an emergent story: threads, the director, performance, production.
- The script decides what happens; the world records it, so beliefs, relationships and continuity exist.
- It is one entry point and one Narrative IR, and that IR is the world itself.

**3. MCP Tasks map onto takes, when a real long-running provider exists.**
- The Take states already match a task's life: queued → generating → ready / failed.
- The adapter will move to `tools/call` returning a task, then `tasks/get` polling, once:
  - there is a provider worth waiting for;
  - the client can be checked against an outside implementation. That needs the MCP SDK or the Inspector, which
    is a download and must be allowed first.
- Until then it stays request/response, and says so.

**4. No fleet of servers.**
- At most one capability gateway per capability family: research, visual, audio, spatial, composition, QA,
  publishing.
- Each offers a handful of verbs (discover, generate, inspect, poll, fetch, cancel). Provider-specific complexity
  stays inside the adapter.
- StarReel-style 120-tool surfaces are not copied.

**5. External studios are adapters or references, never the core.**

| Project | Role here |
|---|---|
| Jellyfish, short-drama-production | shot and asset preparation reference, production gates |
| drama-skills (MIT) | a possible script → ScriptSource front end (a skill that writes the screenplay the ScriptSource compiles) |
| OpenMontage | agent orchestration method |
| Toonflow (MIT), Moyin | future export targets for human finishing |
| StarReel MCP, remotion-video, mcp-video | capability providers behind the registry |
| HyperFrames | the composition backend today |

## Not done now, and why

- **ScriptSource.** It is the next architecture step after the performance layer. The work: a screenplay contract,
  a compiler into events, and a test that a scripted wallet scene and the emergent one give the same kind of plans.
- **A real `visual.generate` provider.** Every usable video model costs money (roughly $0.1–0.3 per second), and
  the budget is $0. The mock provider through MCP stays the proof. A dry-run prompt compiler, with a cost estimate
  and nothing sent, is the $0 step that is possible.
