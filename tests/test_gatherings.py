"""Gatherings: an announced tournament changes who is where and who is watching, and decides nothing else."""
from __future__ import annotations

import unittest

from contracts.intervention import InterventionProposal
from producer.intervention import Ledger
from world.db import connect, init_db
from world.domains import active
from world.domains import gatherings as G
from world.events import Change, EventSpec, apply_event
from world.intent import Intent
from world.seed import build_world


def saga(seed=3):
    conn = connect()
    init_db(conn, seed)
    build_world(conn, seed, "jianghu_saga_v1")
    return conn


def pack(conn):
    return next(d for d in active(conn) if d.id == "gatherings")


def announce(conn, kind="tournament", day=3, place="qingyun", id_="g1"):
    v = Ledger().admit(conn, InterventionProposal(id_, "S", "A", "announce_gathering", "", {"kind": kind, "place": place, "day": str(day)}, 0, 2, "x"), 100)
    assert v.admitted, v.reason
    return v.event_id


def at(day, minute):
    return day * 1440 + minute


class Today(unittest.TestCase):
    def test_the_day_it_is_announced_for_and_no_other(self):
        c = saga()
        announce(c)
        self.assertEqual(G.today(c, at(3, 800))["place"], "qingyun")
        self.assertIsNone(G.today(c, at(2, 800)))
        self.assertIsNone(G.today(c, at(4, 800)))

    def test_nothing_announced_nothing_happens(self):
        c = saga()
        it = Intent("ming", "move", "inn")
        self.assertEqual(pack(c).scripted(c, it, at(3, 800)), it)
        self.assertEqual(pack(c).shape(c, "ming", at(3, 800), [(1.0, Intent("ming", "challenge", "kai"))]), [(1.0, Intent("ming", "challenge", "kai"))])
        self.assertEqual(pack(c).influences(c, "ming", at(3, 800)), [])


class Going(unittest.TestCase):
    def setUp(self):
        self.c = saga()
        announce(self.c)
        self.g = G.today(self.c, at(3, 800))

    def test_some_go_and_some_do_not_and_it_is_the_same_every_time(self):
        people = [r[0] for r in self.c.execute("SELECT id FROM people WHERE status = 'active' ORDER BY id")]
        first = [p for p in people if G.attends(self.c, p, self.g)]
        again = [p for p in people if G.attends(self.c, p, self.g)]
        self.assertEqual(first, again)
        self.assertTrue(0 < len(first) < len(people), first)

    def test_somebody_who_never_heard_does_not_come(self):
        c = saga()
        eid = announce(c)
        c.execute("PRAGMA foreign_keys = OFF")
        g = G.today(c, at(3, 800))
        row = c.execute("SELECT COUNT(*) FROM memories WHERE event_id = ?", (eid,)).fetchone()[0]
        self.assertGreater(row, 5)  # everybody was told
        g2 = dict(g, event_id=10 ** 9)  # an announcement nobody has any memory of
        self.assertFalse(any(G.attends(c, p, g2) for p in ("ming", "kai", "tao")))

    def test_an_attendees_afternoon_walk_is_replaced_by_a_walk_to_the_place_and_nothing_else_is_touched(self):
        goer = next(p for p in ("ming", "kai", "tao", "jun", "hao", "lan", "mei") if G.attends(self.c, p, self.g))
        apply_event(self.c, EventSpec(timestamp=at(3, 100), type="setup", trigger_type="rule", location_id="inn",
                                      changes=[Change("person", goer, "location_id", value="inn")]))
        it = Intent(goer, "move", "park")
        got = pack(self.c).scripted(self.c, it, at(3, 800))
        self.assertEqual((got.action, got.target, got.reason), ("move", "qingyun", "gathering"))
        self.assertEqual(pack(self.c).scripted(self.c, it, at(3, 400)), it)    # before the afternoon: as usual
        self.assertEqual(pack(self.c).scripted(self.c, it, at(3, 1200)), it)   # after it: as usual
        self.assertEqual(pack(self.c).scripted(self.c, Intent(goer, "rest"), at(3, 800)), Intent(goer, "rest"))  # only walks and meals
        apply_event(self.c, EventSpec(timestamp=at(3, 101), type="setup", trigger_type="rule", location_id="qingyun",
                                      changes=[Change("person", goer, "location_id", value="qingyun")]))
        self.assertIsNone(pack(self.c).scripted(self.c, it, at(3, 800)))  # already there: stays

    def test_those_who_stay_away_keep_their_day(self):
        stay = next(p for p in ("ming", "kai", "tao", "jun", "hao", "lan", "mei", "yun", "ning", "rui") if not G.attends(self.c, p, self.g))
        it = Intent(stay, "move", "park")
        self.assertEqual(pack(self.c).scripted(self.c, it, at(3, 800)), it)


