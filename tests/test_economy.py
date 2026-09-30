"""Shot economy: every cut is for something the shot adds, never for the angle; a shot that adds nothing is cut;
the same picture twice in a beat is one shot; beats that undo each other and are told again later are left out,
keeping the later ones so the thing ends where the audience saw it go."""
from __future__ import annotations

import unittest

from contracts.director import FORBIDDEN_CUTS
from narrative.direction import plan_direction
from narrative.economy import cancelling_beats
from tests.test_director_reality import dog_story


class EconomyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c, cls.thread, cls.spec = dog_story()
        cls.plans = {name: plan_direction(cls.c, cls.spec, cls.thread, focalizer=who, strategy=strategy)
                     for name, who, strategy in (("A", "ming", "mystery"), ("B", "dog", "irony"),
                                                 ("C", "omniscient", "irony"))}

    def test_no_cut_is_for_the_angle_alone(self):
        for name, p in self.plans.items():
            for c in p.cuts:
                self.assertNotIn(c.reason, FORBIDDEN_CUTS, name)

    def test_every_shot_adds_something_and_says_what(self):
        for name, p in self.plans.items():
            self.assertEqual(len(p.values), len(p.shots), name)
            for v in p.values:
                gain = v.information + v.emotion + v.relation + v.state + v.action
                self.assertTrue(gain > 0 or v.shot_index == 0 or v.why, (name, v))

    def test_the_same_picture_twice_in_a_beat_is_one_shot(self):
        for name, p in self.plans.items():
            for a, b in zip(p.shots, p.shots[1:]):
                self.assertFalse(a.beat_index == b.beat_index and a.subject == b.subject and a.scale == b.scale
                                 and a.relation == b.relation, (name, a, b))

    def test_the_dogs_eyes_version_is_no_longer_ten_shots_of_one_wallet(self):
        b = self.plans["B"]
        wallet = [s for s in b.shots if s.subject == "wallet_ming"]
        self.assertLessEqual(len(wallet), 3)
        self.assertLessEqual(len(b.shots), 10)

    def test_a_repeated_picture_is_merged_and_an_empty_shot_is_cut(self):
        import dataclasses
        from narrative.economy import value_shots
        p = self.plans["C"]
        shots = list(p.shots)
        k = next(i for i, s in enumerate(shots) if s.scale == "INSERT")
        twin = dataclasses.replace(shots[k], reason="the same insert again")  # same subject, framing, side, beat
        shots = [dataclasses.replace(s, shot_index=n) for n, s in enumerate(shots[:k + 1] + [twin] + shots[k + 1:])]
        kept, _values, dropped = value_shots(self.c, self.spec, shots, p.knowledge, p.focalization, None)
        self.assertEqual(len(kept), len(p.shots))
        self.assertTrue(any("merged" in d.reason for d in dropped))
        self.assertGreater(kept[k].seconds, p.shots[k].seconds)  # one shot, a little longer

    def test_the_first_shot_from_the_animals_height_is_kept(self):
        b = self.plans["B"]
        self.assertTrue(any(s.angle == "ground" or s.relation == "subjective" for s in b.shots))

    def test_beats_that_undo_each_other_are_left_out_keeping_the_later_ones(self):
        elided = cancelling_beats(self.c, self.spec)
        if not elided:
            self.skipTest("this story has no beats that undo each other")
        kept_after = [i for i in range(len(self.spec.beats)) if i not in elided and i > min(elided)]
        props = {self.spec.beats[i].prop.id for i in elided if self.spec.beats[i].prop}
        # the thing's last change of hands before the end is still shown
        self.assertTrue(any(self.spec.beats[i].prop and self.spec.beats[i].prop.id in props for i in kept_after))


if __name__ == "__main__":
    unittest.main()
