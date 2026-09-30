# A world that runs in its space: Runtime 0.2, the previs stage, shot economy and the God View

Written 2026-09-30, from two user briefs.
- The first, after watching the 47-second three.js version: the white box plays three roles at once (the world's
  space, the actors' motion and the video model's control signal), which is why bodies went through things, jumped,
  slid and took things out of thin air, and the director kept cutting between angles of the same thing. Make it a
  previs stage (collision, navigation, attachment, feet, IK; depth, pose and id passes), and give the director shot
  economy (every shot must add something; "changing the angle" is not a reason to cut).
- The second: the world should live in its space, like a game world watched from above. People walk, find, notice and
  meet because of where they are; the model is only an adviser on high-level choices; the viewer is a god's-eye view
  that can play, pause, rewind, speed up, follow anyone and look through anyone's eyes.

## What was adopted, what was adjusted, what was not

**Adopted**
- A runtime that is a stage, not a renderer: collision proxies, navigation, one clock per body, an attachment state
  machine for things, footfalls, IK for hands and feet.
- Previs passes per shot: RGB, depth, normals, id mask, pose, the camera track, the runtime's actions.
- Shot economy: information, emotion, relation, state and action gains, a redundancy penalty, legal cut reasons only.
- Event -> action phases -> coverage: each shot shows a part of its event's action, in order.
- The camera as a small DSL compiled to a deterministic trajectory that every engine plays.
- A hybrid clock: the world stays event-driven; motion and perception run continuously in the runtime and never
  write the world.
- Space feeding the world: witnesses and finders are decided by what bodies can actually perceive.
- A God View with an inspector (goal, current action, feeling, memories, trust, what they hold, what they can see).

**Adjusted**
- **The simulation stays in Python, not three.js.** The second brief calls three.js the "Spatial World Runtime".
  Browser physics is not deterministic, and a second place that decides where things are would be a second world.
  So the autonomous spatial layer is the Python World Runtime (deterministic, part of the ruleset hash when a world
  uses it); three.js is the God View and the director's stage. It plays the runtime and cannot change it.
- **No micro-tick loop.** Motion is computed in closed form from each event (paths, footfalls, contact times), which
  gives the same result as a 20-60 Hz loop without writing or recomputing anything per tick, and can be sampled at
  any time (seek, rewind) exactly.
- **Space is a primitive (`space.perception`), opt-in per recipe** (`town_spatial_v1`). It changes what happens in
  a world, so existing worlds and their tests keep their history; it becomes the default after a longer rhythm run.
- **Foot contact without raycasts.** The white-box floors are flat, so a footfall is a planted point, not a raycast.
- **Camera DSL without a language model.** LAMP turns sentences into a motion DSL with a model; our director already
  writes structured shots, so the DSL (`static`, `push_in amount`, `pull_out from`, `handheld amplitude rates`,
  `tracking lateral`) is compiled from them by rules.
- **The cancelling-beats rule keeps the later beats**, so the thing ends where the audience last saw it go.

**Not done, and why**
- VACE, ComfyUI or any local video model: the GTX 1080 (8 GB) cannot run them usefully; the previs pack is in the
  format they take, ready for a rented GPU or a paid provider, and the dry-run requests now point at it.
