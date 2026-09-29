"""composition.render provider "ffmpeg-compose": the episode from externally made shot clips, plus the soundtrack.

The timeline is the packet's own: a plain title segment until the first shot, each clip fitted to its shot's
slot (scaled to the canvas, cut to length, held on its last frame if short), a plain end segment. It draws no
text: captions ship as the .srt the pipeline writes, and titles would need a font pipeline (HyperFrames has one).
"""
from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from typing import Callable

from audio.backend import SynthAudioBackend
from contracts.backends import AudioBackend, CostEstimate
from contracts.capability import ProviderManifest
from contracts.packet import ProductionPacket
from contracts.render_request import RenderRequest, Take, make_request
from production.provenance import file_sha256
from render.mock_clip import BITEXACT, FFMPEG_DIR, ffmpeg_version

ROOT = Path(__file__).resolve().parent.parent


class FFmpegComposeBackend:
    name = "ffmpeg-compose"

    def __init__(self, packet_lookup: Callable[[str], ProductionPacket], workdir: Path | None = None,
                 audio: AudioBackend | None = None) -> None:
        self._lookup = packet_lookup
        self.workdir = workdir or ROOT / "render" / "projects"
        self.audio = audio or SynthAudioBackend(packet_lookup)
        self._clips: dict[str, dict[str, Path]] = {}
        self._ffmpeg: str | None = None

    def manifest(self) -> ProviderManifest:
        return ProviderManifest(self.name, "1", ["composition.render"], ["clips"], transport="cli", local=True,
                                deterministic=True, max_seconds=600, latency_seconds=10, quality=0.2,
                                notes="concatenates provider clips on the packet's timeline; no drawn text")

    def available(self) -> tuple[bool, str]:
        return (True, "") if FFMPEG_DIR.exists() else (False, f"no ffmpeg in {FFMPEG_DIR}")

    def toolchain(self) -> dict[str, str]:
        if self._ffmpeg is None:
            self._ffmpeg = ffmpeg_version()
        return {"ffmpeg": self._ffmpeg, "encoder": "libx264", "compose": "ffmpeg-compose-1", **self.audio.toolchain()}

    def estimate_cost(self, request: RenderRequest) -> CostEstimate:
        return CostEstimate("USD", 0.0, "local ffmpeg")

    def make_request(self, packet: ProductionPacket, *, clips: dict[str, tuple[Path, str]] | None = None,
                     quality: str = "looks", seed: int = 0) -> RenderRequest:
        clips = clips or {}
        missing = [s.shot_id for s in packet.shots if s.shot_id not in clips]
        if missing:
            raise ValueError(f"ffmpeg-compose needs a clip for every shot; missing {missing}")
        assets = {f"clip:{sid}": h for sid, (_, h) in clips.items()}
        assets["score"] = "sha256:" + hashlib.sha256(self.audio.score_bytes(packet, seed)).hexdigest()
        req = make_request(
            kind="episode_master", backend=self.name, backend_version="1",
            parameters={"width": str(packet.canvas.width), "height": str(packet.canvas.height),
                        "fps": str(packet.canvas.fps), "quality": quality, "score": self.audio.name},
            packet_hash=packet.packet_hash, seed=seed, asset_hashes=assets, toolchain=self.toolchain())
        self._clips[req.request_hash] = {sid: p for sid, (p, _) in clips.items()}
        return req

    def render(self, request: RenderRequest, dest_dir: Path | None = None) -> Take:
        key = request.request_hash.split(":", 1)[1][:16]
        out_dir = dest_dir or self.workdir
        out_dir.mkdir(parents=True, exist_ok=True)
        mp4, wav = out_dir / f"{key}.mp4", out_dir / f"{key}.wav"
        if mp4.exists():
            return Take(request.request_hash, "ready", None, str(mp4), file_sha256(mp4), request.request_hash)
        packet = self._lookup(request.packet_hash)
        clips = self._clips.get(request.request_hash)
        if clips is None:
            return Take(request.request_hash, "failed", error="clips unknown: make_request was not called in this process")
        for sid, path in clips.items():
            if file_sha256(path) != request.asset_hashes[f"clip:{sid}"]:
                return Take(request.request_hash, "failed", error=f"clip {sid} no longer matches its hash")
        score = self.audio.score_bytes(packet, request.seed)
        if "sha256:" + hashlib.sha256(score).hexdigest() != request.asset_hashes["score"]:
            return Take(request.request_hash, "failed", error="the score no longer matches the request")
        wav.write_bytes(score)

        w, h, fps = packet.canvas.width, packet.canvas.height, packet.canvas.fps
        total = packet.qa.total_seconds
        inputs, parts, n = [], [], 0

        def blank(seconds: float) -> None:
            nonlocal n
            inputs.extend(["-f", "lavfi", "-t", f"{seconds:.3f}", "-i", f"color=c=0x101418:s={w}x{h}:r={fps}"])
            parts.append(f"[{n}:v]format=yuv420p,setsar=1[p{n}]")
            n += 1

        blank(packet.shots[0].start_seconds)
        for s in packet.shots:
            inputs.extend(["-i", str(clips[s.shot_id])])
            parts.append(f"[{n}:v]scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,"
                         f"fps={fps},tpad=stop_mode=clone:stop_duration={s.duration_seconds},"
                         f"trim=duration={s.duration_seconds},setpts=PTS-STARTPTS,format=yuv420p,setsar=1[p{n}]")
            n += 1
        tail = total - (packet.shots[-1].start_seconds + packet.shots[-1].duration_seconds)
        if tail > 0.01:
            blank(tail)
        graph = ";".join(parts) + ";" + "".join(f"[p{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0[v]"
        cmd = [str(FFMPEG_DIR / "ffmpeg"), "-y", "-v", "error", *inputs, "-i", str(wav), "-filter_complex", graph,
               "-map", "[v]", "-map", f"{n}:a", "-t", f"{total:.3f}", "-r", str(fps), "-c:v", "libx264",
               "-preset", "veryfast", "-crf", "23" if request.parameters.get("quality") != "draft" else "30",
               "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", *BITEXACT, str(mp4)]
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode or not mp4.exists():
            mp4.unlink(missing_ok=True)
            return Take(request.request_hash, "failed", error=(r.stderr or "no output")[-500:])
        return Take(request.request_hash, "ready", None, str(mp4), file_sha256(mp4), request.request_hash)
