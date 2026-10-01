# Character OS v1: people who live their own lives (plan)

Written 2026-10-01, from the user's Character OS brief, after the Dramaturgy v0 analysis (docs/drama.md) showed why
a long world goes quiet: after day 14 nobody wants anything that collides with anyone else. The brief's answer is
the right one: lasting, renewable wants that come from who a person is and where their life is.

## What already exists, and what is missing

| Brief | Here now | Missing |
|---|---|---|
| Identity (immutable) | persona text, temperament traits (`personas.traits`), a life goal, a home | age, work, background, interests, dislikes, habits |
| Disposition (stable) | adaptive traits and values (`world/psyche.py`: aggression, withdrawal, cynicism, vigilance...) | social style (with strangers, friends, in conflict), shared-interest behaviour |
| Life State (adaptive) | money, arrears, debt, energy, hunger, job security (a town-wide var), goals | work stress, job satisfaction, fatigue over weeks, one's own job and boss |
| Dynamic | emotion (one field), feelings that now last and settle overnight | intensity; a surface feeling against its cause |
| Relationships | trust, affection, fear, rivalry, debt (directed) | respect, resentment, closeness/familiarity, jealousy |
| Goal stack | one level of goals (recover, expose, revenge, amends...) formed by events | life / season / active / immediate levels; goals born from life state, not only from incidents |
| Character agent | decisions are Intents; rule agent for everyone; LLM deciders exist (Gemini/OpenRouter), cached by request hash, validated by rules | wake points (when a person really needs to think); a compact cognitive state for the prompt |
| Routine | fixed schedules, a few decision moments a day | habits (after work an iced coffee; when anxious, checking the phone) that fill the day and show on stage |

## Adopted

- **The four layers, and change speeds by layer** (immutable, stable, adaptive, dynamic). Content writes the first
  two; rules move the last two; nothing is set by an LLM.
- **Interests as a way into a conversation, and mood can spoil it.** A shared interest makes a good topic; the
  outcome depends on how both feel and whether the other wants to listen, so it can also irritate. Shared dislikes
  and shared enemies make allies.
- **Value conflict as a source of opposition.** A person who values honesty and sees a friend lie thinks less of
  them, without anyone deciding they are enemies.
- **Relationships are directed and can disagree.** A can resent B while B still cares about A.
- **Agents wake on events; they choose, they never write.** The LLM only answers "what would I do", in structured
  Intents, and the rules check them. This is already the architecture (LLMs only propose Intents).
- **Habits as behaviour that can be staged** (they become PerformancePlan and animation).

## Adjusted

- **"Each character has their own LLM."**
  - The budget is $0, and Experiment A showed free models make no drama on their own (warm tone 60%+).
  - So the rule agent stays the default for everyone. A character wakes an LLM only at a wake point: a value
    clash, a major choice, a new situation, a goal in conflict.
  - Every answer is cached by request hash, so a world still replays exactly.
  - Wake points are counted per day, and a budget caps them. With no key, or over the budget, the rule agent decides.
- **New actions need new world.**
  - "Search for a job", "go to an interview" and "turn down an offer" each need world rules: whether one is
    employed, an offstage employer, an offer that can come or not.
  - They enter as one life domain at a time, with a closed vocabulary, not as free text.
  - Work comes first, because it touches five of the ten people every day.
- **Only the relationship dimensions that something produces and something reads.**
  - Eleven numbers per pair that no rule uses would be noise.
  - Start with resentment (from value clashes and wrongs), respect (from competence and keeping one's word) and
    familiarity (from time spent together).
  - Jealousy comes with attraction, later.
- **Identity details that matter.**
  - Age, work, interests, dislikes and habits drive something here.
  - Birthplace and education only if a rule, a line or a compatibility uses them.

## Order of work

1. **Identity content for the ten people** (hand-written, in content). Age, work, interests, dislikes and habits,
   shown in the Character Observatory.
2. **Interests in conversation.**
   - A talk can have a topic (a shared interest, a shared dislike, work, the incident of the day).
   - The effect depends on both moods and on compatibility.
   - Shared enemies raise closeness between allies.
3. **Life state, work domain.**
   - Each worker has a job and a boss (offstage).
   - Stress rises with overtime (a seed) and with clashes at work.
   - Satisfaction falls with stress, rises with recognition.
4. **A goal stack that renews.**
   - Life and season goals from content.
   - Active goals born from life state: stress high and satisfaction low leads to considering quitting.
   - Immediate goals chosen each day.
5. **The work domain's actions:** look for work, interview (a secret, unless seen), an offer, accept or decline.
   Others notice, and the Dramaturgy analysis finds the secret, the near miss and the choice.
6. **Relationship dimensions** (resentment, respect, familiarity), each with the rules that move and read it.
7. **Wake points and the LLM pool:**
   - a compact cognitive state (who I am, what I want and fear, what happened, what I know and do not, whom I trust,
     where I am, what I can do);
   - structured Intents, a daily budget, and replay from cache.

## Status, 2026-10-01 (end of the round)

Built on the domain-pack architecture (docs/architecture/domain_packs.md), so that none of it is town-only.

- **Done:**
  1. Identity content. CharacterProfile and CharacterRoster contracts, one JSON roster each for town_v1 and
     jianghu_v1, stored in the world (schema v5), and a "他是誰" tab in the God View.
  2. Interests in conversation (pack `topics`, primitive social.topics): topics chosen from what one knows; shared
     tastes, dislikes and grudges; mood spoils or lifts it; tastes learnt as claims.
  3. and 5. The work domain (pack `work`, primitive life.work), identical code for a town office and a sect:
     - stress, satisfaction, overtime, praise that stings a rival;
     - a renewable goal to leave;
     - a quiet search that can be seen and told, an offer, and resigning or staying.
  7. Character agents: CognitiveState and CognitiveChoice contracts, wake points, a daily budget, and the rule
     agent as fallback (`agent/cognition.py`). Not yet switched on in any world: it needs an LLM key and a cache to
     replay.
- **Not yet:**
  4. The goal stack's season and immediate levels as world state (the profile holds life and season goals as
     text only).
  6. The new relationship dimensions (resentment, respect, familiarity).
  - Surface against underlying emotion.
  - Habits on stage: they are in the profile and the agent's prompt, and nothing plays them yet.

**Acceptance.** A 30-day world where the Dramaturgy tension curve does not fall to the floor after day 14. It
should renew from the characters' own lives, without new outside seeds. Measured with `narrative/dramaturgy.py` and
`drama_gate.py`, against the old 60-day world (tension 0.5-2 after day 14).
