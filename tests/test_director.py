"""Producer 2: it supplies what a story lacks, keeps still when it should, and decides no outcome."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent.volition import VolitionDecider
from producer import director as D
from producer.intervention import Ledger
from world import interventions
from world.db import connect, init_db
from world.domains.roles import role_of
from world.seed import build_world
from world.simulation import Simulation
from tests.test_opportunity import duel


def story(seed=3):
    conn = connect()
    init_db(conn, seed)
    build_world(conn, seed, "jianghu_story_v1")
    return conn


def play(strategy="greedy", days=8, seed=3, ledger=None):
    c = story(seed)
    dr = D.Director(strategy, seed, ledger)
    d = VolitionDecider(seed)
    Simulation(c, d, d, set(), feed="synthetic_v1", producer=dr).run(days)
    return c, dr


class Acting(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c, cls.dr = play("greedy", 10)

    def test_it_acts_through_the_ledger_and_only_in_the_closed_vocabulary(self):
        self.assertTrue(self.dr.ledger.entries)
        for e in self.dr.ledger.entries:
            self.assertIn(e["type"], interventions.PARAMS)
            self.assertTrue(set(e["params"]) <= interventions.PARAMS[e["type"]])
        self.assertTrue(all(e["source"] == "director" for e in self.dr.ledger.entries))

    def test_the_world_never_hears_why_nor_which_story(self):
        everything = " ".join(r[0] for r in self.c.execute("SELECT truth FROM events"))
        for e in self.dr.ledger.entries:
            self.assertNotIn(e["arc_id"], everything)       # the opportunity's id
            if e["purpose"]:
                self.assertNotIn(e["purpose"], everything)
            self.assertNotIn(e["season_id"] + '"', everything)

    def test_every_day_is_a_decision_including_the_ones_to_do_nothing(self):
        days = [d["day"] for d in self.dr.ledger.decisions]
        self.assertEqual(days, list(range(10)))
        self.assertIn("silence", {d["action"] for d in self.dr.ledger.decisions})
        self.assertIn("intervene", {d["action"] for d in self.dr.ledger.decisions})
        for d in self.dr.ledger.decisions:
            self.assertTrue(d["reason"])

    def test_the_hero_is_never_cast_and_never_the_one_cast_towards_an_actor(self):
        cast = [e for e in self.dr.ledger.entries if e["admitted"] and e["type"] == "cast_role"]
        for e in cast:
            self.assertNotEqual(e["target"], e["params"]["toward"])
        # nobody who is a hero (the one a part is played towards) holds a part of their own
        for pid in [r[0] for r in self.c.execute("SELECT person_id FROM character_profiles")]:
            r = role_of(self.c, pid, 5)
            if r:
                self.assertIsNone(role_of(self.c, r[1], 5))

    def test_the_weeks_budget_holds(self):
        led = self.dr.ledger
        for day in range(10):
            self.assertLessEqual(led.spent(day), led.week_budget)

    def test_a_story_it_acted_on_is_one_the_world_was_making(self):
        for d in self.dr.ledger.decisions:
            if d["action"] == "intervene":
                self.assertTrue(O_SURE_LOSS <= d["p_success"] <= O_SURE_WIN or d["kind"] != "reversal")
                self.assertTrue(d["admitted"])


from narrative.opportunity import SURE_LOSS as O_SURE_LOSS, SURE_WIN as O_SURE_WIN  # noqa: E402


class Stillness(unittest.TestCase):
    def test_after_a_peak_it_keeps_still_and_says_so(self):
        c = story()
        for day in (2, 2, 3):
            duel(c, day, "hao", "kai", slap=True, minute=900 + 7 * day)
        dr = D.Director("greedy", 3)
        dr.dawn(c, 4, 4 * 1440 + 5)
        self.assertEqual(dr.ledger.entries, [])
        self.assertEqual(dr.ledger.decisions[0]["action"], "silence")
        self.assertIn("a great deal", dr.ledger.decisions[0]["reason"])

    def test_the_aggressive_one_does_not_keep_still(self):
        c = story()
        for day in (2, 2, 3):
            duel(c, day, "hao", "kai", slap=True, minute=900 + 7 * day)
        dr = D.Director("aggressive", 3)
        dr.dawn(c, 4, 4 * 1440 + 5)
        self.assertNotIn("a great deal", dr.ledger.decisions[0]["reason"])

    def test_nobody_is_aimed_at_who_has_just_had_their_moment(self):
        c = story()
        dr = D.Director("greedy", 3)
        dr.dawn(c, 0, 5)
        first = [d for d in dr.ledger.decisions if d["action"] == "intervene"]
        self.assertTrue(first)
        hero = first[0]["protagonist"]
        t = dr.threads.by_id[first[0]["opportunity"]]
        t.status, t.ended = "completed", 0
        self.assertTrue(dr.threads.resting(hero, 2))
        self.assertFalse(dr.threads.resting(hero, 6))
    def test_a_story_taken_up_again_does_not_count_what_came_before(self):
        from contracts.opportunity import Opportunity
        from producer.arcs import Threads
        op = Opportunity("op-x", "reversal", "hao", ["kai"], 0, 0.3, 0.9, 0.5)
        t = Threads()
        t.take_up(op, 0)
        t.by_id["op-x"].status, t.by_id["op-x"].ended = "completed", 4
        t.take_up(op, 12)
        th = t.by_id["op-x"]
        self.assertEqual((th.status, th.opened, th.ended), ("active", 12, -1))


class Strategies(unittest.TestCase):
    def test_the_same_seed_makes_the_same_decisions(self):
        a, b = play("matched", 6)[1], play("matched", 6)[1]
        self.assertEqual(a.ledger.decisions, b.ledger.decisions)

    def test_the_controls_use_the_same_shaper_and_budget_but_choose_differently(self):
        g, m = play("greedy", 8)[1], play("matched", 8)[1]
        self.assertNotEqual([d.get("opportunity") for d in g.ledger.decisions], [d.get("opportunity") for d in m.ledger.decisions])
        for dr in (g, m):
            self.assertLessEqual(max(dr.ledger.spent(d) for d in range(8)), dr.ledger.week_budget)

    def test_unlimited_has_no_ceiling_and_the_rest_do(self):
        self.assertGreater(D.Director("unlimited", 3).ledger.week_budget, 100)
        self.assertEqual(D.Director("greedy", 3).ledger.week_budget, 6)

    def test_an_unknown_strategy_is_refused(self):
        with self.assertRaises(ValueError):
            D.Director("clairvoyant", 3)

    def test_the_decisions_are_kept_in_a_file_of_the_producers_own(self):
        with tempfile.TemporaryDirectory() as d:
            led = Ledger(Path(d) / "ledger.jsonl")
            c = story()
            dr = D.Director("greedy", 3, led)
            dr.dawn(c, 0, 5)
            lines = (Path(d) / "ledger.decisions.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0])["day"], 0)


class NoProducer(unittest.TestCase):
    def test_a_world_with_no_producer_is_what_it_was(self):
        def run(producer):
            c = story()
            d = VolitionDecider(3)
            Simulation(c, d, d, set(), feed="synthetic_v1", producer=producer).run(4)
            return [(r[0], r[1]) for r in c.execute("SELECT type, timestamp FROM events ORDER BY event_id")]

        class Nothing:
            def dawn(self, conn, day, now):
                pass
        self.assertEqual(run(None), run(Nothing()))


if __name__ == "__main__":
    unittest.main()