class AtATournament(unittest.TestCase):
    def test_those_there_are_readier_to_challenge_and_only_to_challenge(self):
        c = saga()
        announce(c)
        apply_event(c, EventSpec(timestamp=at(3, 100), type="setup", trigger_type="rule", location_id="qingyun",
                                 changes=[Change("person", "ming", "location_id", value="qingyun")]))
        scored = [(1.0, Intent("ming", "challenge", "kai")), (1.0, Intent("ming", "talk", "kai", "warm")), (1.0, None)]
        got = [s for s, _ in pack(c).shape(c, "ming", at(3, 800), scored)]
        self.assertEqual(got, [1.0 + G.TOURNAMENT_PUSH, 1.0, 1.0])
        self.assertEqual([s for s, _ in pack(c).shape(c, "ming", at(3, 1200), scored)], [1.0, 1.0, 1.0])  # out of the afternoon
        apply_event(c, EventSpec(timestamp=at(3, 101), type="setup", trigger_type="rule", location_id="inn",
                                 changes=[Change("person", "ming", "location_id", value="inn")]))
        self.assertEqual([s for s, _ in pack(c).shape(c, "ming", at(3, 800), scored)], [1.0, 1.0, 1.0])  # not there

    def test_an_assessment_is_only_a_gathering(self):
        c = saga()
        announce(c, kind="assessment")
        apply_event(c, EventSpec(timestamp=at(3, 100), type="setup", trigger_type="rule", location_id="qingyun",
                                 changes=[Change("person", "ming", "location_id", value="qingyun")]))
        self.assertEqual([s for s, _ in pack(c).shape(c, "ming", at(3, 800), [(1.0, Intent("ming", "challenge", "kai"))])], [1.0])

    def test_a_month_with_one_has_people_walking_there_and_no_outcome_decided(self):
        import json
        from agent.volition import VolitionDecider
        from world.simulation import Simulation
        c = saga()

        class Producer:
            def dawn(self, conn, day, now):
                if day == 1:
                    Ledger().admit(conn, InterventionProposal("g", "S", "A", "announce_gathering", "", {"kind": "tournament", "place": "qingyun", "day": "4"}, day, 2, "x"), now)

        d = VolitionDecider(3)
        Simulation(c, d, d, set(), feed="synthetic_v1", producer=Producer()).run(6)
        walked = [json.loads(r[0]) for r in c.execute("SELECT truth FROM events WHERE type = 'move' AND json_extract(truth, '$.reason') = 'gathering'")]
        self.assertGreaterEqual(len(walked), 2)
        self.assertTrue(all(t["to"] == "qingyun" for t in walked))
        # the pack added nothing to the world but where people were: no event of its own
        self.assertEqual(c.execute("SELECT COUNT(*) FROM events WHERE type LIKE 'gathering%'").fetchone()[0], 0)


class Calibration(unittest.TestCase):
    def test_a_tournament_actually_starts_bouts(self):
        """Measured, not assumed: with a push of 0.7 not one of eight tournaments started a duel (talk always outscored a challenge)."""
        from agent.volition import VolitionDecider
        from world.simulation import Simulation
        bouts = 0
        for seed in (260934, 7):
            c = connect()
            init_db(c, seed)
            build_world(c, seed, "jianghu_story_v1")

            class Producer:
                def dawn(self, conn, day, now):
                    if day == 2:
                        Ledger().admit(conn, InterventionProposal("g", "S", "A", "announce_gathering", "", {"kind": "tournament", "place": "manor", "day": "5"}, day, 2, "x"), now)

            d = VolitionDecider(seed)
            Simulation(c, d, d, set(), feed="synthetic_v1", producer=Producer()).run(6)
            bouts += c.execute("SELECT COUNT(*) FROM events WHERE type = 'duel' AND timestamp >= ? AND timestamp < ?", (5 * 1440, 6 * 1440)).fetchone()[0]
        self.assertGreaterEqual(bouts, 2)


if __name__ == "__main__":
    unittest.main()
