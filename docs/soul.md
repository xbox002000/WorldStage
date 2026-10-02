# Giving the people a mind, without wasting the free quota

`soul_lab.py` runs a world in which people think at wake points (agent/cognition.py) with a real model, and spends as
little of the free quota as it can. The world is plain `world.db`: everything downstream reads it without the mind.

    python soul_lab.py --name pilot --days 3 --dry                    # the whole pipeline with a stub mind, no network
    python soul_lab.py --name pilot --days 3 --daily-limit 20         # for real (GEMINI_API_KEY in the environment)
    python soul_lab.py --name pilot --days 7 --daily-limit 20         # the same world, further: what was paid for is not asked again
    python soul_lab.py --name pilot --days 3 --baseline               # also the same world with rules only, to compare what is chosen

## What keeps the quota from being wasted

| | |
|---|---|
| answers are kept and asked for first (`mode="cache"`, `llm_cache.db` next to the world) | the world is deterministic, so a day that is run again asks the same questions: running again costs only what is new. Measured: the pilot re-run from a copy of its cache asked 0 times and gave the same 466 events. |
| a ledger by the provider's day (`out/soul/ledger.json`, Pacific time) | `--daily-limit N` is refused here, before the provider has to say no. Every attempt counts, retries included. |
| a day the quota cannot finish is thrown away | `QuotaPause`: the world goes back to the end of the last whole day. The rule agent does not finish the day (a world that is half mind and half rule answers nothing). Run again after the reset. Tested: a stopped and resumed world is event-for-event the world that was never stopped, and the two runs together asked exactly as many questions as the whole run. |
| five failures in a row stop the run | a wrong model name or a dead key does not eat the day. |
| tier A by default | a value crossed, a clash, a resolve. A bad mood on its own was 63 of 177 wake-ups in 14 days and is left to the rules unless `--tier AB`. |
| one model, one retry, no other provider | every try is spent quota; mixing models would make the people's voices (and any comparison) inconsistent. |
| a recorded failure is not an answer | a real answer replaces it, a failure never replaces anything (`LLMCache.put`). |

What the rule agent's uncertainty cannot do: filter wake-ups. Its most wanted option has probability < 0.6 in 96% of them (about 12 options, temperature 0.35), so the tiers are by wake reason, not by margin. Exact repeats of a situation are 2 in 177, so reusing answers by situation saves nothing; a loose key (person, reason, kinds of action) would save 40% but merges different situations, and is not used.

## Pilot (2026-10-02): jianghu_story_v1, seed 501, 3 days, tier A, gemini-3.5-flash-lite

| | |
|---|---|
| requests sent | 20 (19 minds woke; one try failed and was retried) |
| answers usable | 19 / 19 |
| chose something other than the rules' most wanted option | 7 / 19 (37%); the rest chose option 0 |
| days | 5, 7 and 7 minds woke |
| who woke | ning 12, kai 4, ming 2, tao 1 |

What the minds did: the reasons and the unspoken thoughts follow the person. ming (angry, a wound about a father who never approved) turned a
neutral line into a barbed one and thought "他憑什麼一副跩樣？我一定要讓他好看"; ning, who the rules wanted to confront 小瑞, chose a safe
topic every time she differed ("希望她不要問太多我個人的事") and never confronted; kai went for 阿明 where the rules wanted to be friendly.

What did not hold, or is not known (written after the pilot; the second round below answers some of it):
- One seed, 19 decisions, and the world diverges from the rules-only one as soon as one choice differs, so the totals cannot be compared day by day.
  Talk tones: hostile 38 against 25 for rules only, warm 116 against 100, cold 18 against 29, confront 1 against 2. That is a different world, not yet an effect.
- 12 of 19 chose option 0. The options are listed best-first, so this may be anchoring on the first line; not tested (a shuffled order, mapped back, would test it).
- One person woke 12 times of 19: ning's "a clash within reach" fires again and again within a day with nearly the same state. A per-person cap or a cooldown
  would have saved about a third of the questions here; not built yet.
