# World Runtime

Written 2026-09-30, from the user's proposal: make the world loadable, replayable and playable in space like a game
save, instead of letting the production layer guess movement. The proposal named 0 A.D., Wesnoth and OpenRA
(simulation apart from visual replay, command replay, state hashes) and Godot as the first playback engine.

Code: `contracts/runtime.py`, `runtime/world_runtime.py`, `runtime/export.py`, `runtime/godot/` (the player).
Tests: `tests/test_runtime.py`. Godot 4.7.2-stable (official release, SHA-512 checked) lives in `tools/godot/`; it is
not committed.

## Three kinds of data

| Layer | What it says | Where |
|---|---|---|
| World | what happened, who knows, who holds what | `world.db` (events, deltas, claims, memories) |
| Runtime | how it happened in space and time: walking, reaching, contact, which hand | `RuntimeTrace`, `RuntimeSnapshot` |
| Cinema | how it is watched: whose eyes, what the audience knows, camera, performance, edit, sound | `DirectorPlan`, `PerformancePlan`, `ProductionPacket` |

The bug that motivated it: the cartoon renderer guessed "a notice-missing shot shows the wallet in his hand". The
fix is not a better guess. It is a layer that reads who holds what from the world and says *when* it changes hands.

## What was adopted, what was adjusted

**Adopted**
- A runtime that loads the world at any revision, plays its events, tracks transforms and hand-offs, and produces
  a trace with a hash.
- Seek, pause and replay.
- Engines as players only.
- Debugging by layer: when a picture is wrong, first check whether the world is wrong, then the runtime, then the
  camera.

**Adjusted**
- **The canonical runtime is Python, not Godot.**
  - Godot's physics is not deterministic across machines, as the proposal itself warns, and a game engine must not
    become a second source of truth.
  - `WorldRuntime` is a pure function of the world's history, the white-box layouts, the world seed and
    `RUNTIME_VERSION`.
  - Godot, the 2D cartoon renderer, Blender or a video model only play its trace. `runtime/export.py:sample()` is
    the rule every engine follows: a `walk` key moves linearly to the next key, any other pose holds, and a carried
    thing is where its holder is.
- **No checkpoints yet.**
  - The runtime reads the whole history once (0.36 s for 2,045 events), keeps a frame per event, and seeks by
    binary search.
  - Checkpoints will come when a world is too long for that.
- **"Replay" does not re-execute the rules.** World replay already exists (same seed and recorded answers give the
  same world). The runtime replays the *recorded* history, so seeking never runs the simulation.

## How an event becomes motion

The runtime reads each event's deltas in order:

- **Someone's place changes**: they walk to the door, exit, enter the new place, and walk to a free spot. The spot
  is a layout anchor chosen by the world seed, and never one somebody already stands on.
- **Talk, tell, confront, accuse, lend, bark, duel**: the actor approaches to conversational distance and both face
  each other. A duel adds three strikes.
- **A thing leaves a hand** (misplace, drop): contact is the release. The thing lands just behind the body, and an
  unaware owner walks on.
- **A thing is picked up** (take, find): a walk to it, a reach, contact, attach. The part is the right hand, or the
  mouth for an animal.
- **A thing passes between bodies** (give, steal, a duel settling ownership): approach, then hand over and receive
  (or grab).

Who holds what is always the world's own record. The runtime only adds where and when, so it cannot contradict the
world. `check()` returns every disagreement, and it is empty.

## Into production

- `compile_packet(runtime=trace)` gives each directed shot its event's hand-offs (`interactions`) and the instant
  of contact within the shot (`moment`, from the event's motion).
- The cartoon renderer switches the thing from ground to mouth at that instant, not at a fixed 45 %.
- The packet records `runtime_hash`. `make_episodes` builds the runtime for every directed episode.

## The Godot player

```text
godot --path runtime/godot -- --trace=<export.json> --mode=demo      play, pause, seek back, replay, play on
godot --headless --path runtime/godot -- --trace=<export.json> --mode=verify --out=<samples.json>
godot --path runtime/godot --write-movie out.avi --fixed-fps 30 -- --trace=<export.json> --mode=demo
```

The player builds the white-box place (walls, benches, trees as boxes) and the bodies (capsules for people, a box
dog). Then:
- the bodies follow the keys;
- a carried thing hangs at the holder's hand or mouth;
- the camera follows whoever is acting, and between actions keeps the scene's focus framed with the others;
- the HUD shows the playback time and who holds what.

**Proof**
- 814 samples of Godot's playback against `sample()`: largest difference 0.05 mm, which is the rounding.
- The recorded demo (`out/runtime/park_day13.mp4`, 49 s, 1,475 frames, 3.25 ms GPU per frame on the GTX 1080) runs
  day 13 at the park:
  1. The dog walks to Ming's lost wallet and takes it in its mouth (the HUD shows `wallet_ming → dog`).
  2. The playback pauses, seeks back, and replays the same moment to the same result.
  3. It plays on until the dog leaves the wallet by the path.

## Not yet

- **No walking animation or rig.** Bodies glide between keys; the pose name (walk, reach) is in the trace for a rig
  to use.
- **No director camera in Godot.** The Godot camera follows actions. The DirectorPlan's shots (scale, angle, whose
  eyes) are not yet compiled into Godot camera moves.
- **No real paths.** Paths go straight to their goal; nothing steers around a table or a tree yet.
- **Only the playback player is in Godot.** The Director Camera Sandbox (free camera, pause, a POV switch, no
  changes to the world) would be the next step, and Blender or USD export after it.
