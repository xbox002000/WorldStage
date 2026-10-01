"""Opportunities: where a story is close to happening and what it lacks. A read model: it sees, it never touches."""
from __future__ import annotations

import hashlib
import unittest

from contracts.intervention import InterventionProposal
from narrative import opportunity as O
from narrative import pacing
from producer.intervention import Ledger
from world.attention import var
from world.db import connect, init_db
from world.events import Change, EventSpec, apply_event
from world.seed import build_world


def story(seed=3):
    conn = connect()
    init_db(conn, seed)
    build_world(conn, seed, "jianghu_story_v1")
    return conn


def fingerprint(conn) -> str:
    h = hashlib.sha256()
    for table in ("events", "world_vars", "relationships", "people", "objects", "seats"):
        for r in conn.execute(f"SELECT * FROM {table} ORDER BY 1, 2"):
            h.update(repr(tuple(r)).encode())
    return h.hexdigest()


def duel(conn, day, winner, loser, slap=False, minute=900):
    truth = {"actor": winner, "target": loser, "winner": winner, "loser": loser, "p_challenger": 0.5}
    if slap:
        truth["slap"] = {"underdog": winner, "surprise": 0.3, "witnesses": 3, "sneered": []}
    return apply_event(conn, EventSpec(timestamp=day * 1440 + minute, type="duel", trigger_type="decision", truth=truth,
                                       participants=[(winner, "actor"), (loser, "target")]))


class Detecting(unittest.TestCase):
    def setUp(self):
        self.c = story()

    def test_it_only_reads(self):
        before = fingerprint(self.c)
        O.detect(self.c, 0)
        O.detect(self.c, 0, unfiltered=True)
        pacing.phase(self.c, 3)
        self.assertEqual(fingerprint(self.c), before)

    def test_the_underrated_have_a_reversal_that_lacks_only_an_occasion(self):
        found = [o for o in O.detect(self.c, 0) if o.kind == "reversal"]
        self.assertTrue(found)
        for o in found:
            self.assertIn(o.protagonist, ("jun", "hao", "tao"))   # the crowd rates somebody below another: the two it was built with
            self.assertTrue(O.SURE_LOSS <= o.p_success <= O.SURE_WIN)
            self.assertIn("occasion", [m.lack for m in o.missing])
            self.assertGreater(o.potential, 0)

    def test_the_list_is_deterministic_and_most_worth_first(self):
        a, b = O.detect(self.c, 0), O.detect(story(), 0)
        self.assertEqual([o.hash() for o in a], [o.hash() for o in b])
        self.assertEqual([o.potential for o in a], sorted((o.potential for o in a), reverse=True))

    def test_somebody_who_is_bound_to_win_is_not_a_story(self):
        apply_event(self.c, EventSpec(timestamp=10, type="setup", trigger_type="rule", changes=[Change("var", "skill.hao", "value", delta=round(0.99 - var(self.c, "skill.hao", 0.0), 6))]))
        self.assertFalse([o for o in O.detect(self.c, 0) if o.kind == "reversal" and o.protagonist == "hao"
                          and o.others[0] in ("kai", "ming")])
        # ...and the control that ignores what a story is still sees the pair
        self.assertTrue([o for o in O.detect(self.c, 0, unfiltered=True) if o.protagonist == "hao" and o.others[0] == "kai"])

    def test_an_announced_tournament_is_an_occasion(self):
        self.assertIsNone(O.gathering_ahead(self.c, 0))
        v = Ledger().admit(self.c, InterventionProposal("g", "S", "A", "announce_gathering", "", {"kind": "tournament", "place": "qingyun", "day": "4"}, 0, 2, "x"), 100)
        self.assertTrue(v.admitted, v.reason)
        self.assertEqual(O.gathering_ahead(self.c, 0), 4)
        self.assertEqual(O.gathering_ahead(self.c, 5), None)
        for o in O.detect(self.c, 0):
            if o.kind == "reversal":
                self.assertNotIn("occasion", [m.lack for m in o.missing])

    def test_somebody_who_is_hurt_is_waited_for(self):
        duel(self.c, 0, "kai", "hao")
        late = [o for o in O.detect(self.c, 1) if o.kind == "reversal" and "hao" in [o.protagonist, *o.others]]
        self.assertTrue(late)
        self.assertTrue(all("recovery" in [m.lack for m in o.missing] for o in late if o.others == ["kai"] or o.protagonist == "kai"))

    def test_the_vacancy_a_succession_lacks_is_a_seat_that_is_held(self):
        s = [o for o in O.detect(self.c, 0) if o.kind == "succession"]
        self.assertTrue(s)
        self.assertTrue(all("vacancy" in [m.lack for m in o.missing] for o in s))

    def test_an_opportunity_has_a_stable_id_for_the_same_story(self):
        a = {o.opportunity_id for o in O.detect(self.c, 0)}
        b = {o.opportunity_id for o in O.detect(self.c, 1)}
        self.assertTrue(a & b)


class Pacing(unittest.TestCase):
    def test_a_town_where_nothing_happened_is_calm(self):
        self.assertEqual(pacing.phase(story(), 5), "calm")

    def test_turning_points_make_a_peak_and_fade(self):
        c = story()
        for day in (3, 3, 4):
            duel(c, day, "hao", "kai", slap=True, minute=900 + (day * 7))
        self.assertEqual(pacing.phase(c, 5), "peak")
        self.assertGreater(pacing.intensity(c, 5), pacing.intensity(c, 6))
        self.assertEqual(pacing.phase(c, 9), "calm")

    def test_events_of_today_are_not_yet_seen(self):
        c = story()
        duel(c, 5, "hao", "kai", slap=True)
        self.assertEqual(pacing.intensity(c, 5), 0.0)


if __name__ == "__main__":
    unittest.main()
