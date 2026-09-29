# World event ecology (World C)

Written 2026-09-29. It replaces `world_c_design.md`, the first World C draft, which drew "story cards" when the town
went quiet. The user's architecture review (2026-09-29) pointed out that this was drifting towards
"designed interesting events dropped into a world". This version keeps the world mechanics, turns the cards into a
synthetic outside-event benchmark, and lets every character live by rule motives.

## The principle

A story is a result of the simulation, not an input. An outside event can only change conditions: prices,
visibility, job security, a prop in a place, a parcel at the wrong door, news. What people do about it is decided
by each person's needs, traits, feelings and beliefs. Everything is judged by rules, and everything enters
`world.db` through `apply_event` (1 transaction = 1 event = 0..N deltas).

## What each layer answers

| Layer | Answers | Code |
|---|---|---|
| World engine | What happened? | `world/rules.py`, `world/items.py`, `world/money.py`, `world/social.py`, `world/props.py` |
| Character engine | Why did they do it? | `agent/volition.py` (rules), `agent/decision.py` (a model, optional) |
| Claim / memory engine | What does each person think happened? | `contracts/claim.py`, `world/claims.py`, `world/tell.py`, `world/confront.py` |
| Seed layer | What came in from outside, and what could it change here? | `contracts/seed.py`, `world/seeds.py`, `world/feeds/*.json` |
| Story director | Which thread is worth following now? | `narrative/threads.py`, `narrative/director.py` (read-only) |
| Spatial director | Where is everyone, and where is the camera? | `contracts/spatial.py`, `narrative/spatial.py` (read-only) |

## World mechanics (kept from the World C draft)

- **Attention** (`world/attention.py`): being present is not noticing.
  - Loud acts (hostile talk, confront, accuse, the parrot) reach everyone present.
  - Normal acts reach each person with p = 0.5, quiet acts (tell, take, lend) with p = 0.2.
  - Both are scaled by the `visibility` variable. The draws are deterministic.
- **Things**: the rightful owner (`rightful_owner_id`) is separate from the holder (`owner_person_id`), and items have a value.
  - Leaving a place, an absent-minded person may leave something behind (`misplace`).
  - Anyone can pick up what is lying there (`take`) or give it back (`give`). An owner who sees their own lost thing
    takes it back (`find`).
  - At night owners notice what is missing. They infer a suspect from who was around, favouring the person they
    trust least. That suspect can be innocent.
- **Accusation** (`accuse`): people only accuse over what was done to them, so onlookers do not pile on. The outcome
  comes from world truth:
  - `caught`: true, and the accuser has strong grounds. The thing goes back.
  - `denied`: true, but the grounds are weak. The guilty one lies, and the doubt stays.
  - `false`: the accused is wronged and bears a grudge.
- **Money**:
  - Rent is 600 a night. What cannot be paid becomes arrears.
  - People without a job scrape together 900 a day; work pays 1500.
  - Food costs `price_food`.
  - `lend` and `repay` move money and keep `debt_cents`. The town starts with two old debts.
- **A starting secret**: long ago Yun took Mei's ring. It is a real `backstory` event, so lies and accusations about
  it are judged like anything else.
- **Props do what props do** (`world/props.py`):
  - The parrot repeats, once and loudly, the last quiet claim spoken where it lives.
  - A kept dog eats 300 a night.
  - A winning ticket is cashed by whoever holds it.

## Rule motives (`agent/volition.py`)

The event ecology: candidate actions → utility → Intent → validator → event → consequence.

- Options come from `agent/perception.social_options`, the same list a model would see.
- Scores use traits (honesty, temper, gossip, generosity, curiosity), needs (money, arrears, debt, job security),
  relationships (trust, affection, fear, rivalry, what the other owes me), emotion and beliefs.
- A deterministic softmax draw at temperature 0.35 picks one option.
- No option is written for a story: desperate or angry options simply score higher under pressure.
- The model decider (`agent/decision.py`) is kept for experiments. It does not yet know the World C actions (take,
  give, lend, repay, accuse).

## Seed layer (`contracts/seed.py`, `world/seeds.py`)

```text
ExternalEvent (feed file, pinned by hash)
  → adapt(): topic → SeedCandidate (seed type, domains, relevance, SeedEffects)
  → check_effects(): closed vocabulary only
  → one `seed` event per adopted candidate
    (its truth: external_event_id, external_event_hash, candidate_hash, feed, feed_hash)
```

- SeedEffect ops:
  - `set_var`: only `price_food`, `visibility` and `job_security`; optionally wears off after N days.
  - `place_object`: a prop appears at a place.
  - `deliver_object`: a courier's mistake; a parcel for one resident lands with another.
  - `set_object_value`, `news`.
- No op can name a person's action, a feeling, a relationship or a verdict. Tests check that seed events only ever
  write `var` and `object` deltas.
- The feed has its own timetable (`ExternalEvent.day`). Unlike the draft's storyteller, it does not look at how quiet
  the town is, so the effect of seeds can be measured.
- `world/feeds/synthetic_v1.json` is the synthetic seed benchmark: the eight former cards as neutral outside facts.
  - An escaped parrot (information spread)
  - A lottery ticket dropped in the cafe, and a draw two days later (opportunity and ownership)
  - Food prices up (economic pressure)
  - A power cut (infrastructure disruption)
  - Layoffs in the sector (information and economic pressure)
  - A courier mix-up (ownership)
  - Stray animals (ownership and cost)

  The anonymous note and the dog's owner appearing were removed. Both picked a townsperson to act, which is a script,
  not a seed. Writing an anonymous note should come back later as an ordinary action.
- Real news is not connected yet. When it is, it produces `ExternalEvent`s from invented, abstracted facts. It never
  names a real person or brand.

## Not adopted from the review, and why

- A separate stored `Incident` contract (a situation with available actions and possible consequences). The live
  option list (`social_options`) already is the set of available actions, computed from state. Storing incidents
  would create a second picture of the world that can drift from `world.db`. Threads (below) cover the "ongoing
  situation" role on the production side, read-only.
- Fields such as `propagation_score` and `geographic_scope` on ExternalEvent wait for a real feed; a contract should
  not carry fields nothing reads.

## Experiments

| Name | World | Question |
|---|---|---|
| A (done) | World B rules, flash-lite for 4 characters | Does a model make drama? No. |
| C0 | World C, rule motives, no feed | Does the closed town make stories? |
| C1 | World C, rule motives, `synthetic_v1` feed | Do outside events add stories without writing them? |
| D | C1 + story director | Does picking threads beat picking arcs? |
| E | D + spatial plan / previs | Can the chosen scene become control material for video? |

The earlier plan's Experiment B (swap the model) stays possible with `--llm`.
