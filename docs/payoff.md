# Payoff: release that was set up, and how much of it was earned

`narrative/payoff.py`, metric `payoff_metric_v0.1` (a draft: it will move as data says so, then be frozen like dramaturgy v1).
Read only. It finds payoffs in what happened; it never creates one.

## What counts

A moment where somebody who had been held down, kept waiting or counted out is, in front of others, proved right, chosen or put in the
place they were after:

| kind | when | protagonist |
|---|---|---|
| face_slap | a duel the underdog won in front of witnesses (the duel's recorded `slap`, `world/domains/progression.py`) | the winner |
| chosen | a confession that was accepted (`world/domains/romance.py`) | the one who confessed |
| succession | a contested seat won, against the favourite (`world/domains/factions.py`) | the winner |

## Six parts, each 0..1

| part | meaning |
|---|---|
| expectation_gap | how far the audience's expectation, **as of before the event**, was from what happened. An expectation less than a day old counts for a third |
| social_witness | how many saw it, or voted |
| pressure | what the protagonist went through in the week before (shame, wrongs, failure, hostility, from their nightly reflections) |
| magnitude | how much was won (the surprise; how unlikely the yes; the seat) |
| causal_investment | what they put in themselves beforehand: practice and breakthroughs; courtship; campaigning |
| agency_attribution | below |

```text
base          = 0.30 gap + 0.15 witness + 0.20 pressure + 0.20 magnitude + 0.15 investment
earned_payoff = base x agency_attribution
```

## Agency attribution

The share of the causes on record that were the protagonist's own choices, against those that were not. Units:

| cause | units | whose |
|---|---|---|
| a practice they did (up to 10) | 1 each | theirs; half to the producer if done with a manual the producer delivered |
| a defeat turned into tempering | 2 each | theirs |
| the challenge, the courtship, the campaign they chose | 1 each (up to 10) | theirs |
| a gathering the producer announced; a vacancy it opened | 1 each | the producer's |
| the result's unlikeliness (the lower the chance, the more luck) | 3 x min(1, 2 x (1 - chance)), when the chance was under one half | luck |

`agency = own / (own + producer + luck)`. So a payoff the producer handed over (a manual, then a tournament, then a win against the odds)
scores low however dramatic it looks, and one the person made themselves scores high. The weights are in the file and are meant to be argued with.

## Summary

`count`, `by_kind`, `per_person`, `fairness_gini` (how evenly payoffs are shared among the ten; 0 even, near 1 one person has them all),
`base`, `earned`, `earned_share` (earned / base), `earned_payoffs` (those with earned >= 0.35), `mean_agency`.

## What it shows so far

With nobody producing (3 seeds, 28 days, jianghu_saga_v1) a world makes one to three payoffs a month, nearly all of them earned
(agency near 1: nobody handed them over). See docs/producer.md and `producer_lab.py` for what a producer adds to that, and out/producer_lab for the latest numbers.
