# The inner chain: body, feelings, losing control, hurt, self-image, behaviour

Written 2026-10-01, phase 1 of the plan (`C:\Users\xbox0\.claude\plans\concordia-fuzzy-creek.md`). It came from the
user's three questions:
- Has nobody formed a self-image yet?
- Are people hurt by misunderstandings, and does it change what they do?
- What about the body, such as losing one's temper and attacking someone?

The target chain:

```text
body (tired, hungry, under pressure)  ->  arousal against self-control  ->  losing it (shove, blow, smash, tears)
      ->  hurt and regret  ->  experiences  ->  self-models  ->  what one does next
```

## 1.1 Relationships that keep their nuance

**Measured.** After 30 days 63% of trust and 71% of affection sat at ±1. Every warm word added 0.15, with nothing
drawing it back, so love-and-hate was impossible.

**Built.** `world/helpers.py`:
- `soft_delta(current, delta)`: a push further out counts for (1 − |current|)², a pull back counts in full.
- `rel_delta` applies it with clamping in worlds with social.exchange. Every relationship change in the rules goes
  through it: `trust_change`, `field_change` and `_talk`.
- Nightly fade (`world/simulation.py _fade`): trust and affection for people one did not deal with today move 2%
  towards indifference.

A linear factor first left 19% at the ends, because friends meet every day and so never fade. The squared factor
leaves 0%.

## 1.2 The hurt of being misjudged; the hostility spiral

**Measured.**
- Being called a liar for telling the truth happened 49 times in 3 worlds over 30 days, and counted for nothing.
- Every hostile word heard counted as hostility, even in a quarrel one started, and aggression never eased. Several
  people reached 0.9-1.0.

**Built.** `world/psyche.py`:
- A confrontation that is `unfounded` (one told the truth) counts as wronged 0.8; `misinformed` counts as 0.3.
- Hostility one provoked counts 0.3, judged by whether the hostile word answered one's own cold or hostile word,
  accusation or confrontation within 5 minutes.
- A day without being attacked eases aggression by STEP_UP/2, never past its scar.
- A new self-model, 大家都對我有敵意 (world_is_hostile), forms from hostility at 4.0.
- Worlds made before a self-model existed skip it.

## 1.3 Self-models that change behaviour

`world/psyche.py self_bias()` sums the held self-models, each by its strength (1, or 0.5 once softened). It is read
by:
- the rule agent: tone, idle, telling, lending, accusing;
- the replier: retort, deny, apologise, soothe, swallow it;
- belief in what one is told (`world/social.py`).

| self-model | leans |
|---|---|
| 我不能相信別人 | believes told things −0.15, accuses +0.3, tells others less |
| 我總是被冤枉的那個 | defends and denies +0.3, apologises −0.3 |
| 只能靠自己 | keeps to oneself +0.2, lends −0.3 |
| 還是有人對我好 | soothes +0.2, warmer |
| 大家都對我有敵意 | hits back +0.3, warmth −0.2 |

## 1.4 The body pack (primitive body.arousal, `world/domains/body.py`)

- **Arousal** is a world var with a time stamp, read with exponential decay (half-life 90 minutes); sleep clears it.
  - It rises when one is shouted at (+0.15), wrongly accused (+0.3), called a liar (+0.3), exposed (+0.25),
    robbed (+0.3) or hit (+0.35), with diminishing returns: the more worked up, the less more.
  - A warm word from someone one likes takes off 0.1.
- **Self-control** = 0.68 − 0.4×temper − 0.3×(aggression − 0.2). It drops by 0.15 when exhausted (energy < 30),
  0.15 when hungry (> 70), and 0.1 when under pressure at work (stress > 0.7).
- **Losing it is a seizure, not a choice** (core hook `Domain.seize`). It is asked before a decision, before an
  answer mid-quarrel, and before a character agent's mind.
  - Past self-control by more than 0.05, it takes over with a chance of 2.5 × the excess, at most 0.85, decided
    by the world's seed.
  - Then it is weighed among a shove, a blow (past 0.2), and smashing something or breaking down (past 0.1).
  - Once a day at most: one is spent.
- **What follows:**
  - the one hit loses trust and affection and gains fear;
  - witnesses think less of the one who did it, and the claim (推了 / 動手打了) spreads like any other;
  - a blow hurts for two days, and between fighters (martial arts on) skill decides who is hurt;
  - that night comes a `regret` event and, towards someone one cares about, a make_amends goal;
  - appraisal (core hook `Domain.appraise`): lashing out is shame; being hit is hostility and being wronged.
- **Short-fused in words** (core hook `Domain.irritability`): exhaustion, hunger and arousal add heat to tone and
  to retorts.

