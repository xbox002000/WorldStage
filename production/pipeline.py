"""World (read-only) -> SceneSpec -> ProductionPacket -> RenderRequest -> Take -> deterministic QA -> episode files.

Nothing here can write to the world: it only ever holds a read-only connection (world.reader).
Renderers, synthesisers and models come from the capability registry (capability/defaults.py), never by name.
Two routes:
  procedural  a composition provider that draws every shot itself (HyperFrames today);
  shots       each shot from a visual.generate provider, staged by the SpatialPlan, diagnosed and repaired
              (production/shots.py), then a composition provider that takes clips.
"""
from __future__ import annotations

import shutil
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from capability.defaults import default_registry
from capability.registry import CapabilityRegistry
from contracts.base import canonical_json
from contracts.capability import Policy, Requirement
from contracts.render_request import RenderRequest, Take
from contracts.stylepack import SUSPENSE_V1, StylePack
from narrative.compiler import compile_packet
from narrative.direction import plan_direction
from narrative.performance import plan_performance
from narrative.scene_spec import build_scene_specs, validate_spec
from narrative.selector import Candidate, select_top
from narrative.spatial import compile_spatial
from production import db as prod
from production import series
from production.provenance import file_sha256
from production.qa import preflight
from production.shots import ShotOutcome, render_shot
from render.packet_html import to_srt
from world.reader import open_world_reader

FFMPEG_DIR = Path(__file__).resolve().parent.parent / "tools" / "ffmpeg" / "bin"
ROUTES = ("procedural", "cast", "shots")  # cast: the directed cartoon look (needs a DirectorPlan)
FEATURES = {"procedural": ["procedural_visuals"], "cast": ["directed_cast"], "shots": ["clips"]}


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
    episode_id: int | None = None
    recap: str = ""
    continuity: dict | None = None
    providers: dict | None = None  # capability -> the provider(s) that did the job
    shots: list[ShotOutcome] | None = None  # shots route: per-shot attempts, failures and repairs


def _pick(conn: sqlite3.Connection, registry: CapabilityRegistry, req: Requirement, policy: Policy):
    providers, sel = registry.choose(req, policy)
    prod.record_selection(conn, sel, sel.chosen[0])
    return providers[0]


def _render(conn: sqlite3.Connection, composer, request: RenderRequest) -> Take:
    try:
        take = composer.render(request)
        if take.status == "ready":
            take = Take(request.request_hash, "ready", None, take.artifact_path, file_sha256(Path(take.artifact_path)),
                        take.provider_job_id)
    except Exception as e:  # noqa: BLE001 - recorded, and the run carries on with the next scene
        take = Take(request.request_hash, "failed", error=str(e)[:500])
    return Take(take.request_hash, take.status, prod.record_take(conn, take), take.artifact_path, take.artifact_hash,
                take.provider_job_id, take.error)


def _runtime(world: sqlite3.Connection, cache: str | None = None):
    """The world played out in space. With `cache`, resumed from the checkpoint there when it fits this world's history
    (runtime/checkpoint.py) and written back, so a day's episode plays only that day, not the whole run again."""
    from runtime.world_runtime import WorldRuntime
    if cache:
        from runtime.checkpoint import open_runtime
        return open_runtime(world, cache)
    return WorldRuntime(world)


