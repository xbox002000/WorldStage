"""The composition root: the one module that knows which provider implementations this installation has.

Production code gets a registry from here and asks it for capabilities; it imports no renderer, synthesiser or
model client itself (a test enforces that). Adding a provider means registering it here, nothing else.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from capability.registry import CapabilityRegistry
from contracts.packet import ProductionPacket


def default_registry(packet_lookup: Callable[[str], ProductionPacket], *, workdir: Path | None = None,
                     mcp: bool = False, mock_defect_rate: float = 0.25) -> CapabilityRegistry:
    from audio.backend import SilentAudioBackend, SynthAudioBackend
    from render.ffmpeg_compose import FFmpegComposeBackend
    from render.hyperframes_backend import HyperFramesBackend
    from render.mock_clip import MockClipBackend
    from render.whitebox import WhiteboxSpatialBackend

    reg = CapabilityRegistry()
    reg.register(SynthAudioBackend(packet_lookup))
    reg.register(SilentAudioBackend())
    reg.register(WhiteboxSpatialBackend())
    reg.register(MockClipBackend(defect_rate=mock_defect_rate))
    reg.register(HyperFramesBackend(packet_lookup, workdir))
    reg.register(FFmpegComposeBackend(packet_lookup, workdir))
    if mcp:
        from capability.mcp_adapter import VISUAL_MOCK, McpVisualProvider
        reg.register(McpVisualProvider("visual-mock", VISUAL_MOCK))
    return reg
