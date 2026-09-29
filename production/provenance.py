"""Trace a finished artifact back to the world events that caused it, checking every hash on the way.

    Take -> RenderRequest -> ProductionPacket -> SceneSpec -> source events -> world history
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from contracts import packet as packet_mod
from contracts import scene_spec as scene_mod
from contracts.base import from_dict, hash_without
from contracts.packet import ProductionPacket
from contracts.render_request import RenderRequest
from contracts.scene_spec import SceneSpec
from world.snapshot import history_hash, snapshot_hash, world_revision


class ProvenanceError(RuntimeError):
    pass


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def trace_take(prod: sqlite3.Connection, world: sqlite3.Connection, take_id: int) -> dict:
    """Verify the whole chain for one take and return each link's hash. Raises ProvenanceError on any mismatch."""
    take = prod.execute("SELECT * FROM takes WHERE take_id = ?", (take_id,)).fetchone()
    if take is None:
        raise ProvenanceError(f"take {take_id} not found")
    if take["artifact_path"]:
        path = Path(take["artifact_path"])
        if not path.exists() or file_sha256(path) != take["artifact_hash"]:
            raise ProvenanceError("artifact file does not match the recorded artifact_hash")

    row = prod.execute("SELECT request_json FROM render_requests WHERE request_hash = ?", (take["request_hash"],)).fetchone()
    request = from_dict(RenderRequest, json.loads(row[0]))
    if request.request_hash != take["request_hash"] or hash_without(request, "request_hash") != request.request_hash:
        raise ProvenanceError("render request hash mismatch")

    row = prod.execute("SELECT packet_json FROM packets WHERE packet_hash = ?", (request.packet_hash,)).fetchone()
    packet = from_dict(ProductionPacket, json.loads(row[0]))
    if not packet_mod.verify(packet) or packet.packet_hash != request.packet_hash:
        raise ProvenanceError("packet hash mismatch")

    row = prod.execute("SELECT spec_json FROM scene_specs WHERE scene_hash = ?", (packet.scene_hash,)).fetchone()
    spec = from_dict(SceneSpec, json.loads(row[0]))
    if not scene_mod.verify(spec) or spec.scene_hash != packet.scene_hash:
        raise ProvenanceError("scene spec hash mismatch")

    src = spec.source
    if history_hash(world, src.world_revision) != src.history_hash:
        raise ProvenanceError("world history up to the source revision no longer matches (history was altered)")
    known = {r[0] for r in world.execute("SELECT event_id FROM events WHERE event_id <= ?", (src.world_revision,))}
    missing = set(src.source_event_ids) - known
    if missing:
        raise ProvenanceError(f"source events missing from world history: {sorted(missing)}")
    current = world_revision(world)
    return {
        "artifact_hash": take["artifact_hash"], "request_hash": request.request_hash, "packet_hash": packet.packet_hash,
        "scene_hash": spec.scene_hash, "world_revision": src.world_revision, "history_hash": src.history_hash,
        "source_event_ids": list(src.source_event_ids),
        # The full snapshot (which includes current state) can only be re-checked while the world has not moved on.
        "snapshot_checked": current == src.world_revision,
        "snapshot_ok": (snapshot_hash(world) == src.world_snapshot_hash) if current == src.world_revision else None,
        "world_moved_on_by": current - src.world_revision,
    }
