# The Persona layer: Genome, Instance, Branch

Phase 1B of the plan. Contract: `contracts/persona.py`. In a world: `world/personas.py`. Tests: `tests/test_persona.py`.

```text
source -> (Persona Compiler, later) -> CharacterGenome -> CharacterInstance (a person in a world) -> life (events)
                                                           SimulationBranch = which run it is
```

## What is what

| | what it is | where it lives | changes? |
|---|---|---|---|
| **CharacterGenome** | temperament, values, tastes, habits, how they decide, how they speak, what they know, what made them, what they believe | `character_genomes` (schema v7), one row per person | never (triggers refuse update and delete) |
| **CharacterProfile** | the stable core of the genome that the rule agents and domain packs read, plus the part the person plays in this world (job, season goal) | `character_profiles` | never |
| **CharacterInstance** | a genome living as a person in a world: genome id, branch id, person id | derived from the two tables above | state moves by events |
| **SimulationBranch** | recipe and its hash, ruleset hash, cast hash, seed, who decides, where it was forked from, visibility | `meta('branch')` | rewritten only by a fork |

The genome is not the person. Casting (the job and the season's goal) is the world's, so it is in the profile the agents
read and **not** in the genome: one person has the same `genome_id` in the town, the jianghu and any later genre, and
two worlds of one genome become different people by living. The id is the content hash, so any change to a genome is
a different genome.

## What exists, and what it replaces

- The existing casts need nothing new: every person of every recipe is lifted into an `original_character` genome from
  their roster entry, temperament and one-line persona. No events were added and the behaviour fingerprints are unchanged.
- A content pack that wants more writes `world/content/genomes/<content>.json` (`{"people": {"yun": {...}}}`) with any of
  `decisions`, `expression`, `knowledge`, `formative`, `beliefs`, `origin`.
- **Formative events.** Each `formative` entry (childhood, turning point, loss, success, relationship) is written at
  world start as a `backstory` event with a memory for that person, so what made them is world truth: it can be
  remembered, whispered about and traced (1B.4 follows a behaviour back to it).
- The branch is written when the world is built. `schema v6 -> v7` adds the table and nothing else; worlds made earlier
  have no genomes, and every reader returns None or empty for them.

## Real people (the user's rule: public, but renamed)

- `public_person` genomes are research material. A world that holds one that has not been fictionalized is a
  **private branch** (the branch says so by itself) and `assert_publishable` refuses it. `channel/daily.py` calls it
  before anything is made, so such a world is never filmed.
- `fictionalize(genome, name=, replacements=, remove=)` makes the genome that may be published: another name, invented
  stand-ins for a company or a hometown, identifying details dropped (a list item that mentions one is removed whole,
  a text field is emptied). It checks its own work and returns nothing if the real name, an alias or a removed detail
  is still anywhere in it. The new genome records what it was derived from and not who; its `real_names` are empty.
- It returns the **ban list** (real names, aliases, removed details) separately. Keep it in the private research store.
  `scan(texts, banned)` is what the publish gate (phase 8) runs on subtitles, lines, titles and descriptions.
- A nickname nobody listed cannot be found by any program. The author lists it in `remove` or the Persona Compiler
  collects it from the sources; the self-check only guards what is listed.
- No genome is ever made of a private individual (a rule for the Persona Compiler, phase 7).

## Not done here

`influences` in decisions and the circumstance probabilities are 1B.3; the three memories and the causal audit are 1B.4;
the evidence graph (why each field says what it says) is 1B.2; the lab is 1B.5. `fork` is recorded in the branch, but
nothing forks a world from another's snapshot yet (1B.5).

## 1B.3 Why a choice was made (`agent/trace.py`)

In worlds with `social.exchange`, every event that came from a decision or an answer carries `truth.influences`:

```text
p          how likely the chosen option was (the exact softmax probability, not a sample)
options    the best three with their probabilities: {action, target, how (the stance of an answer), tone, p}
factors    what was leaning the options in play
           - self_model: {key, strength, leans: {accuse: 0.3}}   only models that lean an option shown
           - goal:       {slot}                                   the goal that pushed it
           - body:       {arousal, control, tired, hungry}        from the body pack (Domain.influences)
situation  for an answer: {kind: reply, to: <event id answered>, heat, wrong, accused}
seized     losing control: p = 1, and the body that caused it
```

It is a record and nothing else. The test runs the same worlds with it off and compares every event except the record:
identical. Compared with the commit before this work (three recipes, 1 to 8 days, 144 to 1228 events each), the event
streams without the new keys hash identically. Worlds without exchanges (town_v1, jianghu_v1) are not touched at all.

## 1B.4 Three memories and the causal audit (`narrative/causal_audit.py`)

- **facts**: what someone believes happened (their memories).
- **experiences**: what it did to them. Each night's reflection now lists which event gave how much of each experience
  (`truth.experienced`: {kind: [[event, weight], ...]}), where it used to keep only the totals.
- **interpretations**: how they came to see themselves. A reflection records the self-models it formed or softened
  (`truth.formed`, `truth.softened`).

`trace(event)` follows a choice's factors back: a self-model to the reflection that formed it (the latest before the
choice), that reflection to the events behind the experience that built it. A chain is whole when every link exists,
comes before what it explains, and involves the person. A body factor is a state, not a memory, and is listed, not traced.

