# Prior art: self-running story worlds

Surveyed 2026-09-29 before designing world stakes (Experiment C). Sources were read at the level of abstracts, READMEs
and project pages, not full papers; licences are as stated on the repository page.

## Does anything already do the whole thing?

No open project goes from a persistent simulated world to daily produced episodes.

- **Fable Studio, SHOW-1 / Showrunner.** This is the closest match, and it is closed source. Its own write-up says the
  South Park demo was driven by time of day and location plus GPT-4's knowledge of the show, not by simulated events.
  It lists the "tension between simulation-driven and narrative-driven events" as unresolved. Our bet (the world
  produces the events, production only films them) is exactly the open part.
  https://fablestudio.github.io/showrunner-agents/

## Our Experiment A finding is a known effect

- **ANIMASK** (Zhang et al., arXiv 2609.16667, Sept 2026): 40 stories, 3,846 decision points. They found that "the persona
  guarantees who the character is, and the model sets how far the character will go". Replays drift to flatter, cooler
  stories, and when persona and model disagree the model picks caution.
- The research on LLM cooperation says the same thing: models write cooperative strategies well and conflict poorly.

Consequence: prompts will not produce drama. Pressure has to come from world rules (scarcity, secrets, consequences),
and the model should choose among options the rules offer.

## What to borrow (ideas, not code, unless noted)

| Source | What it gives us | Use |
|---|---|---|
| Story sifting: J. Ryan, *Curating Simulated Storyworlds* (thesis); Kreminski's **Felt**, **Winnow** (github.com/mkremins/winnow, JS, licence not stated), *Select the Unexpected* (ICIDS 2022) | Declarative patterns that find stories in an event log. Winnow matches **partial** patterns incrementally, so it catches stories that are still unfolding. StU scores sequences by how unlikely they are. | Replace the hand-coded arc finder with declarative patterns. Partial matches tell the "camera" where a story is starting, which is the Truman-style cut-in. |
| **Talk of the Town** (github.com/james-owen-ryan/talktown, MIT, Python) | Knowledge that spreads, is misremembered and forgotten, and lies (a lie repeated often enough is believed by its teller). `drama.py` lists story patterns: unrequited love, love triangle, extramarital interest, asymmetric friendship, rivalries (sibling, business). | We already have claims and tell/lie. Take the pattern list and misremembering. |
| **RimWorld** AI storytellers | A tension meter (0–1, decays about 0.03 a day) and a storyteller that injects world events (raids, sickness, windfalls) to follow a curve. | A rule-based pressure injector: a debt falls due, someone is laid off, a wallet is found. It changes the world, never the plot. This is also Christof's role in *The Truman Show*. |
| **Comme il Faut / Prom Week → Ensemble** (github.com/ensemble-engine/ensemble, JS); **Versu** social practices | Rule-based "volitions": traits plus relationships plus recent events score each social move. Social practices offer affordances, and the agent chooses. | Give the ambient cast rule-based motives instead of today's random `SeededDecider`. This is free and deterministic, and it is also the menu the model chooses from. |
| **Humanoid Agents** (github.com/HumanoidAgents, EMNLP 2023 demo); **Lyfe Agents** | Needs, emotions and closeness as fast numeric state; cheap option-then-action decisions. | Needs and money as world state that creates pressure; fewer model calls. |
| **Concordia** (google-deepmind/concordia, Apache-2.0, 1.7k stars, active); *Multi-Actor Generative AI as Game Engine* (2025) | An LLM game master resolves free-text actions; there is a "Dramatist" use case. | Do not adopt: an LLM referee breaks deterministic replay and doubles model calls. Our rules-as-referee design is the deliberate difference. |
| **StoryVerse** (FDG 2024), **IBSEN** (ACL 2024, github.com/OpenDFM/ibsen) | An author or a director agent sets plot goals, and actor agents are steered towards them. | Not now: it is a narrative LLM inside the decision chain, which our rules exclude. Reconsider only if world pressure is not enough. |
| Automatic cinematography: film-idiom and editing-pattern research (e.g. *Thinking Like a Director*, ACM 2018; *Computational video editing for dialogue-driven scenes*, SIGGRAPH 2017) | Shot/reverse-shot and other idioms as rules; shot selection as optimisation. | Later, for the follow-anyone camera. `render/cast/stage.js` already does basic conversation cutting. |
| Generative Agents / Smallville (joonspk-research, Apache-2.0), AI Town (a16z, MIT) | Memory, reflection and planning loops; a web town viewer. | Architecture reference only; both have the same agreeable-agent problem. |

## Plan change

Experiment C is redesigned around borrowed pieces rather than new inventions:

1. Resources and needs (money, debt, job) with consequences.
2. A storyteller that injects pressure events on a tension curve.
3. Private acts, discovery, suspicion and accusation, built on the existing claims.
4. Rule-based volitions for everyone. The active characters' model picks from the options the rules offer, so dramatic
   options are on the menu when the pressure is high.
5. Declarative story patterns with partial matching. They drive the daily pick and a "follow this story" camera.
