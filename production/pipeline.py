"""World (read-only) -> SceneSpec -> ProductionPacket -> RenderRequest -> Take -> deterministic QA -> episode files.

Nothing here can write to the world: it only ever holds a read-only connection (world.reader).
"""
from __future__ import annotations

import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from contracts.base import canonical_json
from contracts.render_request import Take
from contracts.stylepack import SUSPENSE_V1, StylePack
from narrative.compiler import compile_packet
from narrative.scene_spec import build_scene_specs, validate_spec
from narrative.selector import select_top
from production import db as prod
from production.provenance import file_sha256
from production.qa import preflight
from render.hyperframes_backend import FFMPEG_DIR, HyperFramesBackend
from render.packet_html import to_srt
from world.reader import open_world_reader


@dataclass(frozen=True)
class EpisodeResult:
    scene_id: str
    title: str
    take_id: int
    request_hash: str
    packet_hash: str
    scene_hash: str
    video: Path | None
    cache_hit: bool
    qa_status: str
    seconds: float


def produce(world_db: str | Path, prod_db: str | Path, out_dir: Path, *, top: int = 3, orientation: str = "portrait",
            style: StylePack = SUSPENSE_V1, quality: str = "looks", render: bool = True,
            prod_conn: sqlite3.Connection | None = None) -> list[EpisodeResult]:
    import time

    world = open_world_reader(world_db)
    conn = prod_conn or prod.open_production_db(prod_db)
    backend = HyperFramesBackend(lambda h: prod.load_packet(conn, h))
    ffprobe = FFMPEG_DIR / "ffprobe"
    results: list[EpisodeResult] = []

    chosen, _ = select_top(world, top)
    for spec in build_scene_specs(world, chosen):
        validate_spec(world, spec)
        packet = compile_packet(spec, style, orientation)
        request = backend.make_request(packet, quality=quality)
        prod.save_scene_spec(conn, spec)
        prod.save_packet(conn, packet)
        prod.save_request(conn, request)

        started = time.perf_counter()
        cached = prod.ready_take(conn, request.request_hash)
        hit = bool(cached and cached.artifact_path and Path(cached.artifact_path).exists()
                   and file_sha256(Path(cached.artifact_path)) == cached.artifact_hash)
        if hit:
            take = cached
        elif not render:
            take = Take(request.request_hash, "queued", prod.record_take(conn, Take(request.request_hash, "queued")))
        else:
            try:
                job = backend.submit(request, idempotency_key=request.request_hash)
                mp4 = backend.poll(job).artifact_path
                take = Take(request.request_hash, "ready", None, mp4, file_sha256(Path(mp4)))
            except Exception as e:  # noqa: BLE001 - recorded, and the run carries on with the next scene
                take = Take(request.request_hash, "failed", error=str(e)[:500])
            take = Take(take.request_hash, take.status, prod.record_take(conn, take), take.artifact_path,
                        take.artifact_hash, error=take.error)
        elapsed = time.perf_counter() - started

        video, qa_status = None, "not_rendered"
        if take.status == "ready" and take.artifact_path:
            qa = preflight(packet, Path(take.artifact_path), ffprobe)
            if not hit:
                prod.record_qa(conn, take.take_id, "deterministic", qa.passed, qa.status, {"checks": qa.checks, **qa.detail})
            qa_status = qa.status + "_visual_unchecked" if qa.passed else qa.status
            if qa.passed:
                target = out_dir / spec.scene_id
                target.mkdir(parents=True, exist_ok=True)
                video = target / "episode.mp4"
                shutil.copyfile(take.artifact_path, video)
                (target / "subtitles.srt").write_text(to_srt(packet), encoding="utf-8")
                (target / "packet.json").write_text(canonical_json(packet), encoding="utf-8")
                (target / "scene_spec.json").write_text(canonical_json(spec), encoding="utf-8")
                if not conn.execute("SELECT 1 FROM episodes WHERE scene_hash = ? AND take_id = ?",
                                    (spec.scene_hash, take.take_id)).fetchone():
                    conn.execute("INSERT INTO episodes(scene_hash, take_id, title, status, created_at) VALUES (?,?,?,?,strftime('%s','now'))",
                                 (spec.scene_hash, take.take_id, spec.title, "draft"))
                    conn.commit()
        elif take.status == "failed":
            qa_status = "render_failed"
        results.append(EpisodeResult(spec.scene_id, spec.title, take.take_id or 0, request.request_hash,
                                     packet.packet_hash, spec.scene_hash, video, hit, qa_status, elapsed))
    world.close()
    if prod_conn is None:
        conn.close()
    return results
