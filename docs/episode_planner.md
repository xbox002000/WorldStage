# Episode planner: from what happened to the shape of one episode (phase 3)

`narrative/episode_planner.py`, `contracts/episode_plan.py` (`episode_planner_v0.1`, a draft). Read only: it adds no event and
decides nothing; every beat points at events that really happened.

```text
world history -> choose_material -> classify -> checklist -> shape -> EpisodePlan -> (intents) -> narrative/direction.py -> packet
```

## What it decides

| | |
|---|---|
| **Material** | an unshown payoff of the last day with an earned score of at least 0.25 comes first (the audience has been waiting); then the strongest choice somebody made against themselves (a recorded dilemma of tension 0.4 or more); else the director's best thread, not the pair of the last episodes when there is another |
| **Ladder** | each event on one rung: daily, anomaly, doubt, rising, conflict, choice, irreversible, change (a table by event type and variant) |
| **Tension** | per beat from its rung, the event's heat, its recorded dilemma and importance; the curve of the *filmed* beats; `has_breath` when it climbs, drops and climbs, or opens quiet (<= 0.30) |
| **Scene checklist** | read from the world's own deltas: who wanted what (their goal), who stood against them, who was there, whether the audience sees what nobody on screen knows, how a feeling and a relationship moved, what else changed (a seat, a skill, a goal, a thing), what question it leaves. **A scene in which nothing changed, or nobody is on stage, is not filmed** (it is listed as dropped, with the reason) |
| **Core question** | a payoff: "can they prove themselves / will they be accepted / who will hold the seat"; an inner conflict: the dilemma's own question; else the thread's open question, else the most potent situation the episode stands on, else "how will these two end up" |
| **Reveal** | irony (the audience knows what somebody it concerns does not: from the first beat), mystery (the truth comes later: at the first beat that reveals), or plain |
| **Near miss** | the events of the episode that are a near-discovery in the drama analysis |
| **Left open** | after a payoff, the hero's next want (or "who looks down on them next"); otherwise a live situation of the same people that goes on beyond the episode; empty when everything is closed, which is reported |
| **Bystanders** | after a face slap, a confession or a seat, with two or more witnesses, a derived beat for the room's reaction (`bystander_shock`) on the same event |

## The web-novel line

For a payoff, six steps are looked for in the world's last 14 days: *belittled* (cold or hostile words to the hero, or a defeat),
*hidden growth* (their training or breakthrough, shown to the audience though the crowd did not see it), *gathering* (an announced
tournament or seat, or three witnesses), the *reversal* itself, the *bystanders*, and the hero's *next goal* (their own goal change or
reflection within two days). **A step the world did not produce is reported as missing and never invented**; the set-up steps are
kept in the episode even though they changed nothing yet.

## Shot intents: one closed vocabulary

`ShotIntent` (contracts/episode_plan.py) is what a shot is *for*, in 21 words: the director's twelve functions plus `setup`,
`face_slap`, `bystander_shock`, `longing_glance`, `rival_standoff`, `confession`, `choice`, `aftermath`, `next_question`. The director's
`Function` is now the same type, so there is one list. `plan_direction(..., intents=)` adds an intent to a scene's functions and
`_shots_for` has a neutral recipe for each (scale, angle, relation, motion, subject, what to look at, seconds). Nothing upstream
says "cinematic, 8k": each provider's compiler translates an intent into its own prompt or controls (phase 8).

## In the daily job

`DailyConfig.episode_first` (off by default, because it changes which episode a day makes) lets the planner choose the material
and hands its intents to the director. In every `--world-c` day an `episode_plan.json` is written next to `director_plan.json`. A day's
material with no thread is told plainly (a directed packet without audience-knowledge planning).

## What it did on a produced fortnight (`episode_lab.py`: 8 fresh seeds, 14 days, jianghu_story_v1, the greedy producer)

112 days, 112 episodes (no quiet day).

| | |
|---|---|
| episodes with a core question | 112 (100%) |
| something left open at the end | 110 (98%) |
| a release the audience waited for / a choice against oneself / a running story | 21 / 11 / 80 |
| episodes that breathe | 35 (31%) |
| near miss | 11 |
| scenes dropped for nothing changing, of 609 | 104 (17%) |
| thin episodes (the peak under 0.4) | 9 (8%), all running stories |
| web-novel line complete, of the 21 payoff episodes | 5; missing: next goal 15, bystanders 7, belittled 3 |
| distinct shot intents per episode | 2.07 (57 of 112 use one intent only; `escalate` is 52% of the filmed shots) |
| worlds with an inner-conflict episode in the first 7 days | 3 of 8 |

(The first eight seeds, on which it was built, gave the same picture: breath 37%, 11 inner episodes, 2 of 18 complete lines.)

**What this says, honestly**

- The mechanics hold: every episode has a question, climbs a ladder from real events, and drops scenes in which nothing changed.
- **It cannot make a week that the world did not make.** Most days the director's best thread is a quarrel between the same two people, so
  seven in ten episodes do not breathe and half have a single shot intent. The planner reports that; fixing it is the world's job
  (more kinds of story reaching a thread) and the thread selector's (it does not know the producer's stories; payoff-first was the cure
  for the week of "talk, talk, talk" that the plain ranking made).
- **Inner conflict is rare in this world**: 14 recorded dilemmas of tension 0.4 or more in eight fortnights (2 at 0.5), so the planner's
  threshold is 0.4 (the drama analysis's own) and three worlds in eight have such an episode within a week. The acceptance "at least
  one inner-conflict episode in seven days" is **met only in those three**.
- **The full web-novel line is rare**: 5 of 21. The world seldom records the hero's next want within two days of the moment, and a
  face slap with no earlier belittling (the hero was never put down on record) has no first step.
- Whether an episode is *good* is not measured here. The week of seed 501 is in `out/episode_lab_c/week_seed_501.md`
  (a table per day: question, ladder, intent, tension, who is there, what the scene changed), for episode-by-episode scoring.

Not done: the provider-side translation of intents and the character/scene bible (phase 8); the season grammar (one node per episode,
one arc closed per season) is still the producer's, not the planner's.
