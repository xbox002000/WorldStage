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

## Into the packet: the A story, the B story and the ordinary moment are filmed (2026-10-02)

Until now the B story and the texture existed only in `episode_plan.json` and the control room; a packet was one thread's scenes. Now
`DailyConfig(episode_first=True, episode_ab=True)` (both off by default) films them. Files: `production/episode_packet.py`,
`contracts/episode_packet.py` (`EpisodePacketMap`), `episode_packet_lab.py`, `tests/test_episode_packet.py`.

```text
Options(ab_story=True) -> Material (A arc, B arc, texture) -> compose(): plan -> filmed beats, in the plan's order -> one arc
  -> SceneSpec -> DirectorPlan (each beat's intent added to its functions) -> ProductionPacket   +   EpisodePacketMap beside it
```

- **The compiler is not touched.** The packet is what `compile_packet` always made from a SceneSpec whose beats are the plan's filmed beats
  (A, B and texture, in the plan's order: by event id, so the story lines interleave as they happened). Every shot's `function` is one
  word of the closed `ShotIntent` list and its `intent` text starts with it ("escalate: pressure closing in"); a test scans all of them
  for model words (cinematic, 8k, lens, ...) and finds none.
- **Which beat and which story line a shot belongs to is in a map beside the packet, not a field in it**: `episode_packet_map.json`
  (packet hash, plan hash, per shot: beat index, story A/B/texture, intent, event; per beat: how many shots it got; what was cut and why).
  *This deviates from "the packet records it"*, and the reason is the byte-for-byte requirement below: any field added to `Shot`
  changes every packet's bytes, the schema and `PACKET_VERSION`. A provider's compiler reads packet and map together by `packet_hash`.
- **The beats the plan does not film are not filmed**: a scene in which nothing changed (the planner's rule) used to be filmed anyway when
  the daily job followed a plan (it filmed the whole arc and passed intents only for the changed scenes).
- The reaction beat (`bystander_shock`) is told after the beat it reacts to. (The first version of the daily job built `{event: [intent]}`
  with a dict comprehension, so an event with two beats kept only the last intent: face_slap was replaced by bystander_shock. That
  happens to 27 events in the 111 episodes below. `episode_first` without `episode_ab` still does that; it was left as it was.)

### Length: there was no budget, so there is one now

Nothing in the code limited an episode's length (an episode was as long as its scenes). More scenes need a limit, and it should be anchored
to what is filmed today, not to what the A/B episode turns out to be: **`BODY_SECONDS_BUDGET = 30 s` of shots** (the title card, the recap
and the ending are the style's, about 5 s more). Today's longest single-story packet over the 8 seeds is 29 s (thread director) and
30 s (planner). Rule, when an A/B episode is over it: **cut the texture first; then the B story's earlier scene; then the rest of the B
story; the A story is never cut** (if it alone is over, the map says `over_budget`; that never happened in 111 episodes). A cut is made by
planning the episode again without those scenes, so the curve and the breath in the plan are those of what is filmed; the map's `trimmed`
lists what went and why, and `source_plan_hash` names the uncut plan. Tests: texture goes first, B only after texture, the earlier B scene
before the later, A is never cut, within the budget nothing is cut.

### Measured (episode_packet_lab.py: seeds 501..508, jianghu_story_v1, 14 days, greedy producer, no spatial runtime)

Each arm tells its own fortnight (its own memory of what it has shown). `off` = the thread director's pick (today's default), `first` =
`episode_first` with the single-story planner (what the daily job does with that flag), `ab` = `episode_first` + `episode_ab`, shown with
no budget and with the 30 s budget. Only packets were compiled; nothing was rendered.

| 112 days | off | first | ab, no budget | **ab, 30 s** |
|---|---|---|---|---|
| episodes | 112 | 111 | 111 | **111** |
| shots per episode (mean / p90 / max) | 7.1 / 10 / 13 | 7.5 / 10 / 12 | 10.1 / 13 / 17 | **9.6 / 12 / 14** |
| seconds of shots (mean / p90 / max) | 16.6 / 24 / 29 | 18.4 / 24 / 30 | 24.2 / 33 / 43 | **23.2 / 29 / 30** |
| episodes over 30 s | 0 | 0 | 17 (15%) | 0 |
| distinct shot intents in the packet (mean) | 3.29 | 3.94 | 4.54 | **4.41** |
| packets with a single intent | 0 | 0 | 0 | 0 |
| packets with two intents or fewer | 6.2% | 4.5% | 0% | 0% |
| share of `escalate` among the shots | 39% | 34% | 37% | 37% |
| distinct intents of the *plan's beats* (mean) | n/a | 2.05 | 3.03 | **2.89** |
| plans whose beats have a single intent | n/a | 48.6% | 3.6% | **7.2%** |
| dry-run, every shot a model would want, kling_3_pro (USD, nothing sent) | 2.55 | 2.42 | 3.51 | **3.40** |

Of the 111 A/B episodes: 84 film a B story (88 had one planned), 82 film texture (100 planned); of the 1070 shots, 667 are A, 282 B and
121 texture (seconds per episode: A 14.9, B 5.7, texture 2.7). 18 episodes were trimmed (texture in 18, B as well in 10); the A story was
never cut. 69 of 681 filmed beats (10%) got no shot from the director's shot economy; they are in the map with `shots: 0` and a note.

### What did not hold

- **"Single-intent packets" was never a packet problem.** The planner's single-intent measure is about its *beats* (48.6% of single-story
  plans, 7.2% with A/B: the earlier 51% to 5% holds). In the packet the director's own coverage (orient, escalate with its reaction
  shot, connect ...) already gives every episode at least two intents, so the packet measure is 0% in every arm and the rise in kinds
  (3.94 to 4.41) is modest. The share of `escalate` hardly moves (34% to 37%).
