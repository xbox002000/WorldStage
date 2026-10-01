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
