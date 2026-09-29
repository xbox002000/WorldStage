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



class DaysAndTimeTests(unittest.TestCase):
    def test_every_day_ends_with_a_marker_and_the_world_resumes_from_the_next_day(self):
        conn, sim = run(9, 2)
        ends = [r[0] for r in conn.execute("SELECT timestamp FROM events WHERE type='day_end' ORDER BY event_id")]
        self.assertEqual(ends, [1439, 1440 + 1439])
        self.assertEqual(sim.next_day(), 2)

    def test_running_in_two_steps_equals_running_at_once(self):
        from agent.decision import SeededDecider as Seeded
        from world.db import connect as connect_db
        from world.snapshot import snapshot_hash

        def build(steps):
            conn = connect_db()
            init_db(conn, 11)
            build_world(conn, 11)
            for n in steps:  # a fresh Simulation object each time, as a daily job would use
                d = Seeded(11)
                Simulation(conn, d, d, set()).run(n)
            return snapshot_hash(conn)

        self.assertEqual(build([3]), build([1, 2]))
        self.assertEqual(build([3]), build([1, 1, 1]))

    def test_an_unfinished_day_cannot_be_resumed(self):
        from world.events import Change, EventSpec, apply_event
        from world.state import WorldError
        conn, sim = run(9, 1)
        apply_event(conn, EventSpec(timestamp=1440 + 500, type="stray", trigger_type="t",
                                    changes=[Change("person", "ming", "energy", delta=-1)]))
        with self.assertRaises(WorldError):
            sim.next_day()

    def test_people_do_not_act_on_the_dot_but_never_leave_their_slot(self):
        conn, _ = run(184729, 3)
        offsets = [(r["timestamp"] % 1440) for r in conn.execute("SELECT timestamp FROM events WHERE type='move'")]
        scripted_slots = {480, 720, 1080, 1260}
        off_the_dot = [o for o in offsets if o not in scripted_slots]
        self.assertGreater(len(off_the_dot), len(offsets) // 2)  # most moves are jittered
        for o in offsets:
            base = max(s for s in scripted_slots if s <= o)
            self.assertLessEqual(o - base, 25)  # never more than JITTER_MAX minutes after the slot starts

    def test_times_are_replayable_and_depend_on_the_seed(self):
        def times(seed):
            conn, _ = run(seed, 2)
            return [r[0] for r in conn.execute("SELECT timestamp FROM events ORDER BY event_id")]

        self.assertEqual(times(5), times(5))
        self.assertNotEqual(times(5), times(6))

    def test_event_timestamps_never_go_backwards(self):
        conn, _ = run(184729, 4)
        ts = [r[0] for r in conn.execute("SELECT timestamp FROM events ORDER BY event_id")]
        self.assertEqual(ts, sorted(ts))


if __name__ == "__main__":
    unittest.main()
