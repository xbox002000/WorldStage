# Social worlds: depth, growth, romance, factions

Phase 2B of the plan. Everything here is a **domain pack** (`world/domains/`), switched on by recipe primitives, so the core names none of
it and an older recipe is byte-for-byte what it was. They are in `jianghu_saga_v1` (the test bed: the town's ten people in the jianghu) and
`jianghu_story_v1` (the same, with two underrated disciples already in it: the world the producer lab runs on).

Schema v8 added: relationship columns `resentment`, `respect`, `familiarity`, `attraction`, `estimate`, `bond`; tables `factions`,
`affiliations`, `seats`; the entity types `faction`, `affiliation`, `seat` in `event_deltas`.

## Depth in relationships (`social.depth`, relations.py)

Trust and affection say how one stands with another, not what they have been through. Familiarity grows with every exchange (and flirts,
dates, confessions) and fades slowly when they stop meeting; resentment comes from hostile words, false accusations, theft, blows, being
beaten, and fades 3% a night (an apology takes some away); respect falls for the caught liar, the thief, the one who lost control in public,
and rises for the winner of a fair duel and the one who repays, *for everybody who saw it*. They are world truth and they decide things: a
grudge cools the next warm word and sharpens a cold one, and in a quarrel it is one more reason to say it (`reply:grudge`). They soften at
the ends like trust (no pair stuck at +-0.9 after 21 days).

## Growth and what others think of it (`growth.progression`, progression.py)

Practice builds *tempering*, a defeat builds a lot, and enough of it (more the higher the ability) is a breakthrough: the ability jumps (0.04
to 0.12), never falls back, and the event lists every practice and defeat behind it. `relationships.estimate` is what each person believes of
each other's ability, in the ability's own units; practice is private, so it lags, and only a duel in front of witnesses (or the night's news
of one) moves it. A duel that shows somebody to be more than they were taken for records `slap` (who was surprised, who had sneered) and
`gaps`; those who underestimated the winner respect them more (the more, the further off they were), the loser and the sneerers feel shame,
the winner success. A challenger weighs the risk by what they *believe* of the other, not the truth: the one who looks down on somebody is
the likelier to challenge them, and to be wrong. Calibration: a month has a few breakthroughs, not one a day (an early version made
everyone a master in 28 days).

## Romance (`romance.attraction`, romance.py)

Charm, orientation and attachment are in the genome; who is drawn to whom comes from charm, what two people have in common (tastes, values),
how well they know each other, and what lies between them, moved a night at a time. Four actions the rules judge: `flirt`, `confess`
(accepted by how the other feels, who else is in the picture, a seeded roll), `date`, `break_up`. Being together is a fact (`bond`), and can be a
secret: it is a claim only those who saw it hold, and gossip spreads it like any other. Seeing somebody you love flirt with, or be taken
by, another is jealousy (a grudge against the third, against the loved one too if you were together); leaving somebody for somebody leaves a
betrayed ex and two enemies. **Only adults take part** (18 and over, tested); the stage shows a courtship and no more. Over 21 days and six seeds
the correlation between charm and the attraction a person receives is 0.54 to 0.76, a month has one to three confessions and often a couple.

## Circles, factions and the fight for a seat (`social.factions`, factions.py)

A circle is read, a night at a time, from the ties between people (label propagation, deterministic), and written down as `circle.<person>` because it
decides things (`Domain.solidarity`: whom a bystander stands by, whom one believes). A circle of three or more loose people that has a leader
founds a faction when its members say so (an event); `recruit`, `defect` and `campaign` are actions, and on the day a seat is to be decided the
faction votes (the leader counts double, one who stands votes for oneself), with every vote and the tally in the event. A seat falls vacant when the content
or the producer says so. Membership can be a secret. Seen so far (28 days, three seeds): factions founded by the second day from the seed's own ties,
members poached from one side to another (`left_faction`), a seat won by a different person on every seed.

## Gatherings (`event.gatherings`, gatherings.py) and roles (`production.roles`, roles.py)

See docs/producer.md. An announcement changes who is where; a role leans choices a person already has, resisted by their nature.

## Measuring

dramaturgy_metric_v1 stays frozen (the packs' situations are extensions: hidden strength, face slap, crush, love triangle, secret couple,
heartbreak, power struggle, faction rivalry, defection). `narrative/payoff.py` measures release (docs/payoff.md); `producer_lab.py` measures what
producing adds.
