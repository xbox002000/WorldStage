"""Growth and what others think of it (world/domains/progression.py): tempering, breakthroughs that never fall back, estimates
that lag the truth, and the surprise when a duel shows it."""
from __future__ import annotations

import json
import unittest

from agent.volition import VolitionDecider
from world.db import connect, init_db
from world.domains import active
from world.domains.progression import GAP_SHOWN, REALMS, realm
from world.events import Change, EventSpec, apply_event
from world.intent import Intent
from world.seed import build_world
from world.simulation import Simulation


def saga(seed: int = 3):
    conn = connect()
    init_db(conn, seed)
    build_world(conn, seed, "jianghu_saga_v1")
    return conn


def pack(conn, name="progression"):
    return next(d for d in active(conn) if d.id == name)


def now(conn):
    return conn.execute("SELECT COALESCE(MAX(timestamp), 0) FROM events").fetchone()[0]


def setvar(conn, key, value):
    cur = conn.execute("SELECT value FROM world_vars WHERE key = ?", (key,)).fetchone()[0]
    apply_event(conn, EventSpec(timestamp=now(conn), type="setup", trigger_type="rule", location_id=None,
                                changes=[Change("var", key, "value", delta=value - cur)]))


def setest(conn, a, b, value):
    cur = conn.execute("SELECT estimate FROM relationships WHERE actor_id = ? AND target_id = ?", (a, b)).fetchone()[0]
    apply_event(conn, EventSpec(timestamp=now(conn), type="setup", trigger_type="rule", location_id=None,
                                changes=[Change("relationship", f"{a}:{b}", "estimate", delta=round(value - cur, 6))]))


def est(conn, a, b):
    return conn.execute("SELECT estimate FROM relationships WHERE actor_id = ? AND target_id = ?", (a, b)).fetchone()[0]


def var(conn, key):
    return conn.execute("SELECT value FROM world_vars WHERE key = ?", (key,)).fetchone()[0]


def duel(conn, winner, loser, witnesses, t=600):
    """A duel as the simulation would make it: every domain's effects, then the event, then what follows from it."""
    spec = EventSpec(timestamp=t, type="duel", trigger_type="decision", location_id="inn", importance=0.8,
                     truth={"actor": winner, "target": loser, "winner": winner, "loser": loser, "bully": False},
                     participants=[(winner, "actor"), (loser, "target")] + [(w, "witness") for w in witnesses])
    for d in active(conn):
        spec = d.effects(conn, spec, set())
    eid = apply_event(conn, spec)
    return eid, json.loads(conn.execute("SELECT truth FROM events WHERE event_id = ?", (eid,)).fetchone()[0])


class Realms(unittest.TestCase):
    def test_the_ladder(self):
        self.assertEqual(realm(0.0), (0, "入門"))
        self.assertEqual(realm(0.45)[1], "精熟")
        self.assertEqual(realm(0.99)[1], "宗師")
        self.assertEqual([lo for _n, lo in REALMS], sorted(lo for _n, lo in REALMS))


