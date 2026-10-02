# The control room (導播室): one world, one page, the story and the 3D world together

`python -m channel.studio` runs a produced world one day at a time (default: the martial-arts story world in its own space,
`jianghu_story_spatial_v1`, the greedy producer), lets the episode planner shape each day's episode, writes `studio.json`, a page
(`render/studio/`) and the 3D God View of the same world (`render/godview/`, in a frame), and serves them at http://127.0.0.1:8795/.

**The two used to be separate** (`channel/live.py`, the 3D God View, shows *where* people stand; the control room shows *what is being told*).
They are now one page over one world, with links both ways: 導播室 | 世界現場（3D） at the top.

- **From a scene to the world**: every scene card has 「▶ 在現場看這一幕」; the episode has 「從第一場在現場看」; a person has 「在現場看他」. The 3D view
  opens at that moment, in that place (and follows that person), playing at 1x.
- **Watch an episode**: 「▶ 在現場播放這一集」 opens the 3D world and follows the episode's scenes in order, a few seconds each, at 1x (with what people say as bubbles: the line, its subtext in small type, the answer, those who watched).
- **From the world to the story**: in the 3D view the first button of the bar is 「↩ 回導播室」: it goes to the episode of the day the clock is at.
- **Switching worlds**: the 「世界」 menu at the top lists every world (one folder each under `out/studio`) and 「＋ 新增一個世界…」 makes
  another (小鎮日常, 江湖故事; a seed; how many days to run first; it takes 1–3 minutes, during which the page does not answer). A world made in
  this run can go on; one left by an earlier run can be read, not continued. `--preset town` opens the town first;
  `--recipe jianghu_story_v1` is the same world without space (faster, no 3D tab).
- The standalone 3D page still works: `python -m channel.live --out out/live --port 8793 [--recipe jianghu_story_spatial_v1]`.

| area | what it answers |
|---|---|
| **Header** | which world, which producer, how many days, how many payoffs and how much of them the people earned; "go on" (one day, seven days) asks the serving process to run the world and rewrites the page |
| **Season strip** | every day at a glance: the column's height is the episode's peak tension, its colour the kind (爽點集 amber, 內在衝突集 violet, 故事線集 blue); under it a filled dot (the producer acted), a hollow one (it kept still on purpose), a star (a payoff). Filters by kind; ← → move between days; the address (`#d=4`) remembers the day |
| **The episode** | the one question it poses, what is left open, small facts (breath, who knows what when, inner conflict, near miss, how many scenes are filmed); for a payoff the six steps (lit: the world produced it; dashed: it did not, and nothing is invented; click one for the events); the tension curve (a dot per scene; click to go to the scene); the scene cards (what the scene is for, who is there, the caption of what happened, what it changed in feelings and relationships, who stood against whom); the scenes not filmed, with why |
| **Producer** (side) | this day's decision in plain words (acted, or kept still and why), what it did and what it cost, its strength (輕/中/重), the producer's private reason, the week's budget, the world's rhythm (calm, warming, peak) |
| **Payoffs** (side) | every payoff of the season, how much of it the person earned themselves against the producer's set-up or luck; click to go to its day |
| **Story state** (side) | the stories the world has formed, as of that day (`narrative/state.py`): the running threads and for how many days each has *not moved*; who the audience knows to be more than they are taken for, and for how long it has waited; what is a step from happening and what it lacks; what has been told (by mechanic and by pair); who carries most unanswered |
| **People** (side) | by what has piled up unanswered; real martial skill against what everyone takes it to be (a gap is "被低估"); a person's closest ties, debt and payoffs |

## The character timeline (角色時間軸, phase 5)

The second button at the top, 「角色時間軸」, shows **one person across the whole world**: pick somebody (the buttons at the top, each with how many
moments they have), and every day is one cell, oldest on the left. The grid scrolls sideways inside its own box (the page itself never does; the
row names stay in place), so it also works at phone width.

| row | what it shows |
|---|---|
| **天** | the day; the colour under it is the kind of that day's episode (as in the season strip). Click: that day's episode |
| **角色** | what the person was in that day's episode: 主角 (dark), 配角 (light) or not in it (·). Click: that episode |
| **心情** | a line through the days: how pleasant the day was (above the middle line: pleasant), a dot per day (green/red), the tooltip says the feeling the day is remembered by |
| **重要時刻** | marks for the moments that matter: 爽點 ★, 愛情 ♥ (confession, date, break-up), 突破 ▲, 失控 ⚡ (a shove, a blow, smashing something, breaking down), 背叛與揭穿 ✕ (a lie or a distortion exposed, caught in the act, wrongly accused, a theft), 比武 ⚔, 改投 ⇄ (founding a faction, joining, leaving, going over to another), 目標改變 ◎ (formed, transformed, abandoned, completed) |
| **關係轉折** | somebody's affection or respect for this person crossed zero and stayed across it (↑ green: became warm, ↓ red: turned cold; the mark says who) |

