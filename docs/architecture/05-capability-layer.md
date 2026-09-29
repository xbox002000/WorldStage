# 05 Capability layer and provider selection

Code: `contracts/capability.py`, `contracts/backends.py`, `capability/registry.py`, `capability/defaults.py`.

**Problem.** Production code named its renderer (`HyperFramesBackend`), so adding a second renderer, video model or
TTS meant editing the pipeline. The request contract also carried HyperFrames-specific fields.

**Options.**
1. A backend `if` chain in the pipeline.
2. A plugin framework with entry points.
3. Capability interfaces, a registry of manifests, and one composition root.

**Decision: option 3.**

- Core code asks for a **capability** with a **requirement**. For example: `visual.generate` needs
  `[t2v, depth]`, 5 s, 1080×1920.
- The registry filters providers by manifest:
  - features;
  - length and size limits;
  - cost against the policy budget;
  - remote allowed or not;
  - denied or not;
  - availability right now.
- It ranks what is left by the policy: `cheap`, `quality` or `fast`, with an explicit `order` first.
- It returns the whole ranked list as the fallback chain, and every rejected provider with its reason. That record
  is stored in `provider_selections`.

Capabilities in use:

| Capability | Providers |
|---|---|
| `visual.generate` | `mock-clip`, `mcp:visual-mock` |
| `spatial.control` | `whitebox` |
| `audio.score` | `synth`, `silence` |
| `composition.render` | `hyperframes` (feature `procedural_visuals`), `ffmpeg-compose` (feature `clips`) |

**Why.**
- A new provider answers three questions: what it offers (manifest), whether it can run now (`available`), and
  which component versions pin its output (`toolchain`). It then implements its one method.
- Its own input format (prompt, workflow, Blender scene, HTML) stays inside it; this is the backend-specific compiler.
- Nothing about it leaks into SceneSpec, the packet or RenderRequest.

**Tradeoffs.**
- Manifests are self-declared. A provider that claims `depth` and ignores it will only be caught by QA.
- `quality` is a rough number that someone sets by hand.

**Rejected alternatives.**
- Entry-point plugins are too much machinery for one installation.
- Selecting by provider name in config gives no reasons and no fallback.

**Migration impact.**
- `Toolchain` became `dict[str, str]`, with JSON identical to the old class, so no request hash changed.
- HyperFrames receives its audio provider instead of creating one.
- The default route and its output are unchanged: the full old suite passes.
