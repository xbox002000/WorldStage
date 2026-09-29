# Character dynamics: goals, knowledge and change over time

Written 2026-09-30, from three user briefs:
- goal dynamics and information asymmetry;
- world recipes (see `world_recipe.md`);
- characters as a function of time.

Code: `world/goals.py`, `narrative/knowledge.py`, `world/psyche.py`, `narrative/timelines.py`; tests
`test_goals`, `test_psyche`.

## Goals (schema v4, `goals` table)

- Each person has six fixed goal slots, created with the world. A goal that forms later is a change to an empty
  slot, never an insert outside `apply_event`.
- **States**: active, blocked, abandoned, completed, transformed. The event that records a goal change is labelled
  formed or transformed.
- **Every change is a `goal_change` event** whose parent is its cause, and whose truth carries the reason in plain
  words. For example:
  - Noticing a loss forms `recover`.
  - A denied accusation transforms `recover` into `expose`.
  - A false accusation gives the accused `revenge` or `clear_name`, depending on temper and on how much they have
    come to value revenge.
  - Being caught ends `keep_secret` and forms `make_amends` or `revenge`.
  - Revenge cools after five days.
- **Goals lean the person's own options** (`agent/volition.goal_bias`); they never add an option the world does not
  offer. A choice that a goal pushed up carries `goal:<person>:<slot>` in its reason. That is how
  "thread A's event changed B's goal, and B's goal moved thread C" is found. It counts as a causal crossing in
  `derive_threads`.

## Knowledge (`narrative/knowledge.py`)

- For an item or rumour thread, the town splits into four groups: knows, suspects (unsure but right), wrong (holds
  an answer the world does not support), and unaware (the question concerns them and they hold nothing).
- The audience knows the answer if an event carrying the truth was shown. Dramatic irony means the audience knows
  while someone concerned is wrong or unaware.
- `gap` is the director's asymmetry signal.
- Two world rules make asymmetry real rather than declared:
  - **Honest drift in retelling** (from Talk of the Town): an unsure teller (confidence < 0.7) may bend the act.
    The chance is 0.8 × (1 − confidence). When confronted, it comes out as `misinformed`, not as a lie.
  - **Owners guess only from what they saw.** An owner suspects only from the moment they lost the thing. A bug had
    let owners guess from the later pick-up they never saw.

## Characters over time (`world/psyche.py`)

| Speed | What | Where |
|---|---|---|
| fast | emotion | `people.emotion` |
| medium | relationships, beliefs, goals | relationships, memories/claims, goals |
| slow | adaptive traits (vigilance, cynicism, aggression, withdrawal, trust_default), values (security, truth, belonging, revenge), self-model | `world_vars` psy.<person>.*, changed only by `reflection` events |
| never | core disposition | `personas.traits` |

- **Nightly reflection.**
  - Each person appraises the day's events they took part in or noticed. The categories are betrayal, wronged,
    shame, kindness, hostility, failure and success.
  - Experiences accumulate and fade by 15% a night.
  - Only repetition moves a trait. Values move only after a long run of the same kind of experience.
- **Healing is half as fast as harm, and it scars.** A trait can heal only to rest + 25% of the worst it reached.
  Ordinary warmth does not count as kindness. It counts only when the person was hurting, or when it comes from
  someone they distrust.
- **The self-model forms when a kind of experience crosses a threshold**: "我不能相信別人", "我總是被冤枉的那個",
  "只能靠自己", "還是有人對我好". It softens to half, never to nothing, when the experience fades.
- **The slow layers feed back into what people do next:**
  - how much a listener believes (trust_default);
  - how sure an owner's suspicion is (vigilance);
  - how warm or hostile words are (cynicism, aggression);
  - how much someone keeps to themselves (withdrawal);
  - whether a false accusation breeds revenge (value.revenge).
- **Timelines are read models of the event log**: world, character, relationship, thread. `why_changed(person, a, b)`
  lists every moved trait with the reflections behind it, and the events those cite.

## Sixty days, one world (seed 260931, feed synthetic_v1)

The most changed person is Ming:

| Day | What happened | What moved |
|---|---|---|
| 16 | Tao falsely accuses him of taking the parcel, and his goal fails | self-model "只能靠自己" forms |
| 19–25 | Kai, Ning and Tao keep being hostile to him | aggression +0.06 each time, the value he puts on revenge +0.02 each time |
| 20–27 | Rui is kind to him | withdrawal eases; by day 27 "只能靠自己" softens to half |

By day 60:
- aggression 0.20 → 0.71;
- revenge value 0.10 → 0.28;
- self-model: "只能靠自己" (softened) and "還是有人對我好".

The audit is clean.

Before calibration, ordinary warm chat counted as kindness in a friendly town. It "healed" Kai to total trust
(trust_default 1.0, vigilance 0). That is why only unexpected kindness counts now.

## Experiment C with goals and knowledge (5 worlds × 14 days, ruleset sha256:1d6edd6d88b9)

| Measure | C0 closed | C1 fed |
|---|---|---|
| goal changes per person per day | 0.15 | 0.18 |
| goal-driven causal crossings per world | 1.8 | 3.0 |
| threads born from such a goal, per world | 0 | 0.6 |
| goal transformations per world | 0 | 0 |
| threads with a knowledge gap | 16% | 21% |
| people holding a wrong answer, per world | 2.8 | 10.4 |
| flat days | 7.1% | 1.4% |
| cross-thread rate | 0.36 | 0.38 |

Seed outcomes over the 40 adopted seeds: 1 formed a thread, 8 were delayed, 15 were indirect, 16 were ignored, and 0
were misunderstood. Following the brief, the ignored ones are not treated as failures.

All of this is association under one frozen ruleset, not proof of cause.

Weak spots:
- Goal transformations are still zero. The recover → expose chain needs a true accusation on weak grounds, which
  is rare.
- These numbers were measured before the psyche layer existed. The next experiment should rerun them with it.
