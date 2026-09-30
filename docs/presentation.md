# Presentation Runtime, Director Camera Sandbox, replay fidelity, Shot Cost Planner

Written 2026-09-30, from two user reviews.
- The first asked for a Director Camera Sandbox: load a world, replay, change whose eyes and the camera, and never
  change the world. It also asked for basic skeletal performance, a layered Replay Fidelity Test, and a Shot Cost
  Planner.
- The second asked to take Godot out of the main line: Blender makes the assets, three.js plays the world, Python
  decides it.

## The chain

```text
world.db ─▶ WorldRuntime (Python, canonical) ─▶ RuntimeTrace
                                                    │            DirectorPlan + PerformancePlan ─▶ ProductionPacket
                                                    ▼                                                  │
                 runtime/stage.py: SceneManifest (places, bodies, keys, hand-offs, one cut list per version) ◀┘
                                                    │
Blender 5.2.2 (headless) ─▶ person/dog/wallet .glb ─┤
                                                    ▼
                      three.js Presentation Runtime (render/presentation): a view, never a second world
                           │                                   │
                  HyperFrames (render, seek t)          browser (?sandbox=1: pause, seek, versions, free camera, lens)
```

| Layer | Owns | Must not |
|---|---|---|
| Python world and runtime | what happened, where everyone is, who holds what, when things change hands | — |
| Blender | the cast's meshes, rigs and materials | decide anything about the world |
| SceneManifest (`runtime/stage.py`) | the semantic scene handed to any presentation engine | add or change events |
| three.js | pixels: bodies on the keys, bones posed by the performance, the camera rig | move a body, hand over a thing, run AI or rules |
| Director (the packets' cuts) | whose eyes, what the audience knows, framing, edit | change the world clock |

## Two clocks

- The **world clock** is the runtime's playback time, with idle gaps compressed. It is the same for every version.
- The **film clock** is a version's edit.

Each shot plays a slice of its own event's world time. The shots of one moment continue each other (coverage, not
repetition), and where the world holds still the slice is simply a held pose. Changing the version (whose eyes,
what the audience knows) changes the cut list only.

## Blender assets

- `python -m runtime.blender.build` runs `runtime/blender/build_cast.py` in Blender 5.2.2 headless.
  - A person: an armature of 14 bones (hips, spine, neck, head, arms, forearms, hands, thighs, shins) with
    rigid-skinned low-poly parts. The clothes are tinted per character at runtime.
  - A dog: body, neck, head, mouth, ears, tail and four legs.
  - A wallet.
- **Canonical bytes.** Blender's glTF exporter writes the same triangles in a different order on every run.
  `canonical_glb` rotates each triangle to start at its smallest index (winding kept) and sorts them. After that,
  three builds give identical hashes, recorded in `assets/manifest.json` with the Blender version.
- **Validated.** The Khronos glTF Validator (npm `gltf-validator`, version pinned) reports 0 errors and 0 warnings
  on all three. The one warning it first gave (a skinned mesh under a parent node) was fixed at the source.

## The three.js Presentation Runtime

- **`runtime_rule.js`** holds the runtime's sampling rule, the two clocks, the reach amount and the trigger order.
  These are plain functions with no three.js, so node runs the same file the page runs.
- **`presentation.js`**
  - Builds the places (white-box geometry) and loads the Blender cast (`SkeletonUtils.clone` per body; skinned
    meshes are never frustum-culled, because their bounds stay where they were built).
  - Poses the bones from the runtime and the PerformancePlan, as turns about the body's own axes, whatever each
    bone's axes are:
    - walking legs and arms;
    - sitting, and a crouch and reach at a pick-up;
    - lean and shoulder tension;
    - hands: grip, hold, point, search, fidget;
    - gaze: toward the target, away from it, down, scanning;
    - micro-actions: a glance away, a swallow, a jaw clench, a look around;
    - the dog's ears, tail, head tilt, sniffing and looking back.
  - A carried thing is attached to the holder's hand or mouth bone.
  - Runs the camera rig from each shot:
    - scale sets distance and lens; angle sets eye height;
    - subjective puts the camera at the focalizer's eyes (0.47 m for the dog) and hides the focalizer;
    - over the shoulder, profile, rear and two-shot place the camera around the subject;
    - push-in, pull-out, handheld and tracking move it;
    - it never looks through a wall, a tree or another body: it turns around the subject to the nearest clear
      angle, and stays inside a room.
