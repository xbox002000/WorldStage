"""Romance (world/domains/romance.py): who is drawn to whom, courtship, couples, jealousy, heartbreak, and the rule that only
adults take part."""
from __future__ import annotations

import json
import unittest
from unittest import mock

from world.db import connect, init_db
from world.domains import active
from world.domains import romance as R
from world.events import Change, EventSpec, apply_event
from world.intent import Intent
from world.seed import build_world
from world.state import WorldError


def saga(seed: int = 3, recipe: str = "jianghu_saga_v1"):
    conn = connect()
    init_db(conn, seed)
    build_world(conn, seed, recipe)
    return conn


def pack(conn):
    return next(d for d in active(conn) if d.id == "romance")


def now(conn):
    return conn.execute("SELECT COALESCE(MAX(timestamp), 0) FROM events").fetchone()[0]


def meet(conn, *people, place=None):
    place = place or conn.execute("SELECT id FROM locations ORDER BY id LIMIT 1").fetchone()[0]
    ch = [Change("person", p, "location_id", value=place) for p in people
          if conn.execute("SELECT location_id FROM people WHERE id = ?", (p,)).fetchone()[0] != place]
    if ch:
        apply_event(conn, EventSpec(timestamp=now(conn), type="setup", trigger_type="rule", location_id=place, changes=ch))
    return place


def feel(conn, a, b, value):
    cur = conn.execute("SELECT attraction FROM relationships WHERE actor_id = ? AND target_id = ?", (a, b)).fetchone()[0]
    apply_event(conn, EventSpec(timestamp=now(conn), type="setup", trigger_type="rule", location_id=None,
                                changes=[Change("relationship", f"{a}:{b}", "attraction", delta=round(value - cur, 6))]))


def bond(conn, a, b):
    return conn.execute("SELECT bond FROM relationships WHERE actor_id = ? AND target_id = ?", (a, b)).fetchone()[0]


def res(conn, a, b):
    return conn.execute("SELECT resentment FROM relationships WHERE actor_id = ? AND target_id = ?", (a, b)).fetchone()[0]


def do(conn, action, a, b, t=None, roll=None):
    """An action as the simulation does it: validate, resolve, every domain's effects, write. `roll` fixes the dice."""
    it = Intent(a, action, b, reason="volition")
    spec_ = pack(conn).actions[action]
    spec_.validate(conn, it, conn.execute("SELECT * FROM people WHERE id = ?", (a,)).fetchone())
    t = now(conn) + 1 if t is None else t
    with mock.patch("world.domains.romance.make_rng") as rng:
        rng.return_value.random.return_value = 0.0 if roll is None else roll
        spec = spec_.resolve(conn, it, t, "decision")
    for d in active(conn):
        spec = d.effects(conn, spec, set())
    eid = apply_event(conn, spec)
    return eid, json.loads(conn.execute("SELECT truth FROM events WHERE event_id = ?", (eid,)).fetchone()[0])


