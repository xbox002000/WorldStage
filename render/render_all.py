"""Render every built scene project to out/videos and print wall-clock times.

    python render/render_all.py [--quality draft|looks] [--fps 30] [--workers auto]
"""
from __future__ import annotations

import argparse
import os
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLI = ROOT / "render" / "node_modules" / ".bin" / ("hyperframes.cmd" if os.name == "nt" else "hyperframes")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--projects", default=str(ROOT / "render" / "projects"))
    ap.add_argument("--out", default=str(ROOT / "out" / "videos"))
    ap.add_argument("--quality", default="looks")
    ap.add_argument("--fps", default="30")
    ap.add_argument("--workers", default="auto")
    args = ap.parse_args()

    env = {**os.environ, "HYPERFRAMES_SKIP_SKILLS": "1", "PATH": str(ROOT / "tools" / "ffmpeg" / "bin") + os.pathsep + os.environ["PATH"]}
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    total = 0.0
    for proj in sorted(Path(args.projects).glob("scene_*")):
        target = out / f"{proj.name}.mp4"
        t0 = time.perf_counter()
        r = subprocess.run(
            [str(CLI), "render", str(proj), "-o", str(target), "-q", args.quality, "-f", args.fps, "-w", args.workers, "--quiet"],
            env=env, capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        dt = time.perf_counter() - t0
        total += dt
        size = target.stat().st_size / 1e6 if target.exists() else 0
        print(f"{proj.name}: {'ok' if r.returncode == 0 else 'FAILED'} {dt:5.1f}s {size:.1f} MB")
        if r.returncode:
            print(r.stdout[-800:], r.stderr[-800:])
    print(f"total {total:.1f}s")


if __name__ == "__main__":
    main()
