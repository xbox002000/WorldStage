"""Director Reality Test, fast half: one scene, forced DirectorPlans, different viewing experiences, the same truth.

The rendered half is director_reality.py (it needs the HyperFrames toolchain); this checks everything up to the
cartoon script: the plans, the packets, what the audience would see and read, and that the scene never changes.
"""
from __future__ import annotations

import shutil
import subprocess
import unittest
from pathlib import Path

from narrative.arcs import Arc, load_events
from narrative.compiler import compile_packet
from narrative.direction import plan_direction
from narrative.scene_spec import build_scene_specs
from narrative.selector import Candidate
from narrative.threads import derive_threads
from production.viewing import on_screen, viewing_profile
from render.cast.packet_script import to_script
from tests.test_animals import with_dog
from tests.test_world_c import put
from world.animals import with_senses
from world.events import apply_event
from world.intent import Intent
from world.items import misplace, notice_missing
from world.rules import resolve

CAST_JS = Path(__file__).resolve().parent.parent / "render" / "cast"


def dog_story():
    """Ming drops his wallet at the café while Kai watches, the dog carries it off, Ming misses it and suspects Kai."""
    c = with_dog()
    put(c, 10, ming="cafe", kai="cafe")
    apply_event(c, misplace(c, "ming", "wallet_ming", 20))
    put(c, 30, ming="office", kai="office")
    apply_event(c, with_senses(c, resolve(c, Intent("dog", "take", "wallet_ming"), 40, "decision")))
    apply_event(c, notice_missing(c, "ming", "wallet_ming", 50))
    thread = next(t for t in derive_threads(c) if t.thread_id == "item:wallet_ming")
    events = load_events(c)
    evs = tuple(events[i] for i in thread.event_ids)
    spec = build_scene_specs(c, [Candidate(Arc(evs, max(evs, key=lambda e: e.importance), "thread"), 1.0, {}, 1.0)])[0]
    return c, thread, spec


class RealityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c, cls.thread, cls.spec = dog_story()
        cls.plans = {k: plan_direction(cls.c, cls.spec, cls.thread, **kw) for k, kw in {
            "mystery": dict(focalizer="ming", strategy="mystery", grammar="observational"),
            "dog": dict(focalizer="dog", strategy="irony", grammar="subjective"),
            "reaction": dict(focalizer="ming", strategy="irony", grammar="reaction"),
            "auto": {}}.items()}
        cls.packets = {k: compile_packet(cls.spec, direction=p) for k, p in cls.plans.items()}
        cls.views = {k: viewing_profile(p, {"dog"}) for k, p in cls.packets.items()}

    def test_the_scene_and_its_truth_never_change(self):
        self.assertEqual({p.scene_hash for p in self.plans.values()}, {self.spec.scene_hash})
        self.assertEqual({p.scene_hash for p in self.packets.values()}, {self.spec.scene_hash})
        self.assertEqual(self.plans["dog"].forced, {"focalizer": "dog", "strategy": "irony", "grammar": "subjective"})
        self.assertEqual(self.plans["auto"].forced, {})

    def test_a_mystery_never_shows_or_names_the_culprit(self):
        v = self.views["mystery"]
        self.assertFalse(v["audience_witnesses_culprit_act"])
        self.assertTrue(v["hidden_shots"])
        self.assertFalse(any("小狗" in c for c in v["captions"]))
        self.assertFalse(any(s.thought_by == "dog" for s in self.packets["mystery"].shots))
        self.assertTrue(self.views["dog"]["audience_witnesses_culprit_act"])

    def test_through_the_dogs_eyes_is_low_wordless_and_sensed(self):
        dog, auto = self.views["dog"], self.views["mystery"]
        self.assertLess(dog["camera_height_m"], auto["camera_height_m"])
        self.assertGreater(dog["subjective_share"], 0.3)
        self.assertLess(dog["words_audible_share"], auto["words_audible_share"] + 1e-9)
        self.assertTrue(any(":sense:" in i for i in dog["inner"]))  # a percept, not a sentence about who did what
        self.assertNotIn("dog", [w for s in self.packets["dog"].shots if s.relation == "subjective" for w in on_screen(s)])

    def test_camera_grammars_are_different_ways_of_watching(self):
        mystery, reaction = self.views["mystery"], self.views["reaction"]
        self.assertEqual(mystery["moving_share"], 0.0)  # observational: nothing moves
        self.assertGreater(reaction["reaction_shots"], mystery["reaction_shots"])
        self.assertGreater(reaction["close_share"], mystery["close_share"])

    def test_a_belief_is_something_the_audience_can_see(self):
        shots = [s for s in self.packets["reaction"].shots if s.event_type == "notice_missing"]
        self.assertTrue(any(s.suspect_id == "kai" for s in shots))
        self.assertTrue(any(s.thought and "阿凱" in s.thought for s in shots))

    def test_the_cartoon_script_follows_the_packet(self):
        for key, packet in self.packets.items():
            script = to_script(packet, badge=[key])
            self.assertEqual(len(script["shots"]), len(packet.shots))
            self.assertEqual(script["cast"]["dog"]["kind"], "animal")
        dog = to_script(self.packets["dog"])
        self.assertTrue(any(s["angle"] == "ground" and s["relation"] == "subjective" for s in dog["shots"]))
        self.assertTrue(any(s["caption"] and s["caption"]["kind"] == "sense" for s in dog["shots"]))

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_the_cartoon_code_parses(self):
        for f in ("characters.js", "animals.js", "props.js", "backgrounds.js", "directed.js"):
            subprocess.run(["node", "--check", str(CAST_JS / f)], check=True)


if __name__ == "__main__":
    unittest.main()
