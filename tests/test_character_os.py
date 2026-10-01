"""Character OS convergence: goals that stick and evolve, choices made against oneself, a life at a glance, and the
same people in another world.

- A wish to leave a job is pursued in bouts, never on consecutive days; an offer turns it into weighing the offer,
  a refusal into staying on; a work goal that just ended gives a week's peace. Every turn is an event with a cause.
- An act that serves one value its actor holds dear and betrays another is recorded (truth["dilemma"]), computed
  from their own profile; the director counts it (score part "inner").
- The overview is a read model: it changes nothing and its arc covers the whole history.
- The town's people cast into the jianghu are the same people: identical profiles but for their casting, and the
  world, the director and the runtime work with them.
"""
from __future__ import annotations

import json
import unittest

from agent.volition import VolitionDecider
from world.db import connect, init_db
from world.seed import build_world
from world.simulation import Simulation
from world.snapshot import snapshot_hash


def _world(recipe: str, seed: int, days: int):
    c = connect()
    init_db(c, seed)
    build_world(c, seed, recipe)
    d = VolitionDecider(seed)
    Simulation(c, d, d, set(), feed="synthetic_v1" if recipe.startswith("town_life") else None).run(days)
    return c


class StickyGoals(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = _world("town_life_v1", 55, 24)
        cls.rows = cls.c.execute("SELECT event_id, timestamp, type, truth FROM events ORDER BY event_id").fetchall()

    def test_searching_comes_in_bouts(self):
        last: dict[str, int] = {}
        searches = 0
        for _, ts, etype, truth in self.rows:
            if etype == "job_search":
                who = json.loads(truth)["actor"]
                if who in last:
                    self.assertGreaterEqual(ts // 1440 - last[who], 2, who)
                last[who] = ts // 1440
                searches += 1
        self.assertGreater(searches, 0)

    def test_only_someone_who_wants_to_leave_searches(self):
        for eid, ts, etype, truth in self.rows:
            if etype != "job_search":
                continue
            who = json.loads(truth)["actor"]
            formed = self.c.execute("SELECT 1 FROM events WHERE event_id < ? AND type = 'goal_change' AND "
                                    "json_extract(truth, '$.actor') = ? AND json_extract(truth, '$.kind') = 'leave_job'",
                                    (eid, who)).fetchone()
            self.assertIsNotNone(formed, (eid, who))

    def test_offers_and_refusals_turn_the_goal(self):
        turns = {(json.loads(t)["kind"], json.loads(t)["to"]) for _, _, e, t in self.rows if e == "goal_change"}
        offers = [r for r in self.rows if r[2] == "job_offer"]
        if offers:
            self.assertTrue({("weigh_offer", "transformed"), ("weigh_offer", "formed")} & turns)  # an offer is weighed
            for eid, ts, _, truth in offers:
                who = json.loads(truth)["actor"]
                g = self.c.execute("SELECT json_extract(truth, '$.cause_event') FROM events WHERE type = 'goal_change' AND "
                                   "json_extract(truth, '$.kind') = 'weigh_offer' AND json_extract(truth, '$.actor') = ? "
                                   "AND event_id > ? ORDER BY event_id LIMIT 1", (who, eid)).fetchone()
                self.assertEqual(g[0], eid)  # weighing it was caused by the offer itself
        for eid, ts, _, truth in [r for r in self.rows if r[2] == "decline_offer"]:
            who = json.loads(truth)["actor"]
            g = self.c.execute("SELECT 1 FROM events WHERE type = 'goal_change' AND json_extract(truth, '$.kind') = 'stay_on' "
                               "AND json_extract(truth, '$.actor') = ? AND json_extract(truth, '$.cause_event') = ?", (who, eid)).fetchone()
            self.assertIsNotNone(g)

    def test_a_week_of_peace_after_a_work_goal_ends(self):
        ended: dict[str, int] = {}
        for _, ts, etype, truth in self.rows:
            if etype != "goal_change":
                continue
            t = json.loads(truth)
            if t["kind"] in ("leave_job", "weigh_offer", "stay_on", "earn_recognition") and t["to"] in ("completed", "abandoned"):
                ended[t["actor"]] = ts // 1440
            if t["kind"] == "leave_job" and t["to"] == "formed" and t["actor"] in ended:
                self.assertGreaterEqual(ts // 1440 - ended[t["actor"]], 7, t["actor"])


class InnerConflict(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = _world("town_life_v1", 55, 10)

    def test_dilemmas_are_recorded_and_come_from_the_actor_s_values(self):
        from world.values import RECORD, dilemma
        rows = self.c.execute("SELECT type, truth FROM events WHERE json_extract(truth, '$.dilemma') IS NOT NULL").fetchall()
        self.assertTrue(rows)
        for etype, truth in rows:
            d = json.loads(truth)["dilemma"]
            self.assertGreaterEqual(d["tension"], RECORD)
            self.assertTrue(d["serves"] and d["costs"])
        from world.profiles import profile
        held = set(profile(self.c, json.loads(rows[0][1])["actor"]).values)
        self.assertLessEqual(set(json.loads(rows[0][1])["dilemma"]["costs"]), held)

    def test_the_director_counts_it(self):
        from narrative.director import WEIGHTS, rank_threads
        self.assertIn("inner", WEIGHTS)
        ranked = rank_threads(self.c, 9)
        self.assertTrue(ranked)
        self.assertIn("inner", ranked[0][0].parts)


class Overview(unittest.TestCase):
    def test_a_life_at_a_glance_changes_nothing(self):
        from narrative.observatory import character_overview
        c = _world("town_life_v1", 3, 6)
        before = snapshot_hash(c)
        o = character_overview(c, "ming")
        self.assertEqual(snapshot_hash(c), before)
        self.assertTrue(o["cares"] and o["fears"] and o["arc"])
        self.assertEqual(o["arc"][0]["from_day"], 0)
        self.assertEqual(o["arc_text"], " → ".join(s["word"] for s in o["arc"]))


class CrossDomain(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.town = _world("town_life_v1", 3, 6)
        cls.sect = _world("town_in_jianghu_v1", 3, 6)

    def test_the_same_people_but_for_their_casting(self):
        from contracts.base import to_dict
        from world.profiles import profile
        for (pid,) in self.town.execute("SELECT person_id FROM character_profiles ORDER BY person_id").fetchall():
            a, b = to_dict(profile(self.town, pid)), to_dict(profile(self.sect, pid))
            for k in ("occupation", "season_goal"):
                a.pop(k), b.pop(k)
            self.assertEqual(a, b, pid)
        self.assertEqual(profile(self.sect, "ming").occupation.duty, "train")

    def test_their_lives_follow_the_world(self):
        kinds = {r[0] for r in self.sect.execute("SELECT DISTINCT type FROM events")}
        self.assertIn("train", kinds)
        self.assertNotIn("train", {r[0] for r in self.town.execute("SELECT DISTINCT type FROM events")})
        from world.domains.work import words
        self.assertEqual(words(self.sect, "ming")["quit"], "離開師門")
        self.assertEqual(words(self.town, "ming")["quit"], "辭職")

    def test_the_director_and_the_runtime_still_work(self):
        from narrative.director import rank_threads
        from runtime.world_runtime import WorldRuntime
        self.assertTrue(rank_threads(self.sect, 5))
        rt = WorldRuntime(self.sect)
        rt.advance()
        for k, rows in rt.invariants().items():
            self.assertEqual(rows, [], k)

    def test_personality_shows_in_both_worlds(self):
        """Measured by the persona probe (exact probabilities in standard circumstances), not by counting what six
        days happened to bring: that count was noise (someone is caught in the wrong twice a month)."""
        from cross_domain import spearman
        from persona_probe import PROBES, probe
        from world.db import connect, init_db
        from world.seed import build_world
        worlds = {}
        for recipe in ("town_life_v1", "town_in_jianghu_v1"):
            c = connect()
            init_db(c, 3)
            build_world(c, 3, recipe)
            worlds[recipe] = probe(c, 3)
        a, b = worlds["town_life_v1"], worlds["town_in_jianghu_v1"]
        people = sorted(a)
        for k in PROBES:
            self.assertGreaterEqual(spearman([a[p][k] for p in people], [b[p][k] for p in people]), 0.7, k)


if __name__ == "__main__":
    unittest.main()