class Growth(unittest.TestCase):
    def setUp(self):
        self.c = saga()

    def train(self, who, t=600, manual=False):
        spec = EventSpec(timestamp=t, type="train", trigger_type="decision", location_id="qingyun", importance=0.1,
                         truth={"actor": who, "gain": 0.003, "with_manual": manual}, participants=[(who, "actor")])
        for d in active(self.c):
            spec = d.effects(self.c, spec, set())
        return apply_event(self.c, spec)

    def test_practice_builds_tempering_and_a_manual_doubles_it(self):
        self.train("ming")
        one = var(self.c, "tempering.ming")
        self.train("jun", manual=True)
        self.assertGreater(one, 0)
        self.assertAlmostEqual(var(self.c, "tempering.jun"), 2 * one, places=6)

    def test_enough_tempering_is_a_breakthrough_that_says_what_earned_it(self):
        before = var(self.c, "skill.hao")
        t1 = self.train("hao", t=600)
        setvar(self.c, "tempering.hao", 1.6)  # more than the need at this ability
        t2 = self.train("hao", t=601)
        made = pack(self.c).after_event(self.c, t2)
        self.assertEqual(len(made), 1)
        bid = apply_event(self.c, made[0])
        truth = json.loads(self.c.execute("SELECT truth FROM events WHERE event_id = ?", (bid,)).fetchone()[0])
        self.assertEqual(truth["actor"], "hao")
        self.assertEqual(truth["earned_by"], [t1, t2])  # every practice behind it
        self.assertGreater(var(self.c, "skill.hao"), before + 0.03)
        self.assertEqual(var(self.c, "tempering.hao"), 0.0)  # spent
        self.assertEqual(self.c.execute("SELECT parent_event_id FROM events WHERE event_id = ?", (bid,)).fetchone()[0], t2)

    def test_not_enough_is_not_a_breakthrough_and_ability_never_falls(self):
        t = self.train("ming")
        self.assertEqual(pack(self.c).after_event(self.c, t), [])
        for _ in range(3):
            setvar(self.c, "tempering.kai", 3.0)
            before = var(self.c, "skill.kai")
            made = pack(self.c).after_event(self.c, self.train("kai", t=700 + _))
            apply_event(self.c, made[0])
            self.assertGreater(var(self.c, "skill.kai"), before)

    def test_a_defeat_burns_into_tempering_and_can_break_through(self):
        setvar(self.c, "tempering.jun", 1.4)
        eid, _ = duel(self.c, "tao", "jun", ["hao"])
        self.assertGreater(var(self.c, "tempering.jun"), 1.8)  # 1.4 plus a defeat's worth
        made = pack(self.c).after_event(self.c, eid)
        self.assertEqual(len(made), 1)  # the loser breaks through, out of the humiliation
        truth = made[0].truth
        self.assertEqual((truth["actor"], truth["defeats"]), ("jun", [eid]))


class Estimates(unittest.TestCase):
    def setUp(self):
        self.c = saga()

    def test_everyone_starts_by_rating_everyone_about_right(self):
        for a, b in (("mei", "ming"), ("hao", "kai"), ("ming", "lan")):
            self.assertAlmostEqual(est(self.c, a, b), var(self.c, f"skill.{b}"), delta=0.05)

    def test_growth_is_private_so_the_estimate_lags(self):
        before = est(self.c, "kai", "jun")
        setvar(self.c, "skill.jun", var(self.c, "skill.jun") + 0.3)  # practised in secret
        self.assertEqual(est(self.c, "kai", "jun"), before)
        self.assertGreaterEqual(var(self.c, "skill.jun") - est(self.c, "kai", "jun"), 0.25)

    def test_a_duel_shows_the_truth_to_those_who_saw_and_to_the_one_who_fought(self):
        setvar(self.c, "skill.jun", 0.7)
        for who in ("kai", "hao", "ming"):
            setest(self.c, who, "jun", 0.3)
        eid, truth = duel(self.c, "jun", "kai", ["hao"])
        self.assertGreater(est(self.c, "hao", "jun"), 0.5)   # a witness sees it
        self.assertGreater(est(self.c, "kai", "jun"), 0.55)  # the loser felt it
        self.assertAlmostEqual(est(self.c, "ming", "jun"), 0.3, delta=0.01)  # one who was not there does not know yet

    def test_an_underdog_s_win_is_a_slap_and_flips_the_respect_of_those_who_sneered(self):
        setvar(self.c, "skill.jun", 0.7)
        for who in ("kai", "hao", "ming"):
            setest(self.c, who, "jun", 0.3)
        setest(self.c, "ming", "kai", 0.6)
        eid, truth = duel(self.c, "jun", "kai", ["hao", "ming"])
        slap = truth["slap"]
        self.assertEqual(slap["underdog"], "jun")
        self.assertGreaterEqual(slap["surprise"], 0.1)
        self.assertEqual(slap["witnesses"], 2)
        self.assertIn("hao", truth["gaps"])
        self.assertGreaterEqual(truth["gaps"]["hao"], GAP_SHOWN)
        for who in ("kai", "hao", "ming"):  # who had taken him for less respects him more
            self.assertGreater(self.c.execute("SELECT respect FROM relationships WHERE actor_id = ? AND target_id = 'jun'", (who,)).fetchone()[0], 0.2, who)

    def test_the_expected_winner_s_win_is_no_slap(self):
        setvar(self.c, "skill.ming", 0.8)
        for who in ("kai", "hao"):
            setest(self.c, who, "ming", 0.8)
        eid, truth = duel(self.c, "ming", "tao", ["hao"])
        self.assertNotIn("slap", truth)

    def test_the_surprise_is_felt(self):
        setvar(self.c, "skill.jun", 0.7)
        for who in ("kai", "hao"):
            setest(self.c, who, "jun", 0.3)
        _, truth = duel(self.c, "jun", "kai", ["hao"])
        p = pack(self.c)
        self.assertEqual(p.appraise(self.c, "jun", "duel", truth)[0][0], "success")
        self.assertEqual(p.appraise(self.c, "kai", "duel", truth)[0][0], "shame")
        self.assertEqual(p.appraise(self.c, "hao", "duel", truth)[0][0], "shame")  # he had sneered, and was there
        self.assertEqual(p.appraise(self.c, "lan", "duel", truth), [])  # somebody who was not there feels nothing

    def test_by_night_everyone_hears_of_it(self):
        setvar(self.c, "skill.jun", 0.7)
        setest(self.c, "ming", "jun", 0.3)
        duel(self.c, "jun", "kai", ["hao"], t=600)
        changes = pack(self.c).overnight(self.c, "ming", 1380)
        up = [ch for ch in changes if ch.entity_id == "ming:jun"]
        self.assertEqual(len(up), 1)
        self.assertGreater(up[0].delta, 0.1)
        self.assertEqual(pack(self.c).overnight(self.c, "hao", 1380) and [ch for ch in pack(self.c).overnight(self.c, "hao", 1380) if ch.entity_id.startswith("hao:jun")], [])  # hao saw it

    def test_a_sneer_wants_to_be_proved_right_and_the_challenger_weighs_what_he_believes(self):
        p = pack(self.c)
        setvar(self.c, "skill.jun", 0.7)
        base = [(0.0, Intent("kai", "challenge", "jun", reason="volition"))]
        setest(self.c, "kai", "jun", 0.7)  # knows what he is up against
        wary = p.shape(self.c, "kai", 600, base)[0][0]
        setest(self.c, "kai", "jun", 0.45)  # takes him for an equal
        bold = p.shape(self.c, "kai", 600, base)[0][0]
        self.assertGreater(bold, wary)


