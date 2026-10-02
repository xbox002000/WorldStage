"""The conformance suite itself: the fixtures are sound, and the runner tells a good provider from a bad one.

The stand-ins are the local mock-clip provider (render/mock_clip.py) and small fakes built on it; nothing is paid and nothing
leaves the machine. Clips are made at a tenth of the canvas: the checks do not depend on the pixels and ffmpeg's time does.
"""
from __future__ import annotations

import dataclasses
import json
import os
import unittest
from pathlib import Path

from contracts import bible as cb
from contracts.base import from_dict
from contracts.capability import Policy
from render.mock_clip import MockClipBackend
from tests.provider_conformance import runner as R
from tests.provider_conformance.builder import KINDS

SCALE = 0.1
REQUIRED_KINDS = {"two_person_dialogue", "duel", "hand_over", "public_face_slap", "ambiguous_closeup", "crowd_reaction"}


def mock(rate: float = 0.0, name: str = "mock-clip") -> MockClipBackend:
    return MockClipBackend(name=name, defect_rate=rate)


class Fixtures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = R.load_samples()
        cls.bible = from_dict(cb.Bible, json.loads(R.BIBLE.read_text(encoding="utf-8")))

    def test_the_suite_has_the_required_kinds_from_a_real_world(self):
        kinds = {s["id"] for s in self.data["samples"]}
        self.assertLessEqual(REQUIRED_KINDS, kinds)
        self.assertEqual(kinds, set(KINDS))
        self.assertGreaterEqual(len(self.data["samples"]), 6)
        self.assertEqual((self.data["recipe"], self.data["seed"]), ("jianghu_story_v1", 17))
        for s in self.data["samples"]:
            self.assertEqual(s["source"]["recipe"], "jianghu_story_v1")
            self.assertTrue(s["source"]["packet_hash"].startswith("sha256:"))
            self.assertEqual(s["source"]["function"] in ("connect", "escalate", "payoff", "longing_glance", "reaction", "reveal"), True)

    def test_the_samples_are_distinct_complete_and_agree_with_their_bible(self):
        self.assertEqual(R.check_fixtures(self.data, self.bible), [])
        self.assertEqual(self.data["bible_hash"], self.bible.bible_hash)
        self.assertTrue(cb.verify(self.bible))
        self.assertEqual(cb.check_bible(self.bible), [])

    def test_every_intent_is_in_the_closed_vocabulary_and_no_prompt_has_a_model_word(self):
        from contracts.episode_plan import INTENTS
        for s in self.data["samples"]:
            self.assertIn(s["intent"], INTENTS)
            shot = R.shot_of(s)
            self.assertEqual(cb.model_words_in([shot.prompt, shot.subject, shot.action, shot.environment, shot.camera]), [], s["id"])
            self.assertEqual((shot.width, shot.height, shot.fps), (1080, 1920, 30))
            self.assertTrue(shot.performance and shot.duration_seconds > 0 and shot.seed >= 0)

    def test_a_sample_with_people_in_it_is_filmed_with_people_the_bible_knows(self):
        for s in self.data["samples"]:
            self.assertTrue(s["bible"]["characters"], s["id"])
        crowd = next(s for s in self.data["samples"] if s["id"] == "crowd_reaction")
        self.assertGreaterEqual(len(crowd["bible"]["characters"]), 3)

    def test_a_broken_set_is_reported(self):
        bad = {"samples": [self.data["samples"][0]] * 2}
        problems = R.check_fixtures(bad, self.bible)
        self.assertTrue(any("at least" in p for p in problems) and any("twice" in p for p in problems)
                        and any("same shot" in p for p in problems))
        orphan = json.loads(json.dumps(self.data))
        orphan["samples"][0]["bible"]["scene"] = "scene:nowhere"
        self.assertTrue(any("scene:nowhere" in p for p in R.check_fixtures(orphan, self.bible)))

    @unittest.skipUnless(os.environ.get("PROVIDER_CONFORMANCE_REBUILD"), "set PROVIDER_CONFORMANCE_REBUILD=1 to replay the world")
    def test_the_fixtures_are_what_the_engine_makes_today(self):
        from tests.provider_conformance.builder import drift
        self.assertEqual(drift(), [])


