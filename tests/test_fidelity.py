"""Replay fidelity, layer by layer: the runtime agrees with the world, the presentation runtime's own JS rule agrees
with the runtime, and every version's edit sits on the same world clock. A fault in one layer is reported as that
layer, not as "the video looks wrong"."""
from __future__ import annotations

import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from narrative.compiler import compile_packet
from narrative.direction import plan_direction
from narrative.performance import plan_performance
from runtime.fidelity import fidelity
from runtime.stage import export_scene
from runtime.world_runtime import WorldRuntime
from tests.test_director_reality import dog_story


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class FidelityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c, thread, spec = dog_story()
        cls.rt = WorldRuntime(cls.c)
        trace = cls.rt.trace([b.event_id for b in spec.beats])
        packets = {}
        for name, who, strategy in (("A", "ming", "mystery"), ("B", "dog", "irony"), ("C", "omniscient", "irony")):
            plan = plan_direction(cls.c, spec, thread, focalizer=who, strategy=strategy)
            packets[name] = compile_packet(spec, direction=plan, performance=plan_performance(cls.c, spec, plan),
                                           runtime=trace)
        cls.tmp = tempfile.TemporaryDirectory()
        cls.path = Path(cls.tmp.name) / "scene.json"
        cls.doc = export_scene(cls.c, trace, packets, cls.path)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_every_layer_holds(self):
        r = fidelity(self.c, self.rt, self.doc, self.path)
        self.assertIsNone(r["first_broken"], json.dumps(r["layers"], ensure_ascii=False))
        self.assertLess(r["layers"]["presentation"]["transform_error_m"], 1e-3)
        self.assertTrue(r["layers"]["presentation"]["trigger_order_same"])
        self.assertEqual(r["layers"]["camera"]["versions"], ["A", "B", "C"])

    def test_a_presentation_that_moves_a_body_is_caught_as_a_presentation_fault(self):
        wrong = copy.deepcopy(self.doc)  # what the engine was given differs from what the runtime says
        dog = next(e for e in wrong["entities"] if e["id"] == "dog")
        dog["keys"][-1][2] += 0.5
        r = fidelity(self.c, self.rt, wrong, self.path)
        self.assertEqual(r["first_broken"], "presentation")

    def test_a_thing_in_the_wrong_hands_is_caught(self):
        wrong = copy.deepcopy(self.doc)
        wallet = next(e for e in wrong["entities"] if e["id"] == "wallet_ming")
        for k in wallet["keys"]:
            if k[5] == "carried":
                k[6] = "ming"
        r = fidelity(self.c, self.rt, wrong, self.path)
        self.assertEqual(r["first_broken"], "presentation")
        self.assertTrue(r["layers"]["presentation"]["holder_mismatches"])


if __name__ == "__main__":
    unittest.main()
