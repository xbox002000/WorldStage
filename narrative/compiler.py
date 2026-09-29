"""ProductionCompiler: SceneSpec + StylePack -> ProductionPacket. Deterministic, no LLM, no clock, no randomness.

The compiler decides *how to shoot* what the world says happened. It can never change what happened.
"""
from __future__ import annotations

from dataclasses import replace

from contracts.base import content_hash
from contracts.packet import (
    PACKET_VERSION, AudioPlan, Camera, Canvas, CharacterLock, CompilerRef, ContinuityLocks, Episode, Lighting,
    LocationLock, ProductionPacket, QARequirements, Shot, ShotCharacter, StylePackRef, SubtitleCue, finalize)
from contracts.scene_spec import Beat, SceneSpec
from contracts.stylepack import SUSPENSE_V1, StylePack
from narrative.audio_plan import compile_audio_plan, compile_directed_audio
from narrative.color import avatar_color
from world.ruleset import ROOT, file_hash

COMPILER_VERSION = "1.1.0"
COMPILER_FILES = ("narrative/compiler.py", "narrative/audio_plan.py", "narrative/color.py", "contracts/packet.py",
                  "contracts/stylepack.py", "narrative/direction.py", "contracts/director.py")

# (event type, tone) -> (actor action, target action, actor emotion, target emotion, shot, movement, seconds)
BEATS = {
    ("talk", "warm"): ("chat_warmly", "listen_happily", "warm", "happy", "two_shot", "static", 4),
    ("talk", "neutral"): ("talk", "listen", "calm", "calm", "wide", "static", 3),
    ("talk", "cold"): ("speak_coldly", "flinch", "distant", "hurt", "medium", "slow_push_in", 4),
    ("talk", "hostile"): ("confront", "recoil", "angry", "angry", "close_up", "slow_push_in", 5),
    ("steal", None): ("take_object", "notice_loss", "tense", "shocked", "insert", "static", 4),
    ("tell", "truth"): ("share_news", "listen_intently", "calm", "curious", "two_shot", "static", 4),
    ("tell", "lie"): ("lie_smoothly", "believe", "tense", "calm", "medium", "slow_push_in", 5),
    ("tell", "distortion"): ("twist_story", "listen_intently", "tense", "calm", "medium", "slow_push_in", 4),
    ("tell", "omission"): ("hold_back", "listen_intently", "uneasy", "curious", "medium", "static", 4),
    ("confront", "lie_exposed"): ("expose", "recoil", "angry", "ashamed", "close_up", "slow_push_in", 6),
    ("confront", "distortion_exposed"): ("expose", "flinch", "hurt", "uneasy", "close_up", "slow_push_in", 5),
    ("confront", "concealment_exposed"): ("accuse", "flinch", "hurt", "uneasy", "close_up", "static", 5),
    ("confront", "misinformed"): ("question", "explain", "uneasy", "uneasy", "medium", "static", 4),
    ("confront", "unfounded"): ("accuse", "hurt_by_accusation", "embarrassed", "hurt", "medium", "slow_push_in", 5),
    ("confront", "inconclusive"): ("question", "shrug", "uneasy", "uneasy", "medium", "static", 4),
    # World C acts (before these, they all fell back to a neutral wide shot)
    ("take", None): ("pick_up", "unaware", "tense", "calm", "insert", "static", 4),
    ("misplace", None): ("walk_away", "unaware", "calm", "calm", "insert", "static", 3),
    ("find", None): ("pick_up", "relieved", "relieved", "calm", "medium", "static", 3),
    ("give", None): ("hand_over", "receive", "uneasy", "relieved", "two_shot", "static", 4),
    ("notice_missing", None): ("search", "unaware", "uneasy", "calm", "medium", "slow_push_in", 4),
    ("accuse", "caught"): ("accuse", "caught_out", "angry", "ashamed", "close_up", "slow_push_in", 6),
    ("accuse", "denied"): ("accuse", "deny", "angry", "uneasy", "close_up", "slow_push_in", 5),
    ("accuse", "false"): ("accuse", "hurt_by_accusation", "angry", "hurt", "medium", "slow_push_in", 5),
    ("lend", None): ("hand_over", "receive", "calm", "relieved", "two_shot", "static", 3),
    ("repay", None): ("hand_over", "receive", "calm", "calm", "two_shot", "static", 3),
    ("parrot_speaks", None): ("squawk", "startled", "calm", "shocked", "medium", "static", 4),
    ("seed", None): ("establish", "unaware", "calm", "calm", "wide", "static", 3),
}
FOCAL_MM = {"wide": 24, "two_shot": 35, "medium": 35, "close_up": 85, "insert": 50}
CANVAS = {"portrait": (1080, 1920), "landscape": (1920, 1080)}
POSITION = {"actor": "left", "target": "right", "victim": "right"}


