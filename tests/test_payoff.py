"""Payoff (narrative/payoff.py, payoff_metric_v0.1): release that was set up beforehand, scored for how much the person earned it."""
from __future__ import annotations

import json
import unittest
from unittest import mock

from narrative import payoff as P
from tests.test_progression import now, saga, setest, setvar
from world.domains import active
from world.events import Change, EventSpec, apply_event


def play(conn, spec):
    for d in active(conn):
        spec = d.effects(conn, spec, set())
    return apply_event(conn, spec)


def at(day, minute=600):
    return day * 1440 + minute


def train(conn, who, day, manual=False):
    return play(conn, EventSpec(timestamp=at(day), type="train", trigger_type="decision", location_id="qingyun", importance=0.1,
                                truth={"actor": who, "gain": 0.003, "with_manual": manual}, participants=[(who, "actor")]))


def duel(conn, challenger, defender, winner, day, witnesses=("hao", "ming"), p_challenger=0.5):
    loser = defender if winner == challenger else challenger
    return play(conn, EventSpec(timestamp=at(day, 700), type="duel", trigger_type="decision", location_id="qingyun", importance=0.8,
                                truth={"actor": challenger, "target": defender, "winner": winner, "loser": loser, "bully": False,
                                       "p_challenger": p_challenger},
                                participants=[(challenger, "actor"), (defender, "target")] + [(w, "witness") for w in witnesses]))


def growth(conn, who, to, day):
    """Ability the audience has seen grow (a hidden growth), with the estimates of everybody else left where they were."""
    cur = conn.execute("SELECT value FROM world_vars WHERE key = ?", (f"skill.{who}",)).fetchone()[0]
    apply_event(conn, EventSpec(timestamp=at(day, 100), type="setup", trigger_type="rule", location_id=None,
                                changes=[Change("var", f"skill.{who}", "value", delta=round(to - cur, 6))]))


def underdog(conn, hero="jun", rival="kai", practice_days=6, manual=False, p_challenger=0.5, hero_challenges=True, growth_day=1, duel_day=9):
    for w in ("kai", "hao", "ming"):
        setest(conn, w, hero, 0.3)
    growth(conn, hero, 0.75, growth_day)
    for d in range(practice_days):
        train(conn, hero, 2 + d, manual)
    ch, df = (hero, rival) if hero_challenges else (rival, hero)
    return duel(conn, ch, df, hero, duel_day, p_challenger=p_challenger if hero_challenges else 1 - p_challenger)


class Slap(unittest.TestCase):
    def payoff(self, **kw):
        c = saga()
        eid = underdog(c, **kw)
        found = [p for p in P.payoffs(c) if p["event_id"] == eid]
        self.assertEqual(len(found), 1)
        return found[0]

    def test_an_underdogs_win_in_front_of_others_is_a_payoff_with_its_parts(self):
        p = self.payoff()
        self.assertEqual((p["kind"], p["protagonist"], p["against"]), ("face_slap", "jun", "kai"))
        for k in ("gap", "witness", "pressure", "magnitude", "investment"):
            self.assertTrue(0.0 <= p["parts"][k] <= 1.0, k)
        self.assertGreater(p["parts"]["gap"], 0.3)         # the audience had been waiting
        self.assertGreater(p["parts"]["investment"], 0.5)  # he practised
        self.assertAlmostEqual(p["earned"], p["base"] * p["agency"], places=3)

    def test_irony_made_at_the_moment_of_the_payoff_does_not_count(self):
        late = self.payoff(growth_day=9, practice_days=0)  # the growth appears the same day as the duel
        early = self.payoff(growth_day=1, practice_days=0)
        self.assertLess(late["parts"]["gap"], early["parts"]["gap"] * 0.6)

    def test_what_was_practised_is_the_protagonists_and_a_gift_is_not(self):
        plain = self.payoff(practice_days=6)
        from contracts.intervention import InterventionProposal
        from producer.intervention import Ledger
        c = saga()
        Ledger().admit(c, InterventionProposal("p", "S", "A", "deliver_parcel", "jun", {"object": "manual_secret"}, 0, 1, "x"), 100)
        eid = underdog(c, practice_days=6, manual=True)
        given = next(p for p in P.payoffs(c) if p["event_id"] == eid)
        self.assertLess(given["agency"], plain["agency"])
        self.assertLess(given["earned"], plain["earned"])

    def test_a_win_nobody_expected_of_the_dice_is_partly_luck(self):
        sure = self.payoff(p_challenger=0.8)
        long_shot = self.payoff(p_challenger=0.15)
        self.assertLess(long_shot["agency"], sure["agency"])

    def test_the_stage_the_producer_arranged_is_credited_to_it(self):
        from contracts.intervention import InterventionProposal
        from producer.intervention import Ledger
        c = saga()
        Ledger().admit(c, InterventionProposal("g", "S", "A", "announce_gathering", "", {"kind": "tournament", "place": "qingyun", "day": "9"}, 0, 2, "x"), 100)
        eid = underdog(c)
        staged = next(p for p in P.payoffs(c) if p["event_id"] == eid)
        plain = self.payoff()
        self.assertEqual(len(staged["causes"]["stage"]), 1)
        self.assertLess(staged["agency"], plain["agency"])

    def test_an_expected_win_is_no_payoff(self):
        c = saga()
        setvar(c, "skill.ming", 0.8)
        for w in ("kai", "hao"):
            setest(c, w, "ming", 0.8)
        duel(c, "ming", "tao", "ming", 3)
        self.assertEqual(P.payoffs(c), [])


