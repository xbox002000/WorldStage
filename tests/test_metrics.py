from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from narrative.selector import rank_arcs
from production import db as prod
from production.metrics import (LATE_FROM_DAY, acceptance, continuity_report, decision_mix, episode_flags, episodes,
                                flat_episode_ratio, format_report, has_lie_chain, late_trace, llm_talk_tones,
                                model_drama_share, strong_flip, usage, warm_tone_ratio)
from production.pipeline import make_episodes
from tests.helpers import social_world
from tests.test_series import lie_story
from tests.test_social import STOLE, cid, do, told_memory
from world.events import Change, EventSpec, apply_event
from world.intent import Intent
from narrative.arcs import Ev, load_events


def make(world, conn, cands):
    out = Path(tempfile.mkdtemp(prefix="eps_"))
    return make_episodes(world, conn, out, cands, render=False)


def incident_candidates(world, exclude=frozenset()):
    return [c for c in rank_arcs(world, exclude=exclude)[0] if c.arc.kind == "incident"]


class ToneTests(unittest.TestCase):
    def test_warm_ratio_counts_only_what_a_model_decided(self):
        conn = social_world()
        for ts, tone, source in ((10, "warm", "m"), (11, "warm", "m"), (12, "cold", "m"), (13, "warm", ""), (14, "warm", ""), (15, "hostile", "")):
            do(conn, ts, Intent("john", "talk", "mary", tone, source=source))
        self.assertEqual(llm_talk_tones(conn), {"cold": 1, "warm": 2})
        self.assertAlmostEqual(warm_tone_ratio(conn), 2 / 3)

    def test_no_model_decisions_means_no_ratio(self):
        conn = social_world()
        do(conn, 10, Intent("john", "talk", "mary", "warm"))
        self.assertIsNone(warm_tone_ratio(conn))


class DecisionMixTests(unittest.TestCase):
    def test_the_model_and_the_random_background_are_counted_apart(self):
        conn = social_world()
        do(conn, 10, Intent("tom", "steal", "phone", source="m"))
        do(conn, 11, Intent("john", "talk", "mary", "warm", source="m"))
        do(conn, 12, Intent("john", "talk", "mary", "cold", source="m"))
        do(conn, 13, Intent("mary", "talk", "john", "warm"))
        self.assertEqual(decision_mix(conn), {"model": {"steal": 1, "talk": 2}, "seeded": {"talk": 1}})
        self.assertAlmostEqual(model_drama_share(conn), 1 / 3)

    def test_a_model_that_only_talks_has_no_drama_share_and_no_model_means_none(self):
        conn = social_world()
        do(conn, 10, Intent("john", "talk", "mary", "warm"))
        self.assertIsNone(model_drama_share(conn))
        do(conn, 11, Intent("john", "talk", "mary", "cold", source="m"))
        self.assertEqual(model_drama_share(conn), 0.0)


class FlipStrengthTests(unittest.TestCase):
    @staticmethod
    def ev(flipped, shift):
        return Ev(1, 0, "talk", "cafe", None, 0.5, {}, (), shift, flipped)

    def test_a_flip_counts_as_a_reversal_only_when_trust_really_moves(self):
        self.assertFalse(strong_flip(self.ev(True, 0.12)))  # +0.06 to -0.06 is a crossing of zero
        self.assertTrue(strong_flip(self.ev(True, 0.35)))
        self.assertFalse(strong_flip(self.ev(False, 0.60)))  # a big move that keeps the sign is not a flip


