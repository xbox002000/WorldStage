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

    def test_the_new_state_is_read_from_the_reversal_not_asked_of_the_world_to_log(self):
        events = load_events(self.c)
        step = next(g for g in self.plan.grammar if g.step == "new_state")
        peak = next(g for g in self.plan.grammar if g.step == "reversal").event_ids[0]
        hero = events[peak].truth.get("winner") or events[peak].truth.get("actor")
        for i in step.event_ids:                      # an event, when there is one, is the hero's own
            self.assertEqual(events[i].truth.get("actor"), hero)
        if step.present:                              # and a consequence is only claimed with evidence
            self.assertTrue(step.derived)
            self.assertTrue({"standing", "state", "want", "opening"} & set(step.derived))

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


class WhatChanged(unittest.TestCase):
    """The change of a scene is the world's and the audience's: a growth only the audience has seen is a scene, without a special case."""

    @classmethod
    def setUpClass(cls):
        cls.c = produced(17, 6)
        cls.day = next(d for d in range(6) if P.choose_material(cls.c, d, set())[2] == "payoff")
        cls.arc, cls.thread, cls.kind, cls.payoff, cls.steps = P.choose_material(cls.c, cls.day, set())

    def plan(self, options):
        return P.plan_episode(self.c, self.arc, None, set(), self.day, self.kind, self.payoff, self.steps, None, options)

    def test_a_hidden_growth_is_kept_because_the_audience_is_ahead_not_because_it_is_special(self):
        growth = {i for g in self.steps if g.step == "hidden_growth" for i in g.event_ids}
        ahead = [b for b in self.plan(P.DEFAULT).beats if set(b.event_ids) & growth and b.checklist.audience_advantage > 0]
        self.assertTrue(ahead)
        for b in ahead:
            self.assertTrue(b.shoot)
            self.assertIn("expectation", b.checklist.delta_kinds)
            self.assertTrue(b.checklist.expectation)
        self.assertFalse(P.DEFAULT.keep_setup)

    def test_by_the_worlds_delta_alone_the_same_scene_changes_nothing(self):
        growth = {i for g in self.steps if g.step == "hidden_growth" for i in g.event_ids}
        world = self.plan(P.Options(delta="world", keep_setup=False, stagnation=False, grammar="v1", questions="free"))
        mine = [b for b in world.beats if set(b.event_ids) & growth]
        self.assertTrue(mine)
        self.assertTrue(all("expectation" not in b.checklist.delta_kinds for b in mine))

    def test_a_scene_that_moved_nothing_is_not_progress_but_a_blow_is(self):
        names = {r[0]: r[1] for r in self.c.execute("SELECT id, name FROM people")}
        events = load_events(self.c)
        calm = [e for e in events.values() if e.type == "talk" and e.truth.get("tone") == "warm" and not P.real_progress(self.c, e, names)]
        duels = [e for e in events.values() if e.type == "duel"]
        self.assertTrue(calm)
        self.assertTrue(duels)
        self.assertTrue(all(P.real_progress(self.c, e, names) for e in duels))

    def test_the_voters_of_a_succession_are_its_bystanders(self):
        from narrative import payoff as PP
        votes = [p for p in PP.payoffs(self.c) if p["kind"] == "succession"]
        if not votes:
            self.skipTest("no succession in this fortnight")
        arc, steps = P.payoff_material(self.c, load_events(self.c), votes[0], P.DEFAULT)
        by = next(g for g in steps if g.step == "bystanders")
        self.assertTrue(by.present)
        old = P.payoff_material(self.c, load_events(self.c), votes[0], P.V1)[1]
        self.assertFalse(next(g for g in old if g.step == "bystanders").present)


