# Cast prototype: what a less crude episode could look like

Written 2026-09-29, after the user watched Experiment A's seven episodes and said they were too crude.

## Why

The Experiment A episodes are a debug view of the world: grey graph lines, one-letter discs, one caption line such as
"Ning confronts Lan", no faces, no places, no props, no dialogue, no voices. The world engine can explain every
event; the viewer sees none of it. Presentation, not the world, was the weakest layer.

## What the prototype is

`python prototypes/cast_episode4.py` builds a 26.7 s clip from the real events of Experiment A episode 4 (Lan is hurt and
answers Ning coldly; Ning confronts her; the next day Lan hits back).

- **Characters** (`render/cast/characters.js`): round vector people, ten designs (hair, skin, clothes in the person's identity
  hue, glasses and so on), 15 feelings (the world's twelve plus neutral, cold and smug), blink, breathing, a mouth that
  flaps while a line is spoken, arm poses, effects (sweat, vein, tear, spark).
- **Places** (`render/cast/backgrounds.js`): cafe and park, by time of day (day, dusk, night) and weather (rain falls on the
  window indoors, fog veils everything). Apartment, office and station are still missing.
- **Stage** (`render/cast/stage.js`): a map establishing shot, then scenes cut like a conversation (wide, speaker close-up,
  reaction close-up), dialogue panel with typewriter text, inner thoughts in a second style, screen shake on a shout.
- **Sound**: the existing synth for music, effects and ambience; voices from Gemini TTS; the music ducks under the voice;
  the mix is set to -16 LUFS.
- Everything that changes is a `tl.set` / `tl.to` on a named element, so any frame can be rendered alone. The camera is
  driven by CSS variables (`--cs`, `--cx`, `--cy`), because GSAP's own SVG origin handling shifted the picture by an
  amount that depended on the group's bounding box.

## What the free tier allows (measured 2026-09-29, one call each)

| capability | model | result |
|---|---|---|
| speech | `gemini-3.8-flash-tts` | works; style goes in `speech_metadata.style` (a style written into the text is read aloud); two named speakers per request |
| images | `gemini-3.1-flash-image`, `-lite-image` | free quota 0 |
| music | `lyria-3-clip-preview` | free quota 0 |
| video | `gemini-omni-flash-preview` | free quota 0 |

So characters and places are drawn by code, which also makes them consistent and free.

## Checked and not checked

Checked: the file (1080x1920, 30 fps, 26.7 s, -16.4 LUFS, peak -2.4 dBFS); every frame region by looking at frames; that the four
spoken lines are audible in the final mix and land inside the on-screen dialogue windows (an independent transcription of
the soundtrack gave 6.35-10.27, 11.23-12.59, 16.03-17.65 and 20.67-24.41 s against windows of 6.1-10.25, 10.7-12.7,
15.9-17.68 and 20.73-24.03 s).

Not checked, needs a person: whether the voices sound natural (the transcription heard the cold line as "surprised"), the
Mandarin accent, whether the music suits, and whether the look is what is wanted.

## What integrating it into the daily job would take

1. Dialogue: a model writes one short line per beat from the beat's facts (speaker, tone, the character's own reason,
   what just happened) and a rule check rejects lines that add people, objects or events. Lines are cached and recorded like
   every other model answer, so replays are identical.
2. A `VisualBackend` for the cast look and an `AudioBackend` for TTS; voices stored content-addressed, because the model's
   audio is not reproducible and the render request must pin its bytes.
3. Shot durations come from the voice durations, so the plan is made in two passes (lines and voices, then times).
4. ProductionPacket v3 (dialogue, thought, prop inserts, camera cuts) with a migration and regenerated schemas.
5. Free TTS quota is not published; a local fallback (`hyperframes tts`, Kokoro-82M) needs a model download.
6. Props (key, watch, diary, phone) and the other three places.
