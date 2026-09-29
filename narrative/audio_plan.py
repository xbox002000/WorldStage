"""Shooting plan -> audio plan: which mood plays under each beat and where the effects land. No LLM."""
from __future__ import annotations

from contracts.packet import AudioCue, AudioPlan, Shot
from contracts.scene_spec import Beat

MOOD: dict[tuple[str, str | None], str] = {
    ("talk", "warm"): "warm", ("talk", "neutral"): "calm", ("talk", "cold"): "cold", ("talk", "hostile"): "tense",
    ("steal", None): "tense",
    ("tell", "truth"): "calm", ("tell", "lie"): "uneasy", ("tell", "distortion"): "uneasy", ("tell", "omission"): "uneasy",
    ("confront", "lie_exposed"): "clash", ("confront", "distortion_exposed"): "tense",
    ("confront", "concealment_exposed"): "tense", ("confront", "misinformed"): "uneasy",
    ("confront", "unfounded"): "uneasy", ("confront", "inconclusive"): "uneasy",
}
AMBIENCE = {"rain": "rain", "fog": "fog", "cloudy": "wind"}
MOVE = 0.7  # seconds the camera takes to settle; impacts land as it does


def _impact(importance: float) -> str | None:
    return None if importance < 0.3 else "low" if importance < 0.6 else "mid" if importance < 0.85 else "high"


def compile_audio_plan(beats: list[Beat], shots: list[Shot], title_seconds: float, total: float) -> AudioPlan:
    cues = [AudioCue(0.0, "music", "mood:title", title_seconds, 0.3), AudioCue(0.3, "sfx", "title_hit", 0.0, 0.7)]
    for i, (beat, shot) in enumerate(zip(beats, shots)):
        start = shot.start_seconds
        intensity = round(min(1.0, 0.25 + 0.7 * beat.importance), 2)
        mood = MOOD.get((beat.event_type, beat.variant if beat.event_type != "steal" else None), "calm")
        end = total if i == len(shots) - 1 else start + shot.duration_seconds
        cues.append(AudioCue(start, "music", f"mood:{mood}", round(end - start, 3), intensity))
        if i:
            cues.append(AudioCue(start, "sfx", "whoosh", MOVE, 0.5))
        cues.append(AudioCue(round(start + 0.3, 3), "sfx", "tick", 0.0, 0.3))  # the caption appears
        impact = _impact(beat.importance)
        if impact:
            cues.append(AudioCue(round(start + MOVE, 3), "sfx", f"hit_{impact}", 0.0, intensity))
        if beat.event_type == "steal":
            cues.append(AudioCue(round(start + MOVE, 3), "sfx", "snatch", 0.0, 0.6))
        if beat.event_type == "tell" and beat.variant in ("lie", "distortion"):
            cues.append(AudioCue(round(start + 1.0, 3), "sfx", "glass", 0.0, 0.5))
        if beat.event_type == "confront" and beat.variant in ("lie_exposed", "distortion_exposed", "concealment_exposed"):
            cues.append(AudioCue(start, "sfx", "reveal", 0.0, 1.0))  # the riser peaks as the camera settles
        if beat.trust_flipped:
            cues.append(AudioCue(round(start + 0.5, 3), "sfx", "flip", 0.0, 0.6))

    _ambience(shots, cues)
    return AudioPlan(sorted(cues, key=lambda c: (c.t, c.kind, c.name)))


# the director's music intent -> a synth mood; "silence" and "none" leave the beat mood or nothing at all
INTENT_MOOD = {"tension": "tense", "release": "warm", "sting": "clash"}


def compile_directed_audio(beats: list[Beat], shots: list[Shot], title_seconds: float, total: float) -> AudioPlan:
    """Audio for a directed packet: music per shot from the director's cue (silence is no music at all), effects
    once per beat on its first shot, muffled points of view kept under the music."""
    cues = [AudioCue(0.0, "music", "mood:title", title_seconds, 0.3), AudioCue(0.3, "sfx", "title_hit", 0.0, 0.7)]
    beat_of = {}
    for s in shots:
        beat_of.setdefault(s.event_id, next(b for b in beats if b.event_id == s.event_id))
    seen: set[int] = set()
    for i, shot in enumerate(shots):
        beat = beat_of[shot.event_id]
        start = shot.start_seconds
        end = total if i == len(shots) - 1 else start + shot.duration_seconds
        intensity = round(min(1.0, 0.25 + 0.7 * beat.importance), 2)
        if shot.music != "silence":
            mood = INTENT_MOOD.get(shot.music) or MOOD.get((beat.event_type, beat.variant if beat.event_type != "steal" else None), "calm")
            cues.append(AudioCue(start, "music", f"mood:{mood}", round(end - start, 3),
                                 round(intensity * (0.6 if shot.dialogue == "muffled" else 1.0), 2)))
        if i:
            cues.append(AudioCue(start, "sfx", "whoosh", MOVE, 0.3 if shot.event_id in seen else 0.5))
        if shot.music == "sting":
            cues.append(AudioCue(round(start + MOVE, 3), "sfx", "reveal", 0.0, 1.0))
        if shot.event_id in seen:
            continue
        seen.add(shot.event_id)
        cues.append(AudioCue(round(start + 0.3, 3), "sfx", "tick", 0.0, 0.3))
        impact = _impact(beat.importance)
        if impact:
            cues.append(AudioCue(round(start + MOVE, 3), "sfx", f"hit_{impact}", 0.0, intensity))
        if beat.event_type in ("steal", "take"):
            cues.append(AudioCue(round(start + MOVE, 3), "sfx", "snatch", 0.0, 0.6))
        if beat.trust_flipped:
            cues.append(AudioCue(round(start + 0.5, 3), "sfx", "flip", 0.0, 0.6))
    _ambience(shots, cues)
    return AudioPlan(sorted(cues, key=lambda c: (c.t, c.kind, c.name)))


def _ambience(shots: list[Shot], cues: list[AudioCue]) -> None:
    # Ambience: one bed per run of shots that share weather, and one under night scenes.
    def beds(kind_of):
        run_start, run_kind = None, None
        for shot in shots + [None]:
            kind = kind_of(shot) if shot is not None else None
            if kind != run_kind:
                if run_kind is not None:
                    yield run_kind, run_start, prev_end
                run_kind, run_start = kind, (shot.start_seconds if shot is not None else None)
            if shot is not None:
                prev_end = shot.start_seconds + shot.duration_seconds

    for kind, s, e in beds(lambda sh: AMBIENCE.get(sh.lighting.weather)):
        cues.append(AudioCue(s, "ambience", kind, round(e - s, 3), 0.4))
    for kind, s, e in beds(lambda sh: "night" if sh.lighting.time_of_day == "night" else None):
        cues.append(AudioCue(s, "ambience", kind, round(e - s, 3), 0.4))
