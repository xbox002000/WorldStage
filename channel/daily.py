"""The channel orchestrator (the one place that drives both the world and the production side): continue the world by one day, pick that day's story, make the episode.

The world is advanced on a copy and swapped in only when the day completed and the audit is clean, so a crash,
a dead network or a full disk can never leave a half-simulated day behind.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from agent.decision import GeminiDecider, SeededDecider
from agent.volition import VolitionDecider
from contracts.base import canonical_json
from narrative.director import select_thread
from narrative.scene_spec import build_scene_specs
from narrative.spatial import compile_spatial
from agent.llm import DEFAULT_MODEL, FallbackClient, build_chain
from agent.llm_cache import LLMCache
from contracts.stylepack import SUSPENSE_V1, StylePack
from narrative.selector import DEFAULT_PROTAGONISTS, select_daily
from production import db as prod
from production import experiment, series
from production.pipeline import EpisodeResult, make_episodes
from production.publisher import LocalPublisher
from world.db import connect, init_db
from world.reader import open_world_reader
from world.seed import build_world
from world.simulation import Simulation
from world.snapshot import snapshot_hash, world_revision
from world.state import audit

DEFAULT_ACTIVE = ("ming", "mei", "jun", "lan")


@dataclass
class DailyConfig:
    world_db: str
    prod_db: str
    out_dir: str
    days: int = 1
    seed: int = 184729
    init: bool = False
    use_llm: bool = False
    model: str = DEFAULT_MODEL
    max_calls: int = 60
    min_interval: float = 4.0
    use_openrouter: bool = True
    active_ids: tuple[str, ...] = DEFAULT_ACTIVE
    style: StylePack = SUSPENSE_V1
    orientation: str = "portrait"
    quality: str = "looks"
    render: bool = True
    experiment: str | None = None
    protagonists: frozenset[str] = field(default_factory=lambda: DEFAULT_PROTAGONISTS)
    # World C: rule motives for everyone the model does not decide for, an outside-event feed, and the story
    # director (threads) instead of the arc selector. A spatial plan is written next to each episode.
    world_c: bool = False
    feed: str | None = None
    recipe: str = "town_v1"  # which world recipe a new world is built from (world/recipes/*.json)
    look: str = "procedural"  # procedural | cast (the directed cartoon look; World C episodes only)


@dataclass(frozen=True)
class DayResult:
    sim_day: int
    status: str  # episode | quiet_day | render_failed | qa_failed
    episode: EpisodeResult | None
    usage: dict
    world_revision: int
    snapshot_hash: str


class LLMUnavailable(RuntimeError):
    pass


def create_world(path: str | Path, seed: int, recipe: str = "town_v1") -> None:
    conn = connect(path)
    init_db(conn, seed)
    build_world(conn, seed, recipe)
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()


def _copy_db(src: Path, dst: Path) -> None:
    for suffix in ("", "-wal", "-shm"):
        Path(str(dst) + suffix).unlink(missing_ok=True)
    a, b = sqlite3.connect(str(src)), sqlite3.connect(str(dst))
    with b:
        a.backup(b)
    a.close()
    b.close()


def _swap_in(work: Path, live: Path) -> None:
    """Replace the live world with the finished work copy. Stale WAL files must go first or SQLite would try to
    replay them onto the new file."""
    for suffix in ("-wal", "-shm"):
        Path(str(work) + suffix).unlink(missing_ok=True)
        Path(str(live) + suffix).unlink(missing_ok=True)
    os.replace(work, live)


def _models(client) -> list[str]:
    return [c.model for c in getattr(client, "clients", [client])]


def _usage(client, decider, sim: Simulation) -> dict:
    clients = getattr(client, "clients", [client]) if client is not None else []
    return {
        "llm_calls": getattr(client, "calls", 0), "llm_failures": getattr(client, "failures", 0),
        "switches": getattr(client, "switches", 0), "decider_errors": getattr(decider, "errors", 0),
        "unparseable": getattr(decider, "unparseable", 0),
        "models": sorted({c.model for c in clients if getattr(c, "calls", 0)}),
        "active_ids": sorted(sim.active_ids), "stats": dict(sim.stats),
    }


def _refuse_real_people(live: Path) -> None:
    """A world that holds a real public figure who was not fictionalized is research: it is never filmed."""
    from world.personas import assert_publishable
    check = connect(live)
    try:
        assert_publishable(check)
    finally:
        check.close()


def run_daily(cfg: DailyConfig, *, client_factory: Callable[[LLMCache], object] | None = None,
              sleep: Callable[[float], None] = time.sleep,
              on_day: Callable[[DayResult], None] | None = None) -> list[DayResult]:
    live = Path(cfg.world_db)
    if not live.exists():
        if not cfg.init:
            raise FileNotFoundError(f"{live} does not exist (use init to create a new world)")
        live.parent.mkdir(parents=True, exist_ok=True)
        create_world(live, cfg.seed, cfg.recipe)
    _refuse_real_people(live)
    Path(cfg.prod_db).parent.mkdir(parents=True, exist_ok=True)
    conn = prod.open_production_db(cfg.prod_db)
    try:
        if cfg.experiment:
            _freeze(cfg, live, conn)
        results = []
        for _ in range(cfg.days):
            results.append(_one_day(cfg, live, conn, client_factory))
            if on_day:
                on_day(results[-1])  # progress is visible as each day completes, not only at the very end
        return results
    finally:
        conn.close()


def _write_spatial(world: sqlite3.Connection, cand, folder: Path, thread, shown: set[int]) -> None:
    """How the chosen scene is staged in space (read-only), for a spatial backend such as Blender later."""
    spec = build_scene_specs(world, [cand], [folder.name])[0]
    plan = compile_spatial(spec)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "spatial_plan.json").write_text(canonical_json(plan), encoding="utf-8")
    (folder / "thread.json").write_text(canonical_json(thread), encoding="utf-8")
    from narrative.direction import plan_direction
    (folder / "director_plan.json").write_text(canonical_json(plan_direction(world, spec, thread, shown)), encoding="utf-8")


def _freeze(cfg: DailyConfig, live: Path, conn: sqlite3.Connection) -> None:
    probe = connect(live)
    seed = probe.execute("SELECT value FROM meta WHERE key = 'world_seed'").fetchone()[0]
    probe.close()
    models = [cfg.model] + (["openrouter-free"] if cfg.use_openrouter else []) if cfg.use_llm else [
        "volition" if cfg.world_c else "seeded"]
    if cfg.world_c:
        models = models + [f"feed:{cfg.feed or 'none'}", "director:threads"]
    config = experiment.build_config(
        experiment_id=cfg.experiment, world_seed=seed, active_ids=set(cfg.active_ids) if cfg.use_llm else set(),
        style=cfg.style, models=models, days=cfg.days, orientation=cfg.orientation, quality=cfg.quality)
    experiment.freeze(conn, config)  # records on the first day, refuses to continue if anything drifted since


def _one_day(cfg: DailyConfig, live: Path, conn: sqlite3.Connection, client_factory) -> DayResult:
    work = live.with_name(live.stem + ".work" + live.suffix)
    _copy_db(live, work)
    sim_conn = connect(work)
    try:
        client = None
        if cfg.use_llm:
            cache = LLMCache(sim_conn)
            client = client_factory(cache) if client_factory else build_chain(
                cfg.model, max_calls=cfg.max_calls, min_interval=cfg.min_interval, use_openrouter=cfg.use_openrouter,
                mode="record", cache=cache)
            active = GeminiDecider(client)
            seed = sim_conn.execute("SELECT value FROM meta WHERE key = 'world_seed'").fetchone()[0]
            ambient = VolitionDecider(seed) if cfg.world_c else SeededDecider(seed)
            active_ids = set(cfg.active_ids)
        else:
            seed = sim_conn.execute("SELECT value FROM meta WHERE key = 'world_seed'").fetchone()[0]
            active = ambient = VolitionDecider(seed) if cfg.world_c else SeededDecider(seed)
            active_ids = set()
        sim = Simulation(sim_conn, active, ambient, active_ids, feed=cfg.feed if cfg.world_c else None)
        (day,) = sim.run(1)
        problems = audit(sim_conn)
        if problems:
            raise RuntimeError(f"day {day + 1} left the world inconsistent: {problems[:3]}")
        usage = _usage(client, active, sim)
        if cfg.use_llm and usage["decider_errors"] and not usage["llm_calls"] - usage["llm_failures"]:
            raise LLMUnavailable(f"no model answered on day {day + 1}: {usage['decider_errors']} decisions failed")
        revision, snap = world_revision(sim_conn), snapshot_hash(sim_conn)
        sim_conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except BaseException:
        sim_conn.close()
        for suffix in ("", "-wal", "-shm"):
            Path(str(work) + suffix).unlink(missing_ok=True)
        raise
    sim_conn.close()
    _swap_in(work, live)

    world = open_world_reader(live)
    try:
        if cfg.world_c:
            cand, thread, _ = select_thread(world, day, series.used_event_ids(conn))
        else:
            cand, _ = select_daily(world, day, cfg.protagonists, cfg.style.weights, series.used_event_ids(conn))
        status, episode = "quiet_day", None
        if cand is not None:
            shown = series.used_event_ids(conn)
            (episode,) = make_episodes(world, conn, Path(cfg.out_dir), [cand], scene_ids=[f"day_{day + 1:02d}"],
                                       sim_day=day, orientation=cfg.orientation, style=cfg.style,
                                       quality=cfg.quality, render=cfg.render, route=cfg.look,
                                       threads=[thread] if cfg.world_c else None, shown=shown)
            status = ("episode" if episode.episode_id else
                      "render_failed" if episode.qa_status == "render_failed" else "qa_failed")
            if episode.video is not None:
                LocalPublisher(conn, episode.episode_id).publish(episode.video.parent)
            if cfg.world_c:
                _write_spatial(world, cand, Path(cfg.out_dir) / f"day_{day + 1:02d}", thread, shown)
        conn.execute("INSERT INTO daily_runs(experiment_id, sim_day, world_revision, snapshot_hash, episode_id, status, usage_json, "
                     "created_at) VALUES (?,?,?,?,?,?,?,strftime('%s','now'))",
                     (cfg.experiment, day, revision, snap, episode.episode_id if episode else None, status,
                      json.dumps(usage, sort_keys=True)))
        conn.commit()
    finally:
        world.close()
    return DayResult(day, status, episode, usage, revision, snap)
