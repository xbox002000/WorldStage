"""Diagnose one shot take: which measurable failures (contracts/repair.py) it has. No model, no network.

Frozen and black pictures are judged from frames sampled across the clip (ffmpeg -> 64x64 grey), not from
ffmpeg's freezedetect: that compares neighbouring frames, and a small subject moving slowly changes too little
between two frames to count as motion, so it called moving clips frozen.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np

from contracts.backends import ShotRequest
from contracts.render_request import Take
from contracts.repair import VisualFailure
from production.qa import _fps, probe

SAMPLES = 6
THUMB = 128
CHANGED = 12  # a pixel "moved" when its grey level changes by more than this (compression noise stays below)
MOTION_MIN = 0.001  # share of pixels that moved between the two most different samples; a frozen clip has ~0
BLACK_MAX = 8.0  # mean grey level of the brightest sampled frame
DURATION_TOLERANCE = 0.25


def sample_frames(ffmpeg: Path, media: Path, duration: float) -> np.ndarray:
    frames = []
    for i in range(SAMPLES):
        t = duration * (i + 0.5) / SAMPLES
        raw = subprocess.run(
            [str(ffmpeg), "-v", "error", "-ss", f"{t:.3f}", "-i", str(media), "-frames:v", "1",
             "-vf", f"scale={THUMB}:{THUMB},format=gray", "-f", "rawvideo", "-"], capture_output=True, check=True).stdout
        if len(raw) == THUMB * THUMB:
            frames.append(np.frombuffer(raw, np.uint8).astype(float))
    return np.array(frames)


def diagnose(take: Take, shot: ShotRequest, ffmpeg_dir: Path) -> list[VisualFailure]:
    rh = take.request_hash

    def fail(code: str, detector: str, **evidence) -> VisualFailure:
        return VisualFailure(code, shot.shot_id, rh, detector, {k: str(v) for k, v in sorted(evidence.items())})

    if take.status != "ready" or not take.artifact_path or not Path(take.artifact_path).exists():
        return [fail("PROVIDER_ERROR", "provider", status=take.status, error=(take.error or "no artifact")[:200])]
    media = Path(take.artifact_path)
    info = probe(ffmpeg_dir / "ffprobe", media)
    video = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
    if video is None:
        return [fail("PROVIDER_ERROR", "ffprobe", error="no video stream")]
    out: list[VisualFailure] = []
    if (video["width"], video["height"]) != (shot.width, shot.height) or abs(_fps(video) - shot.fps) > 0.01:
        out.append(fail("FORMAT_ERROR", "ffprobe", got=f"{video['width']}x{video['height']}@{_fps(video):g}",
                        want=f"{shot.width}x{shot.height}@{shot.fps}"))
    duration = float(info["format"]["duration"])
    if abs(duration - shot.duration_seconds) > DURATION_TOLERANCE:
        out.append(fail("DURATION_ERROR", "ffprobe", got=f"{duration:.2f}", want=f"{shot.duration_seconds:g}"))
    frames = sample_frames(ffmpeg_dir / "ffmpeg", media, duration)
    if len(frames) >= 2:
        # counted, not averaged: a small subject moving across a large frame barely shifts the mean
        motion = max((np.abs(a - b) > CHANGED).mean() for i, a in enumerate(frames) for b in frames[i + 1:])
        if motion < MOTION_MIN:
            out.append(fail("FROZEN_FRAMES", "sampled_frames", moved=f"{motion:.4f}", threshold=MOTION_MIN))
        brightest = frames.mean(axis=1).max()
        if brightest < BLACK_MAX:
            out.append(fail("BLACK_FRAMES", "sampled_frames", brightest=f"{brightest:.2f}", threshold=BLACK_MAX))
    return out