- The provider's real daily limit is not known: 20 requests did not meet one.

## Second round (2026-10-02): a per-person cap, shuffled options, 3 seeds x 7 days

Changes: `--per-person-day 2` (default; a person's mind wakes at most twice a day) and the options shown in a deterministic shuffled order
(the answer is mapped back to its rank; tested: a mind that chooses by what an option says gives the identical world shuffled or not).
Same model, tier A, seeds 501, 502, 503, jianghu_story_v1, 7 days, each against the same world with rules only.

| | 501 | 502 | 503 | together |
|---|---|---|---|---|
| minds woke | 23 | 23 | 35 | 81 |
| requests sent | 23 | 23 | 36 | 82 (one retry) |
| answers usable | 23 | 23 | 35 | 81 / 81 |
| chose something other than the rules' favourite | 13 | 7 | 25 | 45 / 81 (56%) |
| chose the rules' favourite | 10 | 16 | 10 | 36 / 81 (44%; by chance about 14%) |
| chose the line shown first | 2 | 4 | 3 | 9 / 81 (11%; by chance about 14%) |

The ledger stood at 102 requests for the day and the provider never said no: the daily limit of gemini-3.5-flash-lite is above 102.

- **The cap works**: 3.3 wake-ups a day against 6.3 in the pilot (about half); the 12-of-19 for one person is gone (the most for one person in 7 days is 11).
- **CORRECTED by the 11-seed round (docs/soul_scale.md): there is a small pull toward the first line shown.** On these 3 seeds it looked absent (11%, below
  chance), but over 11 seeds the first line shown is chosen 20% of the time against about 14.8% by chance (the 8 later seeds: 26%, one seed 43%).
  It is too small to explain the 62% of choices that differ from the rules, and the rules' favourite is still chosen about 2.5 times as often as chance wherever
  it is listed, but it is not nothing. In the pilot (best-first) 63% chose option 0; shuffled, 38% to 44% do.

What the worlds did, 3 seeds, 7 days, soul against rules only (the worlds diverge as soon as one choice differs, so these are two different worlds each time; n = 3, no interval):

| | soul | rules only | by seed (soul vs rules) |
|---|---|---|---|
| hostile talk | 188 | 80 | 67/48, 32/12, 89/20: more in all three |
| cold talk | 155 | 114 | 28/44, 52/29, 75/41 |
| warm talk | 711 | 722 | no difference |
| outbursts (shove, strike, smash, break down) | 6 | 2 | |
| goals formed | 17 | 13 | |
| tension, frozen v1 metric (mean per day) | 7.97 | 7.84 | 6.3/7.2, 7.4/4.5, 10.2/11.9: no direction |
| tension with the packs' situations | 9.86 | 9.22 | |

So the minds are not softer than the rules here (the first pilot's worry, from experiment A, "free models are all warm", did not repeat): they
were harsher, in all three worlds, where the person is angry or has a wound; they also avoid, doing nothing or chatting about something safe, where the
rules wanted to confront (ning, yun). Whether that makes better drama is not shown: the v1 tension is the same on average and points in different directions
by seed. What can be said is that the same world becomes a different world with a mind in it, and that the unspoken thoughts
(`inner`) are consistent with each person's wound and secret (kai: afraid of being surpassed by 阿明 before the master; yun: the ring must not be found out;
mei: pretending the lost ring is not lost).

Not done: these thoughts do not reach the episodes (the speech layer still writes its own lines; `inner` is in decisions.jsonl only); more seeds and days
for an interval; a second model for the most dramatic decisions.

## Eleven seeds (2026-10-02)

Seeds 504-511 were added with the same setting; the paired bootstrap, 90% intervals, and what holds are in `docs/soul_scale.md` (`python soul_stats.py`).
In short: more hostile talk with a mind in it (+22 a world, [+10, +36]), more cold talk and outbursts (small), fewer confront and accuse (-2.0, [-3.4, -0.7]); no
difference in warm talk, goals formed, or tension (v1: -0.02, [-1.9, +1.8]). The second round's "no pull toward the first line" is corrected above.