def compiler_ref() -> CompilerRef:
    files = {f: file_hash(ROOT / f) for f in COMPILER_FILES}
    return CompilerRef(COMPILER_VERSION, content_hash(files))


def _time_of_day(clock: str) -> str:
    hour = int(clock[:2])
    return "night" if hour < 6 or hour >= 20 else "dusk" if hour >= 17 else "day"


def _tighten(shot: str, bias: str) -> str:
    if bias == "tight" and shot == "wide":
        return "medium"
    if bias == "wide" and shot == "close_up":
        return "medium"
    return shot


def caption(beat: Beat, names: dict[str, str]) -> str:
    role = {p.role: names[p.id] for p in beat.participants}
    a, b = role.get("actor", ""), role.get("target") or role.get("victim") or ""
    if beat.event_type == "steal":
        return f"{a} 拿走了 {b} 的{beat.prop.name if beat.prop else '東西'}"
    detail = beat.detail or ""
    if beat.event_type == "tell":
        return {
            "truth": f"{a} 告訴 {b}：{detail}",
            "lie": f"{a} 對 {b} 撒了謊：{detail}",
            "distortion": f"{a} 向 {b} 歪曲了事實：{detail}",
            "omission": f"{a} 告訴 {b}：{detail}" + (f"，卻沒提{beat.detail2}" if beat.detail2 else "，卻有所保留"),
        }.get(beat.variant or "", f"{a} 對 {b} 說了些話")
    if beat.event_type == "confront":
        return {
            "lie_exposed": f"{a} 揭穿了 {b} 的謊言：{detail}",
            "distortion_exposed": f"{a} 指出 {b} 歪曲了事實：{detail}",
            "concealment_exposed": f"{a} 發現 {b} 有所隱瞞",
            "misinformed": f"{a} 質問 {b}，才發現 {b} 也被蒙在鼓裡",
            "unfounded": f"{a} 誤會了 {b}，質問「{detail}」",
            "inconclusive": f"{a} 質問 {b}，沒有結果",
        }.get(beat.variant or "", f"{a} 當面質問 {b}")
    return {
        "warm": f"{a} 親切地和 {b} 聊天",
        "neutral": f"{a} 和 {b} 閒聊",
        "cold": f"{a} 冷淡地回應 {b}",
        "hostile": f"{a} 當面質問 {b}",
    }.get(beat.variant or "", f"{a} 對 {b} 說話")


