"""Render -> Diagnose -> Repair: a typed failure found in a take, and the targeted change that should fix it.

A failure names what is wrong and who saw it (the detector). Codes marked "needs a vision inspector" cannot be
detected by the deterministic QA that exists today; they are part of the vocabulary so a future inspector (a
vision model, a pose tracker) reports into the same records, but nothing may claim them without such a detector.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from contracts.base import hash_without

REPAIR_VERSION = 1

FailureCode = Literal[
    # measurable today (ffprobe / ffmpeg filters / the spatial plan / the provider's own answer)
    "FORMAT_ERROR",  # wrong resolution or frame rate
    "DURATION_ERROR",
    "FROZEN_FRAMES",  # the picture does not move
    "BLACK_FRAMES",
    "AUDIO_MISSING",
    "SPATIAL_ERROR",  # the staging has a blocked sight line
    "PROVIDER_ERROR",  # the provider failed or returned nothing usable
    # needs a vision inspector (not built)
    "IDENTITY_DRIFT", "OBJECT_CONTINUITY_ERROR", "ACTION_ORDER_ERROR", "POSE_ERROR", "CAMERA_ERROR",
    "TEMPORAL_JITTER", "PHYSICS_ERROR", "LIGHTING_ERROR", "AUDIO_SYNC_ERROR", "LIP_SYNC_ERROR",
    "TEXT_RENDER_ERROR", "NARRATIVE_CONTINUITY_ERROR",
]
MEASURABLE = ("FORMAT_ERROR", "DURATION_ERROR", "FROZEN_FRAMES", "BLACK_FRAMES", "AUDIO_MISSING", "SPATIAL_ERROR",
              "PROVIDER_ERROR")

RepairOp = Literal["reseed", "fallback_provider", "conform_duration", "restage", "increase_reference_strength",
                   "lock_object_identity", "preserve_hand_state"]


@dataclass(frozen=True)
class VisualFailure:
    code: FailureCode
    shot_id: str
    request_hash: str
    detector: str  # which check saw it, e.g. ffmpeg.freezedetect
    evidence: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class RepairRequest:
    """Re-render one shot, changing only what the failures call for. Never the story: SceneSpec and packet stay."""

    shot_id: str
    failures: list[VisualFailure]
    ops: list[RepairOp]
    attempt: int  # 1 = the first repair after the original take
    parent_request_hash: str
    version: int = REPAIR_VERSION
    repair_hash: str = ""

    def compute_hash(self) -> str:
        return hash_without(self, "repair_hash")
