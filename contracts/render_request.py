"""RenderRequest: an immutable, content-addressed order for one artifact. Take: one attempt to fulfil it."""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Literal

from contracts.base import content_hash, hash_without

REQUEST_VERSION = 2

TakeStatus = Literal["queued", "submitted", "generating", "ready", "failed", "selected", "rejected", "needs_reconciliation"]


Toolchain = dict[str, str]
"""What the renderer ran on, as component -> version (e.g. hyperframes, ffmpeg, chrome, encoder, audio, model).

Each provider names its own components, so no provider's tools leak into the contract. Local backends promise:
same request + same toolchain -> same artifact. (Until v2 this was a class with HyperFrames' fields; the JSON of
those requests is identical to a dict with the same keys, so their hashes still verify.)"""


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
    toolchain: dict[str, str]
    toolchain_hash: str
    request_hash: str = ""


def make_request(*, kind: str, backend: str, backend_version: str, parameters: dict[str, str], packet_hash: str,
                 seed: int, asset_hashes: dict[str, str], toolchain: Toolchain) -> RenderRequest:
    """Build a request and stamp its hash. The hash covers everything that can change the artifact."""
    req = RenderRequest(REQUEST_VERSION, kind, backend, backend_version, dict(parameters), packet_hash, seed,
                        dict(asset_hashes), dict(toolchain), content_hash(toolchain))
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