Measured: 20 sampled choices a self-model was leaning, in each of four 30-day worlds (candidates 490, 642, 637 and 583
choices): 20 of 20 chains whole in all four. A choice claiming a self-model nobody formed is reported as broken (test).

## 1B.2 The evidence graph (`world/persona_evidence.py`)

`PersonaEvidence` (contracts/persona.py) says why a genome says what it says: sources, and claims with a kind (stated,
inferred, authored), a confidence, the evidence behind each, and the claims it disagrees with.

- It is research and authoring data, kept next to the genome, never in world.db; no rule reads it.
- `fields(genome)` lists every filled-in statement of a genome as a path; `uncovered` says which no claim speaks for;
  `check` refuses a graph with gaps, claims with nothing behind them, unknown sources, bad confidences or contradictions
  that point nowhere. For an invented character `authored(genome)` is the author's word for every field and passes.
- Contradictions stay: both claims remain, each with its own evidence (`conflicts`, `why`).
- `fictionalize_all(genome, evidence, ...)` carries the evidence through the real-person rule: claims about what was
  dropped go, the rest move with their fields, and no real source title, locator or quote is kept (one redacted source).
  The result is scanned for the ban list like the genome is.

## 1B.5 The counterfactual lab (`persona_lab.py`)

- A formative event can now say what it was to the person (`Formative.experience`: betrayal, kindness, ...). It leaves
  the marks living it would (`psyche.SHAPING`): traits move and scar, and a strong one forms the self-model outright.
  `personas.extras_override` builds worlds with other pasts (the lab's branches, the tests').
- Branches per seed: control, **placebo** (a formative event that leaves no mark: the noise floor), jianghu, betrayed,
  kindness, hostile, success, failed. `--target mei` shapes one person only.
- Reports retention (does a probe still rank people alike), drift (probes, traits, values, self-models, goals), relations
  (trust, affection, clashes), a divergence map per person and group drift, always also **beyond the placebo**.

**What 3 seeds x 20 days show** (town, ten people, beyond the placebo):

| | self-models held | hostile words | value drift | notes |
|---|---|---|---|---|
| betrayed | +17.7 | -13 | +0.072 | most turning points (+7.7) |
| failed | +13.7 | -77 | +0.011 | fewer words: they withdraw |
| hostile | +10.0 | +149 | +0.013 | trust and affection differ most (+0.08, +0.07) |
| kindness | +5.3 | -38 | -0.011 | traits moved most (+0.048) |
| success | -1.7 | +37 | -0.004 | |
| jianghu (other world) | -1.7 | +32 | -0.004 | |

- Early shaping shows in what people hold (self-models, values) and in how much they quarrel, and in the direction one
  would expect. The four standard probes (gossip, apology, defend, accuse) do **not** show it beyond the noise after 20
  days: drift beyond the placebo is within ±0.045 for every branch. At day 0 the shaping is clear (a betrayed person is
  more than 20% likelier to accuse: tests/test_persona.py); twenty different lives bury it.
- A bare extra event moves a 20-day world: placebo against control ranks people alike on gossip at only 0.46, on defend at
  0.31, on accuse at 0.45 (apology 0.85). A claim about one person's counterfactual therefore needs the placebo and
  several seeds; a single pair of runs says little.
- The jianghu is no more different from the town than the placebo is, on the probes (see persona_probe.py for the
  day-0 match across worlds, 0.82 to 0.99).
