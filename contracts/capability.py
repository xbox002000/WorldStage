"""Capability layer contracts: what a provider can do, what a job needs, and which provider was chosen and why.

Core code asks for a capability ("visual.generate"), never for a tool ("hyperframes", "comfyui"). A provider is
anything that fulfils a capability: a local class, a CLI, an HTTP API or an MCP server. The manifest is all the
core knows about it; how the provider turns a request into its own input format is the provider's business.

Capability names in use:
  visual.generate     one shot as a video clip
  spatial.control     control material for a staged camera (depth, mask, ...) from a SpatialPlan
  audio.score         an episode's soundtrack (music + effects)
  composition.render  the finished episode from shots, audio and subtitles
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from contracts.base import hash_without

CAPABILITY_VERSION = 1

Transport = Literal["local", "cli", "http", "mcp"]
# Features a provider may offer. A requirement lists the ones a job cannot do without.
Feature = Literal["t2v", "i2v", "reference_image", "first_last_frame", "depth", "pose", "mask", "native_audio",
                  "procedural_visuals", "clips", "music", "sfx", "tts"]


@dataclass(frozen=True)
class ProviderManifest:
    provider_id: str
    version: str
    capabilities: list[str]
    features: list[str]
    transport: Transport
    local: bool  # runs on this machine (no network, no bill)
    deterministic: bool  # same request + same toolchain -> same bytes
    max_seconds: float = 0.0  # 0 = no limit
    max_width: int = 0
    max_height: int = 0
    cost_per_second: float = 0.0  # in `currency`, per second of output
    currency: str = "USD"
    latency_seconds: float = 0.0  # typical wall time per job
    quality: float = 0.5  # 0..1, a rough rank that a policy can prefer
    notes: str = ""
    version_of_manifest: int = CAPABILITY_VERSION

    def hash(self) -> str:
        return hash_without(self)


@dataclass(frozen=True)
class Requirement:
    capability: str
    features: list[str] = field(default_factory=list)
    seconds: float = 0.0
    width: int = 0
    height: int = 0


@dataclass(frozen=True)
class Policy:
    """How to choose among providers that can do the job. The default fits a $0 budget."""

    max_cost: float = 0.0  # per job; 0 = only free providers
    prefer: Literal["cheap", "quality", "fast"] = "cheap"
    allow_remote: bool = True
    order: list[str] = field(default_factory=list)  # explicit preference, ahead of the `prefer` ranking
    deny: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Rejection:
    provider_id: str
    reason: str


@dataclass(frozen=True)
class Selection:
    """The providers that can do the job, best first (the rest are the fallback order), and why the others cannot."""

    requirement: Requirement
    policy: Policy
    chosen: list[str]
    rejected: list[Rejection]
    selection_hash: str = ""