- **The A story gets less screen time**, not more: 14.9 s per episode against 18.4 s, because the plan does not film its scenes in which
  nothing changed. The extra 4.8 s per episode (+26%) is the B story and the ordinary moment, minus what the A story lost.
- **Dry-run cost +40%** if every shot a model would want were sent (2.42 to 3.40 USD per episode at kling_3_pro's listed price). Nothing
  was sent; production/dryrun.py has no code that sends anything. The model budget is the user's call.
- **Order is by time, not by importance**: the plan orders beats by event id, so an episode may open on the B story (its scenes happened
  first) and the A story arrives later; the packet marks the change of story only by the cut (a dissolve when the day changes, else a plain
  cut) and by the map. The whole packet keeps the A story's focalizer: B scenes are shown as the audience's, not through B's own people.
  Whether that reads as two stories or as a jumble is not measured here (nobody has watched it).
- **There is no byte-for-byte test against HEAD, and none can be.** A SceneSpec records `ruleset_hash`, which covers every `contracts/*.py`
  and `world/**/*.py`; the packet records `compiler.hash` over `narrative/compiler.py`, `direction.py` and `contracts/packet.py`. Any new
  contract file (this one, and the bible's) therefore changes every packet's hash while no shot moves. What was checked instead: the packet
  without its provenance hashes (`scene_hash`, `compiler`, `direction_hash`, `performance_hash`, `runtime_hash`, `packet_hash`) of the
  pristine HEAD (a `git archive`) and of this tree: the 20 packets of the daily job (seeds 17 and 502, `episode_first` off and on, 5 days each, with the runtime and the performance plan, `render=False`) are identical, byte for byte (741,942 bytes of canonical JSON), and so are the 4 packets of the `Fingerprint` test's seeded fortnight (golden `ab4a86644a85fd74a273763e`). The compile path (`narrative/compiler.py`, `direction.py`,
  `contracts/packet.py`) is not edited by this work. A permanent test (`Fingerprint`) pins that content for a seeded fortnight, and
  `Off` pins that `make_episodes` without a composition is the documented steps and has no map.
- **A HEAD bug blocks payoff episodes with a succession or a new faction, with or without this work**: `world/domains/factions.py` gives
  those two events `describe="{who}..."` but a packet's caption fills `{a}`, `{b}`, `{thing}` (narrative/compiler.py:118), so compiling any
  packet that holds one raises `KeyError('who')`. The fortnights above only run because the lab (and the test module) patch the two
  strings at run time; a real `episode_first` day on such an event crashes today. The fix is two words (`{who}` to `{a}`); it is outside
  this work's files and was not made.
- `episode_first` still writes a `director_plan.json` without the plan's intents (the packet's own plan has them); for `episode_ab`
  the file is written with them. Not changed for the single-story option.
- The A story's unfilmed (nothing-changed) scenes are not recorded as shown, so a later day's arc may offer them again; the planner drops
  them again. Harmless, not fixed.
