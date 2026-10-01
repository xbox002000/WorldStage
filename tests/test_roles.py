"""Roles: a person cast for a season leans their choices without rewriting them, and the hero is never cast."""
from __future__ import annotations

import json
import unittest

from contracts.intervention import InterventionProposal
from producer.intervention import Ledger
from world import interventions
from world.db import connect, init_db
from world.domains import active
from world.domains import roles as R
from world.events import Change, EventSpec, apply_event
from world.intent import Intent
from world.seed import build_world


def saga(seed=3, recipe="jianghu_saga_v1"):
    conn = connect()
    init_db(conn, seed)
    build_world(conn, seed, recipe)
    return conn


def pack(conn):
    return next(d for d in active(conn) if d.id == "roles")


def cast(conn, who="kai", toward="jun", role="doubter", until="9", id_="r1", at=100):
    wi = InterventionProposal(id_, "S", "A", "cast_role", who, {"role": role, "toward": toward, "until": until}, 0, 1,
                              "讓他看輕主角").world_view()
    return interventions.apply(conn, wi, at)


def problems(conn, who="kai", toward="jun", role="doubter", until="9"):
    wi = InterventionProposal("rx", "S", "A", "cast_role", who, {"role": role, "toward": toward, "until": until}, 0, 1, "x").world_view()
    return "; ".join(interventions.problems(conn, wi))


class Casting(unittest.TestCase):
    def setUp(self):
        self.c = saga()

    def test_casting_is_world_truth_nobody_is_told_and_the_purpose_is_not_in_it(self):
        eid = cast(self.c)
        truth = json.loads(self.c.execute("SELECT truth FROM events WHERE event_id = ?", (eid,)).fetchone()[0])
        self.assertEqual((truth["kind"], truth["target"], truth["params"]["role"]), ("cast_role", "kai", "doubter"))
        self.assertNotIn("看輕", json.dumps(truth, ensure_ascii=False))
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM memories WHERE event_id = ?", (eid,)).fetchone()[0], 0)  # nobody is told
        self.assertEqual(R.role_of(self.c, "kai", 0), ("doubter", "jun"))
        self.assertEqual(R.role_of(self.c, "jun", 0), None)  # the hero is not an actor

    def test_what_may_not_be_cast_is_refused(self):
        self.assertIn("no role", problems(self.c, role="villain"))
        self.assertIn("played by one person towards another", problems(self.c, who="kai", toward="kai"))
        self.assertIn("not a day ahead", problems(self.c, until="0"))
        cast(self.c)
        self.assertIn("already has a part", problems(self.c, who="kai", toward="hao"))
        self.assertIn("an actor themselves", problems(self.c, who="tao", toward="kai"))  # the hero of a part is never an actor
        self.assertIn("somebody's hero", problems(self.c, who="jun", toward="hao"))      # and nobody who has been made a hero is cast

    def test_a_world_without_actors_refuses(self):
        c = saga(3, "town_in_jianghu_v1")
        self.assertIn("no actors", problems(c))

    def test_a_part_ends_and_the_person_goes_back_to_being_themselves(self):
        cast(self.c, until="2")
        self.assertIsNotNone(R.role_of(self.c, "kai", 2))
        self.assertIsNone(R.role_of(self.c, "kai", 3))
        for spec in pack(self.c).nightly(self.c, 2, 2 * 1440 + 1400):
            self.fail("not over yet")
        specs = pack(self.c).nightly(self.c, 3, 3 * 1440 + 1400)
        self.assertEqual([s.type for s in specs], ["role_ended"])
        apply_event(self.c, EventSpec(timestamp=3 * 1440 + 1400, type=specs[0].type, trigger_type="rule", truth=specs[0].truth, changes=specs[0].changes))
        self.assertEqual(self.c.execute("SELECT value FROM world_vars WHERE key = 'role.kai'").fetchone()[0], 0.0)


