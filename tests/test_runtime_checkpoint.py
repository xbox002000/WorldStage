"""Runtime checkpoints (runtime/checkpoint.py): resuming gives exactly what playing the whole history gives, and a
checkpoint that does not fit the world is ignored."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent.volition import VolitionDecider
from contracts.base import content_hash, to_dict
from runtime import checkpoint
from runtime.world_runtime import WorldRuntime
from world.db import connect, init_db
from world.seed import build_world
from world.simulation import Simulation

STATE = ("actions", "interactions", "tracks", "steps", "keys", "by_entity", "_times", "frames", "world_holder", "bodies",
         "things", "doorway", "last_event")


def lived(seed: int = 5, days: int = 1, decider_seed: int | None = None):
    conn = connect()
    init_db(conn, seed)
    build_world(conn, seed, "town_spatial_v1")
    d = VolitionDecider(seed if decider_seed is None else decider_seed)
    sim = Simulation(conn, d, d, set(), feed="synthetic_v1")
    sim.run(days)
    return conn, sim


class Resume(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.TemporaryDirectory()
        cls.path = Path(cls.dir.name) / "runtime.ckpt"
        cls.conn, cls.sim = lived(5, 1)
        cls.mid = WorldRuntime(cls.conn)
        cls.header = checkpoint.save(cls.mid, cls.path)
        cls.sim.run(1)  # the world goes on: another day of history
        cls.full = WorldRuntime(cls.conn)  # played from the very start
        cls.resumed = checkpoint.load(cls.conn, cls.path)
        cls.skipped = cls.resumed.last_event
        cls.played = cls.resumed.advance()

    @classmethod
    def tearDownClass(cls):
        cls.dir.cleanup()

    def test_it_resumes_where_it_was_and_plays_only_what_is_new(self):
        self.assertEqual(self.skipped, self.mid.last_event)
        self.assertGreater(self.played, 0)
        total = self.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        self.assertEqual(self.skipped + self.played, total)

    def test_a_resumed_runtime_is_the_same_runtime(self):
        for name in STATE:
            self.assertEqual(getattr(self.resumed, name), getattr(self.full, name), name)
        self.assertEqual(self.resumed.sched.books, self.full.sched.books)
        self.assertEqual(self.resumed.check(), [])
        last = self.full.last_event
        self.assertEqual(content_hash(to_dict(self.resumed.state_at(last))), content_hash(to_dict(self.full.state_at(last))))
        ids = [r[0] for r in self.conn.execute("SELECT event_id FROM events WHERE type = 'talk' ORDER BY event_id LIMIT 30")]
        self.assertEqual(content_hash(to_dict(self.resumed.trace(ids))), content_hash(to_dict(self.full.trace(ids))))

    def test_open_runtime_writes_and_then_resumes(self):
        path = Path(self.dir.name) / "open.ckpt"
        first = checkpoint.open_runtime(self.conn, path)  # nothing there: played in full, then written
        self.assertTrue(path.exists())
        calls = []
        original = WorldRuntime._play_event
        WorldRuntime._play_event = lambda self, *a, **k: (calls.append(a[0]), original(self, *a, **k))[1]
        try:
            second = checkpoint.open_runtime(self.conn, path)
        finally:
            WorldRuntime._play_event = original
        self.assertEqual(calls, [])  # nothing was played again
        self.assertEqual(second.keys, first.keys)


class Pipeline(unittest.TestCase):
    def test_the_production_pipeline_resumes_from_its_cache(self):
        from production.pipeline import _runtime
        conn, _ = lived(5, 1)
        with tempfile.TemporaryDirectory() as d:
            cache = str(Path(d) / "runtime.ckpt")
            first = _runtime(conn, cache)
            self.assertTrue(Path(cache).exists())
            second = _runtime(conn, cache)
            self.assertEqual(second.keys, first.keys)
            self.assertEqual(second.keys, _runtime(conn).keys)  # and it is what no cache would have played


class Refusal(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.TemporaryDirectory()
        cls.path = Path(cls.dir.name) / "runtime.ckpt"
        cls.conn, _ = lived(5, 1)
        checkpoint.save(WorldRuntime(cls.conn), cls.path)

    @classmethod
    def tearDownClass(cls):
        cls.dir.cleanup()

    def test_it_fits_its_own_world(self):
        self.assertIsNotNone(checkpoint.load(self.conn, self.path))

    def test_a_missing_or_foreign_file_is_ignored(self):
        self.assertIsNone(checkpoint.load(self.conn, Path(self.dir.name) / "nothing.ckpt"))
        other = Path(self.dir.name) / "other.ckpt"
        other.write_bytes(b"not a checkpoint")
        self.assertIsNone(checkpoint.load(self.conn, other))

    def test_another_history_is_never_resumed(self):
        other, _ = lived(6, 1)  # a different world, another seed
        self.assertIsNone(checkpoint.load(other, self.path))
        twin, _ = lived(5, 1)  # the same seed and recipe: the same history, so it fits
        self.assertIsNotNone(checkpoint.load(twin, self.path))
        other_past, _ = lived(5, 1, decider_seed=99)  # the same world seed and recipe, but other things happened
        self.assertNotEqual(checkpoint.history_hash(other_past, 139), checkpoint.history_hash(twin, 139))
        self.assertIsNone(checkpoint.load(other_past, self.path))  # not resumed from somebody else's past

    def test_changed_code_or_a_damaged_file_is_ignored(self):
        real = checkpoint.code_hash
        checkpoint.code_hash = lambda: "another build"
        try:
            self.assertIsNone(checkpoint.load(self.conn, self.path))
        finally:
            checkpoint.code_hash = real
        raw = self.path.read_bytes()
        damaged = Path(self.dir.name) / "damaged.ckpt"
        damaged.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
        self.assertIsNone(checkpoint.load(self.conn, damaged))
        truncated = Path(self.dir.name) / "truncated.ckpt"
        truncated.write_bytes(raw[: len(raw) // 2])
        self.assertIsNone(checkpoint.load(self.conn, truncated))


if __name__ == "__main__":
    unittest.main()