- **Render mode.** HyperFrames seeks a GSAP timeline, so every frame is a function of the film time alone. A probe
  showed HyperFrames waits for a timeline registered after asynchronous loading, so the glTF loading is safe.
- **Sandbox mode** (`?sandbox=1`):
  - Space pauses, ←/→ seek, R replays.
  - 1/2/3 switch the version and keep the same moment of the world.
  - F gives a free camera (WASD, Q/E, drag), and L changes the lens.
  - There is no code path that edits the world.

## Replay fidelity (`runtime/fidelity.py`, `tests/test_fidelity.py`)

Each layer is checked against the one below it, so a wrong picture points at a layer:

| Layer | Checked | Result on the wallet scene |
|---|---|---|
| world | its snapshot hash; who holds what after each event, from its own deltas | recorded |
| runtime | `check()` against the world; hand-off order (a pick-up before the drop); event order; state and trace hashes | ok |
| presentation | node runs the page's `runtime_rule.js` and is compared with the Python rule: transform error, holders, trigger order | ok: 0.05 mm (rounding), 230 triggers in the same order |
| camera | every version's edit maps onto the same world clock | ok: drift 0.0 |

Negative tests confirm the report names the right layer:
- a body moved by 0.5 m is reported as a presentation fault;
- a wallet in the wrong hands is reported as a presentation fault, with the mismatches listed.

## Shot Cost Planner (`production/dryrun.py`)

- A shot goes to a paid video model only where the procedural render cannot carry it:
  - a turn of the beat (reveal, payoff) on a body;
  - a body's performance seen close (MCU, CU, ECU).
- Inserts, hidden acts, places, and wide or medium shots stay procedural at $0.
- Each request carries:
  - the prompt, with the performance;
  - the duration, raised to the provider's minimum;
  - references (the Blender cast and the shot's white-box frame);
  - the camera (scale, angle, whose eyes, movement);
  - the motion (the runtime's hand-offs and when contact falls);
  - continuity (what each body holds before and after).
- Prices come from `production/prices.json`: fal.ai list prices for Kling 3.0 Pro and Seedance 2.0, with their
  source and date. They are estimates.
- Under a budget, the turns are kept first and the rest fall back to procedural.
- Nothing is sent: the module has no network code.

| Version | Shots worth a model | Kling 3.0 Pro |
|---|---|---|
| A (Ming, mystery) | Ming's close-up as he gets the wallet back | $0.67 |
| B (the dog's eyes) | the payoff on Ming | $0.45 |
| C (omniscient) | two reveals on the dog, Ming's payoff | $1.74 (with a $1.00 budget: the two dog reveals, $0.90) |

## What was decided about the tools

- **Installed:** three 0.186.1 (MIT) and gltf-validator (Apache-2.0), pinned in `render/package.json`. Blender 5.2.2
  LTS was already installed by the user.
- **Not installed now**, with reasons:
  - **Blender MCP.** It runs arbitrary Python in a live Blender, with telemetry on by default. That is a
    non-reproducible authoring path, and our assets come from a script.
  - **Playwright MCP.** The in-app browser pane and HyperFrames' pinned headless Chrome already cover loading,
    clicking, screenshots and capture.
  - **A three.js skill pack.** The clock, replay and camera rules here are already fixed, and a second set of
    conventions would compete with them.
  - **LSPs and three.js DevTools MCP.** Development conveniences that change persistent config. The code is JS,
    not TS.
  - **glTF Transform.** The assets are 9–70 KB; there is nothing to optimise yet.
  - **Rigify.** Built into Blender, for when real characters are authored.
- **Godot** is demoted to an optional presentation backend.
  - The committed player (`runtime/godot/main.gd`) stays, and its test skips when Godot is absent.
  - The sandbox built on it was ported to three.js and removed.
  - Godot 4.7.2 stays in `tools/godot` (not committed) and can be deleted.

## Not yet

Superseded in part on 2026-09-30 by `docs/space.md`: runtime 0.2 (paths, seats, turns, footfalls, action tracks),
feet and hands on IK, things with their own silhouettes, the camera solved in Python, shot economy, the Previs Pack
and the God View. Still missing:
- **Faces.** No expressions on the 3D figures (the performance's face channel is not yet on them), no fingers.
- **Scent trails and dog vision** from the 2D cartoon are not yet in the 3D dog view.
- **No sound** in the three.js renders.
- **Not a registered provider yet.** The presentation runtime is driven by scripts, not registered as a
  `composition.render` provider for the daily job.