class Judging(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = R.load_samples()
        cls.good = R.run_conformance(mock(0.0), cls.data, scale=SCALE)

    def test_a_provider_that_makes_every_shot_properly_passes(self):
        r = self.good
        self.assertTrue(r.passed)
        self.assertEqual(len(r.results), len(self.data["samples"]))
        self.assertEqual(r.counts, {"pass": len(r.results), "fail": 0, "skipped": 0})
        self.assertEqual(r.pass_rate, 1.0)
        self.assertTrue(all(x.artifact_hash.startswith("sha256:") for x in r.results))
        self.assertIn("PASS", r.text().splitlines()[0])

    def test_the_report_is_stable_for_a_deterministic_provider(self):
        a = R.run_conformance(mock(0.0), self.data, scale=SCALE, determinism=0, only=["duel", "hand_over"])
        b = R.run_conformance(mock(0.0), self.data, scale=SCALE, determinism=0, only=["duel", "hand_over"])
        self.assertEqual(a.report_hash, b.report_hash)   # the time it took is not part of it
        self.assertEqual([x.artifact_hash for x in a.results], [x.artifact_hash for x in self.good.results if x.sample_id in ("duel", "hand_over")])

    def test_the_providers_own_failures_are_the_ones_the_runner_finds(self):
        flaky = mock(0.25)
        r = R.run_conformance(flaky, self.data, scale=SCALE, determinism=0)
        expect = {s["id"] for s in self.data["samples"] if flaky.frozen(R.shot_of(s, scale=SCALE))}
        self.assertTrue(expect, "the fixture seeds should include a frozen one at this rate, or this test proves nothing")
        self.assertEqual({x.sample_id for x in r.results if x.verdict == R.FAIL}, expect)
        self.assertTrue(all(x.failures == ["FROZEN_FRAMES"] for x in r.results if x.verdict == R.FAIL))
        self.assertFalse(r.passed)
        self.assertAlmostEqual(r.pass_rate, 1 - len(expect) / len(r.results), places=3)

    def test_a_provider_that_freezes_everything_fails_everything(self):
        r = R.run_conformance(mock(1.0), self.data, scale=SCALE, only=["duel", "hand_over"])
        self.assertEqual([x.failures for x in r.results], [["FROZEN_FRAMES"]] * 2)
        self.assertEqual(r.counts["fail"], 2)

    def test_a_provider_that_raises_makes_a_failed_take_not_a_crash(self):
        class Raises(MockClipBackend):
            def generate(self, request, shot, dest):
                raise RuntimeError("the model fell over")
        r = R.run_conformance(Raises("raises"), self.data, scale=SCALE, only=["duel"])
        (x,) = r.results
        self.assertEqual((x.verdict, x.failures), (R.FAIL, ["PROVIDER_ERROR"]))
        self.assertIn("the model fell over", x.evidence[0]["error"])

    def test_a_provider_that_makes_the_wrong_size_fails_on_format(self):
        class Small(MockClipBackend):
            def generate(self, request, shot, dest):
                return super().generate(request, dataclasses.replace(shot, width=shot.width // 2, height=shot.height // 2), dest)
        r = R.run_conformance(Small("small", 0.0), self.data, scale=SCALE, only=["duel"])
        self.assertEqual(r.results[0].failures, ["FORMAT_ERROR"])

    def test_a_provider_that_claims_to_be_deterministic_and_is_not_is_caught(self):
        class Drifts(MockClipBackend):
            calls = 0

            def generate(self, request, shot, dest):
                Drifts.calls += 1
                return super().generate(request, dataclasses.replace(shot, seed=shot.seed + Drifts.calls), dest)
        r = R.run_conformance(Drifts("drifts", 0.0), self.data, scale=SCALE, only=["two_person_dialogue"])
        self.assertEqual(r.results[0].failures, ["NONDETERMINISTIC"])
        self.assertEqual(r.results[0].verdict, R.FAIL)

    def test_a_paid_provider_is_skipped_with_its_reason_and_never_called(self):
        class Paid(MockClipBackend):
            called = 0

            def manifest(self):
                return dataclasses.replace(super().manifest(), provider_id="paid", cost_per_second=0.2, local=False,
                                           transport="http")

            def generate(self, request, shot, dest):
                Paid.called += 1
                raise AssertionError("a paid model was called")
        r = R.run_conformance(Paid("paid", 0.0), self.data, scale=SCALE)
        self.assertEqual(Paid.called, 0)
        self.assertEqual(r.counts["skipped"], len(self.data["samples"]))
        self.assertIn("budget", r.results[0].note)
        self.assertFalse(r.passed)
        allowed = R.run_conformance(Paid("paid", 0.0), self.data, scale=SCALE, allow_skipped=True)
        self.assertFalse(allowed.passed)  # nothing was shown to work: skipping everything is not passing
        self.assertEqual(Paid.called, 0)

    def test_a_provider_that_lacks_a_feature_or_a_size_is_skipped(self):
        class NoText(MockClipBackend):
            def manifest(self):
                return dataclasses.replace(super().manifest(), features=["i2v"])
        r = R.run_conformance(NoText("no-text", 0.0), self.data, scale=SCALE)
        self.assertEqual({x.verdict for x in r.results}, {R.SKIPPED})
        self.assertIn("lacks t2v", r.results[0].note)

        class Tiny(MockClipBackend):
            def manifest(self):
                return dataclasses.replace(super().manifest(), max_seconds=3)
        r = R.run_conformance(Tiny("tiny", 0.0), self.data, scale=SCALE, determinism=0, only=["duel", "confrontation"])
        self.assertEqual([x.verdict for x in r.results], [R.PASS, R.SKIPPED])   # 2 s fits, 7 s does not
        self.assertIn("limit", r.results[1].note)
        self.assertFalse(r.passed)
        allowed = R.run_conformance(Tiny("tiny", 0.0), self.data, scale=SCALE, determinism=0, allow_skipped=True)
        self.assertTrue(any(x.verdict == R.SKIPPED for x in allowed.results))

    def test_a_partial_run_is_never_a_pass(self):
        r = R.run_conformance(mock(0.0), self.data, scale=SCALE, only=["duel"], determinism=0)
        self.assertEqual(r.counts, {"pass": 1, "fail": 0, "skipped": 0})
        self.assertFalse(r.passed)

    def test_an_unavailable_provider_is_skipped_not_crashed_into(self):
        class Down(MockClipBackend):
            def available(self):
                return False, "no key"
        r = R.run_conformance(Down("down", 0.0), self.data, scale=SCALE, only=["duel"])
        self.assertEqual((r.results[0].verdict, "no key" in r.results[0].note), (R.SKIPPED, True))

    def test_a_provider_without_the_capability_is_refused(self):
        class Other(MockClipBackend):
            def manifest(self):
                return dataclasses.replace(super().manifest(), capabilities=["audio.score"])
        with self.assertRaises(ValueError):
            R.run_conformance(Other("other", 0.0), self.data, scale=SCALE)

    def test_the_default_policy_allows_only_free_providers(self):
        self.assertEqual(Policy().max_cost, 0.0)
        self.assertEqual(R.run_conformance.__kwdefaults__["policy"].max_cost, 0.0)


if __name__ == "__main__":
    unittest.main()
