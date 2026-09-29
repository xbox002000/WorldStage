# Story threads and the story director

Written 2026-09-29. Code: `contracts/thread.py`, `narrative/threads.py`, `narrative/director.py`,
`narrative/ecology.py`, `experiment_c.py`.

## What a thread is

A **StoryThread** is a causal line that is still developing. It is derived read-only from `world.db` at a known
revision. It is an interpretation of history, never a second truth: the same world always yields the same threads,
and nothing is stored that the world could contradict.

| Kind | Key | Gathers |
|---|---|---|
| item | `item:<object>` | misplace, take, find, give, steal, notice_missing, accuse, seed, cash_prize, backstory about the thing, and tells/confronts whose claim is about it |
| debt | `debt:<a>:<b>` | lend and repay between the two |
| rumor | `rumor:<incident>` | tells, confrontations and parrot repeats that trace back to one original event |
| feud | `feud:<a>:<b>` | cold or hostile words and false accusations between the two (at least three) |

One event can sit in several threads, which is how threads cross. For example, a false accusation over a watch is in
the watch's thread and in the feud it starts. Threads also cross causally: an event in one thread whose cause is in
another.

Each thread carries:
- `central_question` (for example "手錶最後會落到誰手上？")
- participants
- all events, and the subset a character chose (`decision_event_ids`)
- first and last day
- status: seeded, forming, active, escalating, climax, resolved, dormant
- stakes, momentum and tension
- `information_asymmetry`: beliefs about the thread that world truth does not support
- `cross_threads`
- `seed_origins`: the external events in it

## The director

`narrative/director.py` answers only "which thread is worth following today". It never answers "what must happen".

- The score is a weighted sum:
  - momentum 0.25
  - tension 0.20
  - stakes 0.15
  - information asymmetry 0.15
  - crossing 0.10
  - novelty 0.10
  - payoff proximity 0.05
- No model judges; a model judge can be tried later as a separate experiment.
- A thread qualifies only if its unshown material contains an act a character chose. A thread made only of rules,
  props and seeds is weather, not story.
- The chosen thread becomes an `Arc`: its newest unshown events, plus its origin for context. That goes into the
  existing SceneSpec pipeline unchanged.
- Tests: following threads leaves the world snapshot unchanged, and a run with the director consulted every day
  ends at the same snapshot hash as a run without it.

## First measurements (Experiment C, 2026-09-29)

Five worlds × 14 days, rule motives only ($0). C0 is the closed town; C1 adds the `synthetic_v1` feed.

| Measure | C0 | C1 |
|---|---|---|
| threads | 33.8 | 40.2 |
| long threads (≥ 3 days, ≥ 4 events) | 11.0 | 15.2 |
| active threads per day | 6.5 | 7.7 |
| cross-thread rate | 0.31 | 0.30 |
| delayed-consequence rate | 0.79 | 0.76 |
| event diversity (kinds of chosen acts) | 7.4 | 8.4 |
| information asymmetry (threads with a wrong belief) | 0.14 | 0.09 |
| relationship flips per day | 2.5 | 2.4 |
| flat-day ratio | 0.043 | 0.014 |
| seed influence rate | – | 0.43 |
| seed direct-plot rate | – | 0.10 |
| goal change rate | 0 | 0 |

These are the numbers after lending was limited (no lending while in debt, not to someone who still owes you, once
a week per person). A first run had shown C1 ahead on crossing (0.32 against 0.20), but that difference was mostly
lend-and-repay noise.

**Reading:**
- The closed town already produces multi-day threads.
- Outside events add more and longer threads, more kinds of acts and fewer flat days. They do not add crossing or
  wrong beliefs.
- One seed thread in ten has no chosen act. Those are pure weather (a parcel nobody touched).
- Weak spots:
  - Information asymmetry is low. Most beliefs end up true, because gossip is mostly truthful and quiet acts are
    rarely seen.
  - Goals never change, because there is no mechanic for it yet.
  - About 57% of seeds lead to no chosen act. A price rise, for example, only shifts scores.
- These numbers measure structure, not whether a person enjoys watching. That still needs the user's eyes.