def make_episodes(world: sqlite3.Connection, conn: sqlite3.Connection, out_dir: Path, candidates: list[Candidate], *,
                  scene_ids: list[str] | None = None, sim_day: int | None = None, orientation: str = "portrait",
                  style: StylePack = SUSPENSE_V1, quality: str = "looks", render: bool = True, route: str = "procedural",
                  registry: CapabilityRegistry | None = None, policy: Policy = Policy(),
                  threads: list | None = None, shown: set[int] | frozenset[int] = frozenset(),
                  runtime_cache: str | None = None) -> list[EpisodeResult]:
    """Turn chosen arcs into episodes, one after another (a later episode's recap can cite an earlier one).

    With `threads` (one StoryThread per candidate, from the story director) each scene gets a DirectorPlan first,
    and the packet's shots follow it. `shown`: events earlier episodes showed (what the audience already knows)."""
    if route not in ROUTES:
        raise ValueError(f"unknown route {route!r} (one of {ROUTES})")
    registry = registry or default_registry(lambda h: prod.load_packet(conn, h))
    results: list[EpisodeResult] = []

    ids = scene_ids or [f"scene_{i + 1:02d}" for i in range(len(candidates))]
    for i, cand in enumerate(candidates):
        spec = build_scene_specs(world, [cand], [ids[i]])[0]
        validate_spec(world, spec)
        recap = series.build_recap(conn, spec)
        thread = threads[i] if threads else None
        direction = plan_direction(world, spec, thread, set(shown)) if thread is not None else None
        performance = plan_performance(world, spec, direction) if direction is not None else None
        runtime = _runtime(world, runtime_cache).trace([b.event_id for b in spec.beats]) if direction is not None else None
        packet = compile_packet(spec, style, orientation, recap=recap, direction=direction, performance=performance,
                                runtime=runtime)
        prod.save_scene_spec(conn, spec)
        prod.save_packet(conn, packet)
        total, w, h = packet.qa.total_seconds, packet.canvas.width, packet.canvas.height
        audio = _pick(conn, registry, Requirement(
            "audio.score", ["music", "sfx"] if packet.audio_plan.cues else [], total), policy)
        composer = _pick(conn, registry, Requirement(
            "composition.render", FEATURES[route] if direction is not None or route != "cast" else FEATURES["procedural"],
            total, w, h), policy)
        composer.audio = audio  # the composition carries the chosen soundtrack; its hash goes into the request
        providers: dict = {"audio.score": audio.name, "composition.render": composer.name}

        started = time.perf_counter()
        shots: list[ShotOutcome] | None = None
        request: RenderRequest | None = None
        if route in ("procedural", "cast"):  # an undirected packet on the cast route falls back to the procedural look
            request = composer.make_request(packet, quality=quality)
        elif render:
            workdir = getattr(composer, "workdir", out_dir / "_work")
            plan = compile_spatial(spec)
            shots = [render_shot(conn, packet, s, registry, workdir, plan=plan, policy=policy) for s in packet.shots]
            providers["visual.generate"] = sorted({o.provider for o in shots if o.provider})
            if all(o.ok for o in shots):
                request = composer.make_request(packet, clips={o.shot_id: (o.clip, o.clip_hash) for o in shots},
                                                quality=quality)
        if request is not None:
            prod.save_request(conn, request)

        cached = prod.ready_take(conn, request.request_hash) if request else None
        hit = bool(cached and cached.artifact_path and Path(cached.artifact_path).exists()
                   and file_sha256(Path(cached.artifact_path)) == cached.artifact_hash)
        if hit:
            take = cached
        elif not render:  # planned only (the shots route plans no request: its clips do not exist yet)
            take = Take(request.request_hash, "queued", prod.record_take(conn, Take(request.request_hash, "queued"))) \
                if request else Take("", "queued")
        elif request is None:  # some shot could not be made by any provider, even after repairs
            take = Take("", "failed", error="shots failed: " + ", ".join(o.shot_id for o in shots if not o.ok))
        else:
            take = _render(conn, composer, request)
        elapsed = time.perf_counter() - started

        video, qa_status, episode_id = None, "not_rendered", None
        if take.status == "ready" and take.artifact_path:
            qa = preflight(packet, Path(take.artifact_path), FFMPEG_DIR / "ffprobe")
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
                if direction is not None:
                    (target / "director_plan.json").write_text(canonical_json(direction), encoding="utf-8")
                episode_id = series.record_episode(
                    conn, scene_hash=spec.scene_hash, take_id=take.take_id, title=spec.title, sim_day=sim_day,
                    arc_kind=cand.arc.kind, score=cand.score, continuity=cand.continuity, qa_status=qa_status, recap=recap)
        elif take.status == "queued":  # planned but not rendered: still counts as told, so the series moves on
            episode_id = series.record_episode(
                conn, scene_hash=spec.scene_hash, take_id=take.take_id, title=spec.title, sim_day=sim_day,
                arc_kind=cand.arc.kind, score=cand.score, continuity=cand.continuity, qa_status="not_rendered",
                recap=recap, status="planned")
        elif take.status == "failed":
            qa_status = "render_failed"
        results.append(EpisodeResult(spec.scene_id, spec.title, take.take_id or 0, take.request_hash,
                                     packet.packet_hash, spec.scene_hash, video, hit, qa_status, elapsed,
                                     episode_id, recap, cand.continuity, providers, shots))
    return results


def produce(world_db: str | Path, prod_db: str | Path, out_dir: Path, *, top: int = 3, orientation: str = "portrait",
            style: StylePack = SUSPENSE_V1, quality: str = "looks", render: bool = True,
            prod_conn: sqlite3.Connection | None = None, exclude_used: bool = True, route: str = "procedural",
            registry: CapabilityRegistry | None = None, policy: Policy = Policy()) -> list[EpisodeResult]:
    """Batch: the best `top` stories not yet told. With exclude_used=False the same stories are picked again
    (and, being content-addressed, cost nothing to re-render)."""
    world = open_world_reader(world_db)
    conn = prod_conn or prod.open_production_db(prod_db)
    used = series.used_event_ids(conn) if exclude_used else set()
    chosen, _ = select_top(world, top, weights=style.weights, exclude=used)
    results = make_episodes(world, conn, out_dir, chosen, orientation=orientation, style=style, quality=quality,
                            render=render, route=route, registry=registry, policy=policy)
    world.close()
    if prod_conn is None:
        conn.close()
    return results
