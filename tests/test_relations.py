"""Depth in relationships (world/domains/relations.py): familiarity, resentment and respect are world truth that events move
and that decide how people talk."""
from __future__ import annotations

import unittest

from agent.volition import VolitionDecider
from world.db import connect, init_db
from world.domains import active
from world.events import EventSpec, apply_event
from world.intent import Intent
from world.seed import build_world
from world.simulation import Simulation


def saga(seed: int = 3):
    conn = connect()
    init_db(conn, seed)
    build_world(conn, seed, "jianghu_saga_v1")
    return conn


def pack(conn):
    return next(d for d in active(conn) if d.id == "relations")


def play(conn, spec: EventSpec) -> int:
    """An event as the simulation would make it: the pack's effects first."""
    return apply_event(conn, pack(conn).effects(conn, spec, set()))


def dim(conn, a: str, b: str, field: str) -> float:
    return conn.execute(f"SELECT {field} FROM relationships WHERE actor_id = ? AND target_id = ?", (a, b)).fetchone()[0]


def talk(a, b, tone, t=600, reason="", witnesses=()):
    return EventSpec(timestamp=t, type="talk", trigger_type="decision", location_id="inn", importance=0.1,
                     truth={"actor": a, "target": b, "tone": tone, "reason": reason},
                     participants=[(a, "actor"), (b, "target")] + [(w, "witness") for w in witnesses])


class Effects(unittest.TestCase):
    def setUp(self):
        self.c = saga()

    def test_an_exchange_makes_people_know_each_other(self):
        before = dim(self.c, "ming", "mei", "familiarity")
        play(self.c, talk("ming", "mei", "warm"))
        self.assertGreater(dim(self.c, "ming", "mei", "familiarity"), before)
        self.assertGreater(dim(self.c, "mei", "ming", "familiarity"), 0)  # both ways

    def test_hostile_words_leave_a_grudge_and_an_apology_takes_some_away(self):
        play(self.c, talk("ming", "mei", "hostile"))
        grudge = dim(self.c, "mei", "ming", "resentment")
        self.assertGreater(grudge, 0.05)
        self.assertEqual(dim(self.c, "ming", "mei", "resentment"), 0)  # not mutual until the other hits back
        play(self.c, talk("ming", "mei", "warm", t=601, reason="reply:apologize"))
        self.assertLess(dim(self.c, "mei", "ming", "resentment"), grudge)

    def test_a_false_accusation_is_resented_and_a_caught_thief_loses_everybody_s_respect(self):
        play(self.c, EventSpec(timestamp=600, type="accuse", trigger_type="decision", location_id="inn", importance=0.5,
                               truth={"actor": "kai", "target": "jun", "outcome": "false"},
                               participants=[("kai", "actor"), ("jun", "target")]))
        self.assertGreater(dim(self.c, "jun", "kai", "resentment"), 0.2)
        play(self.c, EventSpec(timestamp=601, type="accuse", trigger_type="decision", location_id="inn", importance=0.5,
                               truth={"actor": "kai", "target": "jun", "outcome": "caught"},
                               participants=[("kai", "actor"), ("jun", "target"), ("hao", "witness"), ("tao", "witness")]))
        for who in ("kai", "hao", "tao"):  # the accuser and the ones who saw it
            self.assertLess(dim(self.c, who, "jun", "respect"), -0.1, who)
        self.assertEqual(dim(self.c, "lan", "jun", "respect"), 0)  # somebody who was not there feels nothing

    def test_a_blow_costs_respect_unless_it_answered_one(self):
        play(self.c, EventSpec(timestamp=600, type="strike", trigger_type="decision", location_id="inn", importance=0.6,
                               truth={"actor": "ming", "target": "kai"}, participants=[("ming", "actor"), ("kai", "target"), ("tao", "witness")]))
        self.assertLess(dim(self.c, "tao", "ming", "respect"), 0)
        self.assertGreater(dim(self.c, "kai", "ming", "resentment"), 0.3)
        play(self.c, EventSpec(timestamp=601, type="strike", trigger_type="decision", location_id="inn", importance=0.6,
                               truth={"actor": "kai", "target": "ming", "provoked_by_target": True},
                               participants=[("kai", "actor"), ("ming", "target")]))
        self.assertLess(dim(self.c, "ming", "kai", "resentment"), 0.15)  # it stings, it is not a wrong

    def test_a_duel_earns_respect_from_the_loser_and_from_those_who_watched(self):
        play(self.c, EventSpec(timestamp=600, type="duel", trigger_type="decision", location_id="inn", importance=0.8,
                               truth={"actor": "ming", "target": "jun", "winner": "jun", "loser": "ming", "bully": False},
                               participants=[("ming", "actor"), ("jun", "target"), ("hao", "witness")]))
        self.assertGreater(dim(self.c, "ming", "jun", "respect"), 0.1)
        self.assertGreater(dim(self.c, "hao", "jun", "respect"), 0.05)

    def test_picking_on_the_weak_costs_the_bully_the_respect_of_the_crowd(self):
        play(self.c, EventSpec(timestamp=600, type="duel", trigger_type="decision", location_id="inn", importance=0.8,
                               truth={"actor": "ming", "target": "lan", "winner": "ming", "loser": "lan", "bully": True},
                               participants=[("ming", "actor"), ("lan", "target"), ("hao", "witness")]))
        self.assertLess(dim(self.c, "hao", "ming", "respect"), 0)


