"""AudioBackend "synth": the score for an episode, synthesised locally and deterministically."""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from audio.synth import audio_toolchain, synthesize, to_wav_bytes
from contracts.backends import Capabilities
from contracts.packet import ProductionPacket
from contracts.render_request import RenderRequest


class SynthAudioBackend:
    name = "synth"

    def __init__(self, packet_lookup: Callable[[str], ProductionPacket]) -> None:
        self._lookup = packet_lookup

    def capabilities(self) -> Capabilities:
        return Capabilities(self.name, ["episode_score"], max_seconds=600, supports_reference_images=False,
                            deterministic=True, remote=False)

    def toolchain(self) -> str:
        return audio_toolchain()

    def score_bytes(self, packet: ProductionPacket, seed: int) -> bytes:
        """The whole soundtrack as a WAV. A pure function of the packet's audio plan, its hash and the seed."""
        return to_wav_bytes(synthesize(packet.audio_plan, packet.qa.total_seconds, f"{packet.packet_hash}:{seed}"))

    def render(self, request: RenderRequest, dest: Path) -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(self.score_bytes(self._lookup(request.packet_hash), request.seed))
        return dest
