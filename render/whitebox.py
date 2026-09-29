"""spatial.control provider "whitebox": control images for one staged camera, ray-cast from the SpatialPlan.

The plan's layout is boxes; people are boxes of their height. For each pixel a ray leaves the camera; the nearest
hit gives the depth (distance along the view axis) and which thing is there (the mask). Pure numpy, no Blender,
byte-identical output for the same plan. The Blender whitebox the brief proposes would add lighting and a posed
RGB previs; it would register as another spatial.control provider with the same interface.

Outputs (PNG): depth  8-bit grey, near = white (0.5 m) to far = black (20 m and beyond / nothing hit);
               mask   one flat colour per object or person; `legend` (JSON) maps each colour to its id.
"""
from __future__ import annotations

import hashlib
import json
import math
import struct
import zlib

import numpy as np

from contracts.capability import ProviderManifest
from contracts.spatial import SpatialPlan

VERSION = "whitebox-1"
SENSOR_MM = 36.0
NEAR, FAR = 0.5, 20.0
BODY = 0.45  # a person's footprint, metres


def png(pixels: np.ndarray) -> bytes:
    """A deterministic PNG from an (h, w) uint8 grey or (h, w, 3) uint8 RGB array."""
    h, w = pixels.shape[:2]
    colour = 2 if pixels.ndim == 3 else 0
    raw = b"".join(b"\x00" + pixels[y].tobytes() for y in range(h))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, colour, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def _colour(ident: str) -> tuple[int, int, int]:
    d = hashlib.sha256(ident.encode("utf-8")).digest()
    return 40 + d[0] % 200, 40 + d[1] % 200, 40 + d[2] % 200


def _boxes(plan: SpatialPlan, beat_index: int) -> list[tuple[str, np.ndarray, np.ndarray, float]]:
    """(id, centre of base, size, yaw) for every solid thing in the beat's place, people included."""
    beat = plan.beats[beat_index]
    layout = next(l for l in plan.layouts if l.layout_id == beat.layout_id)
    out = [(o.id, np.array(o.position, float), np.array(o.size, float), o.yaw) for o in layout.objects
           if o.kind != "window"]  # glass: the camera sees through it
    for p in beat.placements:
        size = [BODY, BODY, p.height] if p.height > 0.5 else [0.25, 0.25, max(p.height, 0.1)]
        out.append((p.id, np.array(p.position, float), np.array(size, float), p.yaw))
    return out


def raycast(plan: SpatialPlan, beat_index: int, camera_index: int, width: int,
            height: int) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """Depth in metres (inf where nothing is hit), the index into ids per pixel (-1 floor, -2 nothing), ids."""
    cam = plan.beats[beat_index].cameras[camera_index]
    eye, target = np.array(cam.position, float), np.array(cam.target, float)
    fwd = target - eye
    fwd /= np.linalg.norm(fwd)
    right = np.cross(fwd, [0.0, 0.0, 1.0])
    if np.linalg.norm(right) < 1e-6:  # looking straight down
        right = np.array([1.0, 0.0, 0.0])
    right /= np.linalg.norm(right)
    up = np.cross(right, fwd)
    half = SENSOR_MM / (2 * cam.lens_mm)  # horizontal half-width of the view at distance 1
    xs = ((np.arange(width) + 0.5) / width * 2 - 1) * half
    ys = (1 - (np.arange(height) + 0.5) / height * 2) * half * height / width
    u, v = np.meshgrid(xs, ys)
    dirs = fwd[None, None, :] + u[..., None] * right + v[..., None] * up  # forward component 1: t is planar depth
    dirs = dirs.reshape(-1, 3)

    best = np.full(len(dirs), np.inf)
    which = np.full(len(dirs), -2, dtype=np.int32)
    with np.errstate(divide="ignore", invalid="ignore"):
        t_floor = np.where(dirs[:, 2] < 0, -eye[2] / dirs[:, 2], np.inf)
    hit = t_floor < best
    best[hit], which[hit] = t_floor[hit], -1

    boxes = _boxes(plan, beat_index)
    for k, (_, base, size, yaw) in enumerate(boxes):
        c, s = math.cos(math.radians(-yaw)), math.sin(math.radians(-yaw))
        rot = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])
        centre = base + [0, 0, size[2] / 2]
        o = rot @ (eye - centre)
        d = dirs @ rot.T
        lo, hi = -size / 2, size / 2
        with np.errstate(divide="ignore", invalid="ignore"):
            t1, t2 = (lo - o) / d, (hi - o) / d
        tmin = np.nanmax(np.minimum(t1, t2), axis=1)
        tmax = np.nanmin(np.maximum(t1, t2), axis=1)
        inside = np.all((o > lo) & (o < hi))
        t = np.where(tmax >= np.maximum(tmin, 0), np.where(inside, np.inf, tmin), np.inf)
        t = np.where(t > 0, t, np.inf)
        hit = t < best
        best[hit], which[hit] = t[hit], k
    return best.reshape(height, width), which.reshape(height, width), [b[0] for b in boxes]


class WhiteboxSpatialBackend:
    name = "whitebox"

    def manifest(self) -> ProviderManifest:
        return ProviderManifest(self.name, "1", ["spatial.control"], ["depth", "mask"], transport="local", local=True,
                                deterministic=True, quality=0.2, notes="numpy ray-cast of the plan's boxes")

    def available(self) -> tuple[bool, str]:
        return True, ""

    def toolchain(self) -> dict[str, str]:
        return {"spatial": f"{VERSION};numpy-{np.__version__}"}

    def controls(self, plan: SpatialPlan, beat_index: int, camera_index: int, width: int, height: int) -> dict[str, bytes]:
        depth, which, ids = raycast(plan, beat_index, camera_index, width, height)
        near = np.clip((FAR - np.clip(depth, NEAR, FAR)) / (FAR - NEAR), 0, 1)
        grey = np.where(np.isfinite(depth), np.round(near * 255), 0).astype(np.uint8)
        palette = np.array([_colour(i) for i in ids] + [(90, 90, 90), (0, 0, 0)], dtype=np.uint8)  # floor, nothing
        mask = palette[np.where(which >= 0, which, len(ids) + (which == -2))]
        seen = sorted({ids[k] for k in np.unique(which) if k >= 0})
        legend = {i: "#%02x%02x%02x" % _colour(i) for i in seen}
        return {"depth": png(grey), "mask": png(mask),
                "legend": json.dumps(legend, sort_keys=True, ensure_ascii=False).encode("utf-8")}
