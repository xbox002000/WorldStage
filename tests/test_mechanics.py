"""Narrative mechanics: rebirth forks a timeline without touching the first; the system only informs and leans."""
from __future__ import annotations

import json
import unittest

from agent.volition import VolitionDecider
from contracts.claim import TRUE, Claim
from contracts.mechanic import MechanicSpec, NarrativeMechanicPack
from world.claims import evaluate
from world.db import connect, init_db
from world.mechanics import recorded_pack
from world.mechanics.base import record_pack
from world.mechanics.rebirth import fork
from world.seed import build_world
from world.simulation import Simulation
from world.snapshot import snapshot_hash
from world.state import audit

SEED = 260931


def timeline_a(days: int = 8):
    a = connect()
    init_db(a, SEED)
    build_world(a, SEED)
    d = VolitionDecider(SEED)
    Simulation(a, d, d, set(), feed="synthetic_v1", mechanics=[]).run(days)
    return a


def timeline_b(a, fork_day: int, who: str = "jun", days: int = 8):
    b = connect()
    fork(a, b, SEED, "synthetic_v1", fork_day, who, lambda m: VolitionDecider(SEED))
    d = VolitionDecider(SEED)
    Simulation(b, d, d, set(), feed="synthetic_v1").run(days - fork_day)
    return b


def events_before(conn, ts: int) -> list[tuple]:
    return [tuple(r) for r in conn.execute("SELECT timestamp, type, truth FROM events WHERE timestamp < ? ORDER BY event_id", (ts,))]


class RebirthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.a = timeline_a()
        cls.a_hash = snapshot_hash(cls.a)
        cls.b = timeline_b(cls.a, fork_day=2)

    def test_the_first_timeline_is_never_touched(self):
        self.assertEqual(snapshot_hash(self.a), self.a_hash)

    def test_the_second_timeline_repeats_the_first_up_to_the_fork(self):
        self.assertEqual(events_before(self.a, 2 * 1440), events_before(self.b, 2 * 1440))

    def test_only_the_protagonist_remembers_and_the_fork_is_recorded(self):
        awake = json.loads(self.b.execute("SELECT truth FROM events WHERE type = 'awakening'").fetchone()[0])
        self.assertEqual((awake["actor"], awake["fork_day"], awake["parent_timeline"]), ("jun", 2, self.a_hash))
        holders = {r[0] for r in self.b.execute("SELECT DISTINCT m.observer_id FROM memories m "
                                                "WHERE m.source_id LIKE 'prior_life:%' AND m.source_type = 'external_rumor'")}
        self.assertEqual(holders, {"jun"})
        self.assertEqual(recorded_pack(self.b).mechanics[0].id, "rebirth")

    def test_the_second_run_diverges_and_stays_consistent(self):
        self.assertNotEqual(events_before(self.a, 8 * 1440), events_before(self.b, 8 * 1440))
        self.assertEqual(audit(self.b), [])

    def test_a_fork_replays_exactly(self):
        self.assertEqual(snapshot_hash(timeline_b(self.a, fork_day=2)), snapshot_hash(self.b))


class SystemTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.w = connect()
        init_db(cls.w, SEED)
        build_world(cls.w, SEED)
        record_pack(cls.w, NarrativeMechanicPack("system", [MechanicSpec("system", "character", "mei")]), 1)
        d = VolitionDecider(SEED)
        Simulation(cls.w, d, d, set(), feed="synthetic_v1").run(8)

    def test_quests_come_from_the_protagonists_situation(self):
        quests = [json.loads(t) for (t,) in self.w.execute("SELECT truth FROM events WHERE type = 'system_quest'")]
        self.assertTrue(quests)
        self.assertEqual(quests[0]["goal"], "recover")  # Mei's ring has been gone since before day 1

    def test_hints_and_rewards_are_true(self):
        for (subject, act, obj, pol) in self.w.execute(
                "SELECT c.subject, c.act, c.object, c.polarity FROM memories m JOIN claims c USING (claim_id) "
                "WHERE m.source_id = 'system'"):
            self.assertEqual(evaluate(self.w, Claim(subject, act, obj, pol)), TRUE)

    def test_nobody_else_hears_from_the_system(self):
        who = {r[0] for r in self.w.execute("SELECT DISTINCT observer_id FROM memories WHERE source_id = 'system'")}
        self.assertEqual(who, {"mei"})

    def test_the_system_changes_nothing_but_memories(self):
        ids = [r[0] for r in self.w.execute("SELECT event_id FROM events WHERE type LIKE 'system_%'")]
        n = self.w.execute(f"SELECT COUNT(*) FROM event_deltas WHERE event_id IN ({','.join(map(str, ids))})").fetchone()[0]
        self.assertEqual(n, 0)
        self.assertEqual(audit(self.w), [])


if __name__ == "__main__":
    unittest.main()
