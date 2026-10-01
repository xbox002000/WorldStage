"""dramaturgy_metric_v1 is frozen: on a stored world, what it finds and how it weighs it never changes.

If this fails, a change altered v1. Do not update the golden record to make it pass: v1 must keep meaning what it
meant when worlds were compared with it. Put the new definition next to it as v2 (and its own golden record).
Domain packs' situations are reported apart (extensions) and never count in v1.
"""
from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

from narrative.dramaturgy import METRIC_VERSION, analyse
from world.reader import open_world_reader

HERE = Path(__file__).parent / "fixtures"
GOLDEN = json.loads((HERE / "dramaturgy_metric_v1_golden.json").read_text(encoding="utf-8"))


class FrozenMetricTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rep = analyse(open_world_reader(str(HERE / "dramaturgy_world_v1.db")))
        cls.v1 = [s for s in cls.rep["situations"] if s["metric"] == METRIC_VERSION]

    def test_it_is_still_v1(self):
        self.assertEqual(self.rep["metric"], GOLDEN["metric"])

    def test_v1_finds_and_weighs_exactly_what_it_did(self):
        self.assertEqual(self.rep["count"], GOLDEN["count"])
        self.assertEqual(self.rep["curve"], GOLDEN["curve"])
        self.assertEqual([[s["kind"], s["day"], s["potential"], s["events"]] for s in self.v1[:25]], GOLDEN["top25"])
        digest = hashlib.sha256(json.dumps([[s["kind"], s["day"], s["potential"], s["events"], s["why"], s["question"]]
                                            for s in self.v1], ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        self.assertEqual(digest, GOLDEN["situations_sha256"])

    def test_extensions_stay_out_of_v1(self):
        self.assertTrue(self.rep["extensions"]["count"])  # this world's packs do find their own drama ...
        self.assertTrue(all(not s["metric"].startswith("ext:") for s in self.v1))
        self.assertEqual(self.rep["curve_all"], [round(a + b, 2) for a, b in zip(self.rep["curve"], self.rep["extensions"]["curve"])])


if __name__ == "__main__":
    unittest.main()
