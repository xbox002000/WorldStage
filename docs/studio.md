# The control room (導播室): one world, one page, the story and the 3D world together

`python -m channel.studio` runs a produced world one day at a time (default: the martial-arts story world in its own space,
`jianghu_story_spatial_v1`, the greedy producer), lets the episode planner shape each day's episode, writes `studio.json`, a page
(`render/studio/`) and the 3D God View of the same world (`render/godview/`, in a frame), and serves them at http://127.0.0.1:8795/.

**The two used to be separate** (`channel/live.py`, the 3D God View, shows *where* people stand; the control room shows *what is being told*).
They are now one page over one world, with links both ways: 導播室 | 世界現場（3D） at the top.

- **From a scene to the world**: every scene card has 「▶ 在現場看這一幕」; the episode has 「從第一場在現場看」; a person has 「在現場看他」. The 3D view
  opens at that moment, in that place (and follows that person), playing at 1x.
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
| **People** (side) | by what has piled up unanswered; real martial skill against what everyone takes it to be (a gap is "被低估"); a person's closest ties, debt and payoffs |

Design choices: one question per screen, plain Chinese words for every internal term (the ladder, the shot intents, the six steps),
colour only for kind and for good/bad change, nothing that needs a legend to be read twice (the 「怎麼看這一頁」 button has one),
light and dark, phone width to wide screen, keyboard (← →, Enter on a chart point). It only reads; the single request it can make
is "go on".

`studio.json` and `studio-data.js` carry the same data (a world left by an earlier run can be opened from the file system, without the 3D frame's "go on"), so the built page also opens straight from the file system.
Tests: tests/test_studio.py.
