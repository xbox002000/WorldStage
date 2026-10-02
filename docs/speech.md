# Speech: what people say, in the situation they are in

`narrative/speech.py` (`speech_v0.1`, a draft). A read model for the God View, the control room and, later, the camera. $0, no model, and it
never reaches back into the world: characters act on claims, never on these words.

**Why.** The first lines (`narrative/lines.py`) gave each kind of event a handful of fixed sentences, picked by the event's number. A cold word
was the same five sentences for everybody, a duel had two, and most of what people do (training, a breakthrough, a loss, an outburst, a changed
goal) was silent. It is *not* that no language model is attached yet: nothing in the world waits for one. The character agent (phase 6) would
change what people *decide*; this changes what they *say*, and a model could later polish these lines (phase 5) without touching the world.

**What it looks at**, as of just before the event (`narrative/audience.value_at` winds the history back): how well the two know each
other, what lies between them (trust, grudge, respect, fear, attraction), who the speaker is (honest, hot-tempered, generous, shy), what each
feels, what each believes the other can do (a duel is asked differently of somebody taken for weak), where they are, the time of day, and who is
watching. A line is chosen among those whose conditions hold, by the event's number, so the same event always reads the same; a line with a
condition counts double, so the situation shows.

**What comes with a line**: the *subtext* where the situation has one (a polite word through a grudge: "話說得客氣，心裡其實還在氣"; a cold word to
somebody loved; a threat out of fear), the other side's *answer* (an accusation's, a confession's, a duel's), and what the people *watching* say
(a duel that overturned what the crowd believed makes the doubters gasp: "怎麼可能……"; a seat won is congratulated by the ones who lost it).

**Talk is about something**: the topics pack records the topic and how it landed (bonded, small talk, irritated, grated, cheered up,
back-biting refused); the line follows ("你也喜歡{topic}？太好了！", "別再提{topic}了。"). In the martial-arts world the topics are said in its words
(the profiles keep the town's topic names; "basketball" is 拳腳功夫, "coffee" is 茶).

**Silent no more**: training (when the crowd takes somebody for less than they are: "他們都小看我……我要練到讓他們閉嘴。"; one in three, or the day is all
murmuring), breakthroughs, a thing taken, lost, noticed missing or found, regret, an outburst, a breakdown, a changed goal.

**Where it shows**: the God View's bubbles (the line, its subtext in small type, the answer, the watchers' reactions) and, in the control room, a
"說了什麼" block on each scene card.