class Chosen(unittest.TestCase):
    def confession(self, flirts=4, roll=0.0):
        from tests.test_romance import do, feel, meet
        c = saga()
        meet(c, "ming", "mei")
        feel(c, "ming", "mei", 0.7)
        feel(c, "mei", "ming", 0.6)
        for i in range(flirts):
            apply_event(c, EventSpec(timestamp=at(1 + i), type="flirt", trigger_type="decision", location_id="qingyun", importance=0.3,
                                     truth={"actor": "ming", "target": "mei", "landed": True},
                                     participants=[("ming", "actor"), ("mei", "target")]))
        with mock.patch("world.domains.romance.noticers", return_value=["hao"]):
            eid, _ = do(c, "confess", "ming", "mei", t=at(10), roll=roll)
        return c, eid

    def test_an_accepted_confession_after_a_courtship_is_a_payoff_the_person_earned(self):
        c, eid = self.confession(flirts=4)
        p = next(x for x in P.payoffs(c) if x["event_id"] == eid)
        self.assertEqual((p["kind"], p["protagonist"], p["against"]), ("chosen", "ming", "mei"))
        self.assertEqual(len(p["causes"]["courtship"]), 4)
        self.assertGreater(p["agency"], 0.7)
        self.assertGreater(p["parts"]["gap"], 0.3)  # the audience knew they were drawn to each other before anybody said it

    def test_a_declined_one_is_not_a_payoff(self):
        from tests.test_romance import do, feel, meet
        c = saga()
        meet(c, "ming", "mei")
        feel(c, "ming", "mei", 0.7)
        feel(c, "mei", "ming", 0.05)
        do(c, "confess", "ming", "mei", roll=0.99)
        self.assertEqual(P.payoffs(c), [])

    def test_more_courtship_is_more_of_it_their_own(self):
        few, many = self.confession(flirts=1), self.confession(flirts=6)
        a = next(x for x in P.payoffs(few[0]) if x["event_id"] == few[1])
        b = next(x for x in P.payoffs(many[0]) if x["event_id"] == many[1])
        self.assertGreater(b["parts"]["investment"], a["parts"]["investment"])


class Seats(unittest.TestCase):
    def election(self, favourite_wins):
        from contracts.intervention import InterventionProposal
        from producer.intervention import Ledger
        c = saga()
        Ledger().admit(c, InterventionProposal("s", "S", "A", "open_seat", "chief_disciple", {"day": "3"}, 0, 3, "x"), 100)
        for v in ("tao", "jun", "hao"):
            apply_event(c, EventSpec(timestamp=now(c), type="setup", trigger_type="rule", location_id=None,
                                     changes=[Change("relationship", f"{v}:ming", "respect", delta=0.5)]))
        winner, other = ("ming", "kai") if favourite_wins else ("kai", "ming")
        for i in range(3):
            apply_event(c, EventSpec(timestamp=at(1, 100 + i), type="campaign", trigger_type="decision", location_id="qingyun", importance=0.4,
                                     truth={"actor": winner, "target": "tao", "seat": "chief_disciple", "endorsed": True},
                                     participants=[(winner, "actor"), ("tao", "target")]))
        votes = {"ming": "ming", "kai": "kai", "tao": winner, "jun": winner, "hao": winner}
        eid = apply_event(c, EventSpec(timestamp=at(3, 10), type="succession", trigger_type="rule", location_id=None, importance=0.85,
                                       truth={"seat": "chief_disciple", "winner": winner, "actor": winner, "candidates": ["ming", "kai"], "votes": votes,
                                              "tally": {winner: 4, other: 1}}, participants=[(winner, "actor")]))
        return c, eid

    def test_beating_the_favourite_is_a_payoff_with_a_gap_and_the_favourite_is_not(self):
        c, eid = self.election(favourite_wins=False)
        p = next(x for x in P.payoffs(c) if x["event_id"] == eid)
        self.assertEqual((p["kind"], p["protagonist"], p["causes"]["favourite"]), ("succession", "kai", "ming"))
        self.assertGreater(p["parts"]["gap"], 0.3)
        self.assertEqual(len(p["causes"]["stage"]), 1)  # the vacancy was the producer's
        c2, eid2 = self.election(favourite_wins=True)
        q = next(x for x in P.payoffs(c2) if x["event_id"] == eid2)
        self.assertEqual(q["parts"]["gap"], 0.0)  # no surprise: the one expected to win won


class Summary(unittest.TestCase):
    def test_counts_fairness_and_the_earned_share(self):
        c = saga()
        underdog(c)
        s = P.summary(c)
        self.assertEqual((s["metric"], s["count"], s["by_kind"]), (P.METRIC_VERSION, 1, {"face_slap": 1}))
        self.assertEqual(s["per_person"], {"jun": 1})
        self.assertTrue(0.0 <= s["earned_share"] <= 1.0)
        self.assertEqual(s["protagonists"], 1)
        self.assertGreater(s["fairness_gini"], 0.8)  # one person has all of them: as unfair as it gets among ten

    def test_a_world_with_nothing_scores_nothing(self):
        s = P.summary(saga())
        self.assertEqual((s["count"], s["earned"], s["mean_agency"]), (0, 0.0, 0.0))


if __name__ == "__main__":
    unittest.main()
