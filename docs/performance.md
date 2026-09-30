# Performance, attention and cinematic grammar

Written 2026-09-30, from two reviews of the Director Reality Test:
- "the director exists, the actors do not";
- "it looks like a debug view, not a film".

Code:
- `contracts/performance.py`, `narrative/performance.py` (performance);
- `narrative/grammar.py` (grammar, attention, pacing, edits);
- `render/cast/` (the cinematic render mode);
- `benchmarks/director_reality_v2.json`.

Tests: `tests/test_performance.py`, `tests/test_director_reality.py`.

## Where it sits

```text
StoryThread -> SceneSpec -> DirectorPlan -> PerformancePlan -> ProductionPacket (v5) -> render
                            knowledge, focalization, beats     how each body plays it
                            grammar, attention, camera, edit, sound
```

- **The DirectorPlan** decides what the audience should notice.
- **The PerformancePlan** decides how each body in frame embodies its state.
- **The camera** decides how that is captured.

A close-up of Ming is the same camera for fear, held anger or pretended calm; the performance is what differs.

## Performance is derived, never chosen

`plan_performance` reads the world as of each event (from the deltas, the world's own history). For each character
in frame it builds:

1. **State**
   - their emotion;
   - trust, affection, fear and rivalry toward whoever is involved;
   - what they believe about them (for example, a memory that someone took their thing, unless a later memory
     cleared them);
   - their goals and slow traits (vigilance, aggression, withdrawal);
   - what they hold, and whether it is theirs.
2. **Drives** (0..1), each with causes that point into the world, for example `trust:ming->kai=-0.42`,
   `memory:812`, `event:1213:notice_missing`. The drives are fear, resentment, suspicion, guilt, distress, relief,
   attachment, curiosity and self-protection.
3. **Primary state.** Resentment that low aggression does not release becomes *restrained anger*. Self-protection,
   or fear mixed with resentment, becomes *defensive*.
4. **Intent**: go on (unaware), search, conceal, recover, confront, defend, watch, avoid, reach out; for an animal,
   investigate, lose interest or follow.
5. **Channels**
   - gaze: hold, avoid, scan, down or follow, and at whom;
   - posture: tension, openness, lean;
   - hands: search, point, grip, hold or fidget;
   - face: brows, jaw, mouth, eyes;
   - micro-actions: glance away, swallow, jaw clench, pat pockets, look around, exhale;
   - movement and speech delivery (restrained, short, soft, with a pause before answering).

   A dog has ears, tail, head tilt and pace instead, with sniff, head tilt, look back and freeze.
6. **Continuity**: the body state carried into the next shot (what is held and in which hand or mouth, the gesture,
   the gaze, the emotion). Any change names its cause.

`continuity_breaks` finds unexplained jumps:
- a thing appearing in or leaving a hand without an event;
- an emotion changing without a drive;
- a dog given a voice.

`uncaused` finds any state that is not calm but has no drive, and any drive without a cause.

**A counterfactual** is how a benchmark asks "what if Ming trusted Kai less". It changes the *state* in step 1 only;
the rules after it are the same. The plan records it, and its causes are marked `counterfactual`. So "three
different performances of the same shot" never means three invented expressions.

**Profiles** (`PROFILES`) say which channels a kind of body has: `human`, `dog`. Cats, robots and birds have no world
rules yet, so they have no profile. There is no special renderer for the dog: it is the same interface with a
different profile.

**Whose eyes we are in changes what is shown, heard and understood; it never changes how anyone acts.** The test
compares every shared (beat, person) across Ming's view, the dog's and the omniscient view: they are identical.

## Cinematic grammar is not style

A **StylePack** is how a whole channel looks and sounds. A **cinematic grammar** is how one kind of information is
usually released:

| Grammar | Used for |
|---|---|
| `conceal_reaction_reveal` | a mystery |
| `show_follow_payoff` | irony |
| `pov_insert_reaction_silence_reveal` | a witness's or an animal's eyes |
| `establish_observe_isolate_payoff` | plain telling |

Every shot is labelled with its grammar step and its **information function**: orients, shows_truth, withholds,
misleads, hints or confirms. Together with the dramatic function, the camera language, the cut reason and a
**sound anchor** (the thing's motif, a breath under fear, room tone when held), no shot is there without a purpose.

## Pacing, attention, controlled release

- **Pacing.**
  - The shots that establish run long.
  - The run-up to the turn gets shorter: ×0.7, then ×0.8, then ×0.9.
  - There is a held breath just before the turn (×1.4).
  - The reaction is allowed to stay (×1.35).
- **Edit variants** a benchmark can force:
  - `tight`: cut as soon as the point is made;
  - `hold`: a second longer where it lands;
  - `reaction_first`: the face that learns comes before what it learns.
- **AttentionPlan.** Shot by shot, it records the primary thing to look at, what is there for whoever looks, and
  what is kept out of sight.
- **Controlled release.** In a mystery the truth is let in once, by what the camera finds and never by words. In the
  wallet story: after Ming has the wallet back, the camera finds the dog close by and stays. The dog really was
  there (it was sensed in that event); the shot adds nothing the world did not contain.

## The cinematic render mode

`render/cast/packet_script.to_script(mode="cinematic")` is the default. It removes everything the engine knows but
an audience should not read: the time stamp, variant labels, narration boxes, thought panels, and the shot function
line. Debug mode keeps all of them.

In cinematic mode:
- **A belief** is a picture in the mind: a brief desaturated flash of the suspect's face while Ming searches.
- **An animal's eyes**
  - The view is wide and low. People tower, their faces out of frame.
  - Smells are drawn as drifting trails in the colour of whose they are; the wallet carries Ming's.
  - Attention jumps from one smell to the next and back.
  - The dog's own snout and what it carries are at the bottom of the view.
- **Bodies act.**
  - The eyes follow the gaze plan.
  - The body leans with the posture.
  - The micro-actions happen at their moments: pats of the pockets, a look around, a jaw clench, a swallow, an
    exhale, sniffs, a head tilt, a look back.

## Director Reality Test v2 (packet-level; the architecture questions)

`python director_reality.py --bench benchmarks/director_reality_v2.json --out out/reality_v2`. Results:

| Check | Result |
|---|---|
| Performance changes with character state (trusting / fearful / resentful), camera and edit identical | PASS |
| Camera changes framing, not acting (observational / push-in / reaction / subjective) | PASS |
| Edit changes timing, not acting (tight / hold / reaction-first) | PASS |
| Sound changes with the telling (A / B / C) | PASS |
| Focalization changes what the audience can know (witnesses the act: A no, B yes, C yes) | PASS |
| Whose eyes does not change how people act (12 shared beat-person pairs identical) | PASS |
| World snapshot hash unchanged by all planning | PASS |
| Performance continuous and caused, in every variant | PASS |

For Ming, discovering the loss:

| State | Performance |
|---|---|
| Trusting Kai | distressed, scanning, patting his pockets |
| Fearing Kai | defensive, eyes avoiding, fast breath |
| Resenting Kai (low aggression) | restrained anger, a held stare, jaw clench, a swallow |

## Honest limits

- **The cartoon's range.** Its faces have 15 expressions and its arms 6 poses. The performance plan says more than
  the 2D stage can show (jaw, brows and lean are approximations). The plan is written so that a 3D rig or a video
  model can play it in full; that is the point of keeping it provider-neutral.
- **No voices.** The town's events have no spoken lines, so speech delivery is planned but never heard.
- **A naming convention.** The owner a thing smells of is taken from the object id's suffix (`wallet_ming`).
- **Sound.** Sound anchors are planned per shot. The synth plays the music cues, but the motif and breath anchors
  are not yet sounds of their own.