**What it measured** (a produced martial-arts fortnight, 1942 events): 987 events with a line (916 before), 150 distinct talk sentences (43
before), a martial-arts world no longer talks about basketball. **What it did not do**: subtext is still thin (50 in the fortnight, from grudges, loves, fear, and what the speaker feels: a hurt or ashamed person's neutral word, an angry person's cold one), the pools are the first writing (a few lines a situation), and a multi-turn *conversation* is still one line per
event. The next step, if more is wanted, is a model polishing these lines inside the same conditions (recorded, cached, replayable), or more pools.
Romance stays within what a public channel shows (a look, an offer of tea, a confession); every speaker is an adult (the romance pack's rule).

## Underneath the feeling (`narrative/inner_state.py`, `inner_state_v0.1`, a draft; phase 2.3)

A read model of *what somebody shows and what is underneath it*: `{surface: 生氣, underneath: 怕被阿浩丟下, because: {event_id, text}, evidence, confidence}`.
It reads the history up to a line and nothing else: it imports no write path of the world, makes no event, and the same world always reads
the same (tests/test_inner_state.py checks all three, and that an unsure reading is kept in the model but never said).

**How a reading is found.** (1) The event that set the speaker's present emotion (`event_deltas`, `person.emotion`); a night in between
(the settling of anger or shame into unease, `OVERNIGHT`) is followed back to the daytime event, so "uneasy" this morning reads through to the
quarrel last evening, a little less sure (x0.85). A feeling with no event behind it, or one older than two days, is not read. (2) What the
event was to *this* person: their role in it, its recorded outcome or tone, and what held between the two of them *just before it* (relationship
fields, the self-model they had formed, the goal the event itself gave rise to: a `goal_change` that names it as its cause). (3) A closed table
of readings, each with a confidence and the records that make it so. Examples: a cold word from somebody the speaker is fond of (affection >= 0.5
or attraction >= 0.3) reads as "怕被丟下"; a loss in front of two or more people as "怕被人看輕", and once the loss has given rise to a goal,
"不甘心，想著「有一天打贏…」"; a conflict that turned out to be a mistake as "說的明明是實話，卻被當面質疑"; a missing thing as who the owner
suspects and how sure *they* are (never who really took it: the hidden truth is not read).

**Every reading can be checked.** `verify()` re-reads each claim from the history: the cause event exists, is before the line, the person
took part, and it set that very emotion; each relationship field or self-model it leaned on had that value then, and the event that last set
it did set it (`set_by`; None means it was so from the start of the world); each recorded field of the event is what the reading says.

**In speech** (`speak()`): a line keeps the subtext the relationship gives it (the five old rules), and a *bare emotion* subtext ("心裡有事，沒說出口",
"壓著火氣") is replaced by the traced reading when there is one: "表面生氣，底下是怕被阿浩丟下". It is hung on the speaker's *first* line after
the cause and on the first line they say to the person it is about, never on every word of a bad day, and only at confidence 0.5 or more. It rides
on talk, duels, accusations, confrontations, flirting, confessions, break-ups, campaigning, and on a breakdown, outburst, regret, a thing found
missing, and a drill. `speech.INNER_SUBTEXT = False` turns it off (that is the "before" below). The line carries an `inner` block (surface,
underneath, because, confidence, rule) for the God View and the control room; nothing else on the line changes (a test compares them).

**What it measured** (3 fresh seeds 611, 612, 613 x 14 days, `jianghu_story_v1`, 5942 events with a speaker, 3026 of them with a line; the same
lines before and after):

| | before | after |
|---|---|---|
| lines with a subtext (3 worlds) | 179 (57 / 63 / 59 per world) | 300 (76 / 127 / 97): +68% |
| of them with a traced cause event | 0 (the old rules read fields and record no event) | 136 (45%); 136 of 136 pass `verify()` |
| of the 136: every field it leaned on was set by a recorded event | | 101 (74%); 5 lean on a field that was so from the world's start; 30 lean on the event alone |
| distinct subtext sentences | 5 | 64 (the traced ones are 26 once the names are taken out, from 19 rules) |
| tone, line or any other field of a line | | unchanged on all 3026 (the same lines; only `subtext` / `inner` differ) |
| time to speak all events of a world | 0.25 s per 1900 | 0.41 s |

Said at every line instead of once, it would be 441 lines (306 traced): the "said once" rule costs a third of them, on purpose.

**What did not hold, or is still thin.**
- It is +68%, not several-fold. Subtext is still on one line in ten (300 of 3026), and 55% of the subtexts are still the old relationship rules.
- Of the 569 lines spoken by somebody in a bad mood, 241 (42%) have a reading at all. The rest have no rule that holds, and are left silent
  rather than invented: a cold word that hurt with nothing special between the two (123), the speaker's own hostile word with no fondness, fear or
  grudge behind it (76), a hostile word received with nothing behind it (56), being made to train overtime (49: nothing in the records says *why* it
  weighs on this person), an unresolved confrontation (15), a shove (7).
- The readings that carry the numbers are the plain ones. A grudge as the reason behind a hard word (old_grudge, hard_from_grudge) is 42 of
  136 (31%); "對X的戒心還沒放下" on a kind word is 14 and sits at the lowest confidence that is still said (0.55).
- The self-model is almost unused in a fortnight: reflections formed `world_is_hostile` in 2 of the 3 worlds and nothing else, so the rules that
  lean on a self-model fired twice (on_my_own: never; "怕被所有人丟下" is written and tested on a made history, not seen in these worlds). Likewise
  "一直想被看見，今天終於有人看見了" (a praise to somebody who had formed the goal) did not occur in these worlds. They need a longer run or a world made
  with such a past (`character_genomes` formative events).
- The confidences (0.55-0.8) are hand-set priors per rule, not calibrated against anything; nobody has judged whether a viewer would agree with
  the readings. "Traceable" means the records say so, not that the reading is the truth of the person.
- A feeling is one word in the world, with no intensity, so "表面開心" with something underneath is read only for a doubted winner or a kind word to
  somebody hurt; calm and most happy moments have nothing.
- Not done: the observatory and the episode plan do not read it yet (they can: `inner_state(conn, person, event_id, names)`); only the speech and
  its God View / control-room carriers do. Its sentences are the first writing, like the pools.
