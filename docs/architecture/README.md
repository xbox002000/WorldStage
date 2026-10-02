# Architecture

Written 2026-09-30, after the "Architecture Evolution Brief" review. Decision records use the brief's numbering. Where
an earlier design doc already records the decision, it is linked rather than copied.

| # | Topic | Where |
|---|---|---|
| 00 | Principles and audit | [00-principles-and-audit.md](00-principles-and-audit.md) |
| 01 | World core (event sourcing, claims, read-only production) | top-level [README](../../README.md), `world/`, tests `test_events`, `test_production` |
| 02 | Narrative mechanics | [../narrative_mechanics.md](../narrative_mechanics.md) |
| 03 | Story threads and director | [../story_thread_architecture.md](../story_thread_architecture.md), [../world_event_ecology.md](../world_event_ecology.md) |
| 04 | Production graph (SpatialPlan; ActionGraph and ContinuityState deferred) | [../spatial_plan_architecture.md](../spatial_plan_architecture.md), [00 §Deferred](00-principles-and-audit.md#deferred-and-why) |
| 05 | Capability layer and provider selection (the brief's 05 and 07) | [05-capability-layer.md](05-capability-layer.md) |
| 06 | MCP | [06-mcp.md](06-mcp.md) |
| 08 | Spatial whitebox | [08-spatial-whitebox.md](08-spatial-whitebox.md) |
| 09 | Render → Diagnose → Repair | [09-render-diagnose-repair.md](09-render-diagnose-repair.md) |
| 10 | Experiments | `production/experiment.py` (a frozen config per experiment id), [../experiment_A.md](../experiment_A.md) |
| 11 | Provider conformance and the Bible (attaching a video model) | [provider_conformance.md](provider_conformance.md) |

## The pipeline as built

```text
world.db ─(read-only)─▶ threads / arcs ─▶ SceneSpec ─▶ ProductionPacket ─▶ SpatialPlan
                                                               │
                        ┌──────────── capability registry ─────┴──────────────┐
          route procedural                                            route shots
   composition.render[procedural_visuals]             spatial.control[depth] ─▶ control PNGs
          (hyperframes)                                visual.generate[t2v,depth] ─▶ clip
                                                          ▲    │ diagnose
                                                          └────┘ repair (reseed / next provider)
                                                      composition.render[clips] (ffmpeg-compose)
                        └────────── audio.score (synth | silence) ─────────────┘
                                          ▼
                                 Take ─▶ deterministic QA ─▶ episode ─▶ publisher
```
