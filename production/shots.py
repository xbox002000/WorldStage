"""Shot-level production: SpatialPlan -> control images -> RenderRequest -> visual provider -> Diagnose -> Repair.

Every provider comes from the capability registry; this module names none. For each shot:
1. the staged camera for the shot's beat gets control images (depth, mask) from a spatial.control provider,
   unless the plan is invalid (a blocked sight line), which is recorded as SPATIAL_ERROR and sends no control;
2. the shot's requirement (features, length, size) selects visual providers, best first;
3. the take is diagnosed; each measurable failure maps to a targeted repair (reseed, next provider, ...), which
   makes a new request for that shot only. A failed take is marked rejected so no cache ever reuses it.
The story is never touched: SceneSpec and packet stay as they are, only how the shot is made changes.
"""
from __future__ import annotations

import dataclasses
import hashlib
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from capability.registry import CapabilityRegistry, NoProvider
from contracts.backends import ShotRequest
from contracts.capability import Policy, Requirement
from contracts.packet import ProductionPacket, Shot
from contracts.render_request import RenderRequest, Take, make_request
from contracts.repair import RepairRequest, VisualFailure
from contracts.spatial import SpatialPlan
from production import db as prod
from production.provenance import file_sha256
from production.shot_qa import diagnose

MAX_ATTEMPTS = 4
CONTROL_SCALE = 4  # control images at a quarter of the canvas: enough for layout, cheap to ray-cast
# packet shot type -> the SpatialPlan camera that frames it
CAMERA_FOR = {"wide": "wide", "two_shot": "two_shot", "medium": "over_shoulder", "close_up": "over_shoulder",
              "insert": "insert"}
# failure -> what to change. Content failures cannot be detected yet; were a vision inspector to report one,
# reseeding is the only lever a text/depth-conditioned provider offers without new reference material.
REPAIRS: dict[str, list[str]] = {
    "PROVIDER_ERROR": ["fallback_provider"],
    "FORMAT_ERROR": ["fallback_provider"],
    "DURATION_ERROR": ["conform_duration", "fallback_provider"],
    "FROZEN_FRAMES": ["reseed"],
    "BLACK_FRAMES": ["reseed"],
    "IDENTITY_DRIFT": ["increase_reference_strength", "reseed"],
    "OBJECT_CONTINUITY_ERROR": ["lock_object_identity", "reseed"],
    "POSE_ERROR": ["preserve_hand_state", "reseed"],
}


@dataclass
class ShotOutcome:
    shot_id: str
    ok: bool
    clip: Path | None
    clip_hash: str | None
    provider: str | None
    attempts: int
    failures: list[VisualFailure] = field(default_factory=list)
    repairs: list[RepairRequest] = field(default_factory=list)
    take_id: int | None = None


def base_seed(packet: ProductionPacket, shot: Shot) -> int:
    return int.from_bytes(hashlib.sha256(f"{packet.packet_hash}:{shot.shot_id}".encode()).digest()[:4], "big") % 2 ** 31


def describe(shot: Shot) -> str:
    """A plain, backend-neutral description. Providers build their own prompt format from the ShotRequest."""
    who = ", ".join(f"{c.name} ({c.action}, {c.emotion})" for c in shot.characters)
    return (f"{shot.camera.shot_type} shot, {shot.camera.movement}. {shot.location.name}, {shot.lighting.time_of_day}, "
            f"{shot.lighting.weather}. {who}. {shot.action}.")


def _camera_index(plan: SpatialPlan, shot: Shot) -> tuple[int, int] | None:
    beat = next((b for b in plan.beats if b.event_id == shot.event_id), None)
    if beat is None or not beat.cameras:
        return None
    want = CAMERA_FOR.get(shot.camera.shot_type, "wide")
    cam = next((i for i, c in enumerate(beat.cameras) if c.shot == want), 0)
    return beat.beat_index, cam


def _controls(conn, registry, policy, plan, shot, packet, workdir) -> tuple[dict[str, Path], list[VisualFailure]]:
    if plan is None:
        return {}, []
    if not plan.valid:
        bad = "; ".join(plan.problems)[:300] or "a required sight line is blocked"
        return {}, [VisualFailure("SPATIAL_ERROR", shot.shot_id, "", "spatial_plan", {"problems": bad})]
    where = _camera_index(plan, shot)
    if where is None:
        return {}, []
    w, h = packet.canvas.width // CONTROL_SCALE, packet.canvas.height // CONTROL_SCALE
    try:
        (spatial, *_), sel = registry.choose(Requirement("spatial.control", ["depth"], 0, w, h), policy)
    except NoProvider as e:
        prod.record_selection(conn, e.selection, None)
        return {}, []
    prod.record_selection(conn, sel, sel.chosen[0])
    out: dict[str, Path] = {}
    for kind, data in sorted(spatial.controls(plan, where[0], where[1], w, h).items()):
        path = workdir / "controls" / f"{hashlib.sha256(data).hexdigest()[:16]}.{'json' if kind == 'legend' else 'png'}"
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(data)
        out[kind] = path
    return out, []