class Decisions(unittest.TestCase):
    def setUp(self):
        self.c = saga()

    def set_grudge(self, a, b, value):
        from world.events import Change
        apply_event(self.c, EventSpec(timestamp=1, type="setup", trigger_type="rule", location_id=None,
                                      changes=[Change("relationship", f"{a}:{b}", "resentment", delta=value)]))

    def test_a_grudge_cools_warm_words_and_sharpens_cold_ones(self):
        scored = [(1.0, Intent("ming", "talk", "kai", "warm")), (1.0, Intent("ming", "talk", "kai", "cold")),
                  (1.0, Intent("ming", "talk", "kai", "hostile"))]
        calm = dict((it.tone, s) for s, it in pack(self.c).shape(self.c, "ming", 600, scored))
        self.set_grudge("ming", "kai", 0.6)
        grim = dict((it.tone, s) for s, it in pack(self.c).shape(self.c, "ming", 600, scored))
        self.assertLess(grim["warm"], calm["warm"])
        self.assertGreater(grim["cold"], calm["cold"])
        self.assertGreater(grim["hostile"], calm["hostile"])

    def test_an_old_grudge_makes_an_argument_worse_only_when_it_runs_deep(self):
        self.assertEqual(pack(self.c).reply_options(self.c, "ming", "kai", 3, 600), [])
        self.set_grudge("ming", "kai", 0.5)
        opts = pack(self.c).reply_options(self.c, "ming", "kai", 3, 600)
        self.assertEqual([(it.tone, it.reason) for _, it in opts], [("hostile", "reply:grudge")])
        self.assertEqual(pack(self.c).reply_options(self.c, "ming", "kai", 1, 600), [])  # not mid-quarrel

    def test_the_decision_record_names_a_deep_grudge(self):
        self.assertEqual(pack(self.c).influences(self.c, "ming", 600), [])
        self.set_grudge("ming", "kai", 0.5)
        got = pack(self.c).influences(self.c, "ming", 600)
        self.assertEqual((got[0]["kind"], got[0]["against"]), ("grudge", "kai"))


class Lives(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = saga(5)
        d = VolitionDecider(5)
        Simulation(cls.c, d, d, set(), feed="synthetic_v1").run(14)

    def test_nobody_is_stuck_at_the_ends_and_things_have_moved(self):
        for f in ("resentment", "respect", "familiarity"):
            stuck, moved = self.c.execute(f"SELECT SUM(ABS({f}) >= 0.9), SUM({f} != 0) FROM relationships").fetchone()
            self.assertEqual(stuck or 0, 0, f)
            self.assertGreater(moved, 10, f)

    def test_grudges_fade_and_people_not_met_are_known_less(self):
        pk = pack(self.c)
        changes = pk.overnight(self.c, "ming", 14 * 1440 + 1380)
        for ch in changes:
            a, b = ch.entity_id.split(":")
            cur = dim(self.c, a, b, ch.field)
            if ch.field == "resentment":
                self.assertLess(ch.delta, 0)   # a grudge only ever fades by itself, and never past nothing
                self.assertLessEqual(-ch.delta, cur)
            if ch.field == "familiarity":
                self.assertLess(ch.delta, 0)
                self.assertGreaterEqual(cur + ch.delta, 0)
        self.assertTrue({"resentment", "familiarity"} & {ch.field for ch in changes})

    def test_a_world_without_the_pack_never_touches_the_new_columns(self):
        conn = connect()
        init_db(conn, 3)
        build_world(conn, 3, "town_in_jianghu_v1")
        d = VolitionDecider(3)
        Simulation(conn, d, d, set(), feed="synthetic_v1").run(4)
        for f in ("resentment", "respect", "familiarity", "attraction"):
            self.assertEqual(conn.execute(f"SELECT COUNT(*) FROM relationships WHERE {f} != 0").fetchone()[0], 0, f)


if __name__ == "__main__":
    unittest.main()
