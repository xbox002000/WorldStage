"""The second recipe: jianghu runs on the same core. New primitives, new content, the same threads, director and plans."""
from __future__ import annotations

import json
import unittest

from agent.volition import VolitionDecider
from tests.test_world_c import put
from world.db import connect, init_db
from world.events import apply_event
from world.intent import Intent, validate
from world.jianghu import rep, skill
from world.recipes import compiled
from world.rules import resolve
from world.seed import build_world
from world.simulation import Simulation
from world.snapshot import snapshot_hash
from world.state import WorldError, audit


def jianghu(seed: int = 1):
    c = connect()
    init_db(c, seed)
    build_world(c, seed, "jianghu_v1")
    return c


def act(c, it: Intent, now: int) -> dict:
    validate(c, it)
    eid = apply_event(c, resolve(c, it, now, "decision"))
    return json.loads(c.execute("SELECT truth FROM events WHERE event_id = ?", (eid,)).fetchone()[0])


class RecipeTests(unittest.TestCase):
    def test_the_recipe_compiles_and_the_world_is_jianghu(self):
        order = compiled("jianghu_v1").order
        for p in ("martial_arts", "reputation", "duel", "sect_factions"):
            self.assertIn(p, order)
        self.assertNotIn("money.rent", order)
        c = jianghu()
        self.assertEqual(c.execute("SELECT value FROM meta WHERE key = 'recipe'").fetchone()[0], "jianghu_v1")
        self.assertEqual(c.execute("SELECT owner_person_id, rightful_owner_id FROM objects WHERE id = 'manual'").fetchone()[:],
                         ("lu", "lin"))  # the old secret: Lu has the manual

    def test_town_worlds_cannot_duel_or_train(self):
        from tests.test_world_c import fresh
        c = fresh()
        put(c, 10, ming="office", kai="office")
        with self.assertRaises(WorldError):
            validate(c, Intent("ming", "challenge", "kai"))
        with self.assertRaises(WorldError):
            validate(c, Intent("ming", "train"))


class PrimitiveTests(unittest.TestCase):
    def test_training_is_slow_and_a_manual_doubles_it(self):
        c = jianghu()
        before_lu, before_su = skill(c, "lu"), skill(c, "su")
        act(c, Intent("lu", "train"), 500)  # Lu has the manual
        act(c, Intent("su", "train"), 501)
        self.assertGreater(skill(c, "lu") - before_lu, 0)
        self.assertAlmostEqual((skill(c, "lu") - before_lu) / (1 - before_lu), 2 * (skill(c, "su") - before_su) / (1 - before_su), 5)

    def test_a_duel_is_decided_by_the_world_and_can_settle_who_holds_a_thing(self):
        c = jianghu()
        apply_event(c, __import__("world.events", fromlist=["EventSpec"]).EventSpec(
            timestamp=10, type="setup", trigger_type="rule",
            changes=[__import__("world.events", fromlist=["Change"]).Change("person", p, "location_id", value="inn")
                     for p in ("lin", "lu")]))
        t = act(c, Intent("lin", "challenge", "lu"), 600)
        self.assertIn(t["winner"], ("lin", "lu"))
        if t["winner"] == "lin":  # Lin is the manual's rightful owner and Lu holds it: settled by the sword
            self.assertEqual(t["returned"], "manual")
            self.assertEqual(c.execute("SELECT owner_person_id FROM objects WHERE id = 'manual'").fetchone()[0], "lin")
        with self.assertRaises(WorldError):  # they just fought
            validate(c, Intent("lu", "challenge", "lin"))
        self.assertEqual(audit(c), [])

    def test_nobody_duels_someone_who_cannot_fight(self):
        c = jianghu()
        with self.assertRaises(WorldError):
            validate(c, Intent("hua", "challenge", "zhou"))  # both at the inn, neither a fighter


class SharedCoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = jianghu(1)
        d = VolitionDecider(1)
        Simulation(cls.c, d, d, set()).run(20)

    def test_a_month_of_jianghu_stays_consistent_and_replays(self):
        self.assertEqual(audit(self.c), [])
        again = jianghu(1)
        d = VolitionDecider(1)
        Simulation(again, d, d, set()).run(20)
        self.assertEqual(snapshot_hash(again), snapshot_hash(self.c))

    def test_duels_leave_reputations_and_goals_behind(self):
        self.assertTrue(self.c.execute("SELECT COUNT(*) FROM events WHERE type = 'duel'").fetchone()[0])
        kinds = {json.loads(t)["kind"] for (t,) in self.c.execute("SELECT truth FROM events WHERE type = 'goal_change'")}
        self.assertTrue(kinds & {"surpass", "revenge"})
        self.assertNotEqual(rep(self.c, "lin"), 0.8)

    def test_the_director_sees_what_a_thread_did_to_people(self):
        from narrative.director import score_thread
        from narrative.threads import derive_threads
        scores = [score_thread(self.c, t, set()) for t in derive_threads(self.c)]
        self.assertTrue(all("change" in s.parts for s in scores))
        self.assertTrue(any(s.parts["change"] > 0 for s in scores))  # duels form goals: surpass, revenge

    def test_threads_director_spatial_plan_and_packet_run_unchanged(self):
        from narrative.compiler import compile_packet
        from narrative.direction import plan_direction
        from narrative.director import select_thread
        from narrative.scene_spec import build_scene_specs
        from narrative.spatial import compile_spatial
        shown, planned = set(), 0
        for day in range(20):
            cand, thread, _ = select_thread(self.c, day, shown)
            if cand is None:
                continue
            spec = build_scene_specs(self.c, [cand], [f"d{day}"])[0]
            plan = plan_direction(self.c, spec, thread, shown)
            packet = compile_packet(spec, direction=plan)
            staged = compile_spatial(spec)
            self.assertEqual(len(packet.shots), len(plan.shots))
            self.assertEqual(len(staged.beats), len(spec.beats))
            self.assertTrue(all(b.location in ("qingyun", "manor", "inn", "market", "road") for b in staged.beats))
            shown |= set(cand.arc.ids)
            planned += 1
        self.assertGreater(planned, 5)


if __name__ == "__main__":
    unittest.main()