def _shot(spec: SceneSpec, beat: Beat, index: int, start: float, style: StylePack, names: dict[str, str],
          previous: Beat | None, last: bool) -> Shot:
    key = (beat.event_type, beat.variant if beat.event_type not in ("steal", "take", "misplace", "find", "give",
                                                                    "notice_missing", "lend", "repay", "parrot_speaks",
                                                                    "seed") else None)
    a_act, t_act, a_emo, t_emo, shot_type, movement, seconds = BEATS.get(key, BEATS[("talk", "neutral")])
    shot_type = _tighten(shot_type, style.camera_bias)
    duration = max(1, round(seconds * style.duration_scale)) + (2 if beat.trust_flipped else 0)
    if last and style.ending == "unresolved":
        duration += 1  # hold on the unresolved last beat
    background = 0
    characters = []
    for p in beat.participants:
        if p.role in POSITION:
            position = POSITION[p.role]
            action, emotion = (a_act, a_emo) if p.role == "actor" else (t_act, t_emo)
        else:
            position, action, emotion = "background", "watch", "uneasy"
            background += 1
        person = spec.characters[p.id]
        characters.append(ShotCharacter(p.id, person.name, person.asset_id, p.role, position, action, emotion))
    actor = next((c for c in characters if c.role == "actor"), characters[0] if characters else None)
    other = next((c for c in characters if c.role in ("target", "victim")), None)
    tod = _time_of_day(beat.clock)
    if previous is None:
        note = None
    elif previous.location.id == beat.location.id:
        note = f"same place as previous shot: {beat.location.name}"
    else:
        note = f"moved from {previous.location.name} to {beat.location.name}"
    return Shot(
        shot_id=f"s{index:02d}", event_id=beat.event_id,
        intent=(f"show {actor.name} {actor.action}" + (f" toward {other.name}" if other else "")) if actor
        else f"establish {beat.location.name}: something from outside reaches the town",
        subject=", ".join(c.name for c in characters if c.position != "background"),
        action=actor.action if actor else "establish", environment=f"{beat.location.name}, {beat.weather}, {tod}",
        camera=Camera(shot_type, movement, FOCAL_MM[shot_type]), lighting=Lighting(tod, beat.weather),
        start_seconds=round(start, 3), duration_seconds=duration, caption=caption(beat, names),
        thought=beat.motivation, characters=characters, props=[beat.prop] if beat.prop else [],
        location=beat.location, day=beat.day, clock=beat.clock, render_backend="procedural",
        route_reason="procedural by default: no stock or AI backend enabled",
        continuity_refs=[c.asset_id for c in characters] + [f"loc_{beat.location.id}"] + ([beat.prop.asset_id] if beat.prop else []),
        continuity_note=note, trust_flipped=beat.trust_flipped,
    )


RECAP_SECONDS = 2.0  # extra time on the title card to read the recap


# DirectorPlan scale/relation -> the packet's shot sizes (the renderers and the shot route know these five)
SCALE_TO_SHOT = {"EWS": "wide", "WS": "wide", "MS": "medium", "MCU": "close_up", "CU": "close_up", "ECU": "close_up",
                 "INSERT": "insert"}
MOTION_TO_MOVEMENT = {"push_in": "slow_push_in"}
LONE_ACTS = ("take", "misplace", "notice_missing", "find", "cash_prize", "feed_pet", "seed")


def _directed_shots(spec: SceneSpec, direction, style: StylePack, names: dict[str, str], start: float) -> list[Shot]:
    """One packet shot per DirectorPlan shot. The first shot of each beat carries its caption; the others are
    coverage of the same moment (a reaction, an insert, a point of view)."""
    shots, t, seen = [], start, set()
    sound = {c.shot_index: c for c in direction.sound}
    last_beat = len(spec.beats) - 1
    for n, cs in enumerate(direction.shots):
        beat = spec.beats[cs.beat_index]
        base = _shot(spec, beat, n, t, style, names, spec.beats[cs.beat_index - 1] if cs.beat_index else None,
                     last=False)
        shot_type = "two_shot" if cs.relation == "two_shot" and cs.scale in ("MS", "WS") else SCALE_TO_SHOT[cs.scale]
        shot_type = _tighten(shot_type, style.camera_bias)
        seconds = max(1, round(cs.seconds * style.duration_scale)) + (1 if beat.trust_flipped and cs.function == "reveal" else 0)
        if cs.beat_index == last_beat and n == len(direction.shots) - 1 and style.ending == "unresolved":
            seconds += 1
        present = [c for c in base.characters if beat.event_type not in LONE_ACTS or c.role in ("actor", "witness")]
        first = cs.beat_index not in seen
        seen.add(cs.beat_index)
        cue = sound.get(n)
        shots.append(replace(
            base, shot_id=f"s{n:02d}", intent=f"{cs.function}: {cs.reason}",
            camera=Camera(shot_type, MOTION_TO_MOVEMENT.get(cs.motion, cs.motion), FOCAL_MM[shot_type]),
            start_seconds=round(t, 3), duration_seconds=seconds, caption=base.caption if first else "",
            thought=base.thought if first else None, characters=present or base.characters,
            continuity_note=base.continuity_note if first else f"same moment, {cs.function}",
            function=cs.function, direction_note=cs.reason, relation=cs.relation, angle=cs.angle,
            focalizer=direction.focalization.focalizer, spatial_camera=cs.spatial_camera,
            music=cue.music if cue else "", dialogue=cue.dialogue if cue else "full"))
        t += seconds
    return shots


