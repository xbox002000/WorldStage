"""Provider interfaces, one per capability (see contracts/capability.py). The world kernel never imports any
implementation of these, and production code gets implementations only from the capability registry.

Every provider answers the same three questions and nothing more:
  manifest()   what capability it offers, with which features and limits, at what cost;
  available()  whether it can run right now (tool installed, key present, server reachable), and if not why;
  toolchain()  the component versions that go into its RenderRequests (so their hashes pin what ran).
and then does the job for its capability. How it turns a request into its own format (a prompt, a ComfyUI
workflow, a Blender scene, HTML) is its own compiler's business.

VisualBackend       visual.generate      one shot as a clip
SpatialBackend      spatial.control      depth / mask / ... for one staged camera
AudioBackend        audio.score          the episode's soundtrack
CompositionBackend  composition.render   the finished episode
Publisher           puts a finished episode somewhere (local folder, YouTube, ...)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from contracts.capability import ProviderManifest
from contracts.packet import ProductionPacket
from contracts.render_request import RenderRequest, Take
from contracts.spatial import SpatialPlan


@dataclass(frozen=True)
class CostEstimate:
    currency: str
    amount: float
    note: str


@dataclass(frozen=True)
class ShotRequest:
    """Everything a visual provider needs for one shot, self-contained so it can cross a process or network
    boundary (an MCP server has no access to production.db). Backend-neutral: providers compile it themselves."""

    shot_id: str
    prompt: str  # a plain description of the shot; a provider may build its own prompt from the fields below
    duration_seconds: float
    width: int
    height: int
    fps: int
    seed: int
    subject: str = ""
    action: str = ""
    environment: str = ""
    camera: str = ""
    controls: dict[str, str] = field(default_factory=dict)  # control kind (depth, mask, first_frame) -> file path
    reference_asset_ids: list[str] = field(default_factory=list)


class Provider(Protocol):
    def manifest(self) -> ProviderManifest: ...

    def available(self) -> tuple[bool, str]: ...

    def toolchain(self) -> dict[str, str]: ...


class VisualBackend(Provider, Protocol):
    def generate(self, request: RenderRequest, shot: ShotRequest, dest: Path) -> Take:
        """Make the clip for `shot` at `dest`. request.request_hash is the idempotency key: a retry after a timeout
        must never cause a second charge. A failure is a Take with status "failed", not an exception."""


class SpatialBackend(Provider, Protocol):
    def controls(self, plan: SpatialPlan, beat_index: int, camera_index: int, width: int, height: int) -> dict[str, bytes]:
        """Control images for one camera of one staged beat, as control kind -> PNG bytes."""


class AudioBackend(Provider, Protocol):
    def score_bytes(self, packet: ProductionPacket, seed: int) -> bytes:
        """The whole soundtrack as a WAV: a pure function of the packet and the seed for deterministic providers."""


class CompositionBackend(Provider, Protocol):
    audio: AudioBackend  # given at construction; its toolchain and score hash go into every request

    def make_request(self, packet: ProductionPacket, *, clips: dict[str, tuple[Path, str]] | None = None,
                     quality: str = "looks", seed: int = 0) -> RenderRequest:
        """The episode request. clips maps shot_id -> (clip path, clip hash) for shots made by a visual provider;
        a provider with the procedural_visuals feature draws the other shots itself."""

    def render(self, request: RenderRequest, dest_dir: Path) -> Take: ...

    def estimate_cost(self, request: RenderRequest) -> CostEstimate: ...


class Publisher(Protocol):
    def publish(self, episode_dir: Path) -> str:
        """Return a reference (path or URL) to the published episode."""
