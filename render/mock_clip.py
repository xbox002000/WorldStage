"""visual.generate provider "mock-clip": stands in for an AI video model (H3, Wan, Veo, ...), locally, at $0.

It answers a ShotRequest the way a video model would, with a clip of the requested size and length, and it uses the
depth control when given one (the clip is built on it). Its picture is a placeholder: a moving marker over the
depth image. It also reproduces one real failure mode of such models, on purpose and
deterministically: for some (shot, seed) pairs the clip comes out frozen (a still picture), the way image-to-video
models sometimes return no motion. Reseeding usually fixes it, which is what the repair loop has to find out.
"""
from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

from contracts.backends import ShotRequest
from contracts.capability import ProviderManifest
from contracts.render_request import RenderRequest, Take
from production.provenance import file_sha256

FFMPEG_DIR = Path(__file__).resolve().parent.parent / "tools" / "ffmpeg" / "bin"
BITEXACT = ["-fflags", "+bitexact", "-flags:v", "+bitexact", "-map_metadata", "-1", "-threads", "1"]


def ffmpeg_version() -> str:
    out = subprocess.run([str(FFMPEG_DIR / "ffmpeg"), "-version"], capture_output=True, text=True, check=True).stdout
    return out.splitlines()[0]


class MockClipBackend:
    def __init__(self, name: str = "mock-clip", defect_rate: float = 0.25) -> None:
        self.name = name
        self.defect_rate = defect_rate  # share of (shot, seed) pairs that come out frozen
        self._ffmpeg: str | None = None

    def manifest(self) -> ProviderManifest:
        return ProviderManifest(self.name, "1", ["visual.generate"], ["t2v", "i2v", "depth"], transport="local",
                                local=True, deterministic=True, max_seconds=10, max_width=1920, max_height=1920,
                                latency_seconds=2, quality=0.1, notes="placeholder clips; freezes on some seeds")

    def available(self) -> tuple[bool, str]:
        exe = FFMPEG_DIR / "ffmpeg.exe"
        return (True, "") if exe.exists() or (FFMPEG_DIR / "ffmpeg").exists() else (False, f"no ffmpeg in {FFMPEG_DIR}")

    def toolchain(self) -> dict[str, str]:
        if self._ffmpeg is None:
            self._ffmpeg = ffmpeg_version()
        return {"model": f"{self.name}-1", "ffmpeg": self._ffmpeg, "encoder": "libx264"}

    def frozen(self, shot: ShotRequest) -> bool:
        digest = hashlib.sha256(f"{shot.shot_id}:{shot.seed}".encode("utf-8")).digest()
        return int.from_bytes(digest[:4], "big") / 2 ** 32 < self.defect_rate

    def compile(self, shot: ShotRequest) -> list[str]:
        """This provider's own input format: an ffmpeg command line (a real model would get a prompt + controls)."""
        w, h, fps = shot.width, shot.height, shot.fps
        if "depth" in shot.controls:
            src = ["-loop", "1", "-framerate", str(fps), "-i", shot.controls["depth"]]
        else:
            src = ["-f", "lavfi", "-i", f"color=c=0x303040:s={w}x{h}:r={fps}"]
        size = max(w, h) // 12
        q = size // 4  # black square with a white core: visible on a white (near) or black (far) depth image
        src += ["-f", "lavfi", "-i", f"color=c=black:s={size}x{size}:r={fps},drawbox=x={q}:y={q}:w={2 * q}:h={2 * q}"
                                     f":color=white:t=fill"]
        if self.frozen(shot):  # the marker never moves
            where = f"x={w // 2}:y={h // 2}"
        else:  # overlay evaluates x/y per frame with t = time (in drawbox, t would be the line thickness)
            where = f"x='mod(t*{w // 3}+{shot.seed % 97 * 7},{w - size})':y='{h // 2}+{h // 6}*sin(t*2)':eval=frame"
        graph = f"[0:v]scale={w}:{h}:flags=bilinear,format=yuv420p[bg];[bg][1:v]overlay={where}:shortest=1,format=yuv420p[v]"
        return [*src, "-t", f"{shot.duration_seconds:g}", "-filter_complex", graph, "-map", "[v]", "-r", str(fps),
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "28", "-pix_fmt", "yuv420p", *BITEXACT]

    def generate(self, request: RenderRequest, shot: ShotRequest, dest: Path) -> Take:
        dest.parent.mkdir(parents=True, exist_ok=True)
        cmd = [str(FFMPEG_DIR / "ffmpeg"), "-y", "-v", "error", *self.compile(shot), str(dest)]
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode or not dest.exists():
            return Take(request.request_hash, "failed", error=(r.stderr or "no output")[-400:])
        return Take(request.request_hash, "ready", None, str(dest), file_sha256(dest), request.request_hash)
