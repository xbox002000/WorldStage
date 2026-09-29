# 00 Principles and audit

## Principles (unchanged; each is enforced by a test)

- `world.db` is the only truth. `world.events.apply_event` is the only write path, and history is append-only.
- LLMs and mechanics only propose Intents. Rules resolve them. Truth, character belief and audience belief are
  separate layers of claims.
- Production holds only read-only world connections (`mode=ro`, `query_only`, never `immutable=1` because of WAL).
- Every artifact is content-addressed: world revision + snapshot → `scene_hash` → `packet_hash` → `request_hash`
  (which includes the toolchain) → `artifact_hash`. `production/provenance.py` walks the chain back.
- New in this round: **production code names capabilities, never tools.** Providers come from
  `capability/defaults.py`. Tests forbid `production/` from importing any renderer or synthesiser, and forbid
  `contracts/`, `world/` and `narrative/` from importing `capability/`, `render/` or `audio/`.

## Audit: the brief's eight questions

**1. What already fits.**

Most of the brief already exists:
- World core, event sourcing, claims, read-only production and provenance.
- A `toolchain_hash` in every request.
- LLM providers behind one client, with a request-hash cache (live, record, replay).
- Prompt fingerprinting, and frozen experiment configs.
- StoryThread with stages, crossings and dormancy.
- ExternalSeed as a closed vocabulary of effects (a seed can never name an outcome).
- NarrativeMechanicPack separate from StylePack (rebirth and system run as code).
- SpatialPlan with sight-line QA.
- An `audience_claims` table that is never world truth.

**2. Coupling found.**

(a) `production/pipeline.py` constructed `HyperFramesBackend` by name.

(b) The `Toolchain` contract had fixed `hyperframes` and `chrome` fields. Any other provider would have had to fill
them in or leave them empty.

(c) HyperFrames created its own audio backend, so audio could not be swapped.

(d) QA was a single pass/fail on the finished file. It gave no typed failure, and nothing could be repaired shot by
shot.

(e) There was no registry and no way to select a provider. The `VisualBackend` protocol existed, but nothing chose
between implementations.

**3. What needed migration.**

- (a), (c) and (e) were refactors: the registry, a composition root, and audio given to the composition provider.
- (b) was a contract change that turned out to be wire-compatible. Toolchain is now `dict[str, str]`, and the old
  class serialised to the same JSON, so every existing `request_hash` still verifies and the old takes still hit the
  cache. `REQUEST_VERSION` stays 2 on purpose.
- (d) needed new contracts (`VisualFailure`, `RepairRequest`) and additive production tables (schema v3:
  `provider_selections`, `visual_failures`, `repair_requests`).

**4. What looks fine now but would block extension.**

- `Shot.render_backend` in the packet ("procedural | stock | ai_clip") routes at compile time. It stays, as a hint
  that does not change hashes, but the registry now decides at render time. When a packet v3 is made for another
  reason, the field should become a requirement (features) rather than a backend kind.
- `to_srt` lives in `render/packet_html.py` although it is renderer-neutral. It is harmless for now.

**5. What is already over-built.**

Not much. `contracts/backends.py` had a `submit`/`poll`/`fetch` visual protocol that no second implementation ever
used. It is replaced by one synchronous `generate`, with the request hash as the idempotency key. An asynchronous
remote provider can poll inside `generate`.

The brief's `prepare`, `inspect` and `cancel` methods are **rejected** until a provider needs them.

**6. Schemas that needed additive migration.**

- render_request: the toolchain became a map with the same JSON.
- New schemas: provider_manifest, provider_selection, shot_request, visual_failure, repair_request.
- production.db v3 adds tables only.

**7. Tests that protect the invariants.**

These already existed:
- `test_production`: production never imports world writers, and only `production/db.py` opens writable SQLite.
- `test_replay`: same seed and recorded answers give the same world.
- `test_contracts`: every input changes the request hash, and the schemas match the dataclasses.
- `test_mechanics`: mechanics act only through events.

**8. Tests added (`tests/test_capability.py`, 24):**
- selection (features, length, budget, availability, policy order, determinism);
- import boundaries, and no provider field in RenderRequest;
- whitebox determinism, and cameras seeing their subjects;
- mock-clip determinism, and the frozen-clip diagnosis matching the ground truth over 8 seeds;
- MCP handshake, tool discovery, and an MCP clip byte-identical to the local one;
- a dead MCP server treated as an unavailable provider;
- repair by reseed, fallback to the next provider, and giving up after N attempts;
- the full shots route passing the same QA as HyperFrames and tracing back to world events;
- the same packet hash on both routes (the story does not change with the renderer);
- the audio provider swap changing the request.

## Adopted, adjusted, rejected

| Brief item | Decision |
|---|---|
| Capability interfaces + registry + selection | Adopted (05). |
| MCP as an adapter, never core | Adopted (06). The client is written against the spec with no SDK. The first MCP capability is `visual.generate`. |
| Blender as spatial compiler | Adjusted (08). The same role is filled by a numpy ray-caster with no install. Blender becomes a second `spatial.control` provider when installed. |
| Render → Diagnose → Repair | Adopted for what can be measured (09). Content failures (identity drift, …) are in the vocabulary, but nothing claims them without a detector. |
| AudioBackend `tts/music/sfx/mix` | Adjusted. One `audio.score` capability now. `audio.tts` becomes its own capability when voices are wired in (the Gemini TTS prototype in `render/cast/`). |
| Two narrative mechanics | Already done, as rebirth and system (the brief suggested mystery and system). A mystery **constraint** mechanic belongs to the director and is not built. |
| 11 architecture files | Adjusted. Only decisions made now get a file. The rest link to the existing design docs (see the index). |
| Capability-split MCP servers (world-mcp, audio-mcp, …) | Deferred until a second outside tool exists. |
| `LLMClient.propose/analyze/compile/diagnose` | Rejected for now. `agent/llm.py` already hides providers behind one call with record/replay, and a four-verb interface has no second caller. |

## Deferred, and why

- **ActionGraph.**
  - The world simulates at event granularity: "a steals the watch", not "reaches, grips, drops".
  - A sub-event action graph would be invented by templates or an LLM, so it would be presentation, not truth.
  - It pays off only once a video provider can follow per-action timing. None can at $0 today (video quota 0, and
    the GTX 1080 cannot run Wan 2.2).
  - It will be built with the first real I2V provider, as a production-side derivation of a SceneSpec beat.
- **ContinuityState.**
  - Partly exists: `ContinuityLocks` in the packet, and object holders per beat in the SceneSpec.
  - A per-shot state that is carried along matters when shots come from a generative model that can drift.
  - It becomes a repair input once a vision inspector can report `OBJECT_CONTINUITY_ERROR`.
- **Audience feedback → rumour.**
  - `audience_claims` exists as a table only.
  - Nothing is published yet, so there is no feedback to take in.
