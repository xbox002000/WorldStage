# Domain packs and character profiles: how a new genre or area of life enters

Written 2026-10-01. The user asked for this so that wuxia, magic or anything else can enter quickly, instead of
being built by feeling one's way.

## The problem it solves

Before this, jianghu (martial arts, duels, sects) was spread over about ten core files:
- **world/**: the action list, validation, resolution, the simulation loop, goal review;
- **agent/**: the rule agent's scoring and the options it perceives;
- **runtime/**: the staging;
- **narrative/**: the compiler's beats, the director's functions, lines, the Observatory's firsts, the God View's
  verbs.

A second genre would have touched them all again.

Now the core names no genre and no area of life. It asks one registry (`world/domains/__init__.py`), and a genre is:

```text
world/domains/<pack>.py                  the rules: actions, motives, consequences, life state, goals, how events look
world/content/<content>.py               places, people, things, schedules, backstory      (as before)
world/content/profiles/<content>.json    who the people are: CharacterProfile (contracts/character.py)
world/recipes/<recipe>.json              which primitives this world runs
```

Nothing else changes. `tests/test_domains.py` proves it: a magic pack written inside the test, registered at run
time, runs in a world without one line of the core being edited.

## What a domain pack can declare

`world/domains/base.py`. Every hook is optional and deterministic, and none writes the world except by returning
events or changes.

**Declarations:**

| | |
|---|---|
| `primitives` | its recipe primitives, added to the library (a recipe switches the pack on by naming one) |
| `actions` | `ActionSpec(name, validate, resolve, targets_person, conflict)` |
| `acts` | claim acts it adds (`ClaimAct(family, object_kind, affirm, deny, belief_effect, distortion)`): they can be told, believed, lied about and judged like any other |
| `styles` | per event type: caption, lines, staging (social, say seconds, strikes), beat, describe, story functions, first-time milestone, heat, whether it opens a scene others may answer, explain text |
| `goal_text` | the goal kinds it adds |

**Hooks for the rule agent:**

| | |
|---|---|
| `options(conn, actor, now, ctx)` | choices it offers, scored |
| `shape(conn, actor, now, scored)` | the last word before the pick (a talk gets its topic) |
| `lean(conn, goal, intent)` | how its goal kinds push options |

**Hooks for the world:**

| | |
|---|---|
| `effects(conn, spec, primitives)` | what it adds to any event (a day's work wears on one) |
| `after_event(conn, event_id)` | consequences as further events (a demand to stay late) |
| `dawn(conn, day, now)` | events at the start of a day |
| `scripted(conn, intent, now)` | keep, change or drop a routine step (kept late: no trip to the park) |
| `overnight(conn, pid, now)` | life state that moves in one's sleep, folded into the upkeep event |
| `nightly(conn, day, now)` | events of the night (a goal born from how life is going) |
| `review_goal(conn, goal, day)` | judges its own goal kinds |
| `initial_vars(pid, profile)` | the life state a person starts with |

**Read models:** `describe(conn, pid)` returns this person's life state in the pack, for the Observatory and a
character's own prompt.

`add_changes(conn, spec, extra, memories, claims, truth)` folds a pack's consequences into an event correctly. A
field the event already changes gets one summed change, because event_deltas has one row per event and field.

## Character profiles

`contracts/character.py` defines a CharacterProfile:
- identity: name, age, gender, background;
- an occupation: the domain that runs it, role, place, superior, duty, words;
- interests and dislikes, as content topics weighted 0..1;
- values;
- habits: when, do, label;
- a social style, including a conflict style;
- an inner core: want, fear, wound, false belief, need, life question;
- a life goal and a season goal.

A CharacterRoster is a content pack's cast and topics. `check_roster` refuses unknown topics or values, weights
outside 0..1, duplicates, and liking and disliking the same thing.

It is stored in the world (schema v5: `character_profiles`, `content_topics`). The world is written once, before
any event, and never changed (triggers refuse it). What life changes is adaptive state that events move: world_vars
(`taste.<pid>.<topic>`, `work.stress.<pid>` ...), goals and relationships. So a world replays without the content
files, and a profile can never be rewritten behind the history's back.

Genre-free by construction:
- topics are the content's own words (釣魚 or 劍法);
- an occupation names the pack that runs it and gives it words (上班/加班/辭職, or 練功/加練/離開師門);
- a superior can be an offstage name (主管) or someone in the world (師父林遠山), in which case the demand is a
  scene he is in.

## Character agents: minds that wake when life asks

`agent/cognition.py`, `contracts/cognition.py`.
- **Everyone lives by the rule agent** (routine, motives, the packs' options), so a world costs nothing to run.
- **A CharacterAgent wakes a mind** (an LLM, or any outside agent framework) only at a wake point:
  - an offer to answer;
  - a decision made today;
  - a strong feeling;
  - a clash among the three things they most want to do;
  - someone present who did something serious against the value they hold dearest.
- **The mind gets a CognitiveState:**
  - who I am, my inner core, my values, habits, feeling and life in each pack, my goals, where I am;
  - the people here as I see them (trust, affection, fear, the tastes I have learnt);
  - my memories as I believe them;
  - the numbered options the rule agent found possible.
  - It contains nothing the person could not know.
- **It answers with a CognitiveChoice:** a number, a reason, and an inner thought. It cannot invent an action, a
  target or a fact, and the validator and the rules still decide what happens.
- **Every pack's actions reach the mind automatically**, because the options are the rule agent's own list.
- **Limits and fallback:**
  - a daily budget caps wake-ups (about 4-5 a day for ten people, measured);
  - without a client, over budget, or on a broken answer, the rule agent decides (tested: a broken mind leaves the
    world exactly as no mind would);
  - the LLM client caches by request hash, so a world with minds replays exactly.
- **Contracts:** JSON Schemas for CharacterProfile, CharacterRoster, CognitiveState and CognitiveChoice are in
  `contracts/schemas/`. An outside tool can author a cast, or play a character, from those alone.

## Packs today

| Pack | Primitives | What it does |
|---|---|---|
| martial | martial_arts, reputation, duel, sect_factions | jianghu, moved out of the core unchanged (fingerprints of town_v1, jianghu_v1 identical before and after) |
| topics | social.topics | talk has a topic: shared tastes and grudges bond, a bad moment spoils it, people learn each other's tastes |
| work | life.work | stress, satisfaction, a superior's demands and praise, a quiet job search, an offer, resigning, a renewable goal to leave |

## Adding magic, concretely

1. **Write `world/domains/magic.py`.** It needs:
   - a primitive `magic` (layer "power");
   - an action `cast`: validate that the caster has the mana and the target is here; resolve to a `spell` event
     that costs mana and changes the target (fear, a hex var);
   - a claim act `hex` ("對{o}下了咒"), so it can be witnessed, told and denied;
   - a style for `spell`: caption, lines, social staging, heat 3, and opens_scene so the victim answers;
   - options that score casting from temper, rivalry and mana;
   - nightly mana regeneration.
2. **List it in `BUILTIN`** in world/domains/__init__.py, so its code is part of the ruleset hash.
3. **Write the content:**
   - `world/content/magic_v1.py`: places tagged for study, people, things;
   - `world/content/profiles/magic_v1.json`: the cast, with an occupation of `{"domain": "work", "role": "學徒",
     "superior": "<master id>", "duty": "study", "words": {"quit": "離開學院"}}`. Work comes for free.
4. **Write a recipe** that names `magic`, `life.work`, `social.topics` and `social.exchange`.

Exchanges, lasting feelings, topics, work, goals, gossip, claims, the runtime, the God View, the Observatory and the
Dramaturgy analysis all work with it unchanged.
