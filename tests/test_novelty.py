"""Pattern saturation, arc death and the debt read model."""
from __future__ import annotations

import unittest

from contracts.opportunity import Opportunity
from narrative import debt, novelty
from producer import arcs, director as D
from tests.test_opportunity import duel, fingerprint, story


def slap(day, hero="hao", other="kai"):
    return {"kind": "face_slap", "protagonist": hero, "against": other, "day": day, "earned": 0.5, "base": 0.6, "event_id": day}


def vote(day, seat="s1"):
    return {"kind": "succession", "protagonist": "jun", "against": None, "seat": seat, "day": day, "earned": 0.5, "base": 0.6, "event_id": day}


class Saturation(unittest.TestCase):
    def test_the_same_thing_again_is_worth_less_each_time(self):
        self.assertEqual([novelty.factor(i) for i in range(5)], [1.0, 0.6, 0.3, 0.1, 0.1])

    def test_a_repeat_of_both_mechanic_and_pair_counts_twice(self):
        s = novelty.saturate([slap(1), slap(5), slap(9, "tao", "ming")])
        self.assertEqual([p["novelty"] for p in s], [1.0, 0.36, 0.3])   # same pair and mechanic; then a new pair, the mechanic a third time

    def test_a_new_mechanic_between_the_same_people_is_still_partly_new(self):
        s = novelty.saturate([slap(1), {**slap(5), "kind": "chosen"}])
        self.assertEqual(s[1]["novelty"], 0.6)

    def test_votes_at_one_seat_saturate_and_the_measure_says_so(self):
        found = [vote(d) for d in (3, 8, 13, 18)]
        s = novelty.summary(found)
        self.assertLess(s["earned_novel"], 0.5 * s["earned"])
        self.assertEqual(s["mechanics"], 1)

    def test_a_pattern_memory_is_what_has_been_told(self):
        m = novelty.PatternMemory.of([slap(1), vote(2)])
        self.assertEqual(m.novelty("face_slap", "hao|kai"), 0.36)
        self.assertEqual(m.novelty("chosen", "a|b"), 1.0)

    def test_the_old_metric_is_untouched(self):
        from narrative import payoff
        self.assertTrue(payoff.METRIC_VERSION.endswith("v0.1"))


class ArcDeath(unittest.TestCase):
    def op(self):
        return Opportunity("op-x", "reversal", "hao", ["kai"], 0, 0.3, 0.9, 0.5)

    def test_a_story_nothing_came_of_is_given_up_and_not_taken_up_again_for_a_while(self):
        c = story()
        t = arcs.Threads()
        t.take_up(self.op(), 0)
        t.settle(c, arcs.STALL_DAYS)
        self.assertEqual(t.by_id["op-x"].status, "abandoned")
        self.assertTrue(t.blocked("op-x", arcs.STALL_DAYS + 1))
        self.assertFalse(t.blocked("op-x", arcs.STALL_DAYS + arcs.ABANDON_REST))

    def test_a_story_that_was_played_is_not_given_up(self):
        c = story()
        t = arcs.Threads()
        t.take_up(self.op(), 0)
        duel(c, 2, "hao", "kai")
        t.settle(c, arcs.STALL_DAYS)
        self.assertNotEqual(t.by_id["op-x"].status, "abandoned")

    def test_noticing_that_a_story_needs_nothing_is_not_tending_it(self):
        c = story()
        t = arcs.Threads()
        t.take_up(self.op(), 0)
        t.take_up(self.op(), 5, acted=False)
        self.assertEqual(t.by_id["op-x"].last_action, 0)


class Portfolio(unittest.TestCase):
    def test_a_repeat_is_gated_out_before_it_is_weighed(self):
        c = story()
        dr = D.Director("portfolio", 3)
        from narrative.opportunity import detect
        ops = [o for o in detect(c, 0) if o.kind == "succession"]
        self.assertTrue(ops)
        seat = ops[0].evidence["seat"]
        dr.threads.found = [vote(1, seat), vote(4, seat), vote(8, seat)]   # that seat has been told three times
        self.assertLess(dr._novelty(ops[0]), D.NOVELTY_FLOOR)
        gated = dr._ranked(c, ops, 0)
        self.assertFalse([o for o in gated if dr._novelty(o) < D.NOVELTY_FLOOR])

    def test_it_records_the_strength_of_what_it_did_and_how_many_arcs_it_tends(self):
        c = story()
        dr = D.Director("portfolio", 3)
        dr.dawn(c, 0, 5)
        d = dr.ledger.decisions[0]
        if d["action"] == "intervene":
            self.assertTrue(set(d["strength"]) <= {"soft", "medium", "hard"})
            self.assertGreaterEqual(d["arcs_active"], 1)

    def test_it_reads_and_never_writes_the_world_except_through_the_ledger(self):
        c = story()
        dr = D.Director("portfolio", 3)
        dr.dawn(c, 0, 5)
        n = sum(1 for e in dr.ledger.entries if e["admitted"])
        self.assertEqual(c.execute("SELECT COUNT(*) FROM events WHERE type = 'intervention'").fetchone()[0], n)


class Debt(unittest.TestCase):
    def test_debt_is_read_only_and_every_part_is_named(self):
        c = story()
        before = fingerprint(c)
        rows = debt.ledger(c)
        self.assertEqual(fingerprint(c), before)
        self.assertEqual(set(rows[0]["parts"]), set(debt.WEIGHTS))
        self.assertEqual([r["debt"] for r in rows], sorted((r["debt"] for r in rows), reverse=True))

    def test_the_underrated_carry_the_gap(self):
        c = story()
        top = {r["person"] for r in debt.ledger(c)[:3]}
        self.assertTrue(top & {"jun", "hao"})


if __name__ == "__main__":
    unittest.main()
