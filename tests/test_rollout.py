"""Imagining: a copy of the world, run under other luck. The real world is read and never written, and its own luck is never used."""
from __future__ import annotations

import unittest

from agent.volition import VolitionDecider
from contracts.intervention import InterventionProposal
from producer.intervention import Ledger
from tests.test_opportunity import fingerprint
from world import rollout
from world.db import connect, init_db
from world.seed import build_world
from world.simulation import Simulation


def clean(seed=3, days=3):
    c = connect()
    init_db(c, seed)
    build_world(c, seed, "jianghu_story_v1")
    d = VolitionDecider(seed)
    Simulation(c, d, d, set(), feed="synthetic_v1").run(days)
    return c


class Imagining(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = clean()
        cls.before = fingerprint(cls.c)
        cls.a = rollout.imagine(cls.c, 3, 2, 1_000_003)
        cls.b = rollout.imagine(cls.c, 3, 2, 1_000_033)

    def test_the_real_world_is_untouched(self):
        self.assertEqual(fingerprint(self.c), self.before)
        self.assertEqual(rollout.world_seed(self.c), "3")

    def test_the_copy_has_the_real_history_and_then_goes_on(self):
        real = [tuple(r) for r in self.c.execute("SELECT event_id, type, timestamp FROM events ORDER BY event_id")]
        got = [tuple(r) for r in self.a.execute("SELECT event_id, type, timestamp FROM events ORDER BY event_id LIMIT ?", (len(real),))]
        self.assertEqual(got, real)
        self.assertGreater(self.a.execute("SELECT COUNT(*) FROM events").fetchone()[0], len(real))
        self.assertEqual(self.a.execute("SELECT MAX(timestamp) FROM events WHERE type = 'day_end'").fetchone()[0] // 1440, 4)

    def test_other_luck_is_other_futures(self):
        tail = lambda m: [tuple(r) for r in m.execute("SELECT type, timestamp, truth FROM events WHERE timestamp >= ? ORDER BY event_id", (3 * 1440,))]  # noqa: E731
        self.assertNotEqual(tail(self.a), tail(self.b))

    def test_the_same_luck_is_the_same_future(self):
        again = rollout.imagine(self.c, 3, 2, 1_000_003)
        tail = lambda m: [tuple(r) for r in m.execute("SELECT type, timestamp, truth FROM events WHERE timestamp >= ? ORDER BY event_id", (3 * 1440,))]  # noqa: E731
        self.assertEqual(tail(self.a), tail(again))

    def test_the_worlds_own_seed_is_refused(self):
        with self.assertRaises(rollout.ImaginedLuckIsTheWorlds):
            rollout.imagine(self.c, 3, 1, 3)

    def test_what_is_said_at_dawn_is_heard_in_the_copy_only(self):
        led = Ledger()
        p = InterventionProposal("x1", "S", "A", "announce_gathering", "", {"kind": "tournament", "place": "manor", "day": "5"}, 3, 2, "x")
        m = rollout.imagine(self.c, 3, 1, 1_000_003, lambda conn, now: led.admit(conn, p, now))
        self.assertEqual(m.execute("SELECT COUNT(*) FROM events WHERE type = 'intervention'").fetchone()[0], 1)
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM events WHERE type = 'intervention'").fetchone()[0], 0)
        self.assertEqual(len(led.entries), 1)


if __name__ == "__main__":
    unittest.main()
