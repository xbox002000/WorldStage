"""The audience's view: knowledge and expectation read from the world's history, as of a revision, never after the fact."""
from __future__ import annotations

import unittest

from contracts.audience import AudienceKnowledge
from narrative import audience as A
from tests.test_progression import duel, now, saga, setest, setvar
from world.events import Change, EventSpec, apply_event


def last(conn):
    return conn.execute("SELECT COALESCE(MAX(event_id), 0) FROM events").fetchone()[0]


class History(unittest.TestCase):
    def test_a_value_can_be_wound_back_to_any_revision(self):
        c = saga()
        r0 = last(c)
        setvar(c, "skill.jun", 0.5)
        r1 = last(c)
        setvar(c, "skill.jun", 0.8)
        r2 = last(c)
        self.assertAlmostEqual(A.value_at(c, "var", "skill.jun", "value", r0), 0.35, places=4)  # how it began
        self.assertAlmostEqual(A.value_at(c, "var", "skill.jun", "value", r1), 0.5, places=4)
        self.assertAlmostEqual(A.value_at(c, "var", "skill.jun", "value", r2), 0.8, places=4)
        self.assertEqual(A.value_at(c, "relationship", "ming:mei", "bond", r2), "")  # never changed: as it is

    def test_untouched_fields_read_as_they_are(self):
        c = saga()
        self.assertAlmostEqual(A.value_at(c, "var", "skill.ming", "value", 0), 0.5, places=4)


class Irony(unittest.TestCase):
    def setUp(self):
        self.c = saga()

    def test_nobody_is_ahead_of_the_crowd_at_the_start(self):
        k = A.knowledge(self.c, last(self.c))
        self.assertEqual([x for x in k.claims if x.kind == "hidden_strength"], [])
        self.assertEqual(len(k.expectations), 10)
        e = next(x for x in k.expectations if x.subject == "ming")
        self.assertAlmostEqual(e.knows, e.expected, delta=0.06)

    def test_secret_growth_is_irony_for_the_audience_and_not_for_the_town(self):
        setvar(self.c, "skill.jun", 0.8)  # practised in secret: the crowd still thinks 0.35
        k = A.knowledge(self.c, last(self.c))
        claim = next(x for x in k.claims if x.kind == "hidden_strength")
        self.assertEqual(claim.people, ["jun"])
        self.assertGreater(claim.gap, 0.35)
        self.assertAlmostEqual(claim.believed, 0.35, delta=0.06)  # what the people in the world take it to be
        # and a person who knows is not the crowd: ming's own view of jun has not moved
        self.assertAlmostEqual(A.value_at(self.c, "relationship", "ming:jun", "estimate", last(self.c)), 0.35, delta=0.06)

    def test_the_audience_waits_for_a_while_before_it_is_paid(self):
        r0 = last(self.c)
        for day in range(4):  # four days pass with the gap open
            apply_event(self.c, EventSpec(timestamp=(day + 1) * 1440, type="setup", trigger_type="rule", location_id=None))
        setvar(self.c, "skill.jun", 0.35)  # no-op marker so the timeline is the same
        # growth shown to the audience on day 1
        apply_event(self.c, EventSpec(timestamp=5 * 1440, type="setup", trigger_type="rule", location_id=None,
                                      changes=[Change("var", "skill.jun", "value", delta=0.45)]))
        for day in range(6, 9):
            apply_event(self.c, EventSpec(timestamp=day * 1440, type="setup", trigger_type="rule", location_id=None))
        e = A.expectation_of(self.c, "jun", last(self.c))
        self.assertGreaterEqual(e.knows - e.expected, A.GAP)
        self.assertEqual(e.since_day, 6)  # the gap stood from the start of day 6 (it opened during day 5): about three days
        self.assertLess(r0, e.since_revision)


class Before(unittest.TestCase):
    def test_a_slap_was_already_an_expectation_before_it_happened_and_is_not_after(self):
        c = saga()
        setvar(c, "skill.jun", 0.75)  # the hidden growth
        for who in ("kai", "hao", "ming"):
            setest(c, who, "jun", 0.3)
        eid, truth = duel(c, "jun", "kai", ["hao", "ming"])
        self.assertIn("slap", truth)
        was = A.before_event(c, eid)
        then = next(x for x in was.expectations if x.subject == "jun")
        self.assertGreaterEqual(then.knows - then.expected, 0.15)  # the irony stood before the event
        self.assertTrue(any(x.kind == "hidden_strength" and x.people == ["jun"] for x in was.claims))
        after = A.expectation_of(c, "jun", last(c))
        self.assertLess(after.knows - after.expected, then.knows - then.expected)  # the duel paid it off: the crowd has caught up

    def test_an_expectation_cannot_be_built_from_the_event_itself(self):
        c = saga()
        setvar(c, "skill.jun", 0.75)
        eid, _ = duel(c, "jun", "kai", ["hao"])
        before = A.before_event(c, eid)
        self.assertEqual(before.as_of, eid - 1)
        self.assertTrue(all(x.as_of == eid - 1 for x in before.expectations))


class Feelings(unittest.TestCase):
    def setUp(self):
        self.c = saga()

    def feel(self, a, b, v):
        cur = self.c.execute("SELECT attraction FROM relationships WHERE actor_id = ? AND target_id = ?", (a, b)).fetchone()[0]
        apply_event(self.c, EventSpec(timestamp=now(self.c), type="setup", trigger_type="rule", location_id=None,
                                      changes=[Change("relationship", f"{a}:{b}", "attraction", delta=round(v - cur, 6))]))

    def test_an_unspoken_crush_and_an_unreturned_love(self):
        self.feel("ming", "mei", 0.6)
        self.feel("mei", "ming", 0.6)
        self.feel("lan", "ming", 0.7)  # lan loves ming; ming does not feel it
        kinds = {(x.kind, tuple(x.people)) for x in A.knowledge(self.c, last(self.c)).claims}
        self.assertIn(("unspoken_crush", ("mei", "ming")), kinds)  # (pairs are listed in id order)
        self.assertIn(("unrequited_love", ("lan", "ming")), kinds)

    def test_a_couple_only_the_two_know_of_is_a_secret_the_audience_holds(self):
        from tests.test_romance import do, feel, meet
        meet(self.c, "ming", "mei")
        feel(self.c, "ming", "mei", 0.7)
        feel(self.c, "mei", "ming", 0.9)
        from unittest import mock
        with mock.patch("world.domains.romance.noticers", return_value=[]):
            do(self.c, "confess", "ming", "mei")
        k = A.knowledge(self.c, last(self.c))
        self.assertIn(("secret_couple", ("mei", "ming")), {(x.kind, tuple(x.people)) for x in k.claims})
        self.assertIsInstance(k, AudienceKnowledge)


if __name__ == "__main__":
    unittest.main()
