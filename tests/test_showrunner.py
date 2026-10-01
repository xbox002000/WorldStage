"""The showrunner plans seasons and arranges opportunities; it names no outcome, and the world never hears why."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent.volition import VolitionDecider
from contracts.intervention import InterventionProposal
from producer import showrunner as S
from producer.intervention import COSTS, Ledger
from world import interventions
from world.db import connect, init_db
from world.seed import build_world
from world.simulation import Simulation


def saga(seed=3):
    conn = connect()
    init_db(conn, seed)
    build_world(conn, seed, "jianghu_saga_v1")
    return conn


class Planning(unittest.TestCase):
    def setUp(self):
        self.c = saga()

    def test_a_season_has_at_most_two_arcs_each_with_its_own_hero_and_closed_beats(self):
        sr = S.Showrunner("full", 3)
        sr.dawn(self.c, 0, 5)
        plan = sr.plans[0]
        self.assertTrue(1 <= len(plan.arcs) <= S.PROTAGONISTS)
        heroes = [a.protagonist for a in plan.arcs]
        self.assertEqual(len(set(heroes)), len(heroes))
        for arc in plan.arcs:
            self.assertIn(arc.kind, ("underdog", "succession", "romance"))
            for b in arc.beats:
                self.assertIn(b.type, interventions.PARAMS)
                self.assertTrue(set(b.params) <= interventions.PARAMS[b.type])
            roles = [b for b in arc.beats if b.type == "cast_role"]
            self.assertTrue(all(b.target != arc.protagonist for b in roles))  # the hero is never the actor

    def test_the_next_season_belongs_to_somebody_else(self):
        sr = S.Showrunner("full", 3)
        sr.dawn(self.c, 0, 5)
        sr.dawn(self.c, S.SEASON_DAYS, S.SEASON_DAYS * 1440 + 5)
        first, second = ({a.protagonist for a in p.arcs} for p in sr.plans)
        self.assertEqual(first & second, set())

    def test_the_same_seed_plans_the_same_season(self):
        a, b = S.Showrunner("full", 3), S.Showrunner("full", 3)
        a.dawn(saga(), 0, 5)
        b.dawn(saga(), 0, 5)
        self.assertEqual(a.plans[0].hash(), b.plans[0].hash())

    def test_the_plan_is_kept_apart_and_says_why(self):
        with tempfile.TemporaryDirectory() as d:
            sr = S.Showrunner("full", 3, plan_dir=Path(d))
            sr.dawn(self.c, 0, 5)
            plan = json.loads((Path(d) / "S1.json").read_text(encoding="utf-8"))
        self.assertTrue(plan["arcs"][0]["reason"])
        self.assertTrue(plan["arcs"][0]["beats"][0]["purpose"])


class Acting(unittest.TestCase):
    def run_season(self, strategy, days=8, seed=3):
        c = saga(seed)
        sr = S.Showrunner(strategy, seed)
        d = VolitionDecider(seed)
        Simulation(c, d, d, set(), feed="synthetic_v1", producer=sr).run(days)
        return c, sr

    def test_every_beat_goes_through_the_ledger_and_the_purpose_stays_there(self):
        c, sr = self.run_season("full")
        self.assertTrue(sr.ledger.entries)
        purposes = {e["purpose"] for e in sr.ledger.entries if e["purpose"]}
        self.assertTrue(purposes)
        everything = " ".join(r[0] for r in c.execute("SELECT truth FROM events"))
        for p in purposes:
            self.assertNotIn(p, everything)  # never in the world's history
        self.assertNotIn("S1-A", everything)
        heard = interventions.made(c)
        self.assertEqual(len(heard), sum(1 for e in sr.ledger.entries if e["admitted"]))
        self.assertTrue(all(set(h) & {"purpose", "arc_id", "season_id"} == set() for h in heard))

    def test_what_is_proposed_is_only_what_costs_and_what_the_world_allows(self):
        _, sr = self.run_season("full")
        for e in sr.ledger.entries:
            self.assertGreaterEqual(e["budget_cost"], COSTS[e["type"]])
            if not e["admitted"]:
                self.assertTrue(e["reason"])  # refused for a reason: a budget, a thing already gone, a part already played

    def test_a_strategy_does_only_its_own_kind_of_thing(self):
        for strategy, kinds in (("stage", {"announce_gathering", "open_seat"}), ("cast", {"cast_role"}), ("parcel", {"deliver_parcel"})):
            _, sr = self.run_season(strategy, days=6)
            self.assertTrue({e["type"] for e in sr.ledger.entries} <= kinds, (strategy, {e["type"] for e in sr.ledger.entries}))

    def test_the_control_does_the_same_things_on_the_same_days_but_aimed_at_nobody_in_particular(self):
        _, full = self.run_season("full")
        _, rnd = self.run_season("random")
        shape = lambda sr: [(e["type"], e["day"], e["budget_cost"]) for e in sr.ledger.entries]  # noqa: E731
        self.assertEqual(shape(full), shape(rnd))  # same kinds, same days, same cost
        aimed = lambda sr: [(e["type"], e["target"]) for e in sr.ledger.entries if e["type"] in ("cast_role", "deliver_parcel")]  # noqa: E731
        self.assertNotEqual(aimed(full), aimed(rnd))  # but not at the same people

    def test_nothing_is_arranged_for_a_hero_who_has_had_their_moment(self):
        sr = S.Showrunner("full", 3)
        c = saga()
        sr.dawn(c, 0, 5)
        arc = sr.plans[0].arcs[0]
        sr.closed.add(arc.arc_id)
        before = len(sr.ledger.entries)
        for day in range(1, 6):
            sr.dawn(c, day, day * 1440 + 5)
        left = {e["arc_id"] for e in sr.ledger.entries[before:]}
        self.assertNotIn(arc.arc_id, left)

    def test_a_world_with_no_producer_is_what_it_was(self):
        c = saga(3)
        d = VolitionDecider(3)
        Simulation(c, d, d, set(), feed="synthetic_v1").run(3)
        self.assertEqual(c.execute("SELECT COUNT(*) FROM events WHERE type = 'intervention'").fetchone()[0], 0)

    def test_the_world_decides_what_comes_of_it(self):
        """The same season on two seeds ends differently: nothing in what the producer does fixes an outcome."""
        a, _ = self.run_season("full", days=12, seed=3)
        b, _ = self.run_season("full", days=12, seed=55)
        outcome = lambda c: [(r[0], json.loads(r[1]).get("winner")) for r in c.execute("SELECT type, truth FROM events WHERE type IN ('duel', 'succession')")]  # noqa: E731
        self.assertNotEqual(outcome(a), outcome(b))


if __name__ == "__main__":
    unittest.main()