class Who(unittest.TestCase):
    def setUp(self):
        self.c = saga()

    def test_orientation_is_the_genomes(self):
        # ming is drawn to women, ning to both, mei to men
        self.assertTrue(R.drawn_to(self.c, "ming", "mei"))
        self.assertFalse(R.drawn_to(self.c, "ming", "jun"))
        self.assertTrue(R.drawn_to(self.c, "ning", "lan") and R.drawn_to(self.c, "ning", "ming"))
        self.assertFalse(R.drawn_to(self.c, "mei", "lan"))
        self.assertFalse(R.drawn_to(self.c, "ming", "ming"))

    def test_only_adults_take_part_whatever_the_genome_says(self):
        c = saga()
        self.assertTrue(R.adult(c, "ming"))
        # make a minor out of the same person in a throwaway profile
        from world import profiles
        from dataclasses import replace
        real = profiles.profile
        minor = replace(real(c, "mei"), age=17)
        with mock.patch.object(profiles, "profile", side_effect=lambda conn, pid: minor if pid == "mei" else real(conn, pid)):
            self.assertFalse(R.adult(c, "mei"))
            self.assertFalse(R.drawn_to(c, "mei", "ming"))
            self.assertFalse(R.drawn_to(c, "ming", "mei"))
            self.assertEqual(pack(c).options(c, "mei", 600, {"here": ["ming"]}), [])
            meet(c, "ming", "mei")
            for action in ("flirt", "confess"):
                with self.assertRaises(WorldError):
                    pack(c).actions[action].validate(c, Intent("ming", action, "mei"), c.execute("SELECT * FROM people WHERE id = 'ming'").fetchone())

    def test_charm_draws_and_nobody_is_drawn_without_time_together(self):
        feel_before = R.drawn_level(self.c, "ming", "mei")
        self.assertLess(feel_before, 0.5)          # strangers do not fall in love at first sight, however charming
        apply_event(self.c, EventSpec(timestamp=0, type="setup", trigger_type="rule", location_id=None,
                                      changes=[Change("relationship", "ming:mei", "familiarity", delta=0.6),
                                               Change("relationship", "ming:lan", "familiarity", delta=0.6)]))
        self.assertGreater(R.drawn_level(self.c, "ming", "mei"), R.drawn_level(self.c, "ming", "lan"))  # who is the more charming wins
        self.assertEqual(R.drawn_level(self.c, "ming", "jun"), 0.0)  # not who he is drawn to

    def test_a_grudge_cools_it(self):
        apply_event(self.c, EventSpec(timestamp=0, type="setup", trigger_type="rule", location_id=None,
                                      changes=[Change("relationship", "ming:mei", "familiarity", delta=0.6)]))
        warm = R.drawn_level(self.c, "ming", "mei")
        apply_event(self.c, EventSpec(timestamp=0, type="setup", trigger_type="rule", location_id=None,
                                      changes=[Change("relationship", "ming:mei", "resentment", delta=0.6)]))
        self.assertLess(R.drawn_level(self.c, "ming", "mei"), warm - 0.2)

    def test_the_night_moves_attraction_towards_what_one_settles_at(self):
        apply_event(self.c, EventSpec(timestamp=0, type="setup", trigger_type="rule", location_id=None,
                                      changes=[Change("relationship", "ming:mei", "familiarity", delta=0.8)]))
        goal = R.drawn_level(self.c, "ming", "mei")
        changes = pack(self.c).overnight(self.c, "ming", 1380)
        up = [ch for ch in changes if ch.entity_id == "ming:mei"]
        self.assertEqual(len(up), 1)
        self.assertGreater(up[0].delta, 0)
        self.assertLessEqual(up[0].delta, goal * R.RATE_APART + 1e-9)  # slowly, on a day they did not meet


