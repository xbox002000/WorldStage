# Convergence round: frozen metric, sticky goals, inner conflict, cross-domain cast, overview, profiling

Written 2026-10-01, from the user's review after Character OS v1: converge and freeze baselines before adding more
genres. Each item below says what was built, what was measured, and what it showed, including what went against
the last round's claims.

## 1. Frozen metric

**Built.** `dramaturgy_metric_v1` is frozen and versioned, with a golden test on a stored world (see docs/drama.md).
Extensions (packs, dilemmas) are reported apart from it.

**What it showed** (same seeds, same 30 days, v1 only):

| | v1 early | v1 late | with extensions, late |
|---|---|---|---|
| exchanges only | 13.7 | 7.9 | 7.9 |
| + topics, work (first version) | 10.2 | 5.6 | 15.4 |
| + topics, work (tuned) | 10.7 | 4.3 | 14.0 |

**What it means.**
- With packs on, classic drama fell. Hostile words fell 39%, gossip 31%, confrontations 30%, accusations 37%,
  lies 73% and thefts 62%.
- What kept the late world alive was the packs' own drama. Whether that drama is worth watching is not shown by
  any metric.
- One cause was a bug: the topics pack's shape hook raised the score of a talk with a good topic, so chat crowded
  out gossip. It is fixed: shape decides what is said, never whether one talks.

## 2. The red line: a pack is not a second core

**Built.** `tests/test_domains.py::PacksAreNotASecondCore` refuses a pack that:
- imports `world.simulation`, `world.db` or anything in `agent/`;
- takes `apply_event` or `mutation`;
- has SQL that writes;
- is longer than 600 lines.

A pack declares and returns, and the core runs the lifecycle. The martial pack had borrowed `agent.volition.rel`;
it now reads the relationship itself.

## 3. Goals that stick and evolve

**Measured before.** The same people searched for another job day after day, with no arc:
- Ming, seed 260934: 14 searches from day 11 to day 29.
- Kai: search, offer, refuse, search, offer, refuse.

**Built.** A goal changes only when something happens:

```text
leave_job --offer--> weigh_offer --decline--> stay_on --(stress at the limit again, after a week)--> leave_job
                                 --accept---> resigned (completed)
leave_job --4 searches, nothing--> earn_recognition (the ambitious) | stay_on
earn_recognition --praised--> completed        stay_on --satisfied again--> completed
```

- Only someone with the goal searches, at most every two days.
- A work goal that just ended gives a week of peace.
- Every turn is a goal_change event caused by the event that turned it (tests/test_character_os.py).

**Example after** (Ming, seed 260934, 30 days):
1. Day 5, wants to leave; searches on days 7, 11, 13 and 15; no offer.
2. Day 15: "找不到出路，那就在這裡證明自己".
3. Day 21: praised by the boss, goal completed.
4. Day 22: an offer; day 23: refuses it, "決定留下：捨不得這裡的人".

## 4. Inner conflict

**Built.** `world/values.py`, under the primitive `character.values`.
- Every act has stakes in the values people hold: core acts, and domain actions through `ActionSpec.stakes`.
- An act that serves a value its actor holds dear and betrays another is recorded on its event, as
  `truth["dilemma"]` with serves, costs and tension.
- This is computed from the actor's own profile. It changes no choice.
- The director has a new score part, `inner` (weight 0.15). Scenes score it, and the Dramaturgy extensions list it
  as `dilemma`.
- In 10 days of town_life_v1 there were 4: confronting someone one likes, for truth and fairness, at the cost of
  belonging. Offers produce the freedom-against-security kind when they come.

## 5. The same people in another world

**Built.**
- `Casting` separates the part a person plays in a world (occupation, season goal) from who they are.
- A roster can be `based_on` another and only recast them, with `topic_words` for the world's names of the same
  topics (咖啡 -> 茶).
- `town_in_jianghu`: the town's ten people as sect disciples and inn folk, with the same profiles and the same old
  business of Mei's ring. Recipe `town_in_jianghu_v1`.
- `cross_domain.py` measures it.

**Result** (20 days, 3 seeds): Spearman rank correlation of each behaviour signature across the ten people, town
against jianghu.

| signature | rho | |
|---|---|---|
| warm | 0.62 | holds |
| retort | 0.53 | holds |
| hostile | 0.49 | holds |
| storm off | 0.23 | weak |
| deceit | 0.20 | weak |
| gossip | 0.04 | does not hold |
| conciliate | -0.04 | does not hold |
| clash | -0.17 | does not hold |

**What adapts:**
- in the jianghu, duels (5-8 per world), training (120-141) and goals to surpass someone;
- the work arc in the sect's words (被掌門要求加練, 打聽別的門派);
- the director ranks threads and the runtime's invariants hold.

**What it means.**
- How someone speaks is theirs in any world.
- Whether they pass things on, apologise or confront is, in the current model, decided by circumstance: what they
  happen to know, who wronged them.
- Hao (gossip 0.9) should be the town's mouth in any world, and is not consistently. Next: weigh gossip, apology
  and confrontation by disposition against opportunity, and measure them per opportunity.

## 6. A life at a glance

**Built.** `narrative/observatory.py::character_overview`, the God View tab "總覽". It shows:
- now; what they are after; what they care about, in order; what they fear and the wound;
- what changed in the last five days; the weightiest memories; who they grew closer to or apart from;
- the arc of how they dealt with people, five days at a time (親近 / 對抗 / 退縮 / 修補 / 平淡).

Example: Ming (對抗 → 親近 → 平淡 → 對抗), Kai (對抗 → 平淡 → 對抗).

**What it showed at once: relationships saturate.**
- After 30 days, 50-55 of 90 relationships have trust at ±1 (affection 59-68). After 5 days, before exchanges,
  it was 1.
- Every warm word adds 0.15 trust, with no diminishing returns and no drift back, and exchanges multiplied the
  words.
- Love-and-hate is impossible at ±1. This is the next round's first fix: diminishing returns near the bounds and
  slow drift.

## 7. Profiling

**Built.** `world/profiling.py`: inclusive milliseconds per layer per day, reported by `drama_gate.py`.

**Spatial town** (8 days):
- 92% of the time is `space.runtime`: the World Runtime catching up with the history so space can answer who sees
  what.
- Inside it, A* search (`nav._search` plus `hypot`) takes about 60%, and time-aware conflict checks about 25%.
- Events per day are steady (146-179) and A* calls per day too (171-306). What grows is the cost per search
  (5.7 ms to 12-19 ms), as people cluster.

**Non-spatial town:**
- 8.7 s a day, about 68% of it in SQL.
- The largest single cost is the topics pack's taste lookups, which scan the unindexed memories table on every
  talk option. They grow with history.

**Not optimised this round, as asked.** The next round would:
- add indexes on memories (observer, claim) and on the claims key;
- precompute octile costs and blocked-cell bitmaps in the A*;
- then decide on a NavigationBackend, with Recast/Detour only if the A* still dominates.