Under the grid, 「發生了什麼」 lists the same moments in time order, in words (the line of the world's own caption, a note, who was the lead in it, when and where).
The legend over the grid is also the filter: click a kind to hide it. 「他是主角的集」 lists the days he led, and 「到他的人物頁」 goes to the People tab (and the
People tab's detail has 「看他的時間軸」).

**Clicking a mark, a row or a day goes to the story**: the episode of that day, with the scene that shows the event picked out (the same focus as clicking a
point of the tension chart). Many moments are *not* in a filmed scene of their day's episode (a goal is formed at midnight; a shove the episode did not
choose); those go to the day, and the page says so (a line on the row, a notice when clicked from the grid). 「▶ 在現場看」 on a row opens the 3D world at that
moment and place, following the person (the existing `seek`); outside the 3D replay window (the last 30 days) the button says 「超出範圍」 and clicking it
tells the window instead of doing nothing.

**Where the data comes from** (`Studio._timeline_day` in `channel/studio.py`, run once per day after the episode is planned; `timeline` in `studio.json`):
a read model over the world; it adds nothing to the world (the test runs it with SQLite refusing every write). Per person: `mood` (the minutes of the day
in each emotion, weighted by how pleasant it is: `happy` 1.0 … `hurt` −0.85, `calm` 0.15), `emo` (the strongest feeling held an hour or more that day),
`role` (a string, one letter a day: `L` lead, `S` supporting, `.` not in it), `ev` (keys of the moments) and `turns`. The moments are stored once, in `events`
(`id`, `k` kind, `d` day, `t` seconds, `c` clock, `cap` caption, `w` who, `plid` place, `b` the scene of that day's episode that shows it, `n` a code the page
puts into words, `x` an extra such as the goal's text or the factions, `h` who acted or won), so a duel with two people is one record. Every record has its
event id, day and time; `b` is only there when the event is in a filmed scene of that day (the tests check it really is). The page tolerates fields it does not
know and kinds it has no word for, and an older `studio.json` without `timeline` shows a sentence instead of the view.

Choices and limits:
- **The lead of an episode is a reading, not a record.** The planner does not name one. It is the payoff's protagonist if the day has a payoff, otherwise the
  person who is in most of the filmed scenes that matter (the scenes that are not a reaction shot or a texture moment, each counting 1 + its tension); one
  lead a day at most, the others in the episode are supporting.
- **A turn needs to pass ±0.15 and stay across it** (so that 0.04 → 0.13 is not a turn). It watches affection and respect others hold *about* him, not what
  he feels about others, and not trust or resentment.
- **Only these kinds are marked.** An ordinary conversation, a flirt, a walk, a meal are not moments; neither is the day's `reflection`. A world with
  quiet days has a timeline with few marks; a person who is rarely in anything has few (the numbers on the buttons say so). 目標改變 is the most frequent
  by far (it includes small chores like finding a lost wallet): hide it from the legend to see the rest.
- **The mood is the world's own emotion, not an inner state**: people are `happy` most of the day in these worlds, so the line sits above the middle and
  the dips are what matter.
- **Size**: the timeline is written a day at a time and each moment once (not once per person). Measured on `--preset jianghu` (seed 501), `studio-data.js`
  with the timeline against without it: 10 days 127,642 B vs 122,900 B (+3.9%); 14 days 187,961 B vs 179,801 B (+4.5%, 29 moments and 8 turns);
  28 days 450,864 B vs 430,304 B (+4.8%, 90 moments and 14 turns). So nothing had to be thinned out; the limit the tests keep is 25%. In the page, the
  28-day world loads in about 0.2 s, and drawing a person's timeline takes 12–50 ms.
- It does not follow the person into the 3D world's own timeline, and it does not read `narrative/observatory.py` (that one is built from a whole database at once; this
  one is written a day at a time, as the world goes on).

Design choices: one question per screen, plain Chinese words for every internal term (the ladder, the shot intents, the six steps),
colour only for kind and for good/bad change, nothing that needs a legend to be read twice (the 「怎麼看這一頁」 button has one),
light and dark, phone width to wide screen, keyboard (← →, Enter on a chart point). It only reads; the single request it can make
is "go on".

`studio.json` and `studio-data.js` carry the same data (a world left by an earlier run can be opened from the file system, without the 3D frame's "go on"), so the built page also opens straight from the file system.
Tests: tests/test_studio.py.

## 看有 LLM 的世界（`--mind`）

`soul_lab.py` 讓角色的心智（LLM）做決定，結果是一個普通的 `world.db`，旁邊有 `decisions.jsonl`（每個醒來的心智：他說什麼、心裡想什麼）和 `<name>.llm_cache.db`（每一筆已付費的答案）。
導播室可以「看」這種世界，而且不花任何額度：

    python -m channel.studio --mind out/soul/soul503 --out out/studio_mind --port 8821     # 開 http://127.0.0.1:8821/
    python -m channel.studio --mind out/soul/soul503 --mind out/soul/soul504 ...           # 可以重複，都出現在世界選單

**做法：把同一個世界只用快取重播一遍。** `Studio(out, mind=<資料夾>)` 用和 soul_lab 完全相同的設定重跑：同一個 recipe 和種子（讀 world.db 的 meta）、沒有製作人、
沒有 feed（`Simulation(c, agent, agent, set())`）、`CharacterAgent(tier="A", budget=20, per_person_day=2, shuffle=soul_lab.recorded_order)`，
心智換成 `ReplayMind`：`LLMClient(mode="replay")` 配一個以唯讀打開的 `llm_cache.db`。replay 模式遇到快取沒有的請求會丟 `CacheMiss`，沒有後端、不會連網，快取也寫不進去
（`agent/cognition.py` 會把任何錯誤吞掉改用規則，所以 `ReplayMind` 另外記下每一次 miss，一天跑完就停下來，不讓規則默默代替心智）。
**重播必須和原來的世界逐筆相同**：跑完後比對 `world.db` 的每一個事件（id、type、timestamp、location、truth），再比對重播出的決定和 `decisions.jsonl`；任何一處不同，
`MindReplayError`，什麼都不寫（不顯示一個「差不多」的世界）。世界不能續走：快取只有已付費的答案，再走一天要問新的問題。

**心聲是怎麼掛上去的。** 心智決定的行動，事件的 truth 裡 `reason` 是 `agent:<他說的話>`、`source` 是模型名；決定本身在 agent 自己的 log（`agent.log`）。`pair_minds()` 把兩邊配起來：
同一個人、同樣的話、時間在決定那一刻或之後、最近的、還沒被別的決定用掉的事件。選了「什麼都不做」的心智沒有事件（`event: null`），只在那天的列表和人物頁。配對是讀模型，世界從不讀它。

`studio.json` 多出的東西（只有這種世界才有；沒有心智的世界一個欄位都沒有）：
- `meta.mind`：模型、心智次數、有事件的／什麼都不做的次數、快取答案數、重播了幾件事、重播設定。
- 每個由心智決定的事件（導播室場景、爽文六步的事件、3D 存檔的事件）有 `mind: {reason, inner, wake: [...], chose, rank, of, rule_top, model}`
  （`rank` 是他選的那個在規則的排名裡第幾位，0 是規則最想做的；`of` 是選項數；`rule_top` 是規則最想做的那一項）。3D 存檔裡只帶 `{reason, inner}`。
- `minds.items`：每一次醒來一筆（`n`、`person`、`name`、`day`、`t`、`clock`、`event`、`place_id`、`beat`（拍進了那天哪一場戲，才有）、以及上面那些）。

**頁面上看到什麼**（都在 `studio.js` 裡，只有資料有 `minds` 才會出現；沒有心智的世界頁面完全沒變）：
- 頁首多一條說明，晶片多一個「心智」；「再走一天」「再走 7 天」變淡，按下去說明原因（額度與快取的限制）而不是真的送出請求；選單上這個世界標「只能看」。
- 每天的集裡，「這天誰動了心思」一張卡：每個醒來的人一列，小標「LLM」，展開看「他說：…」「心裡想：…」（淡色斜體）「為什麼醒來：…」和「規則最想做的是…，他選了…」；沒拍進場景的也在這裡；
  拍進場景的，那張場景卡也有「LLM」小標和同樣的展開，並有「到那場戲」。
- 人物頁多一個「心聲」區：這個人最近幾次的心聲，點一則跳到那一刻（有場景就跳到場景，沒有就跳到那天列表的那一列）。人物列表的小字多「心聲 N 則」。
- 3D 觀測台：由心智決定的說話事件，氣泡下面（潛台詞的小字下面）多一行紫色斜體「心聲 …」，和語言層的潛台詞（淡灰括號）分開；沒有心智的事件沒有這一行。有心聲的氣泡多停留 3 秒。

限制與選擇：
- **三種東西不是由心智決定的，就不會有心聲**：規則決定的日常、被失控接管的行動、以及心智選了但世界沒有照做的（沒有配對到事件，只在列表裡）。大部分場景卡因此沒有「LLM」小標：
  導播室的集挑的是整段故事的高潮，而心智在 tier A 下每天只醒來 3 到 5 次，多半在平常的聊天。所以「這天誰動了心思」那張卡才是主要入口。
- **這個世界沒有空間配方**（`jianghu_story_v1`）。3D 用 `WorldRuntime(conn)` 從事件重新排出位置，和 `python -m runtime.godview` 對任何 world.db 做的一樣；它不是 `jianghu_story_spatial_v1` 的世界。
- **要有 `world.db` 和 `<資料夾名>.llm_cache.db` 兩個檔案**（soul_lab 的資料夾約定）；資料夾名就是 key 的來源（`soul-<種子>`）。若當初不是用 soul_lab 預設的 tier / 每人每天次數 / 預算跑的，重播的事件會不同，這個模式會直接報錯而不是硬做。
- 啟動要把世界重播一遍再排 3D：seed 503（7 天、1102 件事）約 35 秒（重播約 6 秒，3D 存檔約 25 秒）。頁面本身載入約 70 毫秒。
- 大小：seed 503 的 `studio-data.js` 是 125,763 B，其中心聲相關的資料約 16,300 B（+14.9%）；3D 存檔多約 5,800 B。

測試：`tests/test_mind_view.py`（用小世界和 stub 答案：重播與原世界逐筆相同、配對不錯位、沒有心智的事件沒有 `mind`、快取沒有的請求丟錯而不是連網、少一筆答案就停下來；有 `out/soul/soul503` 時再用真的跑一次）。

## 劇本問題（每集的檢查，`narrative/lint.py`）

每一集的頭部，在那一排小標籤的最後，有一顆「劇本問題 N」。N 是劇本檢查器（唯讀，`script_lint_v0.1`）對這一集作為一份文字的檢查結果；0 是綠色，大於 0 是紅色。
點它展開，依代碼分組列出每一項（L1 人稱不對、L2 把語氣當八卦、L3 日期／重播、L4 順序／系統詞、L5 問題有毛病、L6 現代詞、L8 台詞與勝負不符），
每項寫明是哪一種毛病、哪一句話，並有「到那場戲」跳到那個場景。底下一行是重複度：同一句台詞重複幾次、同一組人連拍最多幾拍、聊天／傳話／質問佔幾成的拍。
季節條上有問題的那一天，數字下面有一個紅色驚嘆號；頁首晶片「劇本問題」是整季的總數。規則世界和 LLM 世界一樣（`--mind` 的世界也有）；舊的 `studio.json`（沒有 `lint`）看不到這些，頁面不會壞。

`studio.json` 多出的欄位：
- `lint_days[]`（和 `days` 同序，不放進 days 裡）：`hard` 是那天的硬事件（比武、推人、離開師門、揭穿、告白、繼位…，`{id, type, kind}`），`facts` 是世界對每件東西已經定下來的事（誰的、有沒有別人拿過、哪天找回來），用來檢查「誰拿了X」的前提。
- `days[].episode.lint = {version, count, items: [{code, kind, day, event_id, text}], metrics: {beats, chat_share, dup_lines, max_pair_streak, pair_kind_repeats}}`、`episode.cold_open`（見下）。
- `meta` 同層的 `lint`：整季報告（`narrative/lint.py season_report`：各種毛病的數量、聊天佔比、硬事件入集率）。
- 每個事件多一個 `facts`（比武誰贏誰輸、talk 的語氣、傳話的 claim 種類）；每個場景可能有 `recap: true`（這件事發生在前幾天，這裡只是交代背景，頁面標「前情」）；
  蒙太奇的一拍有好幾個 `event_ids`，`reason` 以 `montage` 開頭，頁面標「蒙太奇 N 回」，只演第一回的台詞。

**冷開場**（`episode.cold_open`，B11）：每集標題下面一句「誰想要什麼、輸了會失去什麼」，取自角色卡的 `core.want`／`core.fear`（最高張力那一場的主角，對手也有就加一句）。卡片沒有就不寫；江湖世界裡卡片的句子若有現代詞（例如「存錢買新手機」）就整句略過，不改寫。

劇本問題是讀模型：導播室用 `episode_planner.SHOW`（A/B 故事加上「全季的帳」）規劃每一天，帳（已播事件、問的問題）在 `Studio` 裡，不寫進世界。
測試：`tests/test_lint.py`（每一項都有手造的小集證明偵測得到、乾淨的集不誤報、只讀）、`tests/test_studio.py`。
