"""composition.render provider "cast": the directed cartoon look. Round vector people and animals in drawn places,
filmed the way the packet's DirectorPlan fields say (scale, eye height, whose eyes, push-ins, hidden faces, muffled
voices). Same HyperFrames toolchain, request contract and determinism as the "hyperframes" provider; only the
drawing differs. It needs a directed packet (v4 fields); undirected packets stay with "hyperframes".
"""
from __future__ import annotations

from pathlib import Path

from contracts.capability import ProviderManifest
from contracts.packet import ProductionPacket
from contracts.render_request import RenderRequest
from render.cast.cast_html import DIRECTED_JS, HERE, build_project
from render.cast.packet_script import to_script
from render.hyperframes_backend import GSAP, HyperFramesBackend
from world.ruleset import file_hash


class CastBackend(HyperFramesBackend):
    name = "cast"

    def __init__(self, *args, script_options: dict | None = None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.script_options = script_options or {}

    def manifest(self) -> ProviderManifest:
        return ProviderManifest(self.name, "1", ["composition.render"], ["directed_cast"],
                                transport="cli", local=True, deterministic=True, max_seconds=600, latency_seconds=90,
                                quality=0.5, notes="directed cartoon look; needs a DirectorPlan-compiled packet")

    def make_request(self, packet: ProductionPacket, *, clips: dict | None = None, quality: str = "looks",
                     seed: int = 0) -> RenderRequest:
        if not packet.direction_hash:
            raise ValueError("the cast look films a DirectorPlan: compile the packet with direction=")
        req = super().make_request(packet, clips=clips, quality=quality, seed=seed)
        from contracts.render_request import make_request
        assets = dict(req.asset_hashes)
        for f in DIRECTED_JS + ("style.css", "packet_script.py", "cast_html.py"):
            assets[f"cast/{f}"] = file_hash(HERE / f)  # the script builder decides the picture too
        params = {**req.parameters, **{f"script.{k}": str(v) for k, v in sorted(self.script_options.items())}}
        return make_request(kind=req.kind, backend=self.name, backend_version=req.backend_version, parameters=params,
                            packet_hash=req.packet_hash, seed=req.seed, asset_hashes=assets, toolchain=req.toolchain)

    def _build(self, packet: ProductionPacket, project: Path, score: bytes | None) -> None:
        build_project(to_script(packet, **self.script_options), project, GSAP, mix=score, directed=True)
