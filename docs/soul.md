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

## 看角色心裡想什麼（2026-10-02）

上面說「這些想法沒有進導播室」，現在可以了，而且不花額度：

    python -m channel.studio --mind out/soul/soul503 --out out/studio_mind --port 8821

它把這個世界用 `llm_cache.db` 裡已付費的答案重播一遍（`LLMClient(mode="replay")`：快取沒有的請求丟 `CacheMiss`，不會連網），並且要求重播出的事件和 `world.db` 逐筆相同、
決定和 `decisions.jsonl` 相同，不同就不顯示。導播室裡，由心智決定的行動有小標「LLM」，展開看他說的話、心裡想的（`inner`）、為什麼醒來、規則最想做的是什麼；人物頁有「心聲」；
3D 觀測台的氣泡下面有一行紫色的「心聲」。細節在 `docs/studio.md`「看有 LLM 的世界」。這一節沒有改前面的任何數字或結論。

## 提示 v2（2026-10-02）：江湖世界的人不該說「想買新手機」

審查在 soul-503 的 LLM 答案裡看到：江湖角色說「想買馬跟新手機」「那張新專輯」「這盆多肉」，選項是「聊音樂」「偷偷找別的工作」；理由與選擇矛盾（選「聊做菜」卻說「我真的沒拿日記」）；她／他混用。原因有兩層：江湖名冊沿用小鎮的人生（這個由新內容包 `jianghu_drama` 處理，見 `docs/jianghu_drama.md`），以及提示本身不知道時代、不知道性別、也不檢查答案。

**v1 一個字都沒動。** `CharacterAgent(prompt_version=1)` 是預設，`PROMPT` 的 sha256 在 `tests/test_drama_content.py` 寫死（`38a88fe4…670422e`）；已記錄的世界（soul501..511）的答案以提示全文為鍵，`channel.studio --mind out/soul/soul503` 重播仍然 1102 個事件逐筆相同。v2 是**另一個提示**，快取鍵自然與 v1 分開，不會撿到 v1 的答案。

v2（`CharacterAgent(prompt_version=2)`；`soul_lab.py --prompt-version 2`，預設 1）加了：

| | |
|---|---|
| 時代一句 | 從配方的 `core` 讀（`martial_arts`）：「這裡是古代的江湖：沒有手機、咖啡、辦公室、電影，也沒有大學或公司；人們說的是師門、鏢局、客棧、銀兩，用的是劍、茶與酒。」沒有登記時代的世界不說。 |
| 性別與代名詞 | 狀態的 `who` 多一格「性別：男（他）」；提示裡一行「人物的稱呼：林嘯＝他、沈青璃＝她…」（狀態裡出現名字的人）。 |
| 選項用世界自己的詞 | 話題用名冊的標籤（「聊琴曲」，不是「聊音樂」）；工作的選項用此人的工作詞（「偷偷打聽別的門派」、「接受邀請，離開師門」）；`break_up` 在江湖寫「向X說清楚，從此不再往來」。 |
| 理由要和所選項一致 | 提示要求 reason 講被選的那個人與那件事，不要提別的選項。 |

**輸出檢查**（`check_answer`，只有 v2）：不合格就丟 `AnswerRejected`，由規則決定這一次（記為 `agent_failed`，同時 `agent_rejected`；`decisions.jsonl` 寫 `error: AnswerRejected` 與原因，不算答案）。這是 provider 有回答的情況，所以**不**計入「連續 5 次失敗就停」。三項：

1. reason 或 inner 含這個時代沒有的詞（`MODERN_WORDS`，46 個；只有世界有登記時代才查，小鎮不查）；
2. reason 提到的人或東西只屬於別的選項、完全沒提所選項的人與東西（人與物名從世界讀；選「什麼都不做」不查）；
3. 他／她不對：reason 與 inner 提到的人（加上所選項的對象）全是同一種性別，卻用了另一種的代名詞（「他們」「其他」「他人」不算代名詞）。

這些是檢查**字**，不是檢查心思：誤殺的情形是理由提到了另一個選項的人但其實有道理（「看到林嘯我就煩，找個人聊天吧」選了別人），或提到未點名的第三人用了另一種代名詞；代價只是這一次換規則決定，花掉一個額度。誤殺率沒有量過（沒有真的 LLM 的 v2 答案）。

用法與限制：

    python soul_lab.py --name drama501 --recipe jianghu_drama_v1 --seed 501 --days 3 --prompt-version 2 --daily-limit 20     # 新世界，要額度
    python soul_lab.py --name drama501 --recipe jianghu_drama_v1 --seed 501 --days 3 --prompt-version 2 --dry               # 假心智，$0

- v2 世界在 `world.db` 的 `meta` 寫 `prompt_version=2`；接續時版本不同會拒絕（它的答案是以那個提示快取的）。v1 世界什麼都不寫，與以前一樣。
- 導播室重播 v2 世界時，`channel/studio.py` 的 `mind_info`／`_init_mind` 要讀 `meta.prompt_version` 並傳給 `CharacterAgent`（那個檔案不在這一輪的範圍；沒傳會用 v1 提示、對不上快取）。
- 這一輪**沒有呼叫任何真的 LLM**：v2 的提示用假心智（`--dry`）驗過內容與管線，答案的品質（現代詞是否真的消失、被擋掉的比例）要等有額度時才量得到。

## Heard in their own words (2026-10-02)

A mind's `reason` used to be visible only in the control room's notes; on screen the person said a template line. Now (`narrative/speech.in_own_words`):
- **Said to somebody** (the reason contains 你): it is what they say; the template is kept as `template`. In an event whose line reads the result
  (duel, challenge, confront, accuse) the reason was written before the result, so it is said first (`opening`) and the result line stays.
- **Said to oneself** (everything else): shown as a thought (`monologue`), never said to the other.
- **Out of its era** (a modern word in a wuxia world): not used; the template stays.

Measured first: of 230 recorded decisions only 21 (9%) are addressed to somebody, so using every reason as speech would have put the person's
explanation of themselves into their mouth. Over the 11 recorded worlds (replayed from the cache, no quota): 221 minds have an event, 26 of those
reach an episode's scenes: 1 says its own line, 4 open with their own words, 12 are heard as a thought, 9 keep the template (a modern word, or no
reason). In 3D, 15 bubbles carry the person's own words.

## Prompt v3: the words said out loud (2026-10-02)

v2's reasons came back as first-person narration in 59 of 59 answers ("我走近柳含霜身旁，與她聊起近日收集的藥草。"), so nobody said anything of
their own. v3 is v2 plus one answer, `say`: the words said out loud to the other, or nothing. v1 and v2 are unchanged (their caches stay valid);
`soul_lab.py --prompt-version 3`. With `say`, the person is heard in it (`in_own_words`), and the reason becomes the thought shown beside it.

jianghu_drama_v1, seed 701, 7 days, gemini-3.5-flash-lite: 27 requests, 27 answers, 0 rejected, **27 of 27 with words said**, 0 modern words. E.g.
秦硯舟 to 謝臨川: 「謝師兄，近日門派發的月俸不知可還夠用？我手頭正有些銀兩的帳目想跟你討教討教。」 thinking 「哼，裝什麼風雅，還不是靠家裡接濟。」
Not measured yet: more seeds, and whether the said words and the chosen tone always agree (a cold choice said warmly is not checked).
