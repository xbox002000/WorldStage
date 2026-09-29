"""Adapter interfaces. The world kernel never imports any implementation of these.

VisualBackend  - produces picture for a shot or a whole episode (procedural HyperFrames, stock footage, AI video)
AudioBackend   - produces sound (synthesised, library, TTS)
Publisher      - puts a finished episode somewhere (local folder, YouTube, ...)
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from contracts.render_request import RenderRequest, Take


@dataclass(frozen=True)
class Capabilities:
    name: str
    kinds: list[str]
    max_seconds: int
    supports_reference_images: bool
    deterministic: bool  # same request -> same bytes
    remote: bool  # costs money / leaves the machine


@dataclass(frozen=True)
class CostEstimate:
    currency: str
    amount: float
    note: str


@dataclass(frozen=True)
class ShotRequest:
    """What a generative backend needs for one shot (used by AI video backends; procedural ignores it)."""

    shot_id: str
    prompt: str
    duration_seconds: int
    reference_asset_ids: list[str]
    first_frame_asset_id: str | None
    last_frame_asset_id: str | None
    seed: int
    aspect_ratio: str


class VisualBackend(Protocol):
    def capabilities(self) -> Capabilities: ...

    def estimate_cost(self, request: RenderRequest) -> CostEstimate: ...

    def submit(self, request: RenderRequest, idempotency_key: str) -> str:
        """Start work and return a job id. idempotency_key is always request.request_hash: a retry after a
        timeout must never cause a second charge."""

    def poll(self, job_id: str) -> Take: ...

    def fetch(self, job_id: str, dest: Path) -> Path: ...


class AudioBackend(Protocol):
    def capabilities(self) -> Capabilities: ...

    def render(self, request: RenderRequest, dest: Path) -> Path: ...


class Publisher(Protocol):
    def publish(self, episode_dir: Path) -> str:
        """Return a reference (path or URL) to the published episode."""
