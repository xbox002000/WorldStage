from __future__ import annotations

import dataclasses
import json
import os
import re
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent.llm import LLMClient
from contracts.stylepack import SUSPENSE_V1
from production import db as prod
from production import series
from channel.daily import DailyConfig, LLMUnavailable, run_daily
from production.experiment import ExperimentDrift, build_config, differences, freeze
from production.publisher import BASE_TAGS, DISCLOSURE, LocalPublisher, compose_listing
from channel.replay import replay_check
from world.db import connect
from world.reader import open_world_reader
from world.simulation import Simulation
from world.snapshot import snapshot_hash, world_revision


class ApiError(Exception):
    def __init__(self, code: int):
        self.code = code


def fake_model(prompt: str, schema: dict, temperature: float) -> str:
    """Stands in for Gemini. Confronts when it can, otherwise tells (mode by prompt length), otherwise talks."""
    m = re.search(r"- confront (\w+) about memory_id (\d+)", prompt)
    if m:
        return json.dumps({"action": "confront", "target": m.group(1), "memory_id": int(m.group(2)), "reason": "fake"})
    m = re.search(r"claim_id (\d+): [^\n]*could tell: (\w+)", prompt)
    if m and len(prompt) % 2 == 0:
        return json.dumps({"action": "tell", "target": m.group(2), "claim_id": int(m.group(1)),
                           "mode": ("lie", "truth", "distortion")[len(prompt) % 3], "reason": "fake"})
    target = re.search(r"^- (\w+) \(", prompt, re.M)
    if not target:
        return json.dumps({"action": "idle", "reason": "fake"})
    return json.dumps({"action": "talk", "target": target.group(1), "tone": ("warm", "cold", "hostile")[len(prompt) % 3],
                       "reason": "fake"})


def factory(backend=fake_model):
    return lambda cache: LLMClient("fake-model", mode="record", cache=cache, backend=backend, min_interval=0, sleep=lambda s: None)


class Workspace(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="daily_")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.world = os.path.join(self.tmp, "world.db")
        self.prod = os.path.join(self.tmp, "p.db")

    def cfg(self, **kw):
        base = dict(world_db=self.world, prod_db=self.prod, out_dir=os.path.join(self.tmp, "eps"), days=1, init=True,
                    seed=21, render=False)
        base.update(kw)
        return DailyConfig(**base)

    def snapshot(self):
        r = open_world_reader(self.world)
        try:
            return snapshot_hash(r), world_revision(r)
        finally:
            r.close()


class DailyJobTests(Workspace):
    def test_the_world_advances_one_day_at_a_time_and_leaves_no_scratch_files(self):
        results = run_daily(self.cfg(days=2))
        self.assertEqual([r.sim_day for r in results], [0, 1])
        leftovers = [p.name for p in Path(self.tmp).iterdir() if p.is_file() and "work" in p.name]
        self.assertEqual(leftovers, [])  # (SQLite's own empty -wal/-shm sidecars are not scratch files)
        self.assertTrue({"p.db", "world.db"} <= {p.name for p in Path(self.tmp).iterdir()})
        conn = connect(self.world)
        self.assertEqual(Simulation(conn, None, None, set()).next_day(), 2)
        conn.close()
        runs = sqlite3.connect(self.prod).execute("SELECT sim_day, world_revision, snapshot_hash FROM daily_runs ORDER BY run_id").fetchall()
        self.assertEqual([r[0] for r in runs], [0, 1])
        self.assertLess(runs[0][1], runs[1][1])
        self.assertEqual((runs[1][2], runs[1][1])[0], self.snapshot()[0])  # the recorded hash is the world as it now stands

    def test_a_day_that_fails_leaves_the_world_exactly_as_it_was(self):
        run_daily(self.cfg(days=1))
        before = self.snapshot()
        with mock.patch("channel.daily.audit", return_value=["pretend inconsistency"]):
            with self.assertRaises(RuntimeError):
                run_daily(self.cfg(init=False))
        self.assertEqual(self.snapshot(), before)
        self.assertEqual([p.name for p in Path(self.tmp).iterdir() if "work" in p.name], [])
        self.assertEqual(sqlite3.connect(self.prod).execute("SELECT COUNT(*) FROM daily_runs").fetchone()[0], 1)

    def test_each_day_tells_a_new_story(self):
        run_daily(self.cfg(days=4))
        conn = prod.open_production_db(self.prod)
        rows = conn.execute("SELECT scene_hash FROM episodes ORDER BY episode_id").fetchall()
        self.assertEqual(len(rows), 4)
        shown: set[int] = set()
        for r in rows:
            events = set(prod.load_scene_spec(conn, r["scene_hash"]).source.source_event_ids)
            self.assertFalse(shown & events)  # nothing is told twice
            shown |= events
        self.assertEqual(series.used_event_ids(conn), shown)
        conn.close()

    def test_a_missing_world_needs_init(self):
        with self.assertRaises(FileNotFoundError):
            run_daily(self.cfg(init=False))


