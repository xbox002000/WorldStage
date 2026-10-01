# The producer, the audience and the world

Phase 2B of the plan (v0.4 and v0.5). The question was: if every person in the world had something like the arc of a good web
novel (held down, quietly growing, proved right in front of the people who doubted them), is that a direction problem, or a
structure that is missing, or the editor's job later?

**Answer.** The foundation is right and a layer is missing. Editing can only pick what has already happened, so the arc has to
happen in the world, or there is nothing to pick. It cannot be written *into* the world either, or the world stops being real.
The Truman Show is the model: Truman's reactions are real, the circumstances are arranged by a producer and played by actors, the
broadcast is cut. We had the first and the third; this is the second.

## Four sentences

> The producer controls the topology of opportunity. The world decides the outcome. The characters decide their intentions.
> The rules decide the consequences.

```text
Producer / Agent / System  ->  Intent  ->  World rules  ->  apply_event()  ->  world.db
```

There is exactly one arrow that writes. The four realms:

```text
PRODUCTION   showrunner, season plan, roles, ledger                       (producer/)
   | opportunity (closed vocabulary, through world/interventions.py)
WORLD        space, time, economy, relations, growth, romance, factions   (world/, world.db = truth)
   | circumstance
CHARACTER    genome, state, memory, self-model, body, goals -> intent     (agent/, world/psyche.py ...)
   | events
NARRATIVE    causal audit, dramaturgy, payoff, audience, episode planner  (narrative/, read only)
```

## What the producer may do, and may not

May: arrange who might meet; announce a gathering; deliver a parcel; open a seat; announce a visitor; cast somebody in a part.
May not: make anybody win, lose, love, fear or respect; fix any result; make the audience surprised; write to world.db.

`world/interventions.py` is the door. The vocabulary is closed (`announce_gathering`, `deliver_parcel`, `open_seat`,
`announce_visitor`, `cast_role`), each with a closed set of parameters, and the words said to the town are the world's own templates. A
`WorldIntervention` has no field in which to say why: **`purpose`, the arc and the season live only in the producer's ledger**
(`producer/intervention.py`, a JSONL file). The world hears "a master has come", never "so that the hero can be proved right". A test
searches the whole history of a produced world for the ledger's purposes and arc ids, and finds none.

The ledger also holds the weekly budget (6 units; a gathering costs 2, a vacancy 3, a parcel or a part 1). It is the producer's matter,
not a fact about the town.

## Roles (actors)