class EpisodeFlagTests(unittest.TestCase):
    def test_lie_chain_needs_the_lie_the_spreading_and_the_catch_in_that_order(self):
        world, _ = lie_story()
        conn = prod.open_production_db()
        make(world, conn, incident_candidates(world))
        (row,) = episodes(conn)
        self.assertTrue(has_lie_chain(row.spec))
        unfinished, _ = lie_story(finish=False)
        conn2 = prod.open_production_db()
        make(unfinished, conn2, incident_candidates(unfinished))
        self.assertFalse(has_lie_chain(episodes(conn2)[0].spec))  # nobody caught it

    def test_an_exposure_episode_is_not_flat_and_a_quiet_one_is(self):
        world, _ = lie_story()
        conn = prod.open_production_db()
        make(world, conn, incident_candidates(world))
        events = load_events(world)
        (row,) = episodes(conn)
        flags = episode_flags(events, row)
        self.assertTrue(flags["exposure"])
        self.assertFalse(flags["flat"])

        calm = social_world()
        for ts, a, b in ((10, "john", "mary"), (20, "mary", "john")):
            do(calm, ts, Intent(a, "talk", b, "neutral"))
        conn2 = prod.open_production_db()
        cand = rank_arcs(calm)[0][0]
        make(calm, conn2, [cand])
        ratio, calm_flags = flat_episode_ratio(calm, episodes(conn2))
        self.assertTrue(calm_flags[0]["flat"])
        self.assertEqual(ratio, 1.0)

    def test_follow_ups_are_measured_against_what_was_already_shown(self):
        world, ids = lie_story()
        conn = prod.open_production_db()
        first = [c for c in incident_candidates(world)]
        # episode 1 tells the beginning only (trim the arc ourselves by excluding the ending), episode 2 the rest
        early = {ids["exposure"], ids["truth"]}
        cand_a = incident_candidates(world, exclude=early)[0]
        make(world, conn, [cand_a])
        shown = set(cand_a.arc.ids)
        cand_b = incident_candidates(world, exclude=shown)[0]
        make(world, conn, [cand_b])
        report = continuity_report(world, episodes(conn))
        self.assertEqual(len(report), 1)  # the first episode has nothing to continue
        self.assertTrue(report[0]["connected"])
        self.assertEqual(report[0]["evidence"]["kind"], "causal")

    def test_an_unrelated_second_episode_is_reported_as_disconnected(self):
        world = social_world()
        do(world, 10, Intent("john", "talk", "mary", "hostile"))
        do(world, 20, Intent("john", "talk", "mary", "hostile"))
        do(world, 30, Intent("ben", "move", "cafe"))
        conn = prod.open_production_db()
        c1 = rank_arcs(world)[0][0]
        make(world, conn, [c1])
        # a second story about people who never appeared before
        apply_event(world, EventSpec(timestamp=60, type="move", trigger_type="t", changes=[Change("person", "anna", "location_id", value="cafe")]))
        do(world, 70, Intent("tom", "talk", "anna", "hostile"))
        do(world, 80, Intent("tom", "talk", "anna", "hostile"))
        used = set(c1.arc.ids)
        c2 = next(c for c in rank_arcs(world, exclude=used)[0] if set(c.arc.peak.people[:2]) == {"tom", "anna"})
        make(world, conn, [c2])
        (report,) = continuity_report(world, episodes(conn))
        self.assertFalse(report["connected"])


class ChainTests(unittest.TestCase):
    def test_late_decisions_that_trace_back_to_the_first_day(self):
        conn = social_world()
        day = 1440
        prev = apply_event(conn, EventSpec(timestamp=100, type="talk", trigger_type="t", truth={"actor": "john", "target": "mary", "tone": "cold"},
                                           participants=[("john", "actor"), ("mary", "target")]))
        for d in range(1, LATE_FROM_DAY + 1):
            prev = apply_event(conn, EventSpec(timestamp=d * day + 100, type="talk", trigger_type="t", parent_event_id=prev,
                                               truth={"actor": "john", "target": "mary", "tone": "cold"},
                                               participants=[("john", "actor"), ("mary", "target")]))
        reached, total = late_trace(conn)
        self.assertEqual((reached, total), (1, 1))

    def test_usage_adds_up_the_daily_runs(self):
        conn = prod.open_production_db()
        for day, calls in enumerate((10, 12)):
            conn.execute("INSERT INTO daily_runs(experiment_id, sim_day, world_revision, snapshot_hash, status, usage_json, created_at) "
                         "VALUES ('A', ?, 1, 'h', 'episode', ?, 0)",
                         (day, json.dumps({"llm_calls": calls, "llm_failures": 1, "switches": day, "decider_errors": 0, "models": ["m", "n"][: day + 1]})))
        conn.execute("INSERT INTO daily_runs(experiment_id, sim_day, world_revision, snapshot_hash, status, usage_json, created_at) "
                     "VALUES ('B', 0, 1, 'h', 'episode', '{\"llm_calls\": 99}', 0)")
        self.assertEqual(usage(conn, "A"), {"days": 2, "llm_calls": 22, "llm_failures": 2, "switches": 1, "decider_errors": 0,
                                            "models": ["m", "n"]})
        self.assertEqual(usage(conn)["llm_calls"], 121)


class AcceptanceTests(unittest.TestCase):
    def test_the_report_names_every_check_and_only_fails_on_evaluated_ones(self):
        world, ids = lie_story()
        conn = prod.open_production_db()
        cand_a = incident_candidates(world, exclude={ids["exposure"], ids["truth"]})[0]
        make(world, conn, [cand_a])
        make(world, conn, [incident_candidates(world, exclude=set(cand_a.arc.ids))[0]])
        result = acceptance(world, conn, days=2, replay_ok=True)
        self.assertEqual(set(result["checks"]), {
            "episodes_produced", "episodes_passed_qa", "warm_tone_ratio", "flat_episode_ratio", "flat_episode_ratio_strict",
            "model_drama_share", "lie_chain_in_an_episode",
            "continuity", "late_decisions_traceable_to_day_1", "world_audit", "llm_failures", "replay_identical"})
        self.assertTrue(result["checks"]["episodes_produced"]["passed"])
        self.assertFalse(result["checks"]["episodes_passed_qa"]["passed"])  # nothing was rendered in this test
        self.assertIsNone(result["checks"]["warm_tone_ratio"]["passed"])
        self.assertIn("warm_tone_ratio", result["not_evaluated"])
        self.assertTrue(result["checks"]["continuity"]["passed"])
        self.assertFalse(result["passed"])  # a failing check fails the run
        text = format_report(result)
        self.assertIn("RESULT: some checks failed", text)
        self.assertIn("FAIL  episodes_passed_qa", text)


if __name__ == "__main__":
    unittest.main()
