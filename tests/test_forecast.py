"""Forecast: imagined futures give probabilities, never the answer, and never touch the real world."""
from __future__ import annotations

import unittest
from unittest import mock

from contracts.intervention import InterventionProposal
from producer import director as D
from producer import forecast
from producer.intervention import Ledger
from tests.test_opportunity import fingerprint
from tests.test_rollout import clean


def tournament(id_="f1", day=5):
    return InterventionProposal(id_, "S", "A", "announce_gathering", "", {"kind": "tournament", "place": "manor", "day": str(day)}, 3, 2, "x")


class Evaluating(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = clean(3, 3)
        cls.before = fingerprint(cls.c)
        with mock.patch.object(forecast, "HORIZON", 2):
            cls.fc = forecast.evaluate(cls.c, 3, Ledger(), {"a": ([tournament()], {"hao", "kai"})}, samples=2)

    def test_there_is_a_forecast_for_each_option_and_for_doing_nothing(self):
        self.assertEqual(set(self.fc), {"silence", "a"})
        for f in self.fc.values():
            self.assertEqual(f.samples, 2)
            self.assertTrue(0.0 <= f.p_payoff <= 1.0 and 0.0 <= f.p_played <= 1.0)

    def test_doing_nothing_gains_nothing_over_itself(self):
        self.assertEqual(self.fc["silence"].gain, 0.0)

    def test_the_real_world_is_untouched_by_imagining(self):
        self.assertEqual(fingerprint(self.c), self.before)

    def test_the_lucks_are_never_the_worlds_own(self):
        c = clean(1_000_003, 1)
        self.assertNotIn(1_000_003, forecast._lucks(c, 4))
        self.assertEqual(len(forecast._lucks(c, 3)), 3)
        self.assertNotIn(3, forecast._lucks(self.c, 4))

    def test_a_ledger_fork_spends_in_the_fork_only(self):
        led = Ledger()
        fork = led.fork()
        fork.entries.append({"budget_cost": 3, "admitted": True, "day": 3})
        self.assertEqual(led.spent(3), 0)
        self.assertEqual(fork.spent(3), 3)


class Choosing(unittest.TestCase):
    def test_a_lookahead_director_decides_from_imagined_futures_and_keeps_the_record(self):
        c = clean(3, 3)
        with mock.patch.object(forecast, "HORIZON", 2), mock.patch.object(forecast, "SAMPLES", 2), mock.patch.object(forecast, "LUCKS", forecast.LUCKS[:2]):
            dr = D.Director("lookahead", 3)
            dr.prepare(c, 3)
            before = fingerprint(c)
            dr.dawn(c, 3, 3 * 1440 + 5)
        d = dr.ledger.decisions[0]
        self.assertTrue(d.get("imagined") or d.get("forecast") or d["action"] == "silence")
        if d["action"] == "intervene":
            self.assertIn("gain", d["imagined"]["forecast"])
            self.assertGreaterEqual(d["imagined"]["score"], forecast.MIN_GAIN)
        else:
            self.assertTrue(d["reason"])
        # whatever it chose, the world was only changed by what the ledger admitted
        admitted = sum(1 for e in dr.ledger.entries if e["admitted"])
        self.assertEqual(c.execute("SELECT COUNT(*) FROM events WHERE type = 'intervention'").fetchone()[0], admitted)
        self.assertTrue(before != fingerprint(c) or admitted == 0)

    def test_only_lookahead_keeps_a_clean_boundary(self):
        c = clean(3, 1)
        g = D.Director("greedy", 3)
        g.prepare(c, 1)
        self.assertIsNone(g._clean)
        la = D.Director("lookahead", 3)
        la.prepare(c, 1)
        self.assertIsNotNone(la._clean)


if __name__ == "__main__":
    unittest.main()
