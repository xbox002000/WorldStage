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
