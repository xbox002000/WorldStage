# The Observatory: watching stories grow and people change

Written 2026-09-30, from two user briefs: a Story Thread Observatory ("why did this world become what it is?") and a
Character Life / Character Observatory ("who is this person, and why did they become who they are?").

## What it is

- **Read models only** (`narrative/observatory.py`), built from world.db: events, deltas, memories, psyche vars,
  goals, relationships.
  - Nothing in them is truth. Every timeline node, milestone and paragraph carries the event_id it comes from.
  - Building them changes nothing (tested: the world's snapshot hash is the same before and after).
- **The God View carries them** (`runtime/godview.py` puts them in the save). Its page is laid out around the world:
  - the world on top;
  - the clock and controls;
  - under them the story list, the selected story and the selected person.
- **Experiment retention.** `spatial_gate.py` and `spatial_compare.py` keep the world at every checkpoint
  (`world_<day>.db`) with a manifest: seed, recipe hash, ruleset hash, code hashes. A story found in a metric can be
  opened again as a world.

## Story Observatory

- **The list.** Each thread shows:
  - its status (seeded, forming, active, escalating, climax, dormant, resolved, and *revived*: slept three days or
    more, then came back);
  - its days, events, tension, misunderstandings and crossings.
- **The selected thread.**
  - *Why this story exists*: its origin event, the main drivers (relationships souring, uncertain beliefs,
    accusations, things changing hands, retellings), the principals and who else it touched, tension and asymmetry,
    the last meaningful event, the latent pressure (the principals' open goals about each other or the thing), and
    the threads it crosses.
  - *A timeline by day.* Each event shows its place, its cause (parent or incident), why it happened, trust changes
    (before and after), feelings, goals, things changing hands, and what each person came to believe (with
    confidence and source).
  - *Follow story*: the view goes to each event of the thread in turn, a few seconds each at 1x. It never runs the
    world; it plays the recorded runtime.

## Character Observatory

Six tabs:

| Tab | What it shows |
|---|---|
| Now | place, action, feeling, what they hold, whom they can see, open goals |
| Life | a lifeline of milestones, each clickable |
| Psychology | traits (slow) against their resting value, values (very slow), self-model statements held, scars (a trait pushed past rest: how far, the floor healing can reach, the event it began with), the core temperament (never changes) |
| Relationships | trust, affection and fear, with a line of how trust moved |
| Knowledge | what they believe, how sure they are, who told them, and whether world truth agrees |
| Biography | compiled from the milestones; each paragraph cites its events and jumps there |

**Milestones.** The psyche's own reading of what a day meant to someone is the source:

| Kind | From |
|---|---|
| betrayal, being wronged, shame, kindness, hostility | the psyche's appraisal of the day |
| loss, discovery | things taken, lost and found |
| goals | a goal formed, transformed, abandoned or completed |
| identity and value shifts | a reflection that formed a self-model statement or moved a value |
| turning points | trust changing sign |
| first times | the first time someone does an act |

Significance is the kind's weight plus the event's importance. Below 0.6 an event stays out of the life.

**Clicking a thing** shows its world truth (who holds it) and what everybody believes about it.

**On the world** (God View):
- names, with semantic level of detail;
- the selected person's trail over the last 90 seconds;
- a pulse where an event just happened;
- a ring under the selected story's principals;
- walls on or off;
- a top view;
- follow, and through someone's eyes.

## What it showed at once

On the live world (13 days, 1,300 events, 112 nightly reflections), no one's traits, values or self-model moved at all.
- The psyche does accumulate experiences (Ming: betrayal 0.38, kindness 0.84, success 0.82).
- A trait moves only when an experience keeps happening: the accumulated weight has to reach 1.5, and it decays to
  0.85 of itself every night. Sparse experiences never get there in two weeks.

This is not a bug. It is the character-change layer's parameters, and it is the user's decision whether people
should change faster.

## Not yet

- **Hand-written identities.** No birth year, family or childhood: the world has personas (temperament), a life
  goal, a home and backstory events, and the Observatory shows only what exists.
- **Appraisal and scars as data.** They are still the psyche's rules: appraisal by role in the event, scars as the
  worst value reached. There is no explicit scar record with triggers, and no leap changes on a single major event.
- **A graph of relationships**, and a "life A against life B" comparison of parallel worlds.
- **Replay only within the save.** Follow story and clicking a node only move the stage inside the save's days (the
  last 30); older events are still in the Observatory.
