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

## How an event becomes motion (runtime 0.2)

The runtime reads each event's deltas in order. Every body has its own clock: whatever it does next starts when it
is free, so two events in the same minute never make it do two things at once (0.1 did: that was the teleporting).

- **Someone's place changes**: they walk to the door and through it, come in through the new place's door (one body
  at a time) and walk to a free spot: a seat, if one is free (they sit down into it), or a standing spot nobody is
  near, or, in a crowd, open floor at least 0.7 m from everybody.
- **Walking** goes straight when the line is clear, and otherwise along an A* path on a 0.15 m grid round every
  blocking box (grown by the body's radius) and every standing body, pulled tight (`runtime/nav.py`). A body turns
  before it walks off, stands up and steps out of a seat before it leaves, and waits for somebody already on their way
  through the same floor. People's feet are planted on footfalls (`RuntimeStep`), so a presentation's feet cannot skate.
- **Talk, tell, confront, accuse, lend, bark, duel**: the actor walks to conversational distance on free floor and
  both turn to face each other (seated, one turns one's head, not the chair).
- **A thing is picked up**: the walk towards it (targeted), an animal's sniff, the reach, contact, the lift to the
  hand or mouth, attached (`RuntimeActionTrack`). From contact to attached the thing travels from where it lay to the
  socket (pose `lift`), so it is never in two places.
- **A thing is let go**: it falls (pose `fall`) to floor that is not inside a bench, a table or a tree.
- **A thing passes between bodies**: approach, contact, and it travels from the giver's hand to the receiver's.

Measured with `runtime/physics.py` on the 30-second benchmark scene, 0.1 against 0.2:

| | runtime 0.1 | runtime 0.2 |
|---|---|---|
| jumps (faster than 2.6 m/s within a place) | 63 | 0 |
| snap turns (faster than 720 degrees/s) | 86 | 2 (off screen, at path corners) |
| a body inside a wall, table, bench or tree | 52 | 0 |
| two bodies inside each other | 45 | 4 brushes of 0.37-0.39 m (the capsules are 0.44), off screen |
| taking hold of something out of reach | 0 | 0 |

The rule every engine plays (`runtime/export.py:sample_full`, the same in `render/presentation/runtime_rule.js` and
`runtime/godot/main.gd`): walk moves to the next key heading its own yaw (eased at corners); turn holds and turns;
rise and settle move and turn; lift travels to the holder; fall travels to the next key; carried is wherever the
holder is; anything else holds. Playback compresses idle gaps but never a gap inside a walk, a turn, a lift or a fall
(0.1 did, and walks ran at 3.6 m/s).

## Into production

- `compile_packet(runtime=trace)` gives each directed shot its event's hand-offs (`interactions`) and the instant
  of contact within the shot (`moment`, from the event's motion).
- The cartoon renderer switches the thing from ground to mouth at that instant, not at a fixed 45 %.
- The packet records `runtime_hash`. `make_episodes` builds the runtime for every directed episode.

## The Godot player (now optional)

Superseded on 2026-09-30 by the three.js Presentation Runtime (`docs/presentation.md`): one web toolchain renders
and serves as the sandbox, and Blender makes the assets. The Godot player below stays as an optional presentation
backend; its test skips when Godot is not installed.

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

- **Walkers do not steer round each other mid-walk.** A body yields (waits) for somebody already on their way through
  the same floor, and plans round standing bodies; two walks planned into each other later are not re-planned.
- **One flat floor per place.** No stairs, slopes or floors above; the apartment is one shared room.
- **Checkpoints.** The runtime still replays the whole history (about 6 s for 2,000 events with paths).
