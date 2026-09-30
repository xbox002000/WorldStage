"""A world that breathes: trust reversals mean a change of heart, clashes wear people out, a beaten fighter heals,
and the rhythm measures read a run the way a viewer would feel it."""
from __future__ import annotations

import unittest

from agent.volition import CONFLICT, recovery_bias, strain
from narrative.rhythm import label_days, rhythm
from tests.test_jianghu import jianghu
from tests.test_world_c import fresh, put
from world.events import Change, EventSpec, apply_event
from world.helpers import STANCE, trust_reversed
from world.intent import Intent, validate
from world.jianghu import INJURY_DAYS, injured
from world.state import WorldError


def set_trust(c, now, a, b, value):
    old = c.execute("SELECT trust FROM relationships WHERE actor_id = ? AND target_id = ?", (a, b)).fetchone()[0]
    apply_event(c, EventSpec(timestamp=now, type="setup", trigger_type="rule",
                             changes=[Change("relationship", f"{a}:{b}", "trust", delta=round(value - old, 6))]))


class TrustReversalTests(unittest.TestCase):
    def test_drifting_across_zero_is_not_a_change_of_heart(self):
        c = fresh()
        set_trust(c, 10, "ming", "kai", 0.03)
        self.assertFalse(trust_reversed(c, "ming", "kai", -0.07))  # 0.03 -> -0.04: noise

    def test_leaving_one_settled_side_for_the_other_is(self):
        c = fresh()
        set_trust(c, 10, "ming", "kai", 0.4)
        set_trust(c, 20, "ming", "kai", 0.05)  # wavering, but the last settled view was trust
        self.assertTrue(trust_reversed(c, "ming", "kai", -0.05 - STANCE))
        self.assertFalse(trust_reversed(c, "ming", "kai", 0.2))


class RecoveryTests(unittest.TestCase):
    def test_after_a_clash_open_conflict_is_less_likely_for_a_day_or_two(self):
        c = fresh()
        put(c, 10, ming="cafe", kai="cafe")
        apply_event(c, EventSpec(timestamp=100, type="setup", trigger_type="rule", importance=0.8,
                                 participants=[("ming", "actor"), ("kai", "target")]))
        self.assertGreater(strain(c, "ming", 200), 0.5)
        self.assertEqual(strain(c, "ming", 100 + 3 * 1440), 0.0)
        scored = [(1.0, Intent("ming", "accuse", "kai", memory_id=1)), (1.0, Intent("ming", "talk", "kai", "warm"))]
        after = recovery_bias(c, "ming", 200, scored)
        self.assertLess(after[0][0], 1.0)  # the accusation is dampened
        self.assertEqual(after[1][0], 1.0)  # a warm word is not
        self.assertIn("challenge", CONFLICT)

    def test_a_beaten_fighter_heals_before_fighting_again(self):
        c = jianghu()
        put(c, 10, lin="inn", lu="inn", tie="inn")
        apply_event(c, EventSpec(timestamp=500, type="duel", trigger_type="rule", location_id="inn", importance=0.75,
                                 truth={"actor": "lin", "target": "lu", "winner": "lin", "loser": "lu"},
                                 participants=[("lin", "actor"), ("lu", "target")]))
        self.assertTrue(injured(c, "lu", 600))
        self.assertFalse(injured(c, "lu", 500 + INJURY_DAYS * 1440 + 1))
        with self.assertRaises(WorldError):
            validate(c, Intent("tie", "challenge", "lu"))


class MeasureTests(unittest.TestCase):
    def test_a_run_is_labelled_day_by_day_for_the_world_and_for_each_life(self):
        c = jianghu()
        from agent.volition import VolitionDecider
        from world.simulation import Simulation
        d = VolitionDecider(1)
        Simulation(c, d, d, set()).run(6)
        labels = label_days(c, 6)
        self.assertEqual(len(labels), 6)
        self.assertTrue(set(labels) <= {"quiet", "simmer", "rising", "peak", "recovery"})
        r = rhythm(c, 0, 6)
        self.assertAlmostEqual(sum(r["shape"].values()), 1.0, places=1)
        self.assertEqual(len(r["strip"]), 6)
        self.assertTrue(r["person_strips"])
        self.assertLessEqual(r["person_shape"]["peak"], r["shape"]["peak"])  # a life is calmer than the whole world


if __name__ == "__main__":
    unittest.main()
