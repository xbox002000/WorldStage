from __future__ import annotations

import unittest

from agent.decision import SeededDecider
from tests.helpers import dump_state
from world.db import connect, init_db
from world.seed import build_world
from world.simulation import Simulation
from world.state import audit


def run(seed: int, days: int = 7):
    conn = connect()
    init_db(conn, seed)
    build_world(conn, seed)
    d = SeededDecider(seed)
    sim = Simulation(conn, d, d, set())
    sim.run(days)
    return conn, sim


class SimulationTests(unittest.TestCase):
    def test_seven_days_meet_v0_targets(self):
        conn, sim = run(184729)
        self.assertGreaterEqual(conn.execute("SELECT COUNT(*) FROM events").fetchone()[0], 20)
        flips = conn.execute(
            "SELECT COUNT(*) FROM events WHERE json_extract(truth,'$.trust_flipped') = 1"
        ).fetchone()[0]
        self.assertGreaterEqual(flips, 3)
        self.assertEqual(audit(conn), [])
        self.assertEqual(sim.stats.get("rejected_schedule", 0), 0)  # scripted days must be legal

    def test_same_seed_replays_identically(self):
        self.assertEqual(dump_state(run(42, 3)[0]), dump_state(run(42, 3)[0]))

    def test_different_seed_gives_different_world(self):
        self.assertNotEqual(dump_state(run(1, 3)[0]), dump_state(run(2, 3)[0]))

    def test_every_relationship_change_has_a_cause_event(self):
        conn, _ = run(7, 4)
        orphans = conn.execute(
            "SELECT COUNT(*) FROM event_deltas d LEFT JOIN events e USING (event_id) WHERE e.event_id IS NULL"
        ).fetchone()[0]
        self.assertEqual(orphans, 0)
        # Social events after a first meeting link back to it.
        linked = conn.execute("SELECT COUNT(*) FROM events WHERE parent_event_id IS NOT NULL").fetchone()[0]
        self.assertGreater(linked, 0)


if __name__ == "__main__":
    unittest.main()
