"""PerformancePlan: characters embody their state, derived from the world and never chosen freely; it carries over
from shot to shot, is the same whoever's eyes we are in, fits the body (a dog has a tail, not a voice), and any
backend can use it without touching the world, story or director contracts."""
from __future__ import annotations

import unittest

from narrative.compiler import compile_packet
from narrative.direction import plan_direction
from narrative.performance import PROFILES, continuity_breaks, plan_performance, uncaused
from production.shots import describe
from render.cast.packet_script import to_script
from tests.test_director_reality import dog_story


def ming_at_loss(plan):
    return next(pb for pb in plan.beats if pb.actor == "ming" and pb.intent == "search")


class PerformanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c, cls.thread, cls.spec = dog_story()
        cls.direction = plan_direction(cls.c, cls.spec, cls.thread, focalizer="ming", strategy="mystery",
                                       camera="push_in")
        cls.plan = plan_performance(cls.c, cls.spec, cls.direction)

    def test_the_same_shot_is_played_differently_when_the_person_is_in_a_different_state(self):
        states = {"trusting": {"ming": {"trust:kai": 0.6, "suspects:kai": 0.0, "psy.vigilance": 0.1, "emotion": "calm"}},
                  "fearful": {"ming": {"fear:kai": 0.8, "psy.vigilance": 0.8, "emotion": "afraid"}},
                  "resentful": {"ming": {"trust:kai": -0.7, "rivalry:kai": 0.6, "psy.aggression": 0.2, "emotion": "angry"}}}
        acted = {k: ming_at_loss(plan_performance(self.c, self.spec, self.direction, cf)) for k, cf in states.items()}
        self.assertEqual(len({(a.primary, a.gaze.mode, a.face.jaw) for a in acted.values()}), 3)
        self.assertEqual(acted["resentful"].primary, "restrained_anger")  # aggression 0.2 does not let it out
        self.assertEqual(acted["resentful"].face.jaw, "tight")
        self.assertEqual(acted["fearful"].gaze.mode, "avoid")
        # the counterfactual is recorded and cited, so the difference is traceable to a state, not invented
        p = plan_performance(self.c, self.spec, self.direction, states["resentful"])
        self.assertEqual(p.counterfactual, states["resentful"])
        self.assertTrue(any(c.kind == "counterfactual" for d in ming_at_loss(p).drives for c in d.causes))

    def test_every_performance_has_a_cause_in_the_world(self):
        self.assertEqual(uncaused(self.plan), [])
        loss = ming_at_loss(self.plan)
        self.assertNotEqual(loss.primary, "calm")
        refs = [c.ref for d in loss.drives for c in d.causes]
        self.assertTrue(any(r.startswith("event:") for r in refs))  # the loss itself
        unaware = next(pb for pb in self.plan.beats if pb.actor == "ming" and pb.intent == "go_on")
        self.assertEqual(unaware.primary, "calm")  # dropping it without noticing: nothing to play

    def test_hands_gaze_and_feeling_carry_over_from_shot_to_shot(self):
        self.assertEqual(continuity_breaks(self.plan), [])
        dog = [pb for pb in self.plan.beats if pb.actor == "dog"]
        self.assertTrue(dog and dog[-1].after.holding == "wallet_ming" and dog[-1].after.hand == "mouth")
        dropped = next(pb for pb in self.plan.beats if pb.actor == "ming" and pb.intent == "go_on")
        self.assertEqual((dropped.before.holding, dropped.after.holding), ("wallet_ming", ""))

    def test_whose_eyes_we_are_in_does_not_change_how_anyone_acts(self):
        acts = {}
        for who in ("ming", "dog", "omniscient"):
            d = plan_direction(self.c, self.spec, self.thread, focalizer=who, strategy="irony")
            p = plan_performance(self.c, self.spec, d)
            beat_of = {s.shot_index: s.beat_index for s in d.shots}
            acts[who] = {(beat_of[pb.shot_index], pb.actor): (pb.primary, pb.intent, pb.gaze.mode) for pb in p.beats}
        shared = set(acts["ming"]) & set(acts["dog"]) & set(acts["omniscient"])
        self.assertTrue(shared)
        for k in shared:
            self.assertEqual(acts["ming"][k], acts["dog"][k])
            self.assertEqual(acts["ming"][k], acts["omniscient"][k])

    def test_a_dog_performs_with_the_body_it_has(self):
        dog = [pb for pb in self.plan.beats if pb.profile == "dog"]
        self.assertTrue(dog)
        for pb in dog:
            self.assertIsNone(pb.speech)
            self.assertIsNone(pb.face)
            self.assertIsNone(pb.hands)
            self.assertIsNotNone(pb.animal)
            self.assertTrue(all(m.name in PROFILES["dog"]["micro"] for m in pb.micro))
        self.assertTrue(any(m.name == "sniff" for pb in dog for m in pb.micro))
        self.assertTrue(all(pb.animal is None for pb in self.plan.beats if pb.profile == "human"))

    def test_any_backend_can_use_the_same_performance(self):
        packet = compile_packet(self.spec, direction=self.direction, performance=self.plan)
        self.assertEqual(packet.performance_hash, self.plan.plan_hash)
        shot = next(s for s in packet.shots if any(pb.actor == "ming" and pb.intent == "search" for pb in s.performances))
        self.assertIn("pat pockets", describe(shot))  # what a video model is told: the same performance, in words
        script = to_script(packet)
        acted = [x for s in script["shots"] for x in s["stage"] if x.get("act")]
        self.assertTrue(acted)  # what the 2D stage plays
        self.assertTrue(all(s.information_function for s in packet.shots))
        with self.assertRaises(ValueError):  # a performance planned for another plan is refused
            other = plan_direction(self.c, self.spec, self.thread, focalizer="dog")
            compile_packet(self.spec, direction=other, performance=self.plan)


if __name__ == "__main__":
    unittest.main()