class Leaning(unittest.TestCase):
    def setUp(self):
        self.c = saga()
        cast(self.c, "kai", "jun", "doubter", "9")

    def scored(self, actor="kai", day=1):
        opts = [(1.0, Intent(actor, "talk", "jun", "cold")), (1.0, Intent(actor, "talk", "jun", "warm")),
                (1.0, Intent(actor, "challenge", "jun")), (1.0, Intent(actor, "talk", "hao", "cold")), (1.0, None)]
        return pack(self.c).shape(self.c, actor, day * 1440 + 600, opts)

    def place(self, where, *people):
        ch = [Change("person", p, "location_id", value=where) for p in people
              if self.c.execute("SELECT location_id FROM people WHERE id = ?", (p,)).fetchone()[0] != where]
        if ch:
            apply_event(self.c, EventSpec(timestamp=100, type="setup", trigger_type="rule", location_id=where, changes=ch))

    def test_a_doubter_leans_only_towards_the_hero_and_only_in_front_of_others(self):
        others = [r[0] for r in self.c.execute("SELECT id FROM people WHERE id NOT IN ('kai', 'jun')")]
        self.place("inn", *others)  # everybody else is somewhere else
        self.place("qingyun", "kai", "jun")  # alone with the hero: no audience for a sneer
        alone = {(it.action, it.tone, it.target): s for s, it in self.scored() if it}
        self.assertEqual(alone[("talk", "cold", "jun")], 1.0)
        self.place("qingyun", "kai", "jun", "hao", "tao")
        crowd = {(it.action, it.tone, it.target): s for s, it in self.scored() if it}
        self.assertGreater(crowd[("talk", "cold", "jun")], 1.0)
        self.assertGreater(crowd[("challenge", None, "jun")], 1.0)
        self.assertLess(crowd[("talk", "warm", "jun")], 1.0)
        self.assertEqual(crowd[("talk", "cold", "hao")], 1.0)  # not towards anybody else

    def test_a_role_only_moves_the_scores_of_options_the_person_already_has(self):
        self.place("qingyun", "kai", "jun", "hao", "tao")
        before = [it for _s, it in self.scored()]
        self.assertEqual(len(before), 5)
        self.assertIn(None, before)  # nothing added, nothing removed, doing nothing is still there

    def test_nobody_else_is_touched_and_a_part_that_is_over_is_not_played(self):
        self.place("qingyun", "kai", "jun", "hao", "tao")
        self.assertEqual([s for s, it in self.scored("hao") if it], [1.0] * 4)  # hao has no part
        self.assertEqual([s for s, it in self.scored("kai", day=10) if it], [1.0] * 4)  # kai's is over by day 10

    def test_the_push_is_bounded_and_the_persons_own_nature_pushes_back(self):
        self.place("qingyun", "kai", "jun", "hao", "tao")
        for name in R.ROLES:
            for key, delta in R.ROLES[name].leans.items():
                self.assertLessEqual(abs(delta), R.MAX_PUSH)
        pol = R.ROLES["doubter"]
        kind, harsh = "tao", "hao"   # tao is not generous; hao is both generous and warm
        self.assertGreater(R.resistance(self.c, kind, pol), R.resistance(self.c, harsh, pol))
        self.assertGreaterEqual(R.resistance(self.c, harsh, pol), R.FLOOR)
        it = Intent("x", "talk", "jun", "cold")
        self.assertGreater(R.push(self.c, kind, "jun", it, "doubter", 3), R.push(self.c, harsh, "jun", it, "doubter", 3))
        self.assertGreater(R.push(self.c, harsh, "jun", it, "doubter", 3), 0)  # a nature slows it, it does not stop it

    def test_the_decision_record_names_the_part(self):
        self.assertEqual(pack(self.c).influences(self.c, "kai", 1 * 1440), [{"kind": "role", "role": "doubter", "toward": "jun"}])
        self.assertEqual(pack(self.c).influences(self.c, "jun", 1 * 1440), [])

    def test_every_policy_is_a_lean_on_choices_a_person_already_has(self):
        known = {"talk", "challenge", "tell", "accuse", "flirt", "confess"}
        for name, pol in R.ROLES.items():
            for key in pol.leans:
                self.assertIn(key.split(":")[0], known, (name, key))


class InTheWorld(unittest.TestCase):
    def test_the_hero_keeps_choosing_for_themselves_and_the_actor_can_lose(self):
        from agent.volition import VolitionDecider
        from world.simulation import Simulation
        c = saga(3)

        class Producer:
            def dawn(self, conn, day, at):
                if day == 0:
                    cast(conn, "kai", "jun", "rival", "12", at=at)

        d = VolitionDecider(3)
        Simulation(c, d, d, set(), feed="synthetic_v1", producer=Producer()).run(8)
        decided = [json.loads(r[0]) for r in c.execute("SELECT truth FROM events WHERE trigger_type = 'decision' AND "
                                                       "json_extract(truth, '$.actor') = 'kai'")]
        marked = [t for t in decided if any(f.get("kind") == "role" for f in (t.get("influences") or {}).get("factors", []))]
        self.assertTrue(marked)  # his choices were leaned by the part, and the record says so
        hero = [json.loads(r[0]) for r in c.execute("SELECT truth FROM events WHERE trigger_type = 'decision' AND json_extract(truth, '$.actor') = 'jun'")]
        self.assertFalse(any(f.get("kind") == "role" for t in hero for f in (t.get("influences") or {}).get("factors", [])))


if __name__ == "__main__":
    unittest.main()
