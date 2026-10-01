"""Narrative state: the stories the world has formed, compiled once. A read model."""
from __future__ import annotations

import unittest

from narrative.state import STALLED_AFTER, compile_state
from tests.test_episode_planner import produced
from tests.test_opportunity import fingerprint


class Compiling(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = produced(501, 9)
        cls.before = fingerprint(cls.c)
        cls.state = compile_state(cls.c, 9, [["hao", "kai"]])

    def test_it_only_reads(self):
        self.assertEqual(fingerprint(self.c), self.before)

    def test_it_has_every_part_the_planner_the_producer_and_the_page_ask_for(self):
        self.assertEqual(set(self.state), {"version", "day", "arcs", "expectations", "patterns", "debts", "opportunities", "payoffs"})
        self.assertEqual(set(self.state["patterns"]), {"mechanics", "pairs", "recent_pairs"})

    def test_a_running_thread_that_has_not_moved_is_called_stalled_and_says_for_how_long(self):
        for a in self.state["arcs"]:
            self.assertEqual(a["stalled"], a["status"] in ("seeded", "forming", "active", "escalating", "climax") and a["stagnation"] >= STALLED_AFTER)
            self.assertGreaterEqual(a["stagnation"], 0)

    def test_the_audience_knows_who_is_taken_for_less_than_they_are(self):
        early = compile_state(produced(501, 1), 1)          # before the doubters have been shown wrong
        names = {x["name"] for x in early["expectations"]}
        self.assertTrue(names & {"阿俊", "阿豪"})           # the two underrated disciples the story world is built with
        for x in early["expectations"]:
            self.assertGreaterEqual(x["gap"], 0.15)
            self.assertGreater(x["knows"], x["expected"])

    def test_the_pattern_memory_counts_what_has_been_told(self):
        from narrative import payoff
        told = len(payoff.payoffs(self.c))
        self.assertEqual(sum(self.state["patterns"]["mechanics"].values()), told)

    def test_the_opportunities_and_debts_are_the_ones_the_other_read_models_find(self):
        from narrative import debt, opportunity
        self.assertEqual([o["kind"] for o in self.state["opportunities"]], [o.kind for o in opportunity.detect(self.c, 9)[:5]])
        self.assertEqual([d["person"] for d in self.state["debts"]], [r["person"] for r in debt.ledger(self.c)[:5]])


if __name__ == "__main__":
    unittest.main()
