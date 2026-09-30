"""composition.render provider "hyperframes": draws every shot procedurally and renders the episode to MP4 with
HyperFrames (headless Chrome + FFmpeg), locally. The soundtrack comes from whichever audio.score provider it is given.

Local and deterministic in the sense of the contract: same request + same toolchain -> same artifact. It runs
against the Chrome that hyperframes manages itself (pinned), never the auto-updating system Chrome.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Callable

from audio.backend import SynthAudioBackend
from contracts.backends import AudioBackend, CostEstimate
from contracts.capability import ProviderManifest
from contracts.base import content_hash
from contracts.packet import ProductionPacket
from contracts.render_request import RenderRequest, Take, Toolchain, make_request
from render.packet_html import build_project
from world.ruleset import file_hash

ROOT = Path(__file__).resolve().parent.parent
RENDER_DIR = ROOT / "render"
CLI = RENDER_DIR / "node_modules" / ".bin" / ("hyperframes.cmd" if os.name == "nt" else "hyperframes")
GSAP = RENDER_DIR / "node_modules" / "gsap" / "dist" / "gsap.min.js"
FFMPEG_DIR = ROOT / "tools" / "ffmpeg" / "bin"
ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _env(chrome: str | None = None) -> dict:
    env = {**os.environ, "HYPERFRAMES_SKIP_SKILLS": "1", "PATH": str(FFMPEG_DIR) + os.pathsep + os.environ["PATH"]}
    if chrome:
        env["HYPERFRAMES_BROWSER_PATH"] = chrome
    return env


def _run(cmd: list[str], env: dict | None = None) -> str:
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env or _env())
    if r.returncode:
        raise RuntimeError(f"{cmd[0]} failed ({r.returncode}): {ANSI.sub('', r.stderr or r.stdout)[-600:]}")
    return ANSI.sub("", r.stdout)


class HyperFramesBackend:
    name = "hyperframes"

    def __init__(self, packet_lookup: Callable[[str], ProductionPacket], workdir: Path | None = None,
                 audio: AudioBackend | None = None) -> None:
        self._lookup = packet_lookup
        self.workdir = workdir or RENDER_DIR / "projects"
        self._toolchain: Toolchain | None = None
        self._chrome: str | None = None
        self.audio = audio or SynthAudioBackend(packet_lookup)

    # -- toolchain ---------------------------------------------------------------------------------------------
    def chrome_path(self) -> str:
        if self._chrome is None:
            out = _run([str(CLI), "browser", "path"])
            path = next((l.strip() for l in reversed(out.splitlines()) if l.strip().lower().endswith(".exe") or "chrome" in l.lower()), "")
            if not path or not Path(path).exists():
                raise RuntimeError("pinned Chrome missing: run `hyperframes browser ensure`")
            self._chrome = path
        return self._chrome

    def toolchain(self) -> Toolchain:
        if self._toolchain is None:
            pkg = json.loads((RENDER_DIR / "node_modules" / "hyperframes" / "package.json").read_text(encoding="utf-8"))
            ffmpeg = _run([str(FFMPEG_DIR / "ffmpeg"), "-version"]).splitlines()[0]
            chrome = _run([self.chrome_path(), "--version"]).strip()
            self._toolchain = {"hyperframes": pkg["version"], "ffmpeg": ffmpeg, "chrome": chrome, "encoder": "libx264",
                               **self.audio.toolchain()}
        return self._toolchain

    # -- CompositionBackend ------------------------------------------------------------------------------------
    def manifest(self) -> ProviderManifest:
        return ProviderManifest(self.name, "1", ["composition.render"], ["procedural_visuals"], transport="cli",
                                local=True, deterministic=True, max_seconds=600, latency_seconds=60, quality=0.3,
                                notes="vector characters and places drawn in HTML; cannot embed external clips")

    def available(self) -> tuple[bool, str]:
        missing = [str(p) for p in (CLI, GSAP, FFMPEG_DIR / "ffmpeg.exe" if os.name == "nt" else FFMPEG_DIR / "ffmpeg")
                   if not p.exists()]
        return (False, "missing " + ", ".join(missing)) if missing else (True, "")

    def estimate_cost(self, request: RenderRequest) -> CostEstimate:
        return CostEstimate("USD", 0.0, "local CPU render")

    def make_request(self, packet: ProductionPacket, *, clips: dict | None = None, quality: str = "looks",
                     seed: int = 0) -> RenderRequest:
        if clips:
            raise ValueError("hyperframes draws every shot itself and cannot embed external clips")
        assets = {"gsap": file_hash(GSAP)}
        for pid, lock in packet.continuity_locks.characters.items():
            assets[lock.asset_id] = content_hash(lock)
        for lid, lock in packet.continuity_locks.locations.items():
            assets[lock.asset_id] = content_hash(lock)
        parameters = {"width": str(packet.canvas.width), "height": str(packet.canvas.height),
                      "fps": str(packet.canvas.fps), "quality": quality}
        if packet.audio_plan.cues:  # the soundtrack is part of the request: its bytes are pinned by hash
            assets["score"] = "sha256:" + hashlib.sha256(self.audio.score_bytes(packet, seed)).hexdigest()
            parameters["score"] = self.audio.name
        return make_request(
            kind="episode_master", backend=self.name, backend_version=self.toolchain()["hyperframes"],
            parameters=parameters,
            packet_hash=packet.packet_hash, seed=seed, asset_hashes=assets, toolchain=self.toolchain())

    def _paths(self, request_hash: str) -> tuple[Path, Path]:
        key = request_hash.split(":", 1)[1][:16]
        return self.workdir / key, self.workdir / f"{key}.mp4"

    def submit(self, request: RenderRequest, idempotency_key: str) -> str:
        assert idempotency_key == request.request_hash
        project, mp4 = self._paths(request.request_hash)
        if mp4.exists():
            return request.request_hash  # same request already fulfilled: never do the work twice
        packet = self._lookup(request.packet_hash)
        score = None
        if "score" in request.asset_hashes:
            score = self.audio.score_bytes(packet, request.seed)
            if "sha256:" + hashlib.sha256(score).hexdigest() != request.asset_hashes["score"]:
                raise RuntimeError("the synthesised score no longer matches the request: audio is not deterministic here")
        self._build(packet, project, score)
        p = request.parameters
        _run([str(CLI), "render", str(project), "-o", str(mp4), "-q", p["quality"], "-f", p["fps"], "--quiet"],
             _env(self.chrome_path()))
        return request.request_hash

    def _build(self, packet: ProductionPacket, project: Path, score: bytes | None) -> None:
        build_project(packet, project, GSAP, score=score)

    def poll(self, job_id: str) -> Take:
        _, mp4 = self._paths(job_id)
        return Take(job_id, "ready" if mp4.exists() else "failed", None, str(mp4) if mp4.exists() else None, None, job_id)

    def render(self, request: RenderRequest, dest_dir: Path | None = None) -> Take:
        return self.poll(self.submit(request, idempotency_key=request.request_hash))

    def fetch(self, job_id: str, dest: Path) -> Path:
        _, mp4 = self._paths(job_id)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(mp4.read_bytes())
        return dest