def compile_packet(spec: SceneSpec, style: StylePack = SUSPENSE_V1, orientation: str = "portrait",
                   fps: int = 30, recap: str = "", direction=None) -> ProductionPacket:
    """With a DirectorPlan (narrative/direction.py) the shots follow the director: several per beat, each with its
    function and reason. Without one, one shot per beat from the BEATS table (the older behaviour)."""
    width, height = CANVAS[orientation]
    names = {pid: p.name for pid, p in spec.characters.items()}
    title_seconds = style.title_seconds + (RECAP_SECONDS if recap else 0.0)
    if direction is not None:
        if direction.scene_hash != spec.scene_hash:
            raise ValueError("the DirectorPlan was made for another scene")
        shots = _directed_shots(spec, direction, style, names, title_seconds)
        t = shots[-1].start_seconds + shots[-1].duration_seconds if shots else title_seconds
    else:
        shots, t, previous = [], title_seconds, None
        for i, beat in enumerate(spec.beats):
            shot = _shot(spec, beat, i, t, style, names, previous, last=(i == len(spec.beats) - 1))
            shots.append(shot)
            t += shot.duration_seconds
            previous = beat
    total = round(t + style.end_seconds, 3)

    locks = ContinuityLocks(
        characters={pid: CharacterLock(p.asset_id, [f"avatar_color={avatar_color(pid, p.slot if p.slot >= 0 else None)}", f"initial={p.name[-1]}"], ["default"])
                    for pid, p in spec.characters.items()},
        locations={loc.id: LocationLock(f"loc_{loc.id}", f"{loc.name} as a labelled node on the town map")
                   for loc in spec.map.locations},
    )
    required = sorted({ref for s in shots for ref in s.continuity_refs})
    audio_plan = (compile_audio_plan(spec.beats, shots, title_seconds, total) if direction is None
                  else compile_directed_audio(spec.beats, shots, title_seconds, total))
    packet = ProductionPacket(
        version=PACKET_VERSION, scene_hash=spec.scene_hash,
        stylepack=StylePackRef(style.id, style.version, style.hash()), compiler=compiler_ref(),
        episode=Episode(title=spec.title, recap=recap, hook=style.hook, title_seconds=title_seconds,
                        end_seconds=style.end_seconds),
        canvas=Canvas(width, height, fps), map=spec.map, continuity_locks=locks, shots=shots,
        audio_plan=audio_plan,
        subtitle_plan=_subtitles(shots),
        qa=QARequirements(width, height, fps, total, required, require_audio=bool(audio_plan.cues)),
    )
    if direction is not None:
        packet = replace(packet, direction_hash=direction.plan_hash)
    return finalize(packet)


def _subtitles(shots: list[Shot]) -> list[SubtitleCue]:
    """A caption stays up over the coverage of its beat (the shots that follow without a caption of their own)."""
    cues, i = [], 0
    while i < len(shots):
        s = shots[i]
        j = i + 1
        while j < len(shots) and not shots[j].caption:
            j += 1
        end = shots[j - 1].start_seconds + shots[j - 1].duration_seconds
        if s.caption:
            cues.append(SubtitleCue(round(s.start_seconds + 0.3, 3), round(end - 0.3, 3), s.caption))
        i = j
    return cues


def with_backend(packet: ProductionPacket, shot_id: str, backend: str, reason: str) -> ProductionPacket:
    """Re-route one shot (e.g. to a paid AI backend); the packet hash changes with it."""
    shots = [replace(s, render_backend=backend, route_reason=reason) if s.shot_id == shot_id else s for s in packet.shots]
    return finalize(replace(packet, shots=shots))
