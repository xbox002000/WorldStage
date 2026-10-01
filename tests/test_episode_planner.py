"""Episode planner: the shape of one episode, read from what happened. It adds nothing and decides nothing."""
from __future__ import annotations

import unittest
from typing import get_args

from agent.volition import VolitionDecider
from contracts import director as cd
from contracts import episode_plan as ep
from narrative import episode_planner as P
from narrative.arcs import load_events
from narrative.dramaturgy import analyse
from producer.director import Director
from tests.test_opportunity import fingerprint
from world.db import connect, init_db
from world.events import EventSpec, apply_event
from world.seed import build_world
from world.simulation import Simulation


def produced(seed=17, days=8, upto=None):
    c = connect()
    init_db(c, seed)
    build_world(c, seed, "jianghu_story_v1")
    d = VolitionDecider(seed)
    Simulation(c, d, d, set(), feed="synthetic_v1", producer=Director("greedy", seed)).run(days)
    return c


class Vocabulary(unittest.TestCase):
    def test_the_shot_intents_contain_the_directors_functions_and_the_new_moments(self):
        self.assertEqual(set(ep.INTENTS), set(get_args(ep.ShotIntent)))
        self.assertTrue(set(get_args(cd.Function)) <= set(ep.INTENTS))
        self.assertTrue({"face_slap", "bystander_shock", "longing_glance", "rival_standoff", "confession"} <= set(ep.INTENTS))

    def test_no_intent_speaks_of_a_model_or_a_lens(self):
        for w in ep.INTENTS:
            self.assertFalse(any(x in w for x in ("cinematic", "8k", "lens", "bokeh")))

    def test_the_ladder_has_eight_rungs_in_order(self):
        self.assertEqual(ep.STAGES[0], "daily")
        self.assertEqual(ep.STAGES[-1], "change")
        self.assertEqual(len(ep.STAGES), 8)
        self.assertEqual(len(ep.GRAMMAR_STEPS), 6)