class LLMDayTests(Workspace):
    def test_a_language_model_drives_the_active_tier_and_the_run_replays_exactly(self):
        results = run_daily(self.cfg(days=3, use_llm=True), client_factory=factory())
        usage = [r.usage for r in results]
        self.assertTrue(all(u["llm_calls"] > 0 for u in usage))
        conn = connect(self.world)
        acts = dict(conn.execute("SELECT json_extract(truth,'$.mode') m, COUNT(*) FROM events WHERE type='tell' GROUP BY m").fetchall())
        model_events = conn.execute("SELECT COUNT(*) FROM events WHERE json_extract(truth,'$.source') = 'fake-model'").fetchone()[0]
        recorded = conn.execute("SELECT COUNT(*) FROM llm_cache").fetchone()[0]
        conn.close()
        self.assertGreater(model_events, 0)
        self.assertGreaterEqual(recorded, sum(u["llm_calls"] for u in usage) - 0)  # every answer is on record
        replay = replay_check(self.world)
        self.assertTrue(replay["identical"], replay)
        self.assertEqual(replay["days"], 3)
        self.assertEqual(replay["models"], ["fake-model"])

    def test_calls_that_failed_are_recorded_too_so_the_replay_matches(self):
        def flaky(prompt, schema, temperature):
            if len(prompt) % 3 == 0:
                raise ApiError(400)  # not retryable: the decision simply does not happen
            return fake_model(prompt, schema, temperature)

        results = run_daily(self.cfg(days=2, use_llm=True), client_factory=factory(flaky))
        self.assertGreater(sum(r.usage["decider_errors"] for r in results), 0)
        conn = connect(self.world)
        failures = conn.execute("SELECT COUNT(*) FROM llm_cache WHERE response_json LIKE '%__failed__%'").fetchone()[0]
        conn.close()
        self.assertGreater(failures, 0)
        self.assertTrue(replay_check(self.world)["identical"])

    def test_when_no_model_answers_the_day_is_abandoned(self):
        run_daily(self.cfg(days=1))
        before = self.snapshot()

        def dead(prompt, schema, temperature):
            raise ApiError(400)

        with self.assertRaises(LLMUnavailable):
            run_daily(self.cfg(init=False, use_llm=True), client_factory=factory(dead))
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(sqlite3.connect(self.prod).execute("SELECT COUNT(*) FROM daily_runs").fetchone()[0], 1)


