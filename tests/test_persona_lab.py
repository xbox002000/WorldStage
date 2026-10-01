"""The counterfactual lab (persona_lab.py): branches of one world differ only in what the lab changes, and the report
separates what a shaping moved from what a bare extra event moves."""
from __future__ import annotations

import unittest

import persona_lab as lab


class Branches(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runs = {b: lab.run_branch(3, b, 1, None) for b in ("control", "placebo", "betrayed", "jianghu")}

    def test_branches_are_different_runs_with_ids(self):
        ids = {r["branch_id"] for r in self.runs.values()}
        self.assertEqual(len(ids), 4)
        self.assertEqual(self.runs["jianghu"]["recipe"], "town_in_jianghu_v1")

    def test_a_shaping_changes_what_people_hold_from_the_first_day(self):
        control, betrayed = self.runs["control"]["life"]["people"], self.runs["betrayed"]["life"]["people"]
        self.assertTrue(all("cannot_trust" in betrayed[p]["self"] for p in betrayed))
        self.assertTrue(all("cannot_trust" not in control[p]["self"] for p in control))
        self.assertGreater(betrayed["mei"]["traits"]["vigilance"], control["mei"]["traits"]["vigilance"])

    def test_the_placebo_leaves_no_mark(self):
        control, placebo = self.runs["control"]["life"]["people"], self.runs["placebo"]["life"]["people"]
        self.assertEqual({p: placebo[p]["self"] for p in placebo}, {p: control[p]["self"] for p in control})
        for p in control:
            self.assertEqual(placebo[p]["traits"]["trust_default"], control[p]["traits"]["trust_default"])

    def test_one_person_can_be_shaped_alone(self):
        r = lab.run_branch(3, "betrayed", 0, "mei")["life"]["people"]
        self.assertEqual(r["mei"]["self"], ["cannot_trust"])
        self.assertTrue(all(r[p]["self"] == [] for p in r if p != "mei"))

    def test_compare_and_beyond_placebo(self):
        vs = lab.compare(self.runs["control"], self.runs["betrayed"])
        self.assertEqual(set(vs["retention"]), set(lab.PROBES))
        self.assertEqual(vs["self_models"]["control"], 0)
        self.assertEqual(vs["self_models"]["branch"], 10)
        noise = lab.compare(self.runs["control"], self.runs["placebo"])
        beyond = lab.beyond_placebo(vs, noise)
        self.assertEqual(beyond["self_models"], 10)  # ten people hold the belief the placebo did not give
        self.assertGreater(beyond["trait_drift"], 0)

    def test_average_over_seeds(self):
        got = lab.average([{"a": 1.0, "b": [1, 3], "c": {"d": 2.0}, "e": "x"}, {"a": 3.0, "b": [3, 5], "c": {"d": 4.0}, "e": "y"}])
        self.assertEqual(got, {"a": 2.0, "b": [2.0, 4.0], "c": {"d": 3.0}, "e": "x"})


if __name__ == "__main__":
    unittest.main()