**Calibration.** The target is 1-5 outbursts per world per month.

| attempt | change | what happened |
|---|---|---|
| 1 | — | 10-14 in 20-odd days: four hostile lines piled arousal to 1.0 |
| 2 | gentler arousal, higher control, one per day | none in 10 days × 6 worlds; the peak excess was −0.38 to +0.01 |
| 3 | control lowered to put the peaks over the threshold | still none: as an option among options, an outburst (score about 1) never beat a retort |
| 4 | made a seizure | 2 in 10 days × 6 worlds, then the 30-day gate below |

## 1.5 Disposition against opportunity

**Measured.** Across two worlds, how much people gossip, apologise and confront did not rank them alike
(ρ 0.04, −0.04, −0.17).

**Built.**
- Telling is weighted by the gossip trait (score × (0.4 + 1.2×gossip)).
- Apologising weighs honesty and generosity more.
- Confronting weighs temper and vigilance.
- `cross_domain.py` measures them per chance: chances to tell, answers given while in the wrong, chances to
  confront or accuse.

**Calibration, continued.**
- 30-day runs still had one world spiral to 19 outbursts. That was verbal: hostile words went from 9 to 38 a day
  as aggression rose linearly to 0.99.
- Fixes:
  - aggression grows by STEP_DOWN × (1 − aggression) and eases on any day with less than one unprovoked attack;
  - remorse: +0.1 self-control per outburst in the last week, up to three;
  - being hit right after going for someone is hostility 0.3, not injustice;
  - control base 0.65.

## Results (3-6 seeds × 30 days)

| | before (town_life_v1) | after (town_life_v1, 6 seeds) | after (town_spatial_v1, 3 seeds) | target |
|---|---|---|---|---|
| relationships stuck at the ends (trust / affection) | 63% / 71% | 0% / 0% | 0% / 0% | ≤ 10% |
| aggression, median per world | 0.34-0.89 | 0.21-0.28 | 0.25-0.29 | < 0.5 |
| negative self-models formed | none | 大家都對我有敵意 17, 我總是被冤枉的那個 4, 只能靠自己 1 | 15, 1, 2 | at least one |
| outbursts per world | (no body) | 1, 7, 2, 4, 2, 3 | 2, 5, 6 | 1-5 |
| v1 tension after day 14 | 9.8 | 8.2 | 5.4 | ≥ 7 |

**Not met.**
- Spatial v1 late is 5.4. It was 4.3 with packs before this phase, and 7.9 with exchanges only.
- With nuanced relationships and no runaway aggression, there are fewer of the classic situations that v1 counts:
  lies, accusations, secrets about wrongdoing.
- I did not tune drama weights to lift the number, because that would bend the world to the metric. Finding and
  shaping drama is the Episode Planner's job (phase 3).
- One world in six had 7 outbursts, against a target of at most 5.

## 1.5 measured properly: the persona probe

- `cross_domain.py` counts what people happened to do. In 20 days someone is in the wrong two or three times, so
  apology and confrontation ranks were noise (ρ −0.04, −0.04).
- `persona_probe.py` puts everyone in the same standard circumstances instead, on a throwaway copy of their world,
  and reads the rule agent's exact probabilities:
  - pass on a grave thing about a third person;
  - apologise when caught;
  - hit back or deny when wrongly accused;
  - accuse someone believed to have deceived one.
- The same genomes are probed in town_life_v1 and town_in_jianghu_v1. Spearman across the ten people, mean of 3
  seeds:

| probe | day 0 | day 20 |
|---|---|---|
| gossip | 0.82 | 0.35 |
| apology | 0.99 | 0.95 |
| defend | 0.97 | 0.33 |
| accuse | 0.92 | 0.29 |

**What it shows.**
- At the start, disposition decides, and it is the same in both worlds (all ≥ 0.82).
- After twenty days of different lives, defence and accusation have diverged. Each person has new self-models,
  aggression and relationships in each world. Apology held.
- "The same person, a different life" is now measurable, per person and per circumstance. This probe is the start
  of the Persona layer's circumstance model (plan 1B.3) and of its counterfactual lab (1B.5).

## Speed (done along the way)

- File worlds use `synchronous = NORMAL`: on the project drive, FULL had made writing 75% of a day.
- Experiments simulate in memory and save the world at the end (`world.db.save_to`).
- Schema v6 adds indexes for the most asked queries.
- Behaviour fingerprints were identical before and after each change.
- A 10-day gate went from 85.6 s to 6.5 s. A 30-day non-spatial gate with 6 seeds runs in about 1 minute; the
  spatial one with 3 seeds in 8 minutes (it was 27).
