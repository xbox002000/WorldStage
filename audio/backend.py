"""audio.score providers: the soundtrack for an episode.

synth    synthesised locally and deterministically from the packet's audio plan (music + effects)
silence  a silent track of the right length (for tests, and for a composition that must not carry the score)
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

import numpy as np

from audio.synth import SR, audio_toolchain, synthesize, to_wav_bytes
from contracts.capability import ProviderManifest
from contracts.packet import ProductionPacket
from contracts.render_request import RenderRequest


class SynthAudioBackend:
    name = "synth"

    def __init__(self, packet_lookup: Callable[[str], ProductionPacket] | None = None) -> None:
        self._lookup = packet_lookup

    def manifest(self) -> ProviderManifest:
        return ProviderManifest(self.name, "1", ["audio.score"], ["music", "sfx"], transport="local", local=True,
                                deterministic=True, max_seconds=600, quality=0.4)

    def available(self) -> tuple[bool, str]:
        return True, ""

    def toolchain(self) -> dict[str, str]:
        return {"audio": audio_toolchain()}

    def score_bytes(self, packet: ProductionPacket, seed: int) -> bytes:
        """The whole soundtrack as a WAV. A pure function of the packet's audio plan, its hash and the seed."""
        return to_wav_bytes(synthesize(packet.audio_plan, packet.qa.total_seconds, f"{packet.packet_hash}:{seed}"))

    def render(self, request: RenderRequest, dest: Path) -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(self.score_bytes(self._lookup(request.packet_hash), request.seed))
        return dest


class SilentAudioBackend:
    name = "silence"

    def manifest(self) -> ProviderManifest:
        return ProviderManifest(self.name, "1", ["audio.score"], [], transport="local", local=True,
                                deterministic=True, quality=0.0, notes="a silent track of the episode's length")

    def available(self) -> tuple[bool, str]:
        return True, ""

    def toolchain(self) -> dict[str, str]:
        return {"audio": "silence-1"}

    def score_bytes(self, packet: ProductionPacket, seed: int) -> bytes:
        return to_wav_bytes(np.zeros((int(round(packet.qa.total_seconds * SR)), 2), dtype=np.float32))
