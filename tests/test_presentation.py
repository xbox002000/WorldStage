"""The three.js Presentation Runtime and its assets: a self-contained project per version, the Blender cast valid
glTF with canonical bytes, the page's code parseable, and the Shot Cost Planner pricing without sending anything."""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from narrative.compiler import compile_packet
from narrative.direction import plan_direction
from narrative.performance import plan_performance
from production.dryrun import needs_model, plan
from runtime.blender.build import canonical_glb
from runtime.stage import export_scene
from runtime.world_runtime import WorldRuntime
from tests.test_director_reality import dog_story

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "render" / "presentation" / "assets"
NODE = shutil.which("node")


class PresentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c, thread, cls.spec = dog_story()
        trace = WorldRuntime(cls.c).trace([b.event_id for b in cls.spec.beats])
        cls.packets = {}
        for name, who, strategy in (("A", "ming", "mystery"), ("C", "omniscient", "irony")):
            d = plan_direction(cls.c, cls.spec, thread, focalizer=who, strategy=strategy)
            cls.packets[name] = compile_packet(cls.spec, direction=d, performance=plan_performance(cls.c, cls.spec, d),
                                               runtime=trace)
        cls.tmp = tempfile.TemporaryDirectory()
        cls.scene = Path(cls.tmp.name) / "scene.json"
        export_scene(cls.c, trace, cls.packets, cls.scene)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_a_version_builds_into_a_self_contained_project(self):
        from render.presentation.build import build
        out = build(self.scene, "C", Path(self.tmp.name) / "C")
        page = (out / "index.html").read_text(encoding="utf-8")
        self.assertIn('"three": "./three/three.module.js"', page)
        self.assertIn('version: "C"', page)
        for rel in ("three/three.module.js", "three/three.core.js", "addons/loaders/GLTFLoader.js", "presentation.js",
                    "runtime_rule.js", "scene.json", "assets/person.glb", "assets/dog.glb", "assets/wallet.glb"):
            self.assertTrue((out / rel).exists(), rel)
        doc = json.loads((out / "scene.json").read_text(encoding="utf-8"))
        self.assertEqual(sorted(doc["cuts"]), ["A", "C"])

    @unittest.skipUnless(NODE, "node is not installed")
    def test_the_page_code_parses_and_the_cast_is_valid_gltf(self):
        for f in ("presentation.js", "runtime_rule.js", "verify.mjs", "validate.mjs"):
            subprocess.run([NODE, "--check", str(ROOT / "render" / "presentation" / f)], check=True)
        r = subprocess.run([NODE, str(ROOT / "render" / "presentation" / "validate.mjs"), str(ASSETS)],
                           capture_output=True, text=True, cwd=ROOT / "render")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(all(json.loads(line)["errors"] == 0 for line in r.stdout.splitlines()))

    def test_canonical_glb_is_a_fixed_point(self):
        with tempfile.TemporaryDirectory() as tmp:
            for glb in sorted(ASSETS.glob("*.glb")):
                p = Path(tmp) / glb.name
                shutil.copyfile(glb, p)
                canonical_glb(p)
                self.assertEqual(p.read_bytes(), glb.read_bytes())  # the committed files are already canonical

    def test_the_cost_planner_prices_turns_and_close_performance_and_respects_a_budget(self):
        c = plan(self.packets["C"])
        self.assertFalse(c["sent"])
        wanted = [r for r in c["shots"] if r["want_model"]]
        self.assertTrue(wanted)
        self.assertTrue(all(r["function"] in ("reveal", "payoff") or r["scale"] in ("MCU", "CU", "ECU") for r in wanted))
        self.assertTrue(all(needs_model(s)[0] is False for s in self.packets["C"].shots if s.function == "hide"))
        cheapest = min(r["cost"]["kling_3_pro"] for r in wanted)
        tight = plan(self.packets["C"], budget=cheapest * 0.5)  # not even one shot fits: all back to procedural
        self.assertEqual(tight["total"], 0.0)
        self.assertTrue(all(r["route"] == "procedural" for r in tight["shots"]))
        enough = plan(self.packets["C"], budget=cheapest)
        self.assertLessEqual(enough["total"], cheapest + 1e-9)
        req = wanted[0]["request"]
        self.assertTrue(req["prompt"] and req["references"] and req["camera"]["scale"])


if __name__ == "__main__":
    unittest.main()
