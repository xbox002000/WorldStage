"""RenderRequest: an immutable, content-addressed order for one artifact. Take: one attempt to fulfil it."""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Literal

from contracts.base import content_hash, hash_without

REQUEST_VERSION = 2

TakeStatus = Literal["queued", "submitted", "generating", "ready", "failed", "selected", "rejected", "needs_reconciliation"]


@dataclass(frozen=True)
class Toolchain:
    """What the renderer ran on. Local backends promise: same request + same toolchain -> same artifact."""

    hyperframes: str
    ffmpeg: str
    chrome: str
    encoder: str
    audio: str = ""  # the audio synthesiser and its numeric library, when the master has a soundtrack


@dataclass(frozen=True)
class RenderRequest:
    version: int
    kind: str  # episode_master | shot
    backend: str
    backend_version: str
    parameters: dict[str, str]
    packet_hash: str
    seed: int
    asset_hashes: dict[str, str]
    toolchain: Toolchain
    toolchain_hash: str
    request_hash: str = ""


def make_request(*, kind: str, backend: str, backend_version: str, parameters: dict[str, str], packet_hash: str,
                 seed: int, asset_hashes: dict[str, str], toolchain: Toolchain) -> RenderRequest:
    """Build a request and stamp its hash. The hash covers everything that can change the artifact."""
    req = RenderRequest(REQUEST_VERSION, kind, backend, backend_version, dict(parameters), packet_hash, seed,
                        dict(asset_hashes), toolchain, content_hash(toolchain))
    return dataclasses.replace(req, request_hash=hash_without(req, "request_hash"))


@dataclass(frozen=True)
class Take:
    request_hash: str
    status: TakeStatus
    take_id: int | None = None
    artifact_path: str | None = None
    artifact_hash: str | None = None
    provider_job_id: str | None = None
    error: str | None = None
