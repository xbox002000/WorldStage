"""soul_stats: the paired bootstrap and the pairing, on small made-up numbers. No API, no world."""
import json
import tempfile
import unittest
from pathlib import Path

import soul_stats as S


class Bootstrap(unittest.TestCase):
    def test_same_seed_same_answer(self):
        v = [1.0, 2.0, -1.0, 4.0, 0.5]
        self.assertEqual(S.bootstrap_mean(v, n=2000), S.bootstrap_mean(v, n=2000))

    def test_mean_is_the_plain_mean(self):
        self.assertAlmostEqual(S.bootstrap_mean([1, 2, 3, 6])["mean"], 3.0)

    def test_a_constant_positive_difference_excludes_zero(self):
        r = S.bootstrap_mean([2.0, 2.0, 2.0, 2.0], n=1000)
        self.assertTrue(r["excludes_zero"])
        self.assertEqual((r["lo"], r["hi"]), (2.0, 2.0))

    def test_a_mixed_sign_difference_includes_zero(self):
        r = S.bootstrap_mean([5.0, -5.0, 4.0, -4.0, 1.0, -1.0], n=3000)
        self.assertFalse(r["excludes_zero"])
        self.assertLess(r["lo"], 0)
        self.assertGreater(r["hi"], 0)

    def test_interval_brackets_the_mean_and_is_ordered(self):
        r = S.bootstrap_mean([1.0, 3.0, 2.0, 8.0, 0.0, 4.0], n=3000)
        self.assertLessEqual(r["lo"], r["mean"])
        self.assertLessEqual(r["mean"], r["hi"])

    def test_wider_level_is_wider(self):
        v = [1.0, 3.0, 2.0, 8.0, 0.0, 4.0]
        a, b = S.bootstrap_mean(v, n=3000, level=0.5), S.bootstrap_mean(v, n=3000, level=0.95)
        self.assertGreaterEqual(b["hi"] - b["lo"], a["hi"] - a["lo"])

    def test_one_seed_gives_no_interval_and_never_claims_a_difference(self):
        r = S.bootstrap_mean([7.0])
        self.assertEqual(r["n"], 1)
        self.assertIsNone(r["lo"])
        self.assertFalse(r["excludes_zero"])

    def test_nothing_gives_nothing(self):
        self.assertIsNone(S.bootstrap_mean([])["mean"])


class Pairing(unittest.TestCase):
    def test_difference_is_soul_minus_rules_by_seed(self):
        soul = {1: {"x": 10}, 2: {"x": 4}}
        rules = {1: {"x": 3}, 2: {"x": 6}}
        self.assertEqual(S.paired_differences(soul, rules, "x"), {1: 7, 2: -2})

    def test_a_seed_in_one_world_only_is_not_used(self):
        soul = {1: {"x": 10}, 2: {"x": 4}, 3: {"x": 1}}
        rules = {1: {"x": 3}, 3: {"x": 1}}
        self.assertEqual(S.paired_differences(soul, rules, "x"), {1: 7, 3: 0})

    def test_a_missing_metric_is_skipped_not_zero(self):
        soul = {1: {"x": 10}, 2: {"x": None}}
        rules = {1: {"x": 3}, 2: {"x": 5}}
        self.assertEqual(S.paired_differences(soul, rules, "x"), {1: 7})

    def test_summarise_keys_and_a_clear_effect(self):
        keys = [k for k, _ in S.PAIRED]
        soul = {s: {k: 10.0 for k in keys} for s in (1, 2, 3, 4)}
        rules = {s: {k: 4.0 for k in keys} for s in (1, 2, 3, 4)}
        res = S.summarise(soul, rules)
        self.assertEqual(list(res), keys)
        self.assertTrue(all(r["excludes_zero"] and r["mean"] == 6.0 for r in res.values()))

    def test_mind_metrics_skip_seeds_without_decisions(self):
        res = S.summarise_mind({1: {"differs_rate": 0.5}, 2: {}, 3: {"differs_rate": 0.7}})
        self.assertEqual(res["differs_rate"]["by_seed"], {1: 0.5, 3: 0.7})
        self.assertAlmostEqual(res["differs_rate"]["mean"], 0.6)


class Decisions(unittest.TestCase):
    def test_rates_and_chance(self):
        rows = [{"differs": True, "shown_at": 0, "of": 4}, {"differs": False, "shown_at": 2, "of": 4},
                {"differs": True, "shown_at": 1, "of": 2}, {"error": "X"}]
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "decisions.jsonl"
            p.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
            m = S.decision_metrics(p)
        self.assertEqual((m["woke"], m["answered"], m["failed"]), (4, 3, 1))
        self.assertAlmostEqual(m["differs_rate"], 2 / 3)
        self.assertAlmostEqual(m["first_line_rate"], 1 / 3)
        self.assertAlmostEqual(m["first_line_vs_chance"], 1 / 3 - (0.25 + 0.25 + 0.5) / 3)

    def test_no_file_no_rates(self):
        with tempfile.TemporaryDirectory() as d:
            m = S.decision_metrics(Path(d) / "none.jsonl")
        self.assertEqual(m, {"woke": 0, "answered": 0, "failed": 0})

    def test_find_seeds_reads_directory_names(self):
        with tempfile.TemporaryDirectory() as d:
            for n in ("soul501", "soul504", "soul504.baseline", "soul501.llm_cache.db", "pilot1"):
                p = Path(d) / n
                p.mkdir() if "." not in n or n.endswith("baseline") else p.write_text("")
            self.assertEqual(S.find_seeds(Path(d)), [501, 504])


if __name__ == "__main__":
    unittest.main()
