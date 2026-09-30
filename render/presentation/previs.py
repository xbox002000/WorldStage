"""The Previs Pack: per shot, the control signals a video model (VACE, a camera-controlled model) or an artist takes,
alongside the picture. Blender and three.js lock space, blocking, camera and timing; a model is left only the look.

    python -m render.presentation.previs out/sandbox/wallet3.json C_omniscient out/previs [--size 540x960]

    out/previs/<version>/
      previs.json                 the PrevisPacket: provenance, the id palette, the depth range, every shot's files
      shot_03/
        rgb.mp4 depth.mp4 normal.mp4 id.mp4 pose.mp4    one clip per pass, the shot's frames only
        camera.json               per frame: position, rotation, vertical fov, aspect, near/far, projection matrix
        pose.json                 per frame: every visible person's 18 keypoints (x, y in pixels, visible 0/1)
        runtime.json              the runtime's action tracks, hand-offs and footfalls inside the shot's world slice
        meta.json                 the shot: scale, relation, subject, whose eyes, function, cut reason, action phase

Passes (render/presentation/presentation.js): depth is linear, white at 0.3 m and black at 25 m; id is flat colour
per entity (the palette is in previs.json) with the set in greys; normal is view-space; pose is OpenPose-style on
black. All come from the same scene, camera and clock as the picture, so they register pixel for pixel.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from render.hyperframes_backend import CLI, HyperFramesBackend, _env, _run
from render.presentation.build import PASSES, build

ROOT = Path(__file__).resolve().parent.parent.parent
FFMPEG = ROOT / "tools" / "ffmpeg" / "bin" / "ffmpeg.exe"
EXTRACT = Path(__file__).resolve().parent / "extract.mjs"
FPS = 30


def _sha(p: Path) -> str:
    return "sha256:" + hashlib.sha256(p.read_bytes()).hexdigest()


def previs(scene: Path, version: str, out: Path, size: tuple[int, int] = (540, 960), passes=PASSES,
           reuse: bool = False) -> dict:
    scene, out = scene.resolve(), out.resolve()
    doc = json.loads(scene.read_text(encoding="utf-8"))
    version = next(v for v in sorted(doc["cuts"]) if v.startswith(version))
    base = out / version
    base.mkdir(parents=True, exist_ok=True)
    chrome = HyperFramesBackend(lambda h: None).chrome_path()
    env = _env(chrome)
    full = {}
    for ps in passes:
        project = build(scene, version, base / "_projects" / ps, size[0], size[1], pass_=ps)
        mp4 = base / f"_{ps}.mp4"
        full[ps] = mp4
        if reuse and mp4.exists():  # rendered already from this same scene
            continue
        _run([str(CLI), "render", str(project), "-o", str(mp4), "-q", "draft" if ps != "rgb" else "looks", "-f",
              str(FPS), "--quiet"], env)
        full[ps] = mp4
        print("pass", ps, mp4, flush=True)
    data = base / "_frames.json"
    r = subprocess.run(["node", str(EXTRACT), str(base / "_projects" / "rgb"), chrome, str(FPS), str(data)],
                       cwd=ROOT / "render", capture_output=True, text=True, timeout=1800)
    if r.returncode:
        raise RuntimeError(f"extract failed: {r.stderr[-800:]}")
    frames = json.loads(data.read_text(encoding="utf-8"))
    cuts = doc["cuts"][version]["shots"]
    shots = []
    for n, cut in enumerate(cuts):
        d = base / f"shot_{n:02d}"
        d.mkdir(exist_ok=True)
        start, dur = cut["film_start"], round(cut["film_end"] - cut["film_start"], 3)
        files = {}
        for ps, mp4 in full.items():
            clip = d / f"{ps}.mp4"
            subprocess.run([str(FFMPEG), "-y", "-loglevel", "error", "-ss", f"{start:.3f}", "-i", str(mp4), "-t", f"{dur:.3f}",
                            "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "12" if ps == "id" else "18", str(clip)],
                           check=True)
            files[ps] = clip.name
        mine = [f for f in frames["frames"] if start - 1e-6 <= f["film"] < cut["film_end"] - 1e-6]
        (d / "camera.json").write_text(json.dumps([{"frame": f["i"], "film": f["film"], "world": f["world"], **f["camera"]}
                                                   for f in mine]), encoding="utf-8")
        (d / "pose.json").write_text(json.dumps({"format": "coco18", "size": list(size),
                                                 "frames": [{"frame": f["i"], "people": f["poses"]} for f in mine]}),
                                     encoding="utf-8")
        t0, t1 = cut["t_start"], cut["t_end"]
        inside = lambda a, b: a <= t1 and b >= t0  # noqa: E731
        (d / "runtime.json").write_text(json.dumps({
            "world_slice": [t0, t1],
            "tracks": [k for k in doc.get("tracks", []) if inside(k["approach"], k["complete"])],
            "handoffs": [h for h in doc["handoffs"] if inside(h["start"], h.get("complete", h["t"]))],
            "steps": {e["id"]: [s for s in e.get("steps", []) if inside(s[0], s[1])] for e in doc["entities"] if e.get("steps")},
        }), encoding="utf-8")
        meta = {k: cut.get(k) for k in ("scale", "angle", "relation", "motion", "subject", "focal", "function", "info",
                                         "step", "phase", "event", "place")}
        meta.update(index=n, film=[start, cut["film_end"]], camera=cut.get("camera", {}).get("solution"),
                    camera_move=cut.get("camera", {}).get("move"))
        (d / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
        shots.append({"index": n, "dir": d.name, "passes": files, "camera": "camera.json", "pose": "pose.json",
                      "runtime": "runtime.json", "meta": "meta.json", "frames": len(mine)})
    packet = {"kind": "previs_packet", "version": 1, "scene": scene.name, "scene_sha": _sha(scene),
              "trace_hash": doc["trace_hash"], "runtime": doc["version"], "cut": version, "fps": FPS, "size": list(size),
              "depth_range_m": [0.3, 25.0], "depth_encoding": "linear, white near",
              "id_palette": {e["id"]: e["mask"] for e in doc["entities"]}, "set_palette": doc.get("set_mask", {}),
              "assets": json.loads((ROOT / "render" / "presentation" / "assets" / "manifest.json").read_text(encoding="utf-8")),
              "lift_gaps_m": frames.get("lift_gaps", [])[:20], "shots": shots}
    (base / "previs.json").write_text(json.dumps(packet, ensure_ascii=False, indent=1), encoding="utf-8")
    return packet


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    size = next((tuple(int(v) for v in a.split("=", 1)[1].split("x")) for a in sys.argv if a.startswith("--size=")), (540, 960))
    p = previs(Path(args[0]), args[1], Path(args[2]), size, reuse="--reuse" in sys.argv)
    print("previs", len(p["shots"]), "shots")