class Reading(unittest.TestCase):
    def test_hidden_strength_is_found_and_described(self):
        c = saga()
        setvar(c, "skill.jun", 0.9)
        p = pack(c)
        sit = [s for s in p.situations(c, {"jun": "阿俊"}) if s["kind"] == "hidden_strength"]
        self.assertEqual([s["people"] for s in sit], [["jun"]])
        d = p.describe(c, "jun")
        self.assertEqual(d["境界"], "宗師")
        self.assertGreater(d["真實武功"], d["別人眼中的武功"] + 0.2)

    def test_a_world_without_the_pack_has_no_estimates_to_speak_of(self):
        conn = connect()
        init_db(conn, 3)
        build_world(conn, 3, "town_in_jianghu_v1")
        self.assertEqual(conn.execute("SELECT COUNT(DISTINCT estimate) FROM relationships").fetchone()[0], 1)


class Lives(unittest.TestCase):
    def test_a_month_in_the_saga_has_growth_and_surprises_and_nothing_inflates(self):
        c = saga(3)
        d = VolitionDecider(3)
        Simulation(c, d, d, set(), feed="synthetic_v1").run(28)
        n = c.execute("SELECT COUNT(*) FROM events WHERE type = 'breakthrough'").fetchone()[0]
        self.assertTrue(1 <= n <= 8, n)
        slaps = [json.loads(r[0]).get("slap") for r in c.execute("SELECT truth FROM events WHERE type = 'duel'")]
        self.assertTrue(any(slaps))
        top = max(r[0] for r in c.execute("SELECT value FROM world_vars WHERE key LIKE 'skill.%'"))
        self.assertLess(top, 0.9)  # nobody has become a grandmaster in a month


if __name__ == "__main__":
    unittest.main()