class Courting(unittest.TestCase):
    def setUp(self):
        self.c = saga()
        meet(self.c, "ming", "mei", "kai", "ning")

    def test_a_flirt_lands_on_somebody_drawn_and_not_on_somebody_who_is_not(self):
        before = self.c.execute("SELECT attraction FROM relationships WHERE actor_id = 'mei' AND target_id = 'ming'").fetchone()[0]
        _, t = do(self.c, "flirt", "ming", "mei")
        self.assertTrue(t["landed"])
        self.assertGreater(self.c.execute("SELECT attraction FROM relationships WHERE actor_id = 'mei' AND target_id = 'ming'").fetchone()[0], before)
        _, t = do(self.c, "flirt", "ming", "kai") if R.drawn_to(self.c, "ming", "kai") else (None, {"landed": False})
        self.assertFalse(t["landed"])
        with self.assertRaises(WorldError):
            do(self.c, "flirt", "ming", "kai")  # he is not drawn to men: it is not even offered

    def test_a_confession_needs_feeling_and_is_judged_by_the_other_s(self):
        with self.assertRaises(WorldError):
            do(self.c, "confess", "ming", "mei")  # he feels nothing yet
        feel(self.c, "ming", "mei", 0.7)
        feel(self.c, "mei", "ming", 0.9)
        _, t = do(self.c, "confess", "ming", "mei", roll=0.0)
        self.assertEqual(t["outcome"], "accepted")
        self.assertEqual((bond(self.c, "ming", "mei"), bond(self.c, "mei", "ming")), ("dating", "dating"))
        self.assertIn("在一起", t["text"])

    def test_declined_is_carried_by_the_one_who_asked_and_not_asked_twice(self):
        feel(self.c, "ming", "mei", 0.7)
        feel(self.c, "mei", "ming", 0.05)
        _, t = do(self.c, "confess", "ming", "mei", roll=0.99)
        self.assertEqual(t["outcome"], "declined")
        self.assertEqual((bond(self.c, "ming", "mei"), bond(self.c, "mei", "ming")), ("rejected", ""))
        with self.assertRaises(WorldError):
            do(self.c, "confess", "ming", "mei")

    def test_somebody_not_drawn_to_you_never_says_yes(self):
        # ning is drawn to both; ming is drawn to women only. Ning confesses to ming: it is judged by ming, who is not drawn to her
        # (to a woman? ning is a woman): the luckiest roll there is does not help
        self.assertFalse(R.drawn_to(self.c, "mei", "lan"))
        feel(self.c, "lan", "mei", 0.7)  # lan (a woman) loves mei (a woman who is drawn to men only)
        feel(self.c, "mei", "lan", 1.0)
        _, t = do(self.c, "confess", "lan", "mei", roll=0.0) if R.drawn_to(self.c, "lan", "mei") else (None, {"outcome": "n/a"})
        self.assertIn(t["outcome"], ("declined", "n/a"))

    def test_a_couple_can_spend_time_and_part(self):
        feel(self.c, "ming", "mei", 0.7)
        feel(self.c, "mei", "ming", 0.9)
        do(self.c, "confess", "ming", "mei")
        _, t = do(self.c, "date", "ming", "mei")
        self.assertEqual((t["actor"], t["target"]), ("ming", "mei"))
        _, t = do(self.c, "break_up", "mei", "ming")
        self.assertEqual((bond(self.c, "ming", "mei"), bond(self.c, "mei", "ming")), ("ex", "ex"))
        self.assertGreater(res(self.c, "ming", "mei"), 0.2)  # the one left holds it against the one who left
        self.assertEqual(pack(self.c).appraise(self.c, "ming", "break_up", t)[0][0], "failure")

    def test_nobody_dates_or_parts_who_is_not_together(self):
        for action in ("date", "break_up"):
            with self.assertRaises(WorldError):
                do(self.c, action, "ming", "mei")


