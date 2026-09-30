"""Bring documents written under an older contract version up to the current one.

A migrated document is a new document: its content changed, so its hash is recomputed by the loader. Old
takes keep their own chain (verified against the version they were written with); migration exists so old
JSON can still be read, inspected and re-compiled, not so that old hashes stay valid.
"""
from __future__ import annotations

import copy

from contracts.packet import PACKET_VERSION
from contracts.render_request import REQUEST_VERSION
from contracts.scene_spec import SCENE_SPEC_VERSION


def migrate_scene_spec(data: dict) -> dict:
    data = copy.deepcopy(data)
    if data.get("version") == 2:  # v2 -> v3: `tone` became the more general `variant`; new optional detail fields
        for beat in data["beats"]:
            beat["variant"] = beat.pop("tone", None)
            beat.setdefault("detail", None)
            beat.setdefault("detail2", None)
            beat.setdefault("incident", None)
        data["version"] = 3
    if data.get("version") != SCENE_SPEC_VERSION:
        raise ValueError(f"cannot migrate scene spec version {data.get('version')}")
    data["scene_hash"] = ""
    return data


def migrate_packet(data: dict) -> dict:
    data = copy.deepcopy(data)
    if data.get("version") == 1:  # v1 -> v2: audio cues gained a duration and an intensity
        for cue in data["audio_plan"]["cues"]:
            cue.setdefault("duration", 0.0)
            cue.setdefault("intensity", 0.5)
        data["version"] = 2
    if data.get("version") == 2:  # v2 -> v3: shots can carry the director's intent; the packet names its plan
        for shot in data["shots"]:
            for key in ("function", "direction_note", "relation", "angle", "focalizer", "spatial_camera", "music"):
                shot.setdefault(key, "")
            shot.setdefault("dialogue", "full")
        data.setdefault("direction_hash", "")
        data["version"] = 3
    if data.get("version") == 3:  # v3 -> v4: what the camera is on, and whose thought or percept a shot shows
        for shot in data["shots"]:
            for key in ("scale", "subject_id", "attention", "event_type", "thought_by", "thought_kind", "suspect_id",
                        "transition"):
                shot.setdefault(key, "")
        data["version"] = 4
    if data.get("version") == 4:  # v4 -> v5: information function, grammar step, performance, sound anchor
        for shot in data["shots"]:
            for key in ("information_function", "grammar_step", "performance_focus", "sound_anchor"):
                shot.setdefault(key, "")
            shot.setdefault("performances", [])
            shot.setdefault("interactions", [])
            shot.setdefault("moment", 0.45)
        data.setdefault("performance_hash", "")
        data.setdefault("runtime_hash", "")
        data["version"] = 5
    if data.get("version") != PACKET_VERSION:
        raise ValueError(f"cannot migrate packet version {data.get('version')}")
    data["packet_hash"] = ""
    return data


def migrate_request(data: dict) -> dict:
    data = copy.deepcopy(data)
    if data.get("version") == 1:  # v1 -> v2: the toolchain records the audio stack
        data["toolchain"].setdefault("audio", "")
        data["version"] = 2
    if data.get("version") != REQUEST_VERSION:
        raise ValueError(f"cannot migrate render request version {data.get('version')}")
    data["request_hash"] = ""
    return data
