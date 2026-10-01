# Drama: a word gets an answer, and what is worth watching can be found

Written 2026-10-01, after the user watched the God View: "幾乎沒什麼劇情……只看到角色們例行性的在走來走去，看不出情緒反應、
衝突、對立", and the cafe was too small ("人都擠成一團"). Then the user's Dramaturgy brief: discover the drama that is
really there, never invent it.

## What was wrong (measured, not guessed)

`drama_gate.py` measures a world from world.db only. Baseline, 3 seeds x 5 days, town_spatial_v1 (out/gates/drama_000):

| | before |
|---|---|
| social events a day | 27.7 |
| clashes a day | 3.8 |
| scenes (3+ turns back and forth) a day | **0** |
| longest exchange | **2 turns** |
| cafe: people at once / seats | 10 / 9 |

The causes:
- **One line and done.** Everyone decides three times a day, one action each, so two people meet, one says a line,
  and nobody ever answers. An accusation had no reply, an insult no comeback: no emotional feedback loop could form.
- **Kind words erased every feeling.** A warm talk set the listener's emotion to "happy", and 60% of talk is warm,
  so by evening 9 of 10 people were happy whatever had happened.
- **The town lived in one room.** Workers left the office at noon and sat in the 9-seat cafe until 18:00, with the
  people at home. The office-park path did not exist, so "going to the park after work" was refused.

## What changed

- **social.exchange** (recipe primitive, on in town_spatial_v1; `agent/reply.py`, `world/simulation.py`):
  - whoever is spoken to, accused or confronted answers at once, and the other answers back, up to 8 turns;
  - each answer is an ordinary Intent the rules resolve: talk with a tone, or walking out;
  - its reason says how it was meant: reply:chat / soothe / apologize / explain / deny / rebuff / retort / storm_off;
  - the answer comes from what was done to them, temper, honesty, generosity, aggression and withdrawal, affection
    and fear, being in the wrong or wrongly accused, a grudge, and fatigue (each turn, and recent clashes);
  - when it turns ugly, one bystander who noticed may step in: comfort the one attacked, or turn on the attacker.
- **Feelings last** (`world/rules.py _felt`):
  - hostility angers the hot-tempered, hurts the rest, frightens those who fear the speaker;
  - kind words calm someone upset only if they are fond of the speaker;
  - a night's sleep softens feelings (anger and shame become unease, lighter feelings pass).
- **Space and days:**
  - the cafe is 14 x 10 m with five tables and a bar with stools: 18 seats;
  - workers go back to the office after lunch, with an afternoon moment to decide (colleagues together);
  - people at home spread over the park, the cafe and home;
  - an office-park path.
- **The runtime says each line in turn.** A talk books the speaker's and the listener's voice (2.5-3.5 s), so an
  exchange logged within one world minute plays line by line.
- **Seeing it** (God View):
  - a speech bubble over the speaker, coloured by stance, with the other's answer to an accusation or a confrontation;
  - feelings next to names;
  - a "好戲" tab (scenes, best first, each plays at 1x) and "▶ 只看好戲" (the best twelve, one after another).
  - Lines (`narrative/lines.py`) and scenes (`narrative/scenes.py`) are read models: phrasings chosen by event id,
    never fed back to anyone.

After (out/gates/drama_003, the final code):

| | before | after |
|---|---|---|
| social events a day | 27.7 | 64.1 |
| clashes a day | 3.8 | 11.9 |
| scenes a day | 0 | 7.8 |
| longest exchange | 2 | 6.3 |
| escalating scenes (5 days) | 0 | 15 |
| walking out / a bystander stepping in | 0 / 0 | ~1 / ~2 a day |
| mean trust at the end (drama_002) | 0.13 | 0.20 |
| pairs with trust below -0.5 | 3 | 6-8 |
| seconds for 5 days (spatial) | 99 | 119 |

The town is warmer on the whole and has a few real enemies; some days are quiet (seed 260934, day 4: one hostile
word).

The first version spiralled: the replies ignored fatigue, and on day 4 there were 24-26 hostile words. Recent clashes
now drain the fight out of a reply, as they already did for decisions.

## Dramaturgy v0: where is the drama in what really happened?

`narrative/dramaturgy.py` is an offline, read-only analysis. Every situation it finds cites the events it stands on:

| Situation | What it means |
|---|---|
| secret | someone did something to someone, and the one it concerns does not know |
| misbelief | someone believes something harmful about a person that world truth contradicts (irony: we know, they do not) |
| live_lie | a lie, distortion or omission not yet exposed |
| near_miss | a confrontation that proved nothing, a denial that held, or the secret's keeper and the one kept from talking face to face |
| contradiction | subtext: warm words to someone one distrusts, cold words to someone one is fond of, an honest person lying |
| goal_clash | open goals that cannot both come true |
| turning_point | trust changing sign |

Each situation gets a potential and a dramatic question.

**On the old 60-day world** (out/life60.db, old rules, town_v1):

- **The drama ran out after two weeks.**
  - Potential tension per day was 6-17 on days 0-14, then 0.5-2 on days 15-59.
  - The world used up what it started with (the old secret, old debts, the first misunderstandings), and nothing
    renewed it.
  - This is the world's problem, not the storyteller's: people have no lasting wants that collide.
- **The best material was there and never filmed.**
  - Long ago Yun took Mei's ring, and Mei never finds out.
  - While that secret lived, Yun and Mei talked face to face 41 times: every one of those chats is dramatic irony.
  - Another thread: a cold word became "阿凱敵意地質問阿蘭" and seven people came to believe it.
- Counts over the 60 days:
  - 6 secrets, 11 misbeliefs, 3 live lies, 8 near misses;
  - 24 contradictions, 3 goal clashes, 52 turning points (too many: most are small trust wobbles around zero).

**On the new rules** (out/live2, 5 days): tension 5.8, 8.3, 13.4, 16.9, 20.8, with 7 secrets, 5 misbeliefs,
4 live lies, 5 near misses and 13 contradictions. It is still to be seen over 30 days whether it keeps renewing.

## Frozen metric: dramaturgy_metric_v1 (2026-10-01)

- **What v1 is.** v1 is the seven core detectors above exactly as they were frozen.
  - `narrative/dramaturgy.py` reports it as `curve`, and `metric` names the version.
  - `tests/test_dramaturgy_metric.py` holds it to a golden record on a stored 20-day world
    (`tests/fixtures/dramaturgy_world_v1.db`). Counts, the per-day curve, the top 25 situations and a hash of all
    of them must match.
- **What happens to changes.**
  - A changed or added core detector is v2, side by side with v1, never in its place.
  - Domain packs' situations and recorded dilemmas are extensions: `extensions.curve` and `curve_all`, each
    situation marked `ext:<pack>` or `ext:values`. They never count in v1.
- **Why.**
  - Without this, two worlds measured a week apart are measured with two rulers.
  - Remeasured with v1 alone, the comparison of the last round reads differently. Packs on, v1: early 10.7 and
    late 4.3, against 13.7 and 7.9 without packs.
  - So the packs did not add classic drama. The late-world tension came from their own situations (late 14.0
    with extensions).
  - Part of the drop was a bug: the topics pack raised the score of a talk with a good topic, which crowded out
    gossip. Fixed: a pack's shape hook decides what is said, never whether one talks.

## The user's Dramaturgy brief: what I adopted and what I adjusted

- **Adopted.**
  - Dramaturgy is its own layer. It reads the world, never writes it, and finds drama instead of inventing it
    (`narrative/dramaturgy.py`, tested read-only).
  - Information asymmetry, secrets and irony are first-class resources, and so are near misses: "nothing happened"
    can carry the most pressure.
  - Subtext is detected from the gap between what is said (tone) and what is felt (trust, affection).
  - Every situation gets a dramatic question.
- **Adjusted.**
  - *"Do not add more world rules first."* The emotional feedback loop (event → emotion → behaviour → the other's
    reaction → new emotion) has to be something characters really do.
  - A world where nobody ever answered had no loop for any analysis to find: 0 exchanges in 13 days.
  - So the reply rule went into the world. It is a behaviour, not a plot: it follows from the character, and it can
    end in an apology as easily as in a fight.
- **Not yet.**
  - *Core want / fear / wound / false belief / life question per character.* The analysis shows that this is what
    the world lacks after day 14. It is world content (identity) and belongs to Character Life v2.
  - *Surface vs underlying emotion.* This needs an appraisal record with a cause, beyond one emotion field.
  - *Episode planner with a dramatic question, escalation ladder and tension curve.* This is the next layer on top
    of the situations found here.
  - *Choice with costs.* The decider does not keep the options it did not take; recording them is a small change
    to the decision log, not done yet.