class Questions(unittest.TestCase):
    def test_a_question_is_a_goal_a_choice_or_a_revelation(self):
        self.assertEqual(P._question_type("誰拿了錢袋？"), "revelation")
        self.assertEqual(P._question_type("阿俊被看輕了，能在眾人面前證明自己嗎？"), "goal")
        self.assertEqual(P._question_type("小瑞和阿寧會和好，還是徹底決裂？"), "choice")
        self.assertEqual(P._question_type("阿蘭要為了忠誠，付出安穩的代價嗎？"), "choice")
        self.assertEqual(P._question_type("然後呢"), "open")

    def test_a_question_to_predict_a_feeling_is_not_one_the_planner_poses(self):
        self.assertTrue(P._regret("阿蘭會後悔嗎？"))
        c = produced(17, 8)
        shown: set[int] = set()
        for day in range(8):
            plan = P.plan_day(c, day, shown)
            if plan is not None:
                self.assertFalse(P._regret(plan.core_question), plan.core_question)
                self.assertFalse(P._regret(plan.ending_question), plan.ending_question)
                self.assertIn(plan.question_type, ("goal", "choice", "revelation", "open"))
                shown |= {i for b in plan.beats for i in b.event_ids}

    def test_an_inner_conflict_asks_what_the_choice_costs(self):
        c = produced(17, 3)
        apply_event(c, EventSpec(timestamp=3 * 1440 + 600, type="lend", trigger_type="decision", importance=0.5,
                                 truth={"actor": "kai", "target": "ming", "dilemma": {"tension": 0.7, "serves": {"loyalty": 0.6}, "costs": {"security": 0.5}}},
                                 participants=[("kai", "actor"), ("ming", "target")]))
        arc, thread, kind, payoff, steps = P.choose_material(c, 3, set())
        plan = P.plan_episode(c, arc, thread, set(), 3, kind, payoff, steps)
        self.assertEqual(plan.question_type, "choice")
        self.assertIn("忠誠", plan.core_question)
        self.assertIn("安穩", plan.core_question)


class StoriesAndTexture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = produced(17, 10)
        cls.sit = analyse(cls.c)["situations"]

    def plans(self, options):
        shown: set[int] = set()
        out = []
        for day in range(10):
            plan = P.plan_day(self.c, day, shown, self.sit, (), options)
            if plan is not None:
                shown |= {i for b in plan.beats for i in b.event_ids}
                out.append(plan)
        return out

    def test_without_the_option_an_episode_is_one_story(self):
        self.assertTrue(all(b.story == "A" for p in self.plans(P.DEFAULT) for b in p.beats))

    def test_a_second_story_is_of_other_people_and_the_ordinary_moment_comes_before_the_peak(self):
        plans = self.plans(P.AB)
        events = load_events(self.c)
        saw_b = saw_t = False
        for plan in plans:
            mine = set(plan.people)
            a_ids = [i for b in plan.beats if b.story == "A" for i in b.event_ids]
            for b in plan.beats:
                if b.story == "B":
                    saw_b = True
                    self.assertFalse({p for i in b.event_ids for p in events[i].people[:2]} & mine)
                if b.story == "texture":
                    saw_t = True
                    self.assertTrue(b.shoot)
                    self.assertLess(max(b.event_ids), max(a_ids))
        self.assertTrue(saw_b or saw_t)

    def test_the_questions_and_the_ending_are_the_a_storys(self):
        for day in range(2, 10):          # the same day, with nothing shown yet: the B story and the ordinary moment add scenes, not questions
            a, b = P.plan_day(self.c, day, set(), self.sit, (), P.DEFAULT), P.plan_day(self.c, day, set(), self.sit, (), P.AB)
            if a is not None and b is not None:
                self.assertEqual((a.core_question, a.ending_question, a.kind), (b.core_question, b.ending_question, b.kind))


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


