from __future__ import annotations

import unittest

from agent.decision import SeededDecider
from agent.perception import candidates
from world.db import connect, init_db
from world.intent import Intent, intent_hash, intent_sort_key
from world.seed import build_world
from world.simulation import Simulation
from world.snapshot import snapshot_hash


def run(seed: int, days: int, reverse: bool):
    conn = connect()
    if reverse:
        conn.execute("PRAGMA reverse_unordered_selects = ON")  # flips row order of any query lacking ORDER BY
    init_db(conn, seed)
    build_world(conn, seed)
    d = SeededDecider(seed)
    Simulation(conn, d, d, set()).run(days)
    return conn


class OrderIndependenceTests(unittest.TestCase):
    def test_result_does_not_depend_on_unordered_query_row_order(self):
        for seed in (184729, 3):
            with self.subTest(seed=seed):
                self.assertEqual(snapshot_hash(run(seed, 3, False)), snapshot_hash(run(seed, 3, True)))

    def test_candidate_options_have_unique_keys(self):
        conn = run(184729, 1, False)
        for actor in [r[0] for r in conn.execute("SELECT id FROM people ORDER BY id")]:
            keys = [(c["action"], c.get("target")) for c in candidates(conn, actor)]
            self.assertEqual(len(keys), len(set(keys)), actor)


class IntentOrderTests(unittest.TestCase):
    def test_sort_key_is_total_and_uses_time_priority_actor_hash(self):
        a = Intent("john", "talk", "mary", "warm", priority=0.5)
        b = Intent("john", "talk", "tom", "warm", priority=0.5)  # same actor, action, priority: only the hash differs
        c = Intent("amy", "move", "cafe", priority=0.5)
        d = Intent("zed", "move", "cafe", priority=0.9)
        keys = [intent_sort_key(10, i) for i in (a, b, c, d)]
        self.assertEqual(len(keys), len(set(keys)))
        ordered = sorted((a, b, c, d), key=lambda i: intent_sort_key(10, i))
        self.assertEqual(ordered[0], d)  # higher priority first
        self.assertEqual(ordered[1], c)  # then actor id
        self.assertEqual(sorted((a, b), key=lambda i: intent_sort_key(10, i)), sorted((b, a), key=lambda i: intent_sort_key(10, i)))
        self.assertLess(intent_sort_key(9, a), intent_sort_key(10, d))  # earlier time beats priority

    def test_hash_ignores_reason_text_but_not_content(self):
        base = Intent("john", "talk", "mary", "warm", reason="hello")
        self.assertEqual(intent_hash(base), intent_hash(Intent("john", "talk", "mary", "warm", reason="something else")))
        self.assertNotEqual(intent_hash(base), intent_hash(Intent("john", "talk", "mary", "cold")))


if __name__ == "__main__":
    unittest.main()