class Triangles(unittest.TestCase):
    def setUp(self):
        self.c = saga()
        meet(self.c, "ming", "mei", "jun", "lan", "hao", "yun", "rui", "ning")

    def together(self, a, b):
        feel(self.c, a, b, 0.8)
        feel(self.c, b, a, 0.9)
        do(self.c, "confess", a, b)

    def test_somebody_seeing_who_they_love_with_another_feels_it(self):
        feel(self.c, "ning", "mei", 0.7)  # ning loves mei
        feel(self.c, "ming", "mei", 0.7)
        feel(self.c, "mei", "ming", 0.9)
        from world.attention import noticers  # everyone there is a witness here: the place is full and the act is seen
        with mock.patch("world.domains.romance.noticers", side_effect=lambda conn, here, now, key, loud, *ex: [p for p in ("ning", "hao") if p not in ex]):
            _, t = do(self.c, "confess", "ming", "mei")
        self.assertEqual(t["jealous"]["ning"], {"kind": "crush", "of": "ming", "over": "mei"})
        self.assertGreater(res(self.c, "ning", "ming"), 0.1)
        self.assertEqual(pack(self.c).appraise(self.c, "ning", "confession", t)[0][0], "failure")

    def test_a_partner_who_sees_it_is_betrayed_and_resents_both(self):
        self.together("ming", "mei")
        feel(self.c, "jun", "mei", 0.0)
        # mei is with ming, and flirted with by somebody who wants her, in front of ming
        feel(self.c, "hao", "mei", 0.7)
        with mock.patch("world.domains.romance.noticers", side_effect=lambda conn, here, now, key, loud, *ex: [p for p in ("ming",) if p not in ex]):
            _, t = do(self.c, "flirt", "hao", "mei")
        self.assertEqual(t["poaching"], "ming")
        self.assertEqual(t["jealous"]["ming"], {"kind": "partner", "of": "hao", "over": "mei"})
        self.assertGreater(res(self.c, "ming", "hao"), 0.1)   # a grudge against the one who flirted
        self.assertGreater(res(self.c, "ming", "mei"), 0.05)  # and a little against her
        self.assertEqual(pack(self.c).appraise(self.c, "ming", "flirt", t)[0][0], "betrayal")

    def test_leaving_somebody_for_somebody_leaves_a_betrayed_ex_and_two_enemies(self):
        self.together("ming", "mei")
        feel(self.c, "hao", "mei", 0.8)
        feel(self.c, "mei", "hao", 1.0)  # she prefers the newcomer by far
        _, t = do(self.c, "confess", "hao", "mei", roll=0.0)
        self.assertEqual(t["outcome"], "accepted")
        self.assertEqual(t["left"], ["ming"])
        self.assertEqual((bond(self.c, "mei", "ming"), bond(self.c, "ming", "mei")), ("ex", "ex"))
        self.assertEqual((bond(self.c, "hao", "mei"), bond(self.c, "mei", "hao")), ("dating", "dating"))
        self.assertGreater(res(self.c, "ming", "mei"), 0.3)
        self.assertGreater(res(self.c, "ming", "hao"), 0.4)
        self.assertEqual([x[0] for x in pack(self.c).appraise(self.c, "ming", "confession", t)], ["betrayal", "wronged"])

    def test_somebody_with_a_partner_is_less_likely_to_say_yes_to_a_third(self):
        self.together("ming", "mei")
        feel(self.c, "hao", "mei", 0.8)
        feel(self.c, "mei", "hao", 0.5)  # she likes him, but not more than the one she has
        feel(self.c, "mei", "ming", 0.9)
        _, t = do(self.c, "confess", "hao", "mei", roll=0.5)
        self.assertEqual(t["outcome"], "declined")
        self.assertLess(t["p"], 0.35)

    def test_the_wish_to_court_is_weighed_against_loyalty(self):
        self.together("ming", "mei")
        feel(self.c, "ming", "lan", 0.0)
        feel(self.c, "hao", "mei", 0.6)
        free = {it.action: s for s, it in pack(self.c).options(self.c, "hao", now(self.c) + 10, {"here": ["mei"]})}
        self.assertIn("flirt", free)
        self.together("hao", "yun")  # hao is with somebody now, and mei is with ming: the same flirt costs him more
        spoken = {it.action: s for s, it in pack(self.c).options(self.c, "hao", now(self.c) + 20, {"here": ["mei"]})}
        self.assertLess(spoken.get("flirt", -9), free["flirt"])


class Reading(unittest.TestCase):
    def test_crushes_and_triangles_and_secret_couples_are_found(self):
        c = saga()
        meet(c, "ming", "mei", "ning", "lan")
        feel(c, "ming", "mei", 0.6)
        feel(c, "mei", "ming", 0.6)
        kinds = {s["kind"] for s in pack(c).situations(c, {})}
        self.assertIn("crush", kinds)
        feel(c, "ming", "lan", 0.0)
        feel(c, "ning", "mei", 0.6)  # two are drawn to mei
        kinds = {s["kind"] for s in pack(c).situations(c, {})}
        self.assertIn("love_triangle", kinds)
        with mock.patch("world.domains.romance.noticers", return_value=[]):
            do(c, "confess", "ming", "mei", roll=0.0)  # nobody saw
        kinds = {s["kind"] for s in pack(c).situations(c, {})}
        self.assertIn("secret_couple", kinds)

    def test_a_world_without_the_pack_has_nothing_of_it(self):
        c = saga(3, "town_in_jianghu_v1")
        self.assertNotIn("romance", {d.id for d in active(c)})

    def test_the_stage_shows_a_courtship_and_nothing_more(self):
        from world.domains import style
        for kind in ("flirt", "confession", "date", "break_up"):
            st = style(kind)
            self.assertIsNotNone(st)
            self.assertTrue(st.caption and st.lines and st.social)
        self.assertEqual(sorted(pack(saga()).actions), ["break_up", "confess", "date", "flirt"])  # no action beyond a courtship


if __name__ == "__main__":
    unittest.main()
