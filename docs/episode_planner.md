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
| **Left open** | after a payoff, the opening the opportunity detector finds, or the hero's next want, or "who looks down on them next"; otherwise a live situation of the same people that goes on beyond the episode; empty when everything is closed, which is reported |
| **Bystanders** | after a face slap, a confession or a seat, with two or more witnesses, a derived beat for the room's reaction (`bystander_shock`) on the same event |

## The web-novel line

For a payoff, six steps are looked for in the world's last 14 days: *belittled* (cold or hostile words to the hero, or a defeat),
*hidden growth* (their training or breakthrough, shown to the audience though the crowd did not see it), *gathering* (an announced
tournament or seat, or three watchers), the *reversal* itself, the *bystanders* (witnesses, voters, those whose view it moved), and the *new state*
(what the reversal leaves behind, read from it). **A step the world did not produce is reported as missing and never invented**; the set-up steps are
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

## v0.2: what a third-party review of the first week said, checked against the code (2026-10-02)

A review of the first fortnight of plans made six claims. Each was checked on the worlds before anything was changed; the planner has an
`Options` record (and `episode_lab.py` runs every variant on the same world, since the planner only reads), so each claim could be measured.

| claim | verdict | what was done |
|---|---|---|
| "A scene's change is the world's delta, not the drama's: a hidden growth changes nothing and is dropped" | **true**, and my first answer (a special case that keeps the set-up scenes of a payoff) was inflating it: of 21 payoff episodes only 14 had a *hidden* growth (the audience ahead of the crowd by 0.30-0.36); in the other 7 the "growth" was a training montage with no gap (0.01-0.03) | a scene's change now has six kinds: state, relationship, emotion, goal, knowledge and **expectation** (the audience ahead: `narrative/audience.py`). All 14 real hidden growths are kept with no special case; the 7 montages are dropped |
| "a thread that exists is not one that moves: the planner kept following a stalled thread" | **true but smaller than it looked**: 4-7 of the 80 thread episodes of a fortnight (5-9%) had only knowledge-passing scenes | a thread in which nothing *real* happened (a feeling, a relationship moved by 0.10 or more, a seat, a goal) is not the day's story; 0 stagnant episodes after, 1-2 quiet days |
| "'will they regret it' is a prediction, not a question a story poses" | **true** (it is the dramaturgy extension's template for every dilemma) | questions are a goal, a choice or a revelation; an inner conflict asks what the choice costs ("要為了忠誠，付出安穩的代價嗎？"); a bare pair asks "和好，還是徹底決裂？"; "regret" questions 11-18 → 0; `question_type` is in the plan |
| "bystanders are half the planner's fault" | **true**: all 7 succession payoffs lacked them because the *voters* are the audience of a vote, and the first version counted only listed witnesses | a vote is seen by those who vote, a duel by those whose view of the two it moved: bystanders 14 → 21 of 21 |
| "the next goal is not an event: make it a consequence (new state)" | **true**: 15 of 21 lacked it because the world seldom logs a hero's new want | step 6 is now `new_state`, read from the reversal (a new standing with others, a seat or skill, a want if one was logged, an opening the opportunity detector finds), present only with evidence; 6 → 21 of 21 |
| "an episode is an A story, a B story and texture; shot variety needs material, not shots" | **true**, and measured | `ab_story`: a second story of other people that moved in the same days, and an ordinary moment before the peak |

**Measured** (episode_lab.py, jianghu_story_v1, 14 days; design on 8 seeds, confirmed on 8 others that were not looked at before):

| | v1 | + narrative delta | + progress, new state, typed questions | + A/B story and texture |
|---|---|---|---|---|
| hidden growth kept (of those with a real gap) | 14/14 and 4/4 (by a special case) | same | same | same |
| stagnant thread episodes | 4 / 7 | 4 / 7 | **0 / 0** | 0 / 0 |
| "regret" questions | 11 / 18 | 11 / 18 | **0 / 0** | 0 / 0 |
| bystanders present (payoff episodes) | 14 / 7 | 14 / 7 | **21 / 14** | 21 / 14 |
| new state (was: next goal) present | 6 / 4 | 6 / 4 | **21 / 14** | 21 / 14 |
| web-novel line complete (payoff episodes) | 5 of 21 / 2 of 14 | 5 / 2 | **18 / 12** | 18 / 12 |
| episodes with one shot intent only | 51% / 53% | 51% / 54% | 51% / 53% | **5.5% / 0.9%** |
| episodes that breathe (a real drop, not just a quiet opening) | 16% / 29% | | 14% / 29% | **59% / 60%** |
| shot intents per episode | 2.07 / 1.86 | 2.01 / 1.76 | 2.08 / 1.91 | **3.03 / 2.88** |
| scenes per episode | 4.5 / 4.2 | | 4.4 / 4.2 | 6.7 / 6.4 |

(two numbers in a cell: the seeds the design was made on / the seeds it was confirmed on.)

**Not adopted, or not yet**: the review's `NarrativeState` layer is built (`narrative/state.py`: the running arcs with how long each has not
moved, who the audience is ahead of, what has been told, who carries most, what is a step from happening) and shown in the control room, but the
planner does not yet read *only* it: its checks are the same functions the state uses, so the two agree, and a rewrite would change nothing measured.
The review's `episode_first` caution is kept: the planner only reads. B stories and texture are in the plan and the control room, **not in what
production films** (a packet is one thread's scenes; composing two stories is phase 8's), so the daily job still plans with the single-story options.

**What this did not fix**: the web-novel line is complete in 18 of 21, not 21: "belittled" is a world problem (3 heroes were never put down on
record). The planner does not invent it. Shot variety rose with the A/B story, which is *more material*, as the review said; episodes are 50% longer.

## The first version on a produced fortnight (`episode_lab.py`: 8 fresh seeds, 14 days, jianghu_story_v1, the greedy producer)

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
