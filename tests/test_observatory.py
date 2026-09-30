"""The Observatory is a read model: building it changes nothing in the world, every milestone and every paragraph of
a biography cites events that exist, a thread's timeline is exactly its events, and a world save carries it."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent.volition import VolitionDecider
from narrative.observatory import observatory
from world.db import connect, init_db
from world.seed import build_world
from world.simulation import Simulation
from world.snapshot import snapshot_hash


class ObservatoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = connect()
        init_db(cls.c, 55)
        build_world(cls.c, 55, "town_v1")
        d = VolitionDecider(55)
        Simulation(cls.c, d, d, set(), feed="synthetic_v1").run(4)
        cls.before = snapshot_hash(cls.c)
        cls.obs = observatory(cls.c)
        cls.events = {r[0] for r in cls.c.execute("SELECT event_id FROM events")}

    def test_building_it_writes_nothing(self):
        self.assertEqual(snapshot_hash(self.c), self.before)

    def test_every_milestone_and_paragraph_is_traceable_to_events(self):
        self.assertTrue(self.obs["characters"])
        cited = 0
        for pid, life in self.obs["characters"].items():
            for m in life["milestones"]:
                self.assertIn(m["event"], self.events, pid)
                self.assertGreaterEqual(m["significance"], 0.6)
            for p in life["biography"]:
                for e in p["events"]:
                    self.assertIn(e, self.events, (pid, p["text"]))
                    cited += 1
            for s in life["scars"]:
                self.assertTrue(s["origin_event"] is None or s["origin_event"] in self.events)
        self.assertGreater(cited, 0)

    def test_a_thread_is_told_through_its_own_events(self):
        from narrative.threads import derive_threads
        threads = {t.thread_id: t for t in derive_threads(self.c)}
        self.assertEqual(set(threads), {t["id"] for t in self.obs["threads"]})
        for t in self.obs["threads"]:
            self.assertEqual([e["id"] for e in t["events"]], threads[t["id"]].event_ids)
            from typing import get_args
            from contracts.thread import ThreadStatus
            self.assertIn(t["status"], get_args(ThreadStatus) + ("revived",))  # revived: slept, then came back
            self.assertEqual(t["why"]["origin"], t["events"][0]["id"])

    def test_the_world_save_carries_it(self):
        from runtime.godview import export_world
        with tempfile.TemporaryDirectory() as tmp:
            doc = export_world(self.c, Path(tmp) / "world.json", 0, None)
            self.assertEqual(len(doc["observatory"]["threads"]), len(self.obs["threads"]))
            self.assertEqual(sorted(doc["observatory"]["characters"]), sorted(self.obs["characters"]))
        self.assertEqual(snapshot_hash(self.c), self.before)


if __name__ == "__main__":
    unittest.main()