def render_shot(conn: sqlite3.Connection, packet: ProductionPacket, shot: Shot, registry: CapabilityRegistry,
                workdir: Path, *, plan: SpatialPlan | None = None, policy: Policy = Policy(),
                max_attempts: int = MAX_ATTEMPTS) -> ShotOutcome:
    controls, early = _controls(conn, registry, policy, plan, shot, packet, workdir)
    features = ["t2v"] + (["depth"] if "depth" in controls else [])
    req = Requirement("visual.generate", features, float(shot.duration_seconds), packet.canvas.width, packet.canvas.height)
    outcome = ShotOutcome(shot.shot_id, False, None, None, None, 0, list(early))
    try:
        providers, sel = registry.choose(req, policy)
    except NoProvider as e:
        prod.record_selection(conn, e.selection, None)
        return outcome
    ffmpeg_dir = Path(__file__).resolve().parent.parent / "tools" / "ffmpeg" / "bin"
    control_hashes = {f"control:{k}": file_sha256(p) for k, p in controls.items()}
    which, seed, parent, pending = 0, base_seed(packet, shot), None, None
    shot_req = ShotRequest(shot.shot_id, describe(shot), float(shot.duration_seconds), packet.canvas.width,
                           packet.canvas.height, packet.canvas.fps, seed, subject=shot.subject, action=shot.action,
                           environment=shot.environment, camera=f"{shot.camera.shot_type}/{shot.camera.movement}",
                           controls={k: str(p) for k, p in controls.items() if k in ("depth", "mask")},
                           reference_asset_ids=sorted(c.asset_id for c in shot.characters))
    while outcome.attempts < max_attempts and which < len(providers):
        provider = providers[which]
        outcome.attempts += 1
        shot_req = dataclasses.replace(shot_req, seed=seed)
        params = {"shot_id": shot.shot_id, "seconds": f"{shot.duration_seconds:g}", "width": str(shot_req.width),
                  "height": str(shot_req.height), "fps": str(shot_req.fps), "features": ",".join(features)}
        if parent:
            params["repair_of"] = parent
        request = make_request(kind="shot", backend=provider.manifest().provider_id,
                               backend_version=provider.manifest().version, parameters=params,
                               packet_hash=packet.packet_hash, seed=seed, asset_hashes=control_hashes,
                               toolchain=provider.toolchain())
        prod.save_request(conn, request)
        if pending is not None:  # the repair that led to this request
            prod.record_repair(conn, pending, request.request_hash)
            pending = None
        take = _take(conn, provider, request, shot_req, workdir)
        failures = diagnose(take, shot_req, ffmpeg_dir)
        if failures:
            prod.record_failures(conn, take.take_id, failures)
            prod.set_take_status(conn, take.take_id, "rejected" if take.status == "ready" else take.status)
            outcome.failures += failures
        else:
            prod.record_selection(conn, sel, provider.manifest().provider_id)
            outcome.ok, outcome.clip, outcome.clip_hash = True, Path(take.artifact_path), take.artifact_hash
            outcome.provider, outcome.take_id = provider.manifest().provider_id, take.take_id
            return outcome
        ops = list(dict.fromkeys(op for f in failures for op in REPAIRS.get(f.code, ["reseed"])))
        repair = RepairRequest(shot.shot_id, failures, ops, outcome.attempts, request.request_hash)
        repair = dataclasses.replace(repair, repair_hash=repair.compute_hash())
        if "fallback_provider" in ops or "conform_duration" in ops:
            which += 1  # conforming length would need a provider option; the next provider is the lever we have
        if "reseed" in ops:
            seed = (seed + 7919 * outcome.attempts) % 2 ** 31
        parent = request.request_hash
        outcome.repairs.append(repair)
        pending = repair
    if pending is not None:  # nothing left to try
        prod.record_repair(conn, pending, None)
    prod.record_selection(conn, sel, None)
    return outcome


def _take(conn: sqlite3.Connection, provider, request: RenderRequest, shot: ShotRequest, workdir: Path) -> Take:
    cached = prod.ready_take(conn, request.request_hash)
    if cached and cached.artifact_path and Path(cached.artifact_path).exists() and \
            file_sha256(Path(cached.artifact_path)) == cached.artifact_hash:
        return cached
    dest = workdir / "shots" / f"{request.request_hash.split(':', 1)[1][:16]}.mp4"
    try:
        take = provider.generate(request, shot, dest)
    except Exception as e:  # noqa: BLE001 - a provider that raises is a failed take, diagnosed like any other
        take = Take(request.request_hash, "failed", error=f"{type(e).__name__}: {e}"[:400])
    return dataclasses.replace(take, take_id=prod.record_take(conn, take))
