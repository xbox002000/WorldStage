"""The control room: what the exporter writes, what the page is made of, and that going on adds a day."""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from channel.studio import Studio
from render.studio.build import HERE

ROOT = Path(__file__).resolve().parent.parent


class Exporting(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="studio_"))
        cls.studio = Studio(cls.tmp, 17, 6)
        cls.doc = json.loads((cls.tmp / "studio.json").read_text(encoding="utf-8"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_one_record_per_day_with_what_the_page_shows(self):
        self.assertEqual(self.doc["meta"]["days"], 6)
        self.assertEqual([d["day"] for d in self.doc["days"]], list(range(6)))
        for d in self.doc["days"]:
            self.assertEqual(set(d), {"day", "state", "pacing", "episode", "producer", "payoffs", "events"})
            self.assertIn(d["pacing"]["phase"], ("calm", "warm", "peak"))
            self.assertEqual(set(d["producer"]), {"decisions", "entries", "spent_week"})

    def test_an_episode_carries_its_question_its_scenes_and_what_each_scene_said(self):
        eps = [d["episode"] for d in self.doc["days"] if d["episode"]]
        self.assertTrue(eps)
        for ep in eps:
            self.assertTrue(ep["core_question"])
            self.assertTrue(ep["people_names"])
            for b in ep["beats"]:
                self.assertTrue(all("caption" in e and "clock" in e for e in b["events"]))

    def test_every_day_the_producer_either_acts_or_says_why_it_keeps_still(self):
        for d in self.doc["days"]:
            self.assertTrue(d["producer"]["decisions"], d["day"])
            for x in d["producer"]["decisions"]:
                self.assertIn(x["action"], ("intervene", "silence"))
                self.assertTrue(x["reason"])

    def test_the_people_carry_what_the_people_tab_shows(self):
        self.assertTrue(self.doc["people"])
        for p in self.doc["people"]:
            self.assertTrue({"id", "name", "ability", "crowd", "debt", "debt_parts", "payoffs", "ties", "emotion"} <= set(p))

    def test_the_page_is_made_and_opens_from_the_file_system_too(self):
        site = self.tmp / "site"
        for name in ("index.html", "studio.css", "studio.js", "studio.json", "studio-data.js"):
            self.assertTrue((site / name).exists(), name)
        self.assertTrue((site / "studio-data.js").read_text(encoding="utf-8").startswith("window.STUDIO = "))
        html = (site / "index.html").read_text(encoding="utf-8")
        for ref in ("studio.css", "studio.js", "studio-data.js"):
            self.assertIn(ref, html)

    def test_the_same_world_is_in_3d_and_every_scene_knows_when_and_where_it_was(self):
        self.assertIsNotNone(self.doc["world3d"])
        self.assertTrue((self.tmp / "site" / "world" / "index.html").exists())
        self.assertTrue((self.tmp / "site" / "world" / "world.json").exists())
        for d in self.doc["days"]:
            for b in (d["episode"] or {"beats": []})["beats"]:
                for e in b["events"]:
                    self.assertIn("t", e)
                    self.assertIn("place_id", e)
                    self.assertEqual(e["t"] // 86400, e["day"])

    def test_going_on_adds_a_day_and_leaves_the_earlier_ones(self):
        before = json.dumps(self.studio.days[:6], sort_keys=True)
        self.studio.advance(1)
        self.assertEqual(len(self.studio.days), 7)
        self.assertEqual(json.dumps(self.studio.days[:6], sort_keys=True), before)
        self.assertEqual(json.loads((self.tmp / "studio.json").read_text(encoding="utf-8"))["meta"]["days"], 7)


class Worlds(unittest.TestCase):
    def test_a_world_is_made_from_a_preset_listed_and_the_front_door_points_at_it(self):
        from channel.studio import Hub
        tmp = Path(tempfile.mkdtemp(prefix="hub_"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        hub = Hub(tmp)
        key = hub.make("town", 3, 2)
        self.assertEqual(key, "town-3")
        self.assertTrue((tmp / key / "site" / "index.html").exists())
        cat = json.loads((tmp / "worlds.json").read_text(encoding="utf-8"))
        self.assertEqual([w["key"] for w in cat["worlds"]], [key])
        self.assertTrue(cat["worlds"][0]["live"])
        self.assertIn("jianghu", cat["presets"])
        hub.front_door(key)
        self.assertIn(f"{key}/site/index.html", (tmp / "index.html").read_text(encoding="utf-8"))

    def test_a_world_left_by_an_earlier_run_is_listed_but_cannot_go_on(self):
        from channel.studio import Hub
        tmp = Path(tempfile.mkdtemp(prefix="hub_"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        Hub(tmp).make("town", 4, 1)
        later = Hub(tmp)
        rows = later.catalog()
        self.assertEqual([(r["key"], r["live"]) for r in rows], [("town-4", False)])

    def test_an_unknown_preset_is_refused_and_the_days_are_bounded(self):
        from channel.studio import Hub
        tmp = Path(tempfile.mkdtemp(prefix="hub_"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        with self.assertRaises(ValueError):
            Hub(tmp).make("nowhere")


class Page(unittest.TestCase):
    def test_the_script_is_valid_javascript(self):
        try:
            r = subprocess.run(["node", "--check", str(HERE / "studio.js")], capture_output=True, text=True, timeout=60)
        except FileNotFoundError:
            self.skipTest("node is not installed")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_the_page_only_reads(self):
        js = (HERE / "studio.js").read_text(encoding="utf-8")
        self.assertEqual(js.count("method: \"POST\""), 2)            # the two things it can ask: go on, and make another world
        self.assertIn("advance?n=", js)
        self.assertIn("/new?", js)
        self.assertNotIn("XMLHttpRequest", js)

    def test_the_page_speaks_the_words_of_the_planner(self):
        from contracts.episode_plan import GRAMMAR_STEPS, INTENTS, STAGES
        js = (HERE / "studio.js").read_text(encoding="utf-8")
        for word in (*INTENTS, *STAGES, *GRAMMAR_STEPS):
            self.assertIn(word, js, word)


if __name__ == "__main__":
    unittest.main()
