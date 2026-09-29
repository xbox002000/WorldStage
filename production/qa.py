"""Render QA, layer A: deterministic preflight. No LLM, no network. This is the only hard gate.

Layer B (an optional Gemini look at snapshots) may only answer a fixed yes/no form and can never fail an
episode on its own; when it is unavailable the episode carries qa_status "deterministic_pass_visual_unchecked".
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from contracts.packet import ProductionPacket

DURATION_TOLERANCE = 0.6  # seconds


@dataclass(frozen=True)
class QAResult:
    passed: bool
    status: str
    checks: dict[str, bool]
    detail: dict


def probe(ffprobe: Path, media: Path) -> dict:
    out = subprocess.run(
        [str(ffprobe), "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(media)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=True).stdout
    return json.loads(out)


def _fps(stream: dict) -> float:
    num, _, den = stream.get("r_frame_rate", "0/1").partition("/")
    return float(num) / float(den or 1)


def known_asset_ids(packet: ProductionPacket) -> set[str]:
    ids = {lock.asset_id for lock in packet.continuity_locks.characters.values()}
    ids |= {lock.asset_id for lock in packet.continuity_locks.locations.values()}
    ids |= {p.asset_id for s in packet.shots for p in s.props}
    return ids


def preflight(packet: ProductionPacket, media: Path, ffprobe: Path) -> QAResult:
    q = packet.qa
    checks: dict[str, bool] = {"file_exists": media.exists() and media.stat().st_size > 0}
    detail: dict = {}
    if checks["file_exists"]:
        info = probe(ffprobe, media)
        video = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
        audio = [s for s in info["streams"] if s["codec_type"] == "audio"]
        duration = float(info["format"]["duration"])
        detail.update({"duration": duration, "audio_streams": len(audio)})
        checks["has_video"] = video is not None
        checks["resolution"] = video is not None and (video["width"], video["height"]) == (q.width, q.height)
        checks["fps"] = video is not None and abs(_fps(video) - q.fps) < 0.01
        checks["duration"] = abs(duration - q.total_seconds) <= DURATION_TOLERANCE
        checks["audio"] = bool(audio) if q.require_audio else True
    checks["assets_known"] = set(q.required_asset_ids) <= known_asset_ids(packet)
    cues = packet.subtitle_plan
    checks["subtitles"] = all(0 <= c.start < c.end <= q.total_seconds for c in cues) and all(
        a.start <= b.start for a, b in zip(cues, cues[1:]))
    shots = packet.shots
    checks["timeline"] = bool(shots) and all(
        abs(b.start_seconds - (a.start_seconds + a.duration_seconds)) < 1e-6 for a, b in zip(shots, shots[1:])) and (
        shots[-1].start_seconds + shots[-1].duration_seconds <= q.total_seconds)
    passed = all(checks.values())
    return QAResult(passed, "deterministic_pass" if passed else "deterministic_fail", checks, detail)
