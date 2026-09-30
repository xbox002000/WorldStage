"""Build the presentation cast with Blender (headless) and make the files canonical.

    python -m runtime.blender.build            # -> render/presentation/assets/{person,dog,wallet}.glb + manifest.json

Blender's glTF exporter writes the same triangles in a different order from run to run. The geometry is identical,
but the bytes are not, and render requests pin assets by hash. So every index buffer is rewritten canonically:
each triangle rotated to start at its smallest index (winding kept, so nothing renders differently), then the
triangles sorted. After that the same script and Blender version always give the same bytes (tested).
"""
from __future__ import annotations

import hashlib
import json
import os
import struct
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
BLENDER = Path(os.environ.get("BLENDER", r"G:\Program Files\Blender Foundation\Blender 5.2\blender.exe"))
OUT = ROOT / "render" / "presentation" / "assets"
SHORT, INT = 5123, 5125


def canonical_glb(path: Path) -> None:
    data = bytearray(path.read_bytes())
    jlen = struct.unpack("<I", data[12:16])[0]
    doc = json.loads(bytes(data[20:20 + jlen]))
    bin_start = 20 + jlen + 8
    for mesh in doc.get("meshes", []):
        for prim in mesh["primitives"]:
            acc = doc["accessors"][prim["indices"]]
            view = doc["bufferViews"][acc["bufferView"]]
            fmt = {SHORT: "H", INT: "I"}[acc["componentType"]]
            size = struct.calcsize(fmt)
            off = bin_start + view.get("byteOffset", 0) + acc.get("byteOffset", 0)
            n = acc["count"]
            idx = list(struct.unpack(f"<{n}{fmt}", data[off:off + n * size]))
            tris = []
            for k in range(0, n, 3):
                a, b, c = idx[k:k + 3]
                m = min(a, b, c)
                tris.append((a, b, c) if m == a else (b, c, a) if m == b else (c, a, b))
            tris.sort()
            data[off:off + n * size] = struct.pack(f"<{n}{fmt}", *[v for t in tris for v in t])
    path.write_bytes(bytes(data))


def build(out: Path = OUT) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    subprocess.run([str(BLENDER), "-b", "--factory-startup", "--python", str(ROOT / "runtime" / "blender" / "build_cast.py"),
                    "--", str(out)], check=True, capture_output=True, timeout=600)
    manifest = {}
    for p in sorted(out.glob("*.glb")):
        canonical_glb(p)
        manifest[p.name] = "sha256:" + hashlib.sha256(p.read_bytes()).hexdigest()
    version = subprocess.run([str(BLENDER), "--version"], capture_output=True, text=True).stdout.splitlines()[0]
    (out / "manifest.json").write_text(json.dumps({"blender": version, "files": manifest}, indent=1), encoding="utf-8")
    return manifest


if __name__ == "__main__":
    print(json.dumps(build(), indent=1))
