"""production.db access. This is the only place in production/ allowed to open a writable SQLite file,
and it is a different file from world.db."""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from contracts.base import canonical_json, from_dict
from contracts.packet import ProductionPacket
from contracts.render_request import RenderRequest, Take
from contracts.scene_spec import SceneSpec

SCHEMA = Path(__file__).with_name("schema.sql")


def open_production_db(path: str | Path = ":memory:") -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    conn.execute("INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', '1')")
    conn.commit()
    return conn


def _now() -> int:
    return int(time.time())


def save_scene_spec(conn: sqlite3.Connection, spec: SceneSpec) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO scene_specs(scene_hash, world_revision, history_hash, spec_json, created_at) VALUES (?,?,?,?,?)",
        (spec.scene_hash, spec.source.world_revision, spec.source.history_hash, canonical_json(spec), _now()))
    conn.commit()


def save_packet(conn: sqlite3.Connection, packet: ProductionPacket) -> None:
    conn.execute("INSERT OR IGNORE INTO packets(packet_hash, scene_hash, packet_json, created_at) VALUES (?,?,?,?)",
                 (packet.packet_hash, packet.scene_hash, canonical_json(packet), _now()))
    conn.commit()


def save_request(conn: sqlite3.Connection, request: RenderRequest) -> None:
    conn.execute("INSERT OR IGNORE INTO render_requests(request_hash, packet_hash, request_json, created_at) VALUES (?,?,?,?)",
                 (request.request_hash, request.packet_hash, canonical_json(request), _now()))
    conn.commit()


def record_take(conn: sqlite3.Connection, take: Take) -> int:
    cur = conn.execute(
        "INSERT INTO takes(request_hash, status, artifact_path, artifact_hash, provider_job_id, error, created_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (take.request_hash, take.status, take.artifact_path, take.artifact_hash, take.provider_job_id, take.error, _now()))
    conn.commit()
    return int(cur.lastrowid)


def ready_take(conn: sqlite3.Connection, request_hash: str) -> Take | None:
    """The newest usable take for this exact request, if any: the reason a re-render can cost nothing."""
    r = conn.execute(
        "SELECT * FROM takes WHERE request_hash = ? AND status IN ('ready','selected') ORDER BY take_id DESC LIMIT 1",
        (request_hash,)).fetchone()
    if r is None:
        return None
    return Take(r["request_hash"], r["status"], r["take_id"], r["artifact_path"], r["artifact_hash"], r["provider_job_id"], r["error"])


def record_qa(conn: sqlite3.Connection, take_id: int, layer: str, passed: bool, status: str, detail: dict) -> None:
    conn.execute("INSERT INTO qa_results(take_id, layer, passed, status, detail_json, created_at) VALUES (?,?,?,?,?,?)",
                 (take_id, layer, int(passed), status, canonical_json(detail), _now()))
    conn.commit()


def load_packet(conn: sqlite3.Connection, packet_hash: str) -> ProductionPacket:
    import json
    row = conn.execute("SELECT packet_json FROM packets WHERE packet_hash = ?", (packet_hash,)).fetchone()
    if row is None:
        raise KeyError(packet_hash)
    return from_dict(ProductionPacket, json.loads(row[0]))
