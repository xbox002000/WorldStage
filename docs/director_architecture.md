# Director layer

Written 2026-09-30, from the user's brief on a director that decides what the audience experiences before the camera
decides how to shoot it. Code: `contracts/director.py`, `narrative/direction.py`, `narrative/knowledge.py`; tests
`tests/test_direction.py`. `daily.py --world-c` writes `director_plan.json` next to each episode.

## Audit (before this change)

- The "director" picked a thread (`narrative/director.py`). The compiler then made one shot per beat from a fixed
  table of event type to shot size (`narrative/compiler.py`).
- Nothing said why a shot exists. Nothing planned what the audience knows, and there was no point of view. Cuts had
  no reasons; the audio plan was separate and knew nothing of the drama.
- World C's acts (take, accuse, give, lend, the parrot ...) were missing from that table, so they all fell back to a
  neutral wide shot. They are in the table now.
- The SpatialPlan already staged four cameras per beat (wide, two-shot, over-the-shoulder, insert), but nothing
  chose among them for a dramatic reason.

## The chain now

```text
StoryThread ─▶ SceneSpec (what happened) ─▶ DirectorPlan (how the audience lives it) ─▶ ProductionPacket ─▶ render
                                                 │
            knowledge ─▶ focalization ─▶ dramatic beats ─▶ camera language ─▶ edit ─▶ sound
```

Each decision feeds the next, and each carries its reason:

1. **AudienceKnowledgePlan.** The strategy is irony (the audience sees what the person concerned does not), mystery
   (the audience does not know either; the culprit's face is withheld until the exposure) or plain.
   - It is read from the thread's knowledge (who knows, who is wrong, who is unaware) and from what earlier episodes
     showed.
   - It is never declared by a "mystery mode": the world has to contain the asymmetry.
2. **FocalizationPlan.** The focalizer is separate from the camera. By default it is the person the question
   concerns who is most in the dark.
   - `in_scope`: beats the focalizer was physically at.
   - `audience_only`: beats shown anyway under irony.
   - POV transitions: when the focalizer was absent and a witness saw it, the view passes to the witness and back.
     A character can carry information for the audience.
3. **DramaticBeat functions**: orient, reveal, hide, escalate, misdirect, payoff, connect, isolate, foreshadow,
   contrast, observe, with a note in plain words.
4. **CameraShot (camera language)**:
   - scale: EWS … ECU and insert;
   - angle, relation (frontal, over-the-shoulder, two-shot, subjective …), motion, speed;
   - subject and attention (eyes, hands, object, space);
   - which SpatialPlan camera stages it;
   - the function and the reason.

   Examples:
   - a reveal is a slow push-in on the face that learns, or on the one who did it when only the audience learns;
   - a hidden act is hands and an object, not a face;
   - a false lead holds steady on the wrongly suspected.
5. **Cut**: open, attention shift, reaction, information reveal (a smash cut in a mystery), time jump (dissolve),
   location change, causal continuity, and a final hold.
6. **SoundCue**:
   - silence before a reveal and a sting on it;
   - tension while the audience knows and a character does not;
   - release on warmth;
   - muffled dialogue in a point-of-view shot.

The plan points only at events of the scene, is deterministic and hashed, and reads the world without writing to it.
The tests check all four.

## Adopted, adjusted, not adopted

- **Adopted:**
  - Director ≠ camera planner.
  - SceneSpec and DirectorPlan are separate.
  - Focalizer ≠ camera.
  - Every shot has a dramatic function.
  - Every cut has a reason.
  - Sound belongs with point of view.
  - Camera language is structured data, not prompt text (the lesson of LAMP's motion DSL).
  - Framing is relative to a subject (Auteur).
- **Adjusted.** Ten proposed contracts became one `DirectorPlan` holding typed parts. "CoveragePlan" is the list of
  shots per beat; "CameraLanguage" is the vocabulary of `CameraShot`.
- **Not adopted.** No external project enters the core. LAMP, ShotDirector, GEN3C or a video model would be
  adapters behind the capability layer, reading `CameraShot` and the SpatialPlan.

## Not done yet (honest list)

- **The ProductionPacket does not read the DirectorPlan yet.** The packet still has one shot per beat from the table.
  Making the compiler consume the plan changes what the shot route renders, and the shot route belongs to the
  capability-layer work. That integration is the next step, and it should be done in one place.
- **A dog's point of view.** The contract allows an animal focalizer, but the dog in the world is an object: it
  cannot perceive.
  - The next primitive is a perceiving animal. It would have a sight height and field, hearing and smell, and no
    language: it would hold "a shiny thing, raised voices, a stranger's smell", not claims.
  - Until then, only people can focalize.
- **Model help.** A model could write the note of each beat, or propose an alternative strategy, but the rules
  decide. Not built.
- **In the first 20 daily picks of a 60-day world:** 16 plans were plain, 2 irony, 2 mystery. Most threads have no
  one in the dark. That is a property of the world, and the next information work should raise it through world
  rules, not through the director.
