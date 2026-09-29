# Animals: perceivers without language

Written 2026-09-30. Code: `world/animals.py`, `agent/animal.py`; the director's animal focalization is in
`narrative/direction.py`; tests `tests/test_animals.py`.

## What an animal is here

A person row whose persona traits say `species` (the town's dog: `dog`, 小狗). It waits offstage (`inactive`)
until the stray-animal outside event brings it to the park. That event's only effect is the closed-vocabulary op
`animal_arrives`.

- **It never holds a claim.** `with_senses` strips every claim memory meant for an animal before an event commits.
  What the animal gets instead is a percept in its own terms: "有人撿起了亮亮的小東西，帶著阿俊的氣味",
  "大聲的爭吵，小瑞很生氣", "阿濤溫柔的聲音". It knows people by smell and voice; it knows nothing of ownership,
  lies or words.
- **Its senses beat a person's.** It senses loud acts always, normal ones with p = 0.8 and quiet ones with p = 0.6.
  The dark does not blind it. People notice (attention); animals sense. `present()` counts only people.
- **Its feelings come from what it senses.** Warm voices make it fonder of the speaker, loud anger makes it afraid.
  Whoever it is most attached to (affection ≥ 0.3) is its keeper, who feeds it each night (300) and becomes dearer
  to it.
- **It acts by its own policy** (`agent/animal.py`, deterministic):
  - follows someone it likes;
  - picks up a thing lying about (less and less interested in one it has already carried);
  - lets it fall somewhere else;
  - barks at someone it fears.

  It cannot talk, tell, lend, accuse or give, and nobody can talk to it, tell it things or argue with it. People do
  not bark.

## What it does to stories

The dog carries off lost things without anyone seeing. The owner then suspects whoever was around when they left
it.

In world 260934, on day 13, the dog picked up Ming's wallet unseen. Ming accused Jun, a false accusation. The dog
dropped the wallet in the park and Ming found it the next day. Nobody in the town ever learns that the dog did it.

## Point of view

When an animal did or sensed the act at the heart of a thread, and the people it concerns are in the dark, the
director tells it through the animal. The focal kind is `animal`, the mode `witness`, and the dramatic goal
"透過小狗的眼睛：牠看見了，卻說不出來".

- Its own acts are filmed low behind it, following the thing in its mouth (angle `ground`, tracking).
- What it watches is a subjective shot from its height: legs, hands, a thing changing hands.
- Dialogue is muffled throughout: it hears voices, not words.

The SpatialPlan stages animals 0.5 m tall. Its point-of-view camera sits at their eye height (0.47 m).

## Not done

- One species. Perception is a fixed table (sense probabilities, percept wording), not a sensory model with range,
  smell trails or sight lines.
- An animal has no goals, no psyche and no memory retrieval of its own. Its policy reads its feelings, not its
  percepts.
- Accusing an animal is allowed by the rules but never offered to people.