A person cast in a part (`world/domains/roles.py`: doubter, rival, mentor, troublemaker, suitor) gets a bias on choices they already
have, towards one person, for some days. It is bounded (at most 0.9 on one option), their own nature resists it (honest and generous
people follow a doubter's part less, but never less than a quarter), the rules still judge whatever they do, so an actor can lose, and the
decision record names the part. The hero is never cast. Casting is world truth (`role.<id>` vars), so it is auditable.

## Gatherings

An announced gathering (`world/domains/gatherings.py`) changes who is where: on the day, those who heard of it go or do not (curiosity,
ambition, being a fighter, a seeded draw), and at a tournament those who are there are readier to challenge. The hero may stay away.

## The audience

`narrative/audience.py` and `contracts/audience.py`. The audience knows what the story has shown (a hidden growth, a feeling nobody has
said, a couple nobody knows of); the people in the world know what they have seen (their memories, their estimates of each other).
The distance is dramatic irony, and the distance between what the audience expected and what happens is a payoff. Neither may be decided
afterwards, so it is computed *as of a revision* by winding the world's history back (`value_at`), and an expectation counts only if it
was already there before the event (`before_event`); one less than a day old counts for a third.

## The season

`producer/showrunner.py`, `contracts/season.py`. A season is 14 days with up to two heroes, in turn (whoever has waited longest); each gets one arc:

| arc | for | opportunities |
|---|---|---|
| underdog | somebody the others rate below what they can do | a doubter among the others, a parcel with a manual, a tournament |
| succession | somebody of a faction that has a seat | the seat opened, a rival cast |
| romance | somebody drawn to somebody | a suitor cast towards the one they are drawn to |

It is revised every morning from what happened: an arc whose hero has had their moment is closed; a beat whose preconditions have gone
is refused by the ledger (a manual already taken, a part already played). A defeat is also a story.

## Producer on and off

`producer_lab.py` runs the same genomes, recipe, seed and model with the producer off, with a **random** control (the same kinds of
opportunity on the same days at the same cost, aimed at nobody in particular) and with the showrunner (full, or only stages, parts or
parcels). Numbers it reports: payoffs and *earned* payoffs (`docs/payoff.md`), the frozen tension measure, turning points, relationship events,
how far people end up from their un-produced selves, the cost, and

- `creative_yield = (earned - earned_off) / cost`: how much more *earned* story one unit of intervention bought;
- `aim = (earned - earned_random) / cost`: how much of that is choosing who, not doing something;
- `stuffing = events / events_off`: an index that would rise if the "improvement" were only a more crowded world.

It records and does not learn: a month has a handful of payoffs, too few to learn from, and a producer that learns from them would learn
to hand them over.

## Producer 2: from an event dispatcher to a manager of opportunity (plan v0.6)

The first showrunner was a fixed recipe per kind of arc, with no view of what the world was already making. It measured as it
should: *producing* added story, but a control that did the same things on the same days aimed at nobody got as much (aim -0.02).
The research brief (Façade, Automated Story Director, DODM, Left 4 Dead, RimWorld, Nemesis, Prom Week, Fable) said the missing
piece is a Director that reads the narrative state of the world first. What was adopted, and what was not:

> The producer does not write a story. It manages the distribution of what could happen: it changes which things have a chance
> of happening; the characters decide whether to; the rules decide how it ends.

```text
pacing -> opportunities -> focus -> shape -> (imagine) -> admit        producer/director.py
 narrative/pacing.py   narrative/opportunity.py   producer/shaper.py   producer/forecast.py + world/rollout.py   producer/intervention.py
```

- **Opportunities are read, not made** (`narrative/opportunity.py`): the reversal (the crowd rates somebody below another, the real
  chance is open, the other looks down on them), the triangle, the succession. Each has a worth (irony x pressure x suspense), the
  chance the protagonist comes out ahead, and **what it lacks**: an occasion, a challenger, a vacancy, strength, or recovery (somebody
  is hurt: only waiting helps). A story whose end is already decided (the hero is bound to win, or to lose) is not an opportunity: it
  has no suspense, and it would be handing over a result.
- **The shaper supplies only what is lacking** (`producer/shaper.py`): a tournament for an occasion; the one who looks down on the hero
  cast as the doubter for a challenger (not the strongest man of the sect, as in version 1); the vacancy; the manual only when the hero
  is a little short. Nothing else, and nothing in the vocabulary names an outcome.
- **Silence is a decision** (`narrative/pacing.py`): after a peak (the weight of the last days' turning points, fading) the director
  keeps still and says so in its ledger (`*.decisions.jsonl`). Variety: a kind of story just told counts half as much again, and the
  same seat does not fall vacant every few days.
- **Imagining, not reading the answer** (`world/rollout.py`, `producer/forecast.py`): the world is deterministic, so the real seed
  played forward *is* the future, and a producer that ran it would be choosing results. Imagining runs a copy under *other luck*
  (the real seed is refused, tested), with and without each of the best stories' answers, under the same few lucks so the difference
  is measured and not the noise; the result is a probability (`Forecast`), and the copy is thrown away. The producer never imports
  `Simulation`: `world/rollout.py` is its only way to a running world (tests/test_layers.py).
- **Not adopted**: learning (a bandit, offline RL). A month holds a handful of payoffs and a producer that learned from them would
  learn to hand them over; the lab records "opportunity -> intervention -> outcome" and nothing learns from it yet.

Two findings from step 0 (diagnosis of version 1, 8 seeds) changed the plan before anything was built:

1. **The tournament did nothing.** On the eight tournaments of version 1 not one duel was fought (0.17 duels a day in the town, 0.0
   on tournament days). The decisions were being made with the pack's push for a challenge (0.7) against talk scoring about 1.0, so a
   fighter at the tournament challenged with a probability of 6-9%. That push is now 2.5 (about 1.5 bouts a tournament, tested), and
   the previous table's "stirring the world" explanation was not what was happening. Re-run with the working tournament, version 1
   stays much where it was (full 3.75 payoffs vs random 3.4 vs off 2.4; earned 1.63 vs 1.62 vs 1.25).
2. **The strongest man was a poor doubter.** The version 1 recipe cast the strongest of the sect as the one who looks down on the
   hero; the underrated heroes were within 0.1 of the strongest, so the bout was an even one and the crowd's surprise at a win was
   small. (The hero won 3 of the 5 bouts against the doubter, so this was a smaller effect than guessed.)

## Producer 2.1: what a third research brief changed, and what measuring it said (plan v0.7)

The brief proposed Dramatic Debt, a Story Portfolio, intervention storylets, pattern saturation, arc death, adaptive pacing, a
"bottleneck" lookahead and a layered objective (legality, then agency, then novelty, then payoff). It was measured, not adopted whole.

| proposal | what was done | verdict |
|---|---|---|
| Pattern saturation | `narrative/novelty.py`: the same mechanic and the same pair of people count 1.0, 0.6, 0.3, 0.1 on each telling. A measure (`earned_novel`, a sibling of payoff_metric_v0.1, which is left alone) and the director's gate (`portfolio`) | adopted as a measure; as a gate it **did not help** |
| Arc death | `producer/arcs.py`: only something *done* for a story counts as tending it; nothing played in 7 days and it is given up, not taken up again for 12 | works (about one arc given up per world), costs nothing |
| Intervention strength | soft / medium / hard recorded with each decision | annotation only: the vocabulary has no hard type yet |
| Layered objective | legality and agency were already hard (ledger, vocabulary, hero never cast); novelty is now a gate before worth | as above |
| Dramatic Debt | `narrative/debt.py` (humiliation, betrayal, gap, longing, grudge), `debt_lab.py` | measured: **does not predict better than what we have** |
| Storylets | the shaper's table (lack -> least intervention) is already that | not rebuilt |
| Bottleneck lookahead | | not built: lookahead has not been shown to help at all |
| Surprise and post-dictability | | deferred until the causal audit feeds the measure |

**Debt as a predictor** (8 seeds, 1520 person-days, no producer; AUC of "carried more, then had a payoff in the next ten days"):
the composite debt 0.58; the opportunity detector's own worth **0.74**; the gap alone 0.69; humiliation 0.57, betrayal 0.59,
longing 0.49, grudge 0.46 (the last two carry no information at all). A composite that is worse than its best part and
worse than what already exists is not wired into the director; it stays as an explanatory read model with this number next to it.

**The portfolio director against the first one** (20 more fresh seeds, 28 days, per world):

| | off | matched | greedy | portfolio |
|---|---|---|---|---|
| payoffs | 1.55 | 3.40 | 5.55 | 5.05 |
| earned | 0.79 | 1.38 | 2.62 | 2.23 |
| earned, discounted for repeats | | 1.03 | 1.65 | 1.45 |
| face slaps / votes / confessions | | 2.3 / 0.8 / 0.3 | 2.5 / 2.4 / 0.7 | 2.6 / 2.0 / 0.5 |
| arcs given up | | 0.65 | 0.35 | 0.95 |

Pre-registered, and what happened:

1. *earned_novel, portfolio - matched, interval above zero*: **met** (+0.42, +0.22..+0.61).
2. *votes at most 40% of the payoffs* (greedy about 47%): **met, barely** (39.6%; greedy 43% on these seeds).
3. *a followed reversal pays off for its hero in 55%, own share 0.7, stuffing 1.05*: **not met**: 52% (24 of 46; greedy 56%, matched 48%); own share 0.79 and stuffing 1.00 hold.
4. *arcs are given up, and the spend is not higher than greedy's*: **met** (11.5 against 12.5 units).

But the point of the exercise was to stop paying for repetition without losing the story, and it did not work:
**portfolio earns less than greedy, even on the metric that discounts repetition** (-0.39 earned, -0.62..-0.16; -0.20 earned_novel,
-0.34..-0.06), and it is not measurably newer (mean novelty +0.03, not distinguishable from zero; mechanics -0.15). The gate removes
stories that were still worth telling and does not bring in better ones. Greedy, with its softer variety weight, stays the default;
`portfolio` stays in the code as an option and as the record of this.

What this says about the brief's worry: the repeated vote *is* the cheapest payoff and a producer that is paid by payoffs does lean
on it (2.4 a world), but a hard gate on repetition is a blunt cure. What would help is not another gate but making the other stories as
cheap to bring off, which is the reversal's 55% (a hero with an open result cannot be promised a win) and the confession's 0.7 a world.

## Versions

Kept apart in `contracts/versions.py` and pinned by `tests/test_versions.py`: database schema 8; character 1; persona 1; seed 1;
intervention 1; audience 1; runtime 0.2; dramaturgy_metric_v1 (frozen); payoff_metric_v0.1 (a draft).

## What the lab says (Producer 2: 28 days, 20 fresh seeds, jianghu_story_v1)

The design was tuned on eight other seeds; these twenty were run once, with the acceptance written down beforehand (plan v0.6).
Differences are paired by seed, mean (90% interval over seeds). "Shown" means the interval's lower end is above zero.

| per world | off | v1 random | v1 full | matched | blind | **greedy** | lookahead |
|---|---|---|---|---|---|---|---|
| payoffs | 1.75 | 3.75 | 3.30 | 3.55 | 3.70 | **5.15** | 3.75 |
| earned payoff | 0.94 | 1.86 | 1.49 | 1.58 | 1.58 | **2.39** | 1.70 |
| face slaps / votes / confessions | 1.1 / 0 / 0.7 | | | 1.8 / 1.1 / 0.7 | 2.7 / 0.5 / 0.6 | 2.1 / 2.4 / 0.7 | 2.0 / 1.4 / 0.4 |
| cost admitted (units) | 0 | 9.9 | 9.7 | 11.0 | 14.0 | 12.4 | 10.2 |

| earned payoff, difference | |
|---|---|
| greedy - off | +1.45 (+1.17..+1.75) shown |
| greedy - matched (the right story, or a real story drawn at random) | +0.81 (+0.49..+1.12) shown |
| greedy - blind (a random pair of fighters) | +0.80 (+0.54..+1.05) shown |
| matched - blind (is the detector worth anything on its own?) | 0.00 (-0.35..+0.35) not shown |
| greedy - v1 full | +0.90 (+0.57..+1.22) shown |
| aggressive - greedy (never keeping still) | -0.08 (-0.27..+0.12) not shown |
| unlimited - greedy (no weekly budget) | -0.07 (-0.16..+0.01) not shown |
| lookahead - greedy | **-0.69 (-1.05..-0.28): lookahead is worse** |

**Acceptance, as written beforehand:**

- *Aiming helps*: **met**, with a qualification. Choosing the best story beats a story drawn at random (+0.81) and a random pair
  (+0.80), both shown. But a random draw among real stories is no better than a random pair (0.00), so the detector's
  listing of stories is not what carries it: the *ranking* is, and it is the ranking by worth and variety that opens a seat now and
  then (votes: 2.4 a world against 1.1 and 0.5). Without a producer no seat ever falls vacant in 28 days, so this is a story that
  exists only because it was made possible, but it is also the cheapest payoff on the books.
- *The hero has their moment*: followed for ten days, 75% of greedy's stories ended in a moment, against 5% for the same people in the world
  with no producer. By kind: **votes 48 of 56, reversals 17 of 31** (55%, against 29% for matched and 23% for blind). A vote's moment is
  anybody's, because the contest is the story; the reversal is the hero's own, and it is the one that was meant. 55% is the
  honest ceiling of a design in which the result is open: a hero with an even chance of winning cannot be promised a win. The old
  "70% of heroes get a payoff" is met only through the votes.
- *Not handed over*: own share 0.80 (>= 0.7), events 0.99 of the world without a producer (<= 1.05), no hero ever cast (tested),
  the imagined luck never the world's (tested). **Met.**
- *Looking ahead*: **not met.** Lookahead is worse than greedy (-0.69) and no better than matched; its imagined futures were
  over-confident (it said the chance of a payoff in the next four days was 0.71, with nothing done 0.33; what followed was 0.56), and
  it chooses silence more often. Three imagined samples under four days are too few to tell options apart, and it costs six minutes
  a world against one. It stays in the code as an option and is not the default.
- *Keeping still*: no evidence it helps. Aggressive (never silent) earns the same, and the weekly budget does not bind (unlimited
  earns the same). The pacing costs nothing (the same spend; the world of the aggressive one has about 23 fewer events of 4200, which is small) and buys nothing the payoff count can see.
  The silences are kept in the ledger as decisions; whether they make the story *better* is a question for the eye, not for this metric.

**What did not hold**, in short: lookahead; the claim that the aiming is the detector's finding of stories; and any reading of the
payoff count as quality, since the largest single gain is a vote the producer made possible every nine days or so. The next test
is not more seeds but whether anybody wants to watch it (God View replay of a greedy season), and a payoff metric that
discounts a repeated kind (payoff_metric_v0.2) before this one is frozen.

## What the lab said of Producer 1 (28 days, 8 seeds, jianghu_story_v1; the tournament push was 0.7 then)

Per world, mean over seeds. The same genomes, recipe, seeds and model; only the producer differs.

| | off | random control | full showrunner | stage only | cast only |
|---|---|---|---|---|---|
| payoffs | 2.4 | 3.6 | 3.6 | 2.8 | 2.1 |
| earned payoff (sum) | 1.25 | 1.74 | 1.54 | 1.30 | 0.93 |
| frozen tension (v1) | 8.8 | 6.9 | 11.0 | 8.0 | 9.2 |
| turning points | 15.8 | 16.0 | 13.9 | 15.5 | 14.9 |
| cost admitted (units) | 0 | 9.3 | 6.6 | 2.3 | 3.3 |
| events (vs off) | 1.00 | | 1.00 | 0.99 | 1.00 |

- Producing does add story: 50% more payoffs than leaving the world alone, and the frozen tension measure is 25% higher. About 80% of the
  payoff the people make themselves (agency attribution), and the world is not crowded to get there (events 1.00x).
- It does **not** show that the aiming matters: a producer that does the same things on the same days aimed at nobody in particular gets as
  many payoffs and a higher earned total (aim = -0.02 per unit). What helps, in this first version, is mostly stirring the world (gatherings
  bring people together, a part gives somebody a push), not choosing the right hero for the right opportunity.
- Cast-only does worse than nothing in earned payoff: a part cast badly gets in the way of what would have happened.
- Eight seeds and one to four payoffs a world is a small sample; every one of these differences is within what a bare extra event does to a
  month (docs/persona.md). The lab is built to be rerun with more seeds as the showrunner changes.

So the 2B acceptance "every hero gets a payoff each season" is **not met** (about one in two), and "producing beats random aiming" is **not shown**.
What is shown: the machinery works end to end, the producer cannot decide an outcome (tested), it does not stuff the world, and the measures can tell a
good producer from a bad one once there is one.
