"""ProductionPacket (v4, directed) -> the scene script render/cast/directed.js plays. A pure function of the packet:
same packet, same script, same video.

The packet already says what each shot is for, how close, from what height, through whose eyes and what is heard.
This module only decides where things stand on a 1080 x 1920 side-view stage and what a thing does during a shot
(it falls, it is picked up, it is carried off), from the event type and who is in the shot.
"""
from __future__ import annotations

import re

from contracts.packet import ProductionPacket, Shot

PLACES = {"cafe", "park", "apartment"}  # drawn in backgrounds.js; others fall back to the cafe
# the prop's state at the start and at the end of a shot, by event type (hand:<role> = held by that role)
PROP_PATH = {
    "take": ("ground", "hand:actor"), "steal": ("hand:victim", "hand:actor"), "find": ("ground", "hand:actor"),
    "misplace": ("hand:actor", "ground"), "give": ("hand:actor", "hand:receiver"),
    "lend": ("hand:actor", "hand:target"), "repay": ("hand:actor", "hand:target"),
}
POSE = {  # (pose at the start, pose after the moment, feeling after the moment) for the actor
    "take": ("down", "hold", None), "find": ("down", "hold", "relieved"), "notice_missing": ("hips", "shock", "shocked"),
    "accuse": ("point", None, None), "confront": ("point", None, None), "duel": ("point", None, None),
    "give": ("hold", None, None),
}
MOTION = {"slow_push_in": "push_in"}


def _hue(lock) -> float:
    tag = next((v for v in lock.identity_lock if v.startswith("avatar_color=")), "avatar_color=hsl(210")
    m = re.search(r"hsl\((\d+(?:\.\d+)?)", tag)
    return float(m.group(1)) if m else 210.0


def cast_of(packet: ProductionPacket) -> dict:
    names = {c.id: c.name for s in packet.shots for c in s.characters}
    out = {}
    for pid, lock in sorted(packet.continuity_locks.characters.items()):
        animal = lock.asset_id.startswith("animal_")
        out[pid] = {"name": names.get(pid, pid), "hue": _hue(lock), "kind": "animal" if animal else "person"}
        if animal:
            out[pid]["species"] = lock.asset_id.split("_", 1)[1] if "_" in lock.asset_id else "dog"
    return out


def _stage(shot: Shot, cast: dict) -> list[dict]:
    front = [c for c in shot.characters if c.position != "background"]
    back = [c for c in shot.characters if c.position == "background"]
    xs = {1: [430], 2: [320, 760], 3: [250, 540, 830]}.get(len(front)) or [140 + i * 800 / max(1, len(front) - 1)
                                                                             for i in range(len(front))]
    out = []
    actor = next((c.id for c in shot.characters if c.role == "actor"), None)
    for c, x in zip(front, xs):
        s = {"who": c.id, "x": round(x), "feel": c.emotion, "back": False,
             "look": 1 if x < 540 else -1 if len(front) > 1 else 0}
        if c.id == actor:
            pose, pose2, feel2 = POSE.get(shot.event_type, ("down", None, None))
            s["pose"] = pose
            if pose2:
                s["pose2"] = pose2
            if feel2:
                s["feel2"] = feel2
            if shot.event_type == "misplace":
                s["walk_after"] = 200
            elif shot.event_type == "take" and cast[c.id]["kind"] == "animal":
                s["walk_before"] = 60
        elif c.role in ("target", "victim", "suspect") and shot.event_type in ("accuse", "confront"):
            s["pose"] = "shock"
        out.append(s)
    for i, c in enumerate(back):
        x = 180 + (i + 0.5) * 720 / max(1, len(back))
        out.append({"who": c.id, "x": round(x), "feel": c.emotion, "back": True, "look": 1 if x < 540 else -1})
    return out


def _prop_state(state: str | None, shot: Shot) -> str | None:
    if state is None or state == "ground":
        return state
    role = state.split(":", 1)[1]
    who = next((c.id for c in shot.characters if c.role == role), None)
    return f"hand:{who}" if who else None


def to_script(packet: ProductionPacket, *, series: str = "虛擬小鎮", tagline: str = "", badge: list[str] | None = None,
              leads: list[str] | None = None, debug: bool = False) -> dict:
    cast = cast_of(packet)
    shots = []
    # a caption stays up over the coverage of its beat: until the next shot that has a caption of its own
    ends = {}
    for n, s in enumerate(packet.shots):
        if s.caption:
            j = n + 1
            while j < len(packet.shots) and not packet.shots[j].caption:
                j += 1
            last = packet.shots[j - 1]
            ends[n] = round(last.start_seconds + last.duration_seconds, 3)
    for n, s in enumerate(packet.shots):
        present = {c.id for c in s.characters}
        focal_kind = cast.get(s.focalizer, {}).get("kind", "")
        sense = s.thought_kind == "sense" and s.thought and s.thought_by in present
        prop = s.props[0].id if s.props else None
        path = PROP_PATH.get(s.event_type, ("hand:actor", "hand:actor") if prop else (None, None))
        caption = None
        if sense:  # through an animal's senses the words give way to what it feels
            caption = {"text": s.thought, "kind": "sense", "label": f"{cast[s.thought_by]['name']}的感覺",
                       "until": ends.get(n, round(s.start_seconds + s.duration_seconds, 3))}
        elif s.caption:
            caption = {"text": s.caption, "kind": "narration", "until": ends[n]}
        thought = None
        if s.thought and not sense and s.thought_by in cast:
            thought = {"who": s.thought_by, "text": s.thought, "label": f"{cast[s.thought_by]['name']}（心裡想）",
                       "animal": cast[s.thought_by]["kind"] == "animal"}
        stage = _stage(s, cast)
        actor = next((c.id for c in s.characters if c.role == "actor"), None)
        face = {x["who"]: 1 for x in stage}
        shots.append({
            "start": s.start_seconds, "dur": s.duration_seconds,
            "place": s.location.id if s.location.id in PLACES else "cafe",
            "time": s.lighting.time_of_day, "weather": s.lighting.weather,
            "stamp": {"day": s.day, "clock": s.clock, "placeName": s.location.name},
            "fn": s.function or "observe", "scale": s.scale or "MS", "angle": s.angle or "eye_level",
            "relation": s.relation or "frontal", "motion": MOTION.get(s.camera.movement, s.camera.movement),
            "subject": s.subject_id, "attention": s.attention or "body", "note": s.direction_note,
            "focal": s.focalizer, "focal_kind": focal_kind, "event": s.event_type, "actor": actor,
            "prop": prop, "prop_from": _prop_state(path[0], s) if prop else None,
            "prop_to": _prop_state(path[1], s) if prop else None, "face_of": face,
            "stage": stage, "caption": caption, "thought": thought,
            "suspect": s.suspect_id or None, "thinker": s.thought_by or actor,
            "dialogue": s.dialogue, "cut": s.transition or "cut", "music": s.music,
        })
    first = packet.shots[0] if packet.shots else None
    return {
        "title": packet.episode.title, "series": series, "tagline": tagline, "badge": badge or [],
        "title_seconds": packet.episode.title_seconds, "total": packet.qa.total_seconds, "debug": debug,
        "leads": leads or ([c.id for c in first.characters if c.position != "background"][:2] if first else []),
        "cast": cast, "shots": shots,
    }