class ExperimentTests(Workspace):
    def test_the_first_day_freezes_the_setup_and_later_days_must_match(self):
        run_daily(self.cfg(days=1, experiment="A"))
        run_daily(self.cfg(days=2, init=False, experiment="A"))  # more days is fine
        other = dataclasses.replace(SUSPENSE_V1, version=2, weights={**SUSPENSE_V1.weights, "revelation": 0.30, "conflict": 0.10})
        with self.assertRaises(ExperimentDrift) as ctx:
            run_daily(self.cfg(init=False, experiment="A", style=other))
        self.assertTrue({"stylepack", "scorer_weights"} <= set(ctx.exception.differences))
        self.assertEqual(sqlite3.connect(self.prod).execute("SELECT COUNT(*) FROM daily_runs").fetchone()[0], 3)

    def test_a_new_experiment_id_starts_fresh(self):
        run_daily(self.cfg(days=1, experiment="A"))
        other = dataclasses.replace(SUSPENSE_V1, version=2)
        run_daily(self.cfg(init=False, experiment="B", style=other))
        rows = sqlite3.connect(self.prod).execute("SELECT experiment_id FROM experiments ORDER BY experiment_id").fetchall()
        self.assertEqual([r[0] for r in rows], ["A", "B"])

    def test_frozen_configs_are_immutable_and_diffs_name_the_change(self):
        conn = prod.open_production_db()
        cfg = build_config(experiment_id="A", world_seed=1, active_ids={"ming"}, style=SUSPENSE_V1, models=["m"], days=7,
                           orientation="portrait", quality="looks")
        freeze(conn, cfg)
        freeze(conn, cfg)  # idempotent
        with self.assertRaises(sqlite3.DatabaseError):
            conn.execute("UPDATE experiments SET config_json = '{}'")
        changed = {**cfg, "models": ["other"], "prompt_version": "p9"}
        self.assertEqual(set(differences(cfg, changed)), {"models", "prompt_version"})
        with self.assertRaises(ExperimentDrift):
            freeze(conn, changed)


    def test_only_the_story_is_frozen_not_the_look(self):
        from production.experiment import check_frozen, presentation_hash, story_hash
        conn = prod.open_production_db()
        cfg = build_config(experiment_id="A", world_seed=1, active_ids={"ming"}, style=SUSPENSE_V1, models=["m"], days=7,
                           orientation="portrait", quality="looks")
        freeze(conn, cfg)
        restyled = {**cfg, "presentation_hash": "sha256:other", "render": {"orientation": "landscape", "quality": "delivery"}, "days": 30}
        check_frozen(conn, "A", restyled)  # no error: how it looks, and how many days, do not matter
        with self.assertRaises(ExperimentDrift) as ctx:
            check_frozen(conn, "A", {**cfg, "story_hash": "sha256:other"})
        self.assertEqual(set(ctx.exception.differences), {"story_hash"})
        self.assertNotEqual(story_hash(), presentation_hash())
        self.assertEqual(story_hash(), story_hash())


class ListingTests(Workspace):
    def test_listing_is_deterministic_honest_and_within_limits(self):
        from tests.world_fixture import build_specs, compile_all
        spec, packet = build_specs()[0], compile_all()[0]
        a, b = compose_listing(spec, packet), compose_listing(spec, packet)
        self.assertEqual(a, b)
        self.assertLessEqual(len(a["title"]), 100)
        self.assertIn(spec.title, a["title"])
        self.assertIn(DISCLOSURE, a["description"])
        for shot in packet.shots:
            self.assertIn(shot.caption, a["description"])
        self.assertTrue(set(p.name for p in spec.characters.values()) <= set(a["tags"]))
        peak = next(b for b in spec.beats if b.event_id == spec.peak_event_id)
        lead = [spec.characters[p.id].name for p in peak.participants[:2]]
        tags = a["tags"]
        self.assertEqual(tags[len(BASE_TAGS):len(BASE_TAGS) + 2], lead)  # the story's own people come first
        self.assertTrue(a["hashtags"].count("#") <= 8)

    def test_publishing_writes_the_files_and_records_it(self):
        from contracts.base import canonical_json
        from tests.world_fixture import build_specs, compile_all
        spec, packet = build_specs()[0], compile_all()[0]
        folder = Path(self.tmp) / "ep"
        folder.mkdir()
        (folder / "scene_spec.json").write_text(canonical_json(spec), encoding="utf-8")
        (folder / "packet.json").write_text(canonical_json(packet), encoding="utf-8")
        conn = prod.open_production_db(self.prod)
        prod.save_scene_spec(conn, spec)
        eid = series.record_episode(conn, scene_hash=spec.scene_hash, take_id=None, title=spec.title, sim_day=0, arc_kind="pair",
                                    score=0.5, continuity=None, qa_status="ok", recap="")
        ref = LocalPublisher(conn, eid).publish(folder)
        self.assertTrue(Path(ref).exists())
        self.assertIn("#", (folder / "description.txt").read_text(encoding="utf-8"))
        self.assertEqual(conn.execute("SELECT publisher FROM publications").fetchone()[0], "local")
        conn.close()


if __name__ == "__main__":
    unittest.main()
