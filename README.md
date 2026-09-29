# World-to-Video Engine

A simulated world runs on its own; the system picks the stories worth telling, compiles them into a shooting
plan and renders episodes. Plan and rationale: `C:\Users\xbox0\.claude\plans\concordia-fuzzy-creek.md`.

```text
world.db (SQLite, the only truth) ── events / deltas / claims / memories
   │  read-only (world/reader.py)
   ▼
SceneSpec ──(+ StylePack)──▶ ProductionPacket ──▶ RenderRequest ──▶ Take ──▶ QA ──▶ episode
 narrative/                  narrative/compiler     production/       HyperFrames
```

| Folder | What |
|---|---|
| `world/` | schema, `apply_event` (the only write path), claims, rules, seed world, simulation, snapshot/ruleset hashing, rng |
| `agent/` | LLM clients (Gemini, OpenRouter fallback), request-hash cache (live/record/replay), perception, decision tiers |
| `narrative/` | causal arcs, scoring, selection, SceneSpec builder, ProductionCompiler |
| `contracts/` | frozen dataclasses + generated JSON Schemas (`contracts/schemas/`) — the ABI |
| `production/` | `production.db`, provenance tracing, deterministic QA, pipeline, series memory, experiment freeze, metrics. Read-only towards the world |
| `channel/` | the daily job and the replay check: the only place that drives both the world (on a copy) and production |
| `audio/` | deterministic synthesised score and effects |
| `render/` | packet → HyperFrames project, local render backend |
| `tests/` | `python -m unittest discover -s tests -t .` |

## Commands

```bash
.venv/Scripts/python run_sim.py --days 7 --db out/world.db          # no LLM
.venv/Scripts/python run_sim.py --llm --days 7 --db out/world.db    # Gemini for the active tier
.venv/Scripts/python produce.py --world out/world.db --top 3        # episodes -> out/episodes/
.venv/Scripts/python -m contracts.generate_schemas                  # after changing a contract
```

## Rules that must keep holding

- Nothing outside `world.events.apply_event` changes the world; production code only holds read-only connections.
- All randomness comes from `world/rng.py`; queries that affect state have `ORDER BY`.
- Truth (`event_claims`), character belief (`memories`) and audience belief are different things over the same claims.
- Changing anything in `RULESET_FILES` changes `ruleset_hash`; changing a contract needs its schema regenerated.
- Local FFmpeg lives in `tools/ffmpeg` (not committed); rendering uses hyperframes' pinned headless Chrome.
