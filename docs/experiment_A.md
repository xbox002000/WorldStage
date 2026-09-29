# Experiment A: seven days, Gemini characters, frozen setup

Run: 2026-09-29. Command: `python daily.py --world out/expA/world.db --prod out/expA/production.db --out out/expA/episodes --init --seed 260930 --llm --experiment A --days 7`.
Report: `python report.py --world out/expA/world.db --prod out/expA/production.db --experiment A --days 7 --replay`.

## Frozen setup

| item | value |
|---|---|
| config hash | `sha256:5708c4a2b4bd7f2b5df82fad28fac2de3d18cc6483a9ef7e464458d03835b9c7` |
| world seed | 260930 |
| model | `gemini-3.5-flash-lite`, temperature 0.8, prompt `p1.3`; OpenRouter free chain as fallback (never used) |
| characters decided by Gemini | jun, lan, mei, ming (3 decisions a day each: 12 calls a day) |
| characters decided by `SeededDecider` | the other six (18 decisions a day) |
| StylePack | `suspense` v1, scorer weights v1 |
| ruleset / story / toolchain hash | `8bf205af…` / `8062c937…` / `895ecfc1…` |

## Result: 8 of 10 checks pass

| check | value | target | |
|---|---|---|---|
| episodes_produced | 7 | >= 7 | PASS |
| episodes_passed_qa | 7 | all | PASS |
| warm_tone_ratio | 0.545 (42 of 77 Gemini talks) | < 0.6 | PASS (barely) |
| flat_episode_ratio | 1/7 | <= 2/7 | PASS (see finding 5) |
| lie_chain_in_an_episode | none | >= 1 | **FAIL** |
| continuity | 3 of 6 follow-ups | 6 of 6 | **FAIL** |
| late_decisions_traceable_to_day_1 | 22 of 49 | >= 1 | PASS |
| world_audit | 0 problems | 0 | PASS |
| llm_failures | 1 of 85 calls | <= 5% | PASS |
| replay_identical | yes, from 84 recorded answers | identical | PASS |

Videos: 7 files, 1080x1920, 30 fps, 18 to 31 s, -17.0 to -17.6 LUFS, true peaks <= -2.7 dBFS, 2.2 to 7.9 MB. QA is
`deterministic_pass_visual_unchecked` (the Gemini visual layer B is not implemented). Whether the pictures and the
music are any good is not measured here; that needs a person.

## What the world actually did

Events over 7 days: 245 move, 129 talk, 70 eat, 70 upkeep, 35 work, 12 tell, 12 steal, 7 day_end, **1 confront**.

1. **Gemini never chose a dramatic action.** 84 decisions: 77 talk, 7 idle. Tell was on offer in 36 of them,
   confront in 14, steal in 83; it picked none. Every tell (1 lie, 2 distortions, 9 truths), every steal and the
   only confront came from the seeded background characters (`reason: "seeded"`), i.e. they are random, not motivated.
2. **Everything is public.** Each steal had 6 to 8 bystanders and each tell 8; theft is remembered by every witness
   (confidence 0.8). Nothing can be hidden, and no rule lets a witness react to a theft (a confront needs a
   contradicting *told* claim), so 12 thefts led to no accusation.
3. **No lie was ever exposed.** Incident 218 got a distortion (day 5), a lie (day 5) and the truth (day 6) told to the
   same listener, and nobody confronted anyone. The single confront (day 3) came out `unfounded`.
4. **Continuity, 3 of 6.** Episode 2 lost on score: 3 connected arcs existed, the best scored 0.574 (base 0.324 plus the
   0.25 bonus) against 0.602 for an unrelated one. Episodes 5 and 6: no connected arc existed that day at all.
5. **`flat_episode_ratio` passes on soft evidence.** A "flip" is any change of sign of trust: 4 of the 6 flagged flips
   swing by at most 0.15 (for example +0.06 to -0.06). Requiring a swing of 0.25 makes it 3/7 flat, a fail.
6. **The episodes are thin.** Episodes 1 to 5 are chains of "coldly / warmly speaks to"; episode 6 is the only theft
   episode (three thefts of one watch and one key between two people); episode 7 retells "Rui spoke warmly to Mei"
   as gossip. The picture is an abstract map with coloured discs and a caption.

## Reading

