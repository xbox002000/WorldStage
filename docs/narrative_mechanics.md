# Narrative mechanics

Written 2026-09-29, from the user's proposal to add pluggable narrative mechanics: rebirth, transmigration,
"system" stories, mystery and politics as executable machinery, not prompts.

## What is adopted

- **Mechanics are separate from style.**
  - A `NarrativeMechanicPack` decides how a story works.
  - The `StylePack` decides how it is shown (hook, pacing, look).
  - Same world, different pack: a different kind of story.
- **A mechanic is code with a narrow interface, never a prompt line.** It works only through what the kernel already
  guarantees:
  - events through `apply_event`;
  - beliefs as claims;
  - choices as Intents that a validator judges;
  - consequences decided by rules.
- **Three kinds:**
  - **world**: changes the world's rules for everyone (for example a time loop or a curfew);
  - **character**: gives some people knowledge or abilities others lack (rebirth, a system, a hidden identity,
    foresight);
  - **constraint**: changes what counts as a story and how the director scores it (mystery, romance, revenge).
- **Event sourcing makes time mechanics honest.** Rebirth never rolls `world.db` back. It forks:
  - A new timeline is rebuilt deterministically up to the fork day. The same seed and the same recorded decisions
    give the same world.
  - One person then wakes up holding memories of the first timeline.
  - The fork event records the parent timeline's snapshot hash, the fork day and the protagonist.
- **A system never changes world truth.** It issues quests, checks them against world events, and rewards with what
  the world allows, such as a true piece of information. The character still has to act, and the world still
  decides what that act causes.

## What is adjusted

- **The interface is smaller than proposed.** It has five hooks:
  - `on_world` (initial conditions, as events)
  - `on_dawn(day)`
  - `options(actor)` (extra choices a character has)
  - `bias(actor, options)` (how the mechanic shifts motives)
  - `after_event(event)` (check quests, record rewards)

  `transform_state` is left out on purpose: nothing may change state except an event.
- **Constraint mechanics live on the production side.** "Mystery" does not decide that the culprit is someone else.
  It makes the director prefer threads with a hidden culprit and a wrong suspect.
  - A mechanic may set up a different truth only at world creation, as backstory, never during a run.
- **Abilities are data.** Foresight is the list of known future claims with their source. Mind reading is
  permission to read some beliefs, with range and cost.
  - Both reuse claims, so world truth, a character's belief and what a mind-reader sees can all differ.
  - Not built yet.

## What is built now

**`rebirth`** (character mechanic, `world/mechanics/rebirth.py`):
- It runs timeline A.
- It rebuilds timeline B to the fork day.
- It gives the protagonist the important things they knew in A that had not happened yet. These are memories
  marked `（上一世）`, with source `prior_life:<timeline hash>`.
- In B the protagonist:
  - goes where they remember an opportunity;
  - is colder to people who wronged them in A;
  - may warn others.

  A warning is a claim about something that has not happened in B. If someone acts on it, the world judges it
  against B's truth, so a prophet can be wrong, and a warning can prevent what it foretells.

**`system`** (character mechanic, `world/mechanics/system.py`):
- A rule layer only the protagonist sees.
- Quests are drawn from the current state: get a debt repaid, recover something that is yours, win someone's trust.
- Progress is checked after each event.
- The reward is a true claim the protagonist could not otherwise know, for example who really holds a missing item.
  It is marked as coming from the system.
- The protagonist's motives lean towards quest progress. The quest never forces anyone else.

## Later candidates

These are in order of how well they reuse what exists:
- transmigration: an identity layer (soul vs body; others notice someone "is not themselves");
- foresight;
- mind reading;
- factions: groups, leverage and loyalty;
- a mystery constraint for the director;
- romance: attachment as a relationship mechanic;
- a time loop: a world mechanic that forks every N days.
