"""Render every version of a sandbox scene through the three.js Presentation Runtime with HyperFrames, and a still per
shot of each (the same toolchain and pinned Chrome as every other render).

    python -m render.presentation.render out/sandbox/wallet.json out/present
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from render.hyperframes_backend import CLI, HyperFramesBackend, _env, _run
from render.presentation.build import build
ROOT = Path(__file__).resolve().parent.parent.parent
FFMPEG = ROOT / "tools" / "ffmpeg" / "bin" / "ffmpeg.exe"


def sheet(scene_doc: dict, version: str, mp4: Path, n: int = 10) -> Path:
    """A still from the middle of up to n shots of a version, side by side."""
    shots = scene_doc["cuts"][version]["shots"]
    picks = [shots[round(i * (len(shots) - 1) / max(1, n - 1))] for i in range(min(n, len(shots)))]
    ts = [(s["film_start"] + s["film_end"]) / 2 for s in picks]
    sel = "+".join(f"between(t,{t - 0.02:.2f},{t + 0.02:.2f})" for t in ts)
    out = mp4.with_name(f"{version}_sheet.png")
    subprocess.run([str(FFMPEG), "-y", "-loglevel", "error", "-i", str(mp4), "-vf",
                    f"select='{sel}',scale=216:384,tile={len(ts)}x1", "-frames:v", "1", "-fps_mode", "vfr", str(out)],
                   check=True)
    return out


def render(scene: Path, out: Path, versions: list[str] | None = None, quality: str = "looks") -> list[Path]:
    doc = json.loads(scene.read_text(encoding="utf-8"))
    env = _env(HyperFramesBackend(lambda h: None).chrome_path())
    made = []
    for v in versions or sorted(doc["cuts"]):
        project = build(scene, v, out / v)
        mp4 = out / f"{v}.mp4"
        _run([str(CLI), "render", str(project), "-o", str(mp4), "-q", quality, "-f", "30", "--quiet"], env)
        sheet(doc, v, mp4)
        made.append(mp4)
        print("rendered", mp4, flush=True)
    sheets = [out / f"{v}_sheet.png" for v in (versions or sorted(doc["cuts"]))]
    if len(sheets) < 2:
        return made
    # versions with fewer shots give narrower sheets: pad them all to the widest before stacking
    wide = 216 * max(min(10, len(doc["cuts"][v]["shots"])) for v in (versions or sorted(doc["cuts"])))
    pads = "".join(f"[{k}:v]pad={wide}:384[p{k}];" for k in range(len(sheets)))
    subprocess.run([str(FFMPEG), "-y", "-loglevel", "error", *sum((["-i", str(s)] for s in sheets), []),
                    "-filter_complex", pads + "".join(f"[p{k}]" for k in range(len(sheets))) + f"vstack=inputs={len(sheets)}",
                    str(out / "versions.png")], check=True)
    return made


if __name__ == "__main__":
    render(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3].split(",") if len(sys.argv) > 3 else None)