class Planning(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = produced()
        cls.before = fingerprint(cls.c)
        cls.sit = analyse(cls.c)["situations"]
        cls.plans = {}
        shown: set[int] = set()
        for day in range(8):
            plan = P.plan_day(cls.c, day, shown, cls.sit)
            if plan is not None:
                cls.plans[day] = plan
                for b in plan.beats:
                    shown |= set(b.event_ids)

    def test_it_only_reads(self):
        self.assertEqual(fingerprint(self.c), self.before)

    def test_every_episode_poses_one_question_and_every_beat_is_on_a_rung_with_an_intent(self):
        self.assertTrue(self.plans)
        for plan in self.plans.values():
            self.assertTrue(plan.core_question)
            for b in plan.beats:
                self.assertIn(b.stage, ep.STAGES)
                self.assertIn(b.intent, ep.INTENTS)
                self.assertTrue(0.0 <= b.tension <= 1.0)

    def test_every_beat_points_at_an_event_that_happened(self):
        events = load_events(self.c)
        for plan in self.plans.values():
            for b in plan.beats:
                self.assertTrue(all(i in events for i in b.event_ids))

    def test_a_scene_in_which_nothing_changed_is_not_filmed(self):
        dropped = [b for p in self.plans.values() for b in p.beats if not b.shoot]
        self.assertTrue(all(not b.checklist.changed or not b.who for b in dropped))
        for p in self.plans.values():
            self.assertEqual(p.dropped, [b.index for b in p.beats if not b.shoot])
            self.assertEqual(p.tension_curve, [b.tension for b in p.beats if b.shoot])

    def test_the_plan_is_deterministic_and_hashed(self):
        a = P.plan_day(self.c, 3, set(), self.sit)
        b = P.plan_day(self.c, 3, set(), self.sit)
        self.assertEqual(a.plan_hash, b.plan_hash)
        self.assertTrue(a.plan_hash)

    def test_the_same_pair_is_not_told_two_days_running_when_there_is_another(self):
        shown: set[int] = set()
        recent: tuple = ()
        last = None
        repeats = 0
        for day in range(3, 8):
            plan = P.plan_day(self.c, day, shown, self.sit, recent)
            if plan is None:
                continue
            for b in plan.beats:
                shown |= set(b.event_ids)
            if plan.kind == "thread" and last == set(plan.people):
                repeats += 1
            last = set(plan.people)
            recent = (frozenset(plan.people),)
        self.assertLessEqual(repeats, 1)


class PayoffEpisode(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = produced(17, 6)
        cls.plan = next((P.plan_day(cls.c, d, set()) for d in range(6) if P.choose_material(cls.c, d, set())[2] == "payoff"), None)

    def test_a_release_the_audience_waited_for_comes_first_and_follows_the_web_novel_line(self):
        self.assertIsNotNone(self.plan)
        self.assertEqual(self.plan.kind, "payoff")
        self.assertEqual([g.step for g in self.plan.grammar], list(ep.GRAMMAR_STEPS))
        reversal = next(g for g in self.plan.grammar if g.step == "reversal")
        self.assertTrue(reversal.present)

    def test_a_missing_step_is_reported_not_invented(self):
        events = load_events(self.c)
        for g in self.plan.grammar:
            self.assertEqual(g.present or not g.event_ids, True)
            self.assertTrue(all(i in events for i in g.event_ids))
        self.assertEqual(self.plan.grammar_complete, all(g.present for g in self.plan.grammar))

    def test_the_set_up_is_kept_even_though_it_changed_nothing_yet(self):
        growth = next(g for g in self.plan.grammar if g.step == "hidden_growth")
        if growth.present:
            kept = [b for b in self.plan.beats if set(b.event_ids) & set(growth.event_ids)]
            self.assertTrue(all(b.shoot for b in kept if b.who))

    def test_the_next_goal_is_the_heros_own(self):
        events = load_events(self.c)
        step = next(g for g in self.plan.grammar if g.step == "next_goal")
        peak = next(g for g in self.plan.grammar if g.step == "reversal").event_ids[0]
        hero = events[peak].truth.get("winner") or events[peak].truth.get("actor")
        for i in step.event_ids:
            self.assertEqual(events[i].truth.get("actor"), hero)

    def test_the_room_reacts_in_a_beat_of_its_own(self):
        shock = [b for b in self.plan.beats if b.intent == "bystander_shock"]
        for b in shock:
            self.assertTrue(b.derived)
            self.assertGreaterEqual(len(b.who), 2)


class ToTheCamera(unittest.TestCase):
    """What the plan wants of a scene reaches the director as intents; with none, the director's plan is what it was."""

    @classmethod
    def setUpClass(cls):
        from narrative.scene_spec import build_scene_specs
        from narrative.selector import Candidate
        cls.c = produced(17, 6)
        day = next(d for d in range(6) if P.choose_material(cls.c, d, set())[2] == "payoff")
        arc, thread, kind, payoff, steps = P.choose_material(cls.c, day, set())
        cls.plan = P.plan_episode(cls.c, arc, thread, set(), day, kind, payoff, steps)
        cls.spec = build_scene_specs(cls.c, [Candidate(arc, 0.5, {})], ["s1"])[0]
        cls.intents = {i: [b.intent] for b in cls.plan.beats if b.shoot for i in b.event_ids}

    def test_the_new_intents_become_shots(self):
        from narrative.direction import plan_direction
        got = {s.function for s in plan_direction(self.c, self.spec, None, set(), intents=self.intents).shots}
        self.assertTrue({"face_slap"} & got or {"payoff"} & got)

    def test_with_no_intents_the_plan_is_what_it_was(self):
        from narrative.direction import plan_direction
        a = plan_direction(self.c, self.spec, None, set())
        b = plan_direction(self.c, self.spec, None, set(), intents=None)
        self.assertEqual(a.plan_hash, b.plan_hash)
        self.assertFalse({"face_slap", "bystander_shock"} & {s.function for s in a.shots})


class InnerEpisode(unittest.TestCase):
    def test_a_choice_against_oneself_is_an_episode_of_its_own(self):
        c = produced(17, 3)
        eid = apply_event(c, EventSpec(timestamp=3 * 1440 + 600, type="lend", trigger_type="decision", importance=0.5,
                                       truth={"actor": "kai", "target": "ming", "dilemma": {"tension": 0.7, "serves": {"loyalty": 0.6}, "costs": {"security": 0.5}}},
                                       participants=[("kai", "actor"), ("ming", "target")]))
        arc, thread, kind, payoff, steps = P.choose_material(c, 3, set())
        self.assertEqual(kind, "inner")
        self.assertEqual(arc.peak.id, eid)
        plan = P.plan_episode(c, arc, thread, set(), 3, kind, payoff, steps)
        self.assertTrue(plan.inner_conflict)
        self.assertTrue(plan.core_question)
        self.assertIn("choice", {b.intent for b in plan.beats})


class DailyJob(unittest.TestCase):
    def run_days(self, **kw):
        import os
        import shutil
        import tempfile

        from channel.daily import DailyConfig, run_daily
        tmp = tempfile.mkdtemp(prefix="dailyep_")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        cfg = DailyConfig(world_db=os.path.join(tmp, "world.db"), prod_db=os.path.join(tmp, "prod.db"), out_dir=os.path.join(tmp, "episodes"),
                          days=4, seed=17, init=True, render=False, world_c=True, feed="synthetic_v1", recipe="jianghu_story_v1", **kw)
        results = run_daily(cfg)
        return tmp, results

    def test_every_episode_gets_its_plan_next_to_the_directors(self):
        import json
        import os
        tmp, results = self.run_days(episode_first=True)
        made = [r for r in results if os.path.exists(os.path.join(tmp, "episodes", f"day_{r.sim_day + 1:02d}", "director_plan.json"))]
        self.assertTrue(made)
        for r in made:
            folder = os.path.join(tmp, "episodes", f"day_{r.sim_day + 1:02d}")
            with open(os.path.join(folder, "episode_plan.json"), encoding="utf-8") as f:
                plan = json.load(f)
            self.assertTrue(plan["core_question"])
            self.assertTrue(plan["plan_hash"])

    def test_the_plan_is_written_without_changing_the_choice_when_the_planner_does_not_choose(self):
        import os
        tmp, results = self.run_days()
        for r in results:
            folder = os.path.join(tmp, "episodes", f"day_{r.sim_day + 1:02d}")
            if os.path.exists(os.path.join(folder, "director_plan.json")):
                self.assertTrue(os.path.exists(os.path.join(folder, "episode_plan.json")))


class QuietDay(unittest.TestCase):
    def test_a_world_where_nothing_has_happened_has_no_episode(self):
        c = connect()
        init_db(c, 5)
        build_world(c, 5, "jianghu_story_v1")
        self.assertIsNone(P.plan_day(c, 0, set()))


if __name__ == "__main__":
    unittest.main()