class ScriptSeason(unittest.TestCase):
    """The season ledgers (Options.script; narrative/lint.py is the ruler): today events, a hard event taken in, montage, questions not asked again."""

    DAYS = 10

    @classmethod
    def setUpClass(cls):
        from narrative import lint as LN
        cls.LN = LN
        cls.c = produced(17, cls.DAYS)
        cls.before = fingerprint(cls.c)
        cls.sit = analyse(cls.c)["situations"]
        cls.ledger = P.Ledger()
        cls.shown: set[int] = set()
        cls.plans: dict[int, ep.EpisodePlan] = {}
        cls.resolved: dict[int, dict] = {}
        recent: tuple = ()
        for day in range(cls.DAYS):
            plan = P.plan_day(cls.c, day, cls.shown, cls.sit, recent, P.SHOW, cls.ledger)
            if plan is None:
                continue
            cls.plans[day] = plan
            cls.shown |= {i for b in plan.beats for i in b.event_ids}
            recent = (frozenset(plan.people),) + recent[:1]
            cls.resolved[day] = LN.resolve(cls.c, plan)

    def test_it_only_reads(self):
        self.assertEqual(fingerprint(self.c), self.before)

    def test_the_option_is_off_unless_asked_and_then_a_plan_is_what_it_was(self):
        self.assertFalse(P.DEFAULT.script or P.AB.script or P.V1.script)
        self.assertTrue(P.SHOW.script and P.SHOW.ab_story)
        shown: set[int] = set()
        for day in range(self.DAYS):
            plan = P.plan_day(self.c, day, shown, self.sit, (), P.AB)
            if plan is not None:
                self.assertFalse(any(b.reason.startswith("montage") for b in plan.beats))
                shown |= {i for b in plan.beats for i in b.event_ids}

    def test_an_episode_is_of_its_own_day_and_an_older_event_is_only_a_recent_recap(self):
        events = load_events(self.c)
        for day, plan in self.plans.items():
            for b in plan.beats:
                for i in b.event_ids:
                    self.assertLessEqual(events[i].day, day)
                    self.assertGreaterEqual(events[i].day, day - P.RECAP_DAYS, (day, i))
            self.assertTrue(any(events[i].day == day for b in plan.beats for i in b.event_ids), day)

    def test_nothing_is_filmed_twice_in_a_season(self):
        seen: dict[int, int] = {}
        for day, plan in self.plans.items():
            for b in plan.beats:
                if b.derived:
                    continue
                for i in b.event_ids:
                    self.assertNotIn(i, seen, f"event {i} on day {day} and on day {seen.get(i)}")
                    seen[i] = day

    def test_a_day_with_a_hard_event_takes_one_in_as_the_a_storys(self):
        for day, plan in self.plans.items():
            hard = {h["id"] for h in self.LN.hard_events(self.c, day)}
            fresh = hard - {i for d, p in self.plans.items() if d < day for b in p.beats for i in b.event_ids}
            if fresh:
                on = {i for b in plan.beats if b.shoot for i in b.event_ids}
                self.assertTrue(fresh & on, f"day {day}: hard events {sorted(fresh)} and none of them is filmed")

    def test_the_same_two_people_doing_the_same_kind_of_back_and_forth_is_one_beat(self):
        events = load_events(self.c)
        for day, plan in self.plans.items():
            seen = set()
            for b in plan.beats:
                if b.derived or not b.shoot or events[b.event_ids[0]].type not in ("talk", "tell", "confront") or len(events[b.event_ids[0]].people) < 2:
                    continue
                e = events[b.event_ids[0]]
                kind = ("quarrel" if e.truth.get("tone") in ("cold", "hostile") else "chat") if e.type == "talk" else e.type
                key = (b.story, e.day, frozenset(e.people[:2]), kind)
                self.assertNotIn(key, seen, (day, key))
                seen.add(key)

    def test_a_montage_beat_says_so_and_holds_events_of_one_day_and_one_pair(self):
        events = load_events(self.c)
        folded = [b for p in self.plans.values() for b in p.beats if len(b.event_ids) > 1]
        for b in folded:
            self.assertTrue(b.reason.startswith("montage"), b.reason)
            self.assertEqual(len({events[i].day for i in b.event_ids}), 1)
            self.assertEqual(len({frozenset(events[i].people[:2]) for i in b.event_ids}), 1)

    def test_a_question_is_not_asked_again_within_a_week_and_an_ending_always_names_somebody_in_the_episode(self):
        plans = [self.plans[d] for d in sorted(self.plans)]
        for i, p in enumerate(plans):
            for q in plans[:i]:
                self.assertFalse(q.core_question == p.core_question and 0 < p.day - q.day < P.QUESTION_DAYS, (q.day, p.day, p.core_question))
            self.assertTrue(p.ending_question, p.day)
            self.assertNotIn(p.ending_question, [q.ending_question for q in plans[max(0, i - P.ENDING_EPISODES):i]], p.day)
            names = self.resolved[p.day]["people_names"]
            self.assertTrue(any(n in p.ending_question for n in names), (p.day, p.ending_question, names))

    def test_the_lint_finds_none_of_the_faults_the_season_option_is_for(self):
        prior = []
        bad = []
        names = sorted({n for e in self.resolved.values() for n in e["people_names"]})
        for day in sorted(self.plans):
            for i in self.LN.lint_episode(self.resolved[day], prior=prior, names=names, facts=self.LN.object_facts(self.c, day)):
                bad.append((day, i.code, i.kind, i.text))
            prior.append(self.resolved[day])
        self.assertEqual([b for b in bad if b[1] in ("L1", "L2", "L3", "L4", "L5", "L8")], [])

    def test_the_premise_of_who_took_a_thing_must_hold(self):
        facts = {"objects": {"戒指": {"owner": "小美", "other_takes": 0, "found_day": None, "retaken": False}}}
        self.assertTrue(P._false_premise("誰拿了戒指？", facts))
        self.assertFalse(P._false_premise("誰拿了鑰匙？", facts))
        facts["objects"]["戒指"]["other_takes"] = 1
        self.assertFalse(P._false_premise("誰拿了戒指？", facts, 3))
        facts["objects"]["戒指"]["found_day"] = 1
        self.assertTrue(P._false_premise("誰拿了戒指？", facts, 3))
        self.assertFalse(P._false_premise("誰拿了戒指？", facts, 1))        # found today: not yet answered when the day began

    def test_the_ledger_blocks_by_days_and_by_episodes(self):
        led = P.Ledger()
        led.cores.append((2, "誰拿了戒指？"))
        self.assertTrue(led.blocked_core("誰拿了戒指？", 8))
        self.assertFalse(led.blocked_core("誰拿了戒指？", 9))
        self.assertFalse(led.blocked_core("別的問題", 4))
        for d, q in enumerate(("a", "b", "c", "d")):
            led.endings.append((d, q))
        self.assertTrue(led.blocked_ending("d") and led.blocked_ending("b"))
        self.assertFalse(led.blocked_ending("a"))

    def test_a_bare_pronoun_in_an_ending_is_given_the_name_it_is_about(self):
        class A:       # an arc stub: its peak is a person act
            peak = type("E", (), {"truth": {"actor": "ming"}, "people": ("ming",)})()
        q = P._ending(["他的實力什麼時候會被看見？"], {"ming": "阿明"}, {"ming"}, "核心", None, None, 0, A, [])
        self.assertEqual(q, "阿明的實力什麼時候會被看見？")

    def test_a_cold_open_comes_from_the_character_card_or_is_not_written(self):
        for plan in self.plans.values():
            line = P.cold_open(self.c, plan)
            self.assertIsInstance(line, str)
            if line:
                self.assertIn("想要「", line)
        plan = next(iter(self.plans.values()))
        self.assertEqual(P.cold_open(self.c, plan, modern=("",)), "")        # every sentence of a card that has a word of our time is left out


class QuietDay(unittest.TestCase):
    def test_a_world_where_nothing_has_happened_has_no_episode(self):
        c = connect()
        init_db(c, 5)
        build_world(c, 5, "jianghu_story_v1")
        self.assertIsNone(P.plan_day(c, 0, set()))


if __name__ == "__main__":
    unittest.main()
