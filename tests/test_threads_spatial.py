"""Story threads, the story director and the spatial plan: read-only layers that must never change the world."""
from __future__ import annotations

import functools
import os
import tempfile
import unittest

from agent.volition import VolitionDecider
from contracts.base import canonical_json, from_dict
from contracts.spatial import SpatialObject, SpatialPlan, verify
from narrative.director import rank_threads, select_thread
from narrative.scene_spec import build_scene_specs
from narrative.spatial import blocker, compile_spatial
from narrative.threads import derive_threads
from world.db import connect, init_db
from world.reader import open_world_reader
from world.seed import build_world
from world.simulation import Simulation
from world.snapshot import snapshot_hash

SEED = 260931


@functools.lru_cache(maxsize=None)
def world_path(days: int = 10) -> str:
    path = os.path.join(tempfile.mkdtemp(prefix="worldc_"), "world.db")
    conn = connect(path)
    init_db(conn, SEED)
    build_world(conn, SEED)
    d = VolitionDecider(SEED)
    Simulation(conn, d, d, set(), feed="synthetic_v1").run(days)
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()
    return path


class ThreadTests(unittest.TestCase):
    def setUp(self):
        self.world = open_world_reader(world_path())

    def tearDown(self):
        self.world.close()

    def test_threads_are_derived_deterministically(self):
        self.assertEqual([t.hash() for t in derive_threads(self.world)], [t.hash() for t in derive_threads(self.world)])

    def test_a_thread_can_run_for_days_and_cross_another(self):
        threads = derive_threads(self.world)
        self.assertTrue(any(t.last_day - t.first_day >= 2 and len(t.event_ids) >= 4 for t in threads))
        self.assertTrue(any(t.cross_threads for t in threads))

    def test_seed_threads_are_marked_with_their_origin(self):
        seeded = [t for t in derive_threads(self.world) if t.seed_origins]
        self.assertTrue(seeded)
        self.assertTrue(all(o.startswith("syn-") for t in seeded for o in t.seed_origins))


class DirectorTests(unittest.TestCase):
    def test_following_a_thread_does_not_change_the_world(self):
        world = open_world_reader(world_path())
        before = snapshot_hash(world)
        for day in range(10):
            select_thread(world, day)
        self.assertEqual(snapshot_hash(world), before)
        world.close()

    def test_director_on_or_off_the_world_runs_the_same(self):
        def run(watch: bool) -> str:
            conn = connect()
            init_db(conn, SEED)
            build_world(conn, SEED)
            d = VolitionDecider(SEED)
            sim = Simulation(conn, d, d, set(), feed="synthetic_v1")
            for day in range(4):
                sim.run(1)
                if watch:
                    rank_threads(conn, day)
            return snapshot_hash(conn)
        self.assertEqual(run(True), run(False))

    def test_the_pick_contains_a_chosen_act_and_is_new(self):
        world = open_world_reader(world_path())
        cand, thread, _ = select_thread(world, 9)
        self.assertIsNotNone(cand)
        self.assertTrue(set(thread.decision_event_ids) & set(cand.arc.ids))
        shown = set(cand.arc.ids)
        again, _, _ = select_thread(world, 9, shown)
        if again is not None:
            self.assertFalse(set(again.arc.ids) <= shown)
        world.close()


class SpatialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        world = open_world_reader(world_path())
        cand, _, _ = select_thread(world, 9)
        cls.spec = build_scene_specs(world, [cand])[0]
        world.close()

    def test_plan_is_deterministic_and_round_trips(self):
        a, b = compile_spatial(self.spec), compile_spatial(self.spec)
        self.assertEqual(a.plan_hash, b.plan_hash)
        self.assertTrue(verify(a))
        back = from_dict(SpatialPlan, __import__("json").loads(canonical_json(a)))
        self.assertEqual(back.plan_hash, a.plan_hash)

    def test_every_beat_is_staged_and_the_plan_points_at_its_scene(self):
        plan = compile_spatial(self.spec)
        self.assertEqual(plan.scene_hash, self.spec.scene_hash)
        self.assertEqual(len(plan.beats), len(self.spec.beats))
        for beat, staging in zip(self.spec.beats, plan.beats):
            principals = {p.id for p in beat.participants if p.role != "witness"}
            placed = {p.id for p in staging.placements}
            self.assertLessEqual(principals, placed | {"nobody"})
            self.assertTrue(staging.cameras)

    def test_sight_lines_see_through_windows_but_not_walls_or_trees(self):
        wall = SpatialObject("w", "wall", [5, 0, 0], [4, 0.2, 3])
        window = SpatialObject("win", "window", [5, 0, 0.9], [4, 0.2, 1.5], blocks_sight=False)
        tree = SpatialObject("t", "tree", [5, 5, 0], [1, 1, 5])
        self.assertEqual(blocker([5, -2, 1.6], [5, 2, 1.2], [wall]), "w")
        self.assertEqual(blocker([5, -2, 1.6], [5, 2, 1.2], [window]), "")
        self.assertEqual(blocker([3, 5, 1.6], [7, 5, 1.2], [tree]), "t")
        self.assertEqual(blocker([3, 3, 1.6], [7, 3, 1.2], [tree]), "")

    def test_a_restaging_does_not_change_the_story(self):
        plan = compile_spatial(self.spec)
        self.assertEqual({b.event_id for b in plan.beats}, {b.event_id for b in self.spec.beats})


if __name__ == "__main__":
    unittest.main()
