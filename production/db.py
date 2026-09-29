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
SCHEMA_VERSION = 3
# v1 -> v2: episodes gained series bookkeeping columns
# v2 -> v3: provider_selections, visual_failures, repair_requests (new tables only: CREATE IF NOT EXISTS adds them)
V2_COLUMNS = (("sim_day", "INTEGER"), ("arc_kind", "TEXT"), ("score", "REAL"), ("continuity_json", "TEXT"),
              ("qa_status", "TEXT"), ("recap", "TEXT NOT NULL DEFAULT ''"))


def open_production_db(path: str | Path = ":memory:") -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    version = int(row[0]) if row else SCHEMA_VERSION
    if version < 2:
        have = {r["name"] for r in conn.execute("PRAGMA table_info(episodes)")}
        for name, decl in V2_COLUMNS:
            if name not in have:
                conn.execute(f"ALTER TABLE episodes ADD COLUMN {name} {decl}")
    conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
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


def set_take_status(conn: sqlite3.Connection, take_id: int, status: str) -> None:
    """A take that failed QA becomes 'rejected', so a later run can never reuse it as a cache hit."""
    conn.execute("UPDATE takes SET status = ? WHERE take_id = ?", (status, take_id))
    conn.commit()


def record_selection(conn: sqlite3.Connection, selection, chosen: str | None) -> None:
    conn.execute("INSERT OR REPLACE INTO provider_selections(selection_hash, capability, chosen, selection_json, created_at) "
                 "VALUES (?,?,?,?,?)", (selection.selection_hash, selection.requirement.capability, chosen,
                                        canonical_json(selection), _now()))
    conn.commit()


def record_failures(conn: sqlite3.Connection, take_id: int, failures: list) -> None:
    conn.executemany(
        "INSERT INTO visual_failures(take_id, shot_id, code, detector, evidence_json, created_at) VALUES (?,?,?,?,?,?)",
        [(take_id, f.shot_id, f.code, f.detector, canonical_json(f.evidence), _now()) for f in failures])
    conn.commit()


def record_repair(conn: sqlite3.Connection, repair, next_request_hash: str | None) -> None:
    conn.execute("INSERT OR IGNORE INTO repair_requests(repair_hash, shot_id, attempt, parent_request_hash, next_request_hash, "
                 "repair_json, created_at) VALUES (?,?,?,?,?,?,?)",
                 (repair.repair_hash, repair.shot_id, repair.attempt, repair.parent_request_hash, next_request_hash,
                  canonical_json(repair), _now()))
    conn.commit()


def record_qa(conn: sqlite3.Connection, take_id: int, layer: str, passed: bool, status: str, detail: dict) -> None:
    conn.execute("INSERT INTO qa_results(take_id, layer, passed, status, detail_json, created_at) VALUES (?,?,?,?,?,?)",
                 (take_id, layer, int(passed), status, canonical_json(detail), _now()))
    conn.commit()


def load_scene_spec(conn: sqlite3.Connection, scene_hash: str) -> SceneSpec:
    """Read a stored scene spec, bringing older contract versions up to the current one."""
    import json
    from contracts.migrate import migrate_scene_spec
    from contracts.scene_spec import finalize
    row = conn.execute("SELECT spec_json FROM scene_specs WHERE scene_hash = ?", (scene_hash,)).fetchone()
    if row is None:
        raise KeyError(scene_hash)
    data = json.loads(row[0])
    if data.get("version") != 3:
        return finalize(from_dict(SceneSpec, migrate_scene_spec(data)))
    return from_dict(SceneSpec, data)


def load_packet(conn: sqlite3.Connection, packet_hash: str) -> ProductionPacket:
    import json
    row = conn.execute("SELECT packet_json FROM packets WHERE packet_hash = ?", (packet_hash,)).fetchone()
    if row is None:
        raise KeyError(packet_hash)
    return from_dict(ProductionPacket, json.loads(row[0]))