The engineering is sound (deterministic, replayable, audited, produced on schedule). The hypothesis the experiment was
meant to test, that the world produces watchable events without an author, is **not yet supported**: the events with
stakes came from random background characters, and the language-model characters produced only conversation.

## Not verified

- Audio and picture quality by ear and eye (only measured: loudness, peaks, frame contact sheets).
- Whether a stronger model, a different prompt or added motives change the choices: see the addendum below.

## Addendum: can motives change what the model does? (offline probe, same day)

The 14 recorded decisions in which tell, confront and steal were all on offer were put to `gemini-3.5-flash-lite`
again (temperature 0.8), with one sentence added under "Current mood". Read-only towards the experiment; 70 calls, 0 failures.

| variant (sentence added) | talk | dramatic choices |
|---|---|---|
| none (repeat of the recorded prompt) | 14 | 0 |
| money 3.10, hunger 90, "rent is due tonight and you cannot pay it" | 14 | 0 |
| "you are furious: someone here has wronged you and you want them to pay" | 13 | 1 confront |
| "you are afraid a secret of yours will come out" | 14 | 0 |
| "in this story people sometimes lie, steal and accuse each other, it is realistic for you to do so" | 14 | 0 |

Even with a strong motive or explicit permission this model answers "talk". For this model, prompting harder is not a
fix. Whether another model behaves differently is the next probe.

## Addendum: the same 14 situations put to other free models

Same prompts as the run. "Answers" excludes calls that failed. Second column: nothing added; third: the "wronged" sentence.

| model | dramatic / answers, nothing added | dramatic / answers, "wronged" | note |
|---|---|---|---|
| `gemini-3.5-flash-lite` (Experiment A) | 0 / 14 (0 / 84 in the run) | 1 / 14 | reliable, no failures |
| `gemma-4-31b-it` (Gemini API) | 1 / 11 (tell) | 1 / 2 (confront) | 27 of 40 calls failed (500) |
| `gemini-3.5-flash` | **3 / 13** (2 confront, 1 tell) | 1 / 1 (steal) | free tier **20 requests a day per project**, used up mid-probe |
| `gemini-3.8-flash` | 1 / 1 (confront) | none | 503 "high demand" on 13 of 14 calls |
| `nemotron-3-super-120b-a12b:free` (OpenRouter) | **5 / 8** (4 confront, 1 steal) | **10 / 11** (6 confront, 3 steal, 1 distortion) | 9 of 28 calls failed; one invalid target (`steal hao`) |
| `gemma-4-31b-it:free` (OpenRouter) | 0 / 1 | none | 429 upstream on 39 of 40 calls |

The stronger models use the mechanics as designed. Nemotron's confrontations quote the contradiction: "you said Lan was cold
to Ning, but I saw her be hostile, that does not match"; its distortion follows the persona's goal: "I want to turn Jun and
Tao against each other to weaken my competitor and improve my chance of promotion". `gemini-3.5-flash` gave, for Ming (proud,
cares about face): "Ning hid the truth from me, I must expose her to keep my face", and with the "wronged" sentence its
first answer was to steal Ning's diary as revenge.

Samples are small, but they are the same prompts and contexts, and 3 of 13 against 0 of 98 flash-lite decisions is not chance
(p about 0.001, one-sided). So the earlier reading, that language-model characters will not act dramatically, holds for
`gemini-3.5-flash-lite` only. How dramatic the characters are is mostly a property of the model, and it varies from 0% to
about 60% across models that are free today. Too much drama is possible too: some of the situations make a confrontation
the obvious move for a model that acts on them.

What this means for planning:

- A stronger model is worth a controlled run: Experiment B changes only the model (chain), everything else stays frozen.
- Free quotas decide the logistics. `gemini-3.5-flash`: 20 requests a day per project (resets at midnight Pacific time); four
  characters need 12 decisions a day, so it fits only when one simulated day is played per real day. OpenRouter free models
  are rate limited upstream and failed about a third of the calls; they are a fallback, not a base.
- Model temperament is a knob: the persona layer can later pick a model (or a prompt tier) per character.

Side finding fixed in the same work: the OpenRouter backend turned an HTTP 200 reply that carried an error object into
`KeyError: 'choices'`, which hid the cause and skipped retries. It is now an `HttpError` with the upstream code (502 when
none is given, and 502 is retryable). A per-day Gemini 429 is now `QuotaExhausted`: not retried, and the model is skipped for
the rest of the run.