- Faces, fingers, clothing detail: the white box stays unambiguous, not beautiful (the brief's own rule).
- Separate "beautiful" models per style: the scene now carries `visual` and `collision` apart per object, but there
  is one visual set (boxes and the Blender cast).

## Runtime 0.2 (`runtime/world_runtime.py`, `runtime/nav.py`)

Measured with `runtime/physics.py` on the benchmark scene before and after:

| | 0.1 | 0.2 |
|---|---|---|
| jumps (faster than 2.6 m/s within a place) | 63 | 0 |
| snap turns (faster than 720 degrees/s) | 86 | 2, off screen (path corners) |
| a body inside a wall, table, chair, bench or tree | 52 | 0 |
| two bodies inside each other | 45 | 4 brushes of 0.37-0.39 m (capsules 0.44), off screen |

Two causes accounted for most of it:
- two events in the same minute made one body do two things at once;
- playback compressed idle gaps, and a walk with no other key inside it counted as idle, so walks ran at 3.6 m/s.

What 0.2 does:
- one clock per body;
- A* paths round grown boxes and standing bodies;
- seats with chairs, sitting and rising;
- turns;
- a doorway one body at a time;
- yielding to somebody already on their way;
- footfalls;
- and for every pick-up: targeted, sniff (an animal), reach, contact, lift, attached; for every drop: falling to free
  floor.

The rule every engine plays is the same in Python, JS and GDScript. The fidelity check is layer by layer:

| Layer | Result |
|---|---|
| runtime | ok |
| physics | ok |
| presentation | 0.05 mm, yaw 0.00005 degrees, 249 triggers in the same order |
| camera | drift 0 |

## The stage in three.js (`render/presentation/presentation.js`)

- Proper coordinates. 0.1 drew a mirror image of the runtime; the Blender cast also had its sides swapped.
- Feet are IK'd onto the runtime's footfalls, and are planted in front of a seat.
- Hands (a dog's mouth) are IK'd to the contact point. Measured at contact: a person's hand is 2 cm from the thing,
  the dog's mouth 0.6 cm (0.1: the thing jumped from the floor to the hand).
- A lifted thing travels from the floor to the socket; a dropped one falls.
- Every person has their own colour (golden-angle hues over the whole cast), and the trousers take the opposite hue.
- Things have their own silhouettes: wallet, phone, diary, key, watch, ring, ticket, package, sword, cup, letter and a
  plain thing. All 14 Blender files are canonical and pass the Khronos validator with 0 errors and 0 warnings.

## The camera (`runtime/camera.py`)

For each cut: CameraShot -> move primitive -> keys at 10 Hz in the runtime's coordinates.
- The solver asks "can this shot exist?" at the start, the middle and the end of the shot. The camera must be inside
  the room, not in a solid or a body (the subject included), and see the subject past walls, trees and other people.
- If not, it tries 11 turns round the subject, then closer. On open ground it steps back; in a room it goes to a
  camera mount.
- The set-up is fixed at the shot's start: a subject that turns away turns away from the camera.
- On the benchmark: 22 shots, 0 illegal, 13 re-angled or moved back.

## Shot economy (`narrative/economy.py`) and coverage (`runtime/stage.py`)

- **The five gains.** Each shot is scored on information, feeling, relation, a change of hands and action, against
  what the audience has already seen. A shot that adds nothing is cut, and the same picture twice in a beat becomes
  one longer shot.
- **Cancelling beats.** Two beats that undo each other are left out when everything they say is said again later.
- **Cut reasons.** Every cut names what it adds. `attention_shift` is gone, and `FORBIDDEN_CUTS` lists what may
  never justify a cut.
- **Coverage.** Each shot takes a phase of its event's action: an insert takes the contact, the face of the one who
  acts takes the act and after, a payoff takes what follows. Within a beat the shots run forward in time.

| Version | before | after |
|---|---|---|
| A (Ming, mystery) | 10 shots, 31 s | 8 shots, 27 s |
| B (the dog's eyes) | 16 shots, 47 s, ten of them one handheld wallet shot | 6 shots, 25 s |
| C (omniscient) | 11 shots, 35 s | 8 shots, 27 s |

The Director Reality Test still passes all 8 checks.

## Previs Pack (`render/presentation/previs.py`)

Each shot of a version gets its own folder, `shot_NN/`:

| File | What it holds |
|---|---|
| `rgb.mp4` | the picture |
| `depth.mp4` | linear depth, white at 0.3 m, black at 25 m |
| `normal.mp4` | view-space normals |
| `id.mp4` | Kelly colours per entity, the set in greys |
| `pose.mp4` | OpenPose COCO-18 on black |
| `camera.json` | per frame: position, rotation, fov, projection |
| `pose.json` | per frame: every visible person's keypoints |
| `runtime.json` | the tracks, hand-offs and footfalls inside the shot's world slice |
| `meta.json` | the shot, its phase and its camera solution |

`previs.json` is the PrevisPacket: provenance, the palettes, the depth encoding and the shots.
- All passes come from the same scene, camera and clock, so they register pixel for pixel.
- A version at 540x960 takes about 6 minutes.
- `production/dryrun.py --previs` puts the shot's control files into each request.

## A world in its space (`world/space.py`, `runtime/perception.py`)

- With `space.perception`, the simulation keeps a World Runtime playing along. `attention.noticers` asks it who could
  have perceived an act:
  - sight: range 14 m (dog 8 m), a 220-degree field (dog 250), no wall, tree or pillar in between;
  - hearing: a quiet word 4 m, a normal one 8 m;
  - being close and facing it makes an act harder to miss.
- The deciders only offer a thing lying on the floor if one can see it (a dog: or smell it, within 6 m).
- Deterministic and tested: the same seed gives the same world hash, and every witness recorded had a line of sight
  or earshot.
- 20 days, same seed, without and with space (two seeds, small samples, not yet a rhythm result):

| | seed 260934 | seed 3 |
|---|---|---|
| lost things found again | 11 -> 6 | 5 -> 3 |
| overhearers per tell | 1.22 -> 1.08 | 1.40 -> 0.67 |
| simulation time for 20 days | 5.6 -> 16.8 s | 5.3 -> 17.0 s |

## God View (`runtime/godview.py`, `render/godview/`, `channel/live.py`)

```text
python -m channel.live --new 260934 --days 12 --out out/live     # a spatial world, 12 days, served
http://127.0.0.1:8793/
```

- **Playback.** 1x/10x/60x/600x, skipping stretches where nothing moves; pause, rewind 10 minutes, jump to any event.
- **Cameras.** God (orbit a place), follow someone, through someone's eyes (the dog's at 0.47 m).
- **Inspector.** Where they are, what they are doing, feeling, hunger and energy, money, what they hold, whom and what
  they can see (the same sight rule), goals, trust, what they remember and from whom, and why they last did what they
  did.
- **LIVE.** Runs the simulation one more day, with rule decisions only ($0), on the world's own copy, then reloads.
  About 18 s for a day.
- The page cannot write anything; the simulation is still the only writer.

## Acceptance round (2026-09-30, from the user's "prove the white-box world lives" brief)

**The failing test, found, not relaxed.** 405 tests, one failure: the dog's-eyes plan had lost its ground-height
shot (Director layer). Minimal case: misplace, the dog takes it, the owner notices. The shot economy scored the first
shot from the focalizer's height as "nothing new"; the first shot from a viewpoint is now a new relation. One of my own
economy tests had only passed because of that bug (it asserted something was dropped); it now tests the merge rule.

**One body, one thing at a time (`runtime/scheduler.py`).** Every motion books the body's resources: `move` (walk,
turn, rise, sit, reach, hand over), `hands` (the right hand, or an animal's mouth) and `voice`. Walk + talk is fine;
walk + reach is not. A booking that overlaps raises; the runtime resolves conflicts by waiting. `rt.invariants()`
checks the history: exclusive bookings, teleports (a body or thing changing position without a moving pose, or place
without going offstage), speed (no walk faster than the body walks) and sockets (one thing per mouth, one lift per
hand). The world got the matching rule: an animal with something in its mouth cannot take another thing. On both
full worlds (2,045 and 1,300 events) every invariant is 0.

**Three clocks.** World time (events), runtime time (continuous motion), cinema time (a version's slices at 1:1, and a
viewer's playback rate). The scene clock is runtime time shifted, never compressed; the fastest walk on it is the
dog's trot, 1.6 m/s. Verification (JS, Python, Godot) samples at every key instead of every frame, because a scene
now spans the real hours between events.

**Moving bodies avoid each other.** A walk checks everybody's already-planned motion (where they are at each moment,
not where they end up): along the way, while waiting, and while standing at the end. It detours round them, else waits
and plans again; with no way round it squeezes past (0.42 m centre to centre), and never through furniture. Arrivals
wait outside the door, not in it; people stand up only when nobody is walking there. On the benchmark world:
78 yields and 38 detours.

**The apartment is a flat, not a room.** A 2.8 m corridor (for passing, with no standing spot), a kitchen, a living
room and three bedrooms with two beds each. Residents in order take a bed, then the sofa, then the kitchen chairs;
at night (and at the nightly upkeep) everyone goes to their own place.

**Found by the acceptance runs, and fixed (correctness, not polish)**
- A walk through a wall: when every search failed, a fallback returned a straight line. Every path is now checked
  against the solids' own boxes before it is used, and repaired with a search round the furniture if it crosses one
  (12 of 3,802 paths on the benchmark world); the runtime's invariants include `walls`.
- Sitting down from 1.7 m away in 0.6 s (a crowded bedroom): sitting down now takes as long as the shuffle needs.
- Two capability tests failed after the flat was built (Director layer, the 2D spatial plan): the planner's cameras
  looked past furniture but not past people, and it required every witness of a loud act to see it. Now unframed
  people count as occluders, and a loud act's witnesses may hear it from the next room.

**The smoke gate (`spatial_gate.py`, then `spatial_gate_triage.py`).** 3 seeds x 3 days x both recipes, every
place, about 2 minutes. Each run keeps its world (`world_3.db`) and a manifest (seed, recipe hash, ruleset hash,
code hashes). Failures are classified as world, runtime, spatial or presentation.

The first 90-day comparison ran before this gate existed, and it showed that the benchmark scene had been too narrow
a test: the whole worlds still had bodies inside each other, a walk through furniture and snap turns. The gate
reproduced all of them in 3 days. Triage grouped the 36 incidents into four causes:

| Cause | Fix |
|---|---|
| Walking through people when a crowd left no way round (the last-resort path) | Such a path is now "through people"; the walker waits (up to a minute) and plans again. If the crowd is still there, it stops at the crowd's edge (`stop_short`), as one talks across a crowded table. |
| A corner cut through somebody (my own new sliver pruning ignored people) | The pruning keeps its distance from everybody. |
| A path the grid thought clear passing up to 10 cm too close | Every leg is checked exactly against everybody, except the first and last 25 cm. |
| Sub-degree yaw snaps, and a last step of a few centimetres round a sharp corner | Neither happens any more. |

Gate runs 001 to 007: 36, 36, 28, 25, 8, 1 and 0 failing incidents. The gate's rule is written down: bodies closer
than 0.35 m (9 cm into each other) fail it. Shoulders brushing, between 0.35 m and 0.9 of the two radii, is the
recorded known limitation (smoke_007: 4 brushes, the closest 0.382 m).

**Known limitations, recorded and deliberately not optimised this round**
- The closest two bodies came, off camera, on the benchmark scene: 0.391 m (capsules 0.44 m). In other worlds the
  audit finds a few more brushes of 0.36-0.39 m (see the comparison).
- Rebuilding the runtime for the 2,045-event benchmark world takes about 55 s (it was 20 s before the flat, 400 s
  before the path work). This is a baseline, not a failure.

**Next round, not this one.** Profile the rebuild first: scene build, navigation, pathfinding, perception, line of
sight, avoidance, replay, serialisation. Only if navigation dominates, put navigation behind a `NavigationBackend`
contract (`simple_grid` today; `recast_detour` to evaluate) with one canonical simulation: three.js never decides
canonical movement. Recast/Detour is zlib-licensed; if adopted its version and hash go into the toolchain record.

## Not yet

- **Walkers do not re-plan round each other mid-walk.** A body waits for somebody already on its way through the same
  floor.
- **One flat floor per place, and the apartment is one shared room**, so at night the whole building stands in it.
- **The God View shows the world only as it has been simulated.** LIVE advances whole days (the world's own step),
  not continuously.
- **Space is opt-in** until a 30/60/90-day rhythm run with it has been compared with the town without it.
