# Director Reality Test

Written 2026-09-30, from the user's review: "the DirectorPlan exists; now prove that different plans of the same
events are different things to watch." Code: `director_reality.py`, `benchmarks/director_reality_v1.json`,
`production/viewing.py`, the cartoon renderer `render/cast/` (`packet_script.py`, `directed.js`, `animals.js`,
`props.js`) and its provider `render/cast_backend.py`. Tests: `tests/test_director_reality.py`.

## The test

One world (seed 260934, 20 days, the synthetic feed), one stretch of one thread, `item:wallet_ming`:

1. Day 12, 21:01, the park: Ming drops his wallet without noticing. Kai, Mei and Rui are there.
2. 23:59, at home: Ming misses it and wonders whether Kai took it. Kai is only in his head.
3. Day 13, 12:13, the park: the dog picks it up in its mouth.
4. 18:25: the dog leaves it somewhere else; Tao and Yun see.
5. 21:27: the dog picks it up again.
6. Day 14, 12:17: the dog leaves it again.
7. 18:27: Ming finds it. The dog is near, sniffing.

Nobody wrote this. The benchmark only says "the stretch around the first time an animal took the thing" and stops
if the world has no such story.

Each variant forces some of the director's choices and leaves the rest to it:

| Variant | Whose eyes | What the audience knows | Camera grammar |
|---|---|---|---|
| ming_mystery_observe | Ming | mystery: never who moved it | observational: wide, eye level, nothing moves |
| dog_irony_subjective | the dog | irony: the dog did it | subjective, at a dog's height |
| kai_irony_reaction | Kai | irony: Kai saw Ming drop it, and Ming suspects him | close and reaction-heavy |
| axis_* (six) | one axis changed at a time: whose eyes, what the audience knows, or the camera grammar | | |

The scene hash must be the same for every variant: nothing about what happened may change. The script asserts it.

## What the director had to learn for this

- **Forced choices** (`plan_direction(focalizer=, strategy=, grammar=)`). The plan records what was forced
  (`DirectorPlan.forced`), so a benchmark plan can never pass as the director's own.
- **A mystery hides every giveaway.** Before, only the "take" beats were withheld, so "the dog dropped the wallet in
  the park" gave the answer away. Now every beat where the culprit handles the thing is hidden. It is filmed as the
  act without the face, and its caption has no agent: "錢包不見了", "錢包被留在了公園". This also applies to
  mysteries the director chooses on its own.
- **Camera grammars** (`regrammar`): observational, push_in, subjective, reaction. They change only how beats are
  filmed, never which beats exist or what they are for.
- **Words where the animal is.** A dog's point of view muffles voices only in beats the dog is in. Elsewhere the
  audience hears what the dog cannot.
- **Inner text** (packet v4 `thought`, `thought_by`, `thought_kind`, `suspect_id`):
  - A person's belief shows as a thought. Ming suspecting Kai becomes a thought bubble with Kai's face and a
    question mark. A belief the world does not support is now something you can see.
  - An animal's percept replaces the narration: "叼起了亮亮的小東西，上面有阿明的氣味". The dog does not know it is
    a wallet, or Ming's, or theft.

## What the packet and the renderer had to learn

- **Packet v4.** Each shot now carries:
  - the scale (WS … CU, INSERT);
  - which entity or prop the camera is on;
  - where it looks (eyes, hands, object …);
  - the event type;
  - whose inner text it shows, and whether that is a belief or a percept;
  - who is suspected;
  - the director's transition into the shot.

  A renderer needs nothing but the packet. The v3 → v4 migration fills in empty values.
- **Captions for every event type.** This was a bug: every World C and jianghu event (take, misplace, find, accuse,
  duel, train …) was captioned "X 對 Y 說話", including in the jianghu episodes already sent.
- **The directed cartoon renderer** (`render/cast/directed.js`). It reads each packet field and does this:
  - **Scale** sets the zoom.
  - **Angle** sets where the eye line sits. At ground level the camera drops to a dog's height.
  - **Subjective** means the focalizer is not drawn:
    - For a dog, the picture takes on dog colour vision and a blurred snout sits at the bottom of the frame. What it
      carries hangs in front of its nose.
    - For a person, the frame has a soft vignette.
  - **Over the shoulder**: the focalizer's dark shoulder is in the foreground.
  - **Hide** means the doer is never drawn. The thing is lifted out of frame by an unseen shadow.
  - **Motion**: push-in, pull-out, handheld and tracking.
  - **Muffled**: voices you can hear but not understand.
  - **Transitions**: a dissolve on a time jump, a white flash on a smash cut.

  It is registered as the provider `cast` for the feature `directed_cast`. The daily job uses it with
  `daily.py --world-c --look cast`. Undirected packets stay on the old procedural look.

## Results

See the table appended by the final run below. The numbers come from `production/viewing.py`, which reads only the
packet: camera height, share of subjective and close shots, share of screen time when words are audible, whether
the audience witnesses the culprit's act, and screen time per character.

## What this does not prove

- The measures describe what is on screen. They do not measure whether it feels different to a viewer; only
  watching can show that. The three videos and the side-by-side comparison are there to watch.
- Only three places are drawn (café, park, apartment); others fall back to the café. Jianghu places and the town's
  office and station have no drawings yet.
- No voices: the town's events have no spoken lines, and TTS would need the network.
