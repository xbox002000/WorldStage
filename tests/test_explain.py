from __future__ import annotations

import unittest

from tests.helpers import social_world
from tests.test_series import lie_story
from tests.world_fixture import reader
from world.events import Change, EventSpec, apply_event
from world.explain import causes, earliest_cause, explain_event, format_explanation


class ExplainTests(unittest.TestCase):
    def test_a_confrontation_shows_what_the_accuser_knew_and_why(self):
        conn, ids = lie_story()
        x = explain_event(conn, ids["exposure"])
        self.assertEqual(x["type"], "confront")
        hows = sorted(k["how"] for k in x["knew"])
        self.assertEqual(hows, ["聽John說", "聽Mary說"])  # the two conflicting accounts, each with its source
        self.assertEqual(x["verdict"]["outcome"], "lie_exposed")
        self.assertEqual([c["event_id"] for c in x["causes"]], [ids["theft"], ids["lie"], ids["truth"]])
        self.assertIn("欺騙", "；".join(x["claims"]["truth"]))

    def test_a_tell_shows_the_memory_it_was_passed_on_from(self):
        conn, ids = lie_story(finish=False)
        x = explain_event(conn, ids["lie"])
        self.assertEqual(x["verdict"]["mode"], "lie")
        self.assertEqual(len(x["knew"]), 1)
        self.assertEqual(x["knew"][0]["how"], "親眼看到")
        self.assertEqual(x["knew"][0]["learned_in_event"], ids["theft"])

    def test_the_text_report_is_readable(self):
        conn, ids = lie_story()
        text = format_explanation(explain_event(conn, ids["exposure"]))
        for expected in ("事件 #", "當時他知道", "來龍去脈", "lie_exposed"):
            self.assertIn(expected, text)

    def test_a_decision_days_later_traces_back_to_the_first_day(self):
        conn = social_world()
        day = 1440
        first = apply_event(conn, EventSpec(timestamp=100, type="talk", trigger_type="t", truth={"actor": "john", "target": "mary", "tone": "cold"},
                                            participants=[("john", "actor"), ("mary", "target")],
                                            changes=[Change("relationship", "mary:john", "trust", delta=-0.1)]))
        prev = first
        for d in range(1, 6):  # one link per day, each event caused by the one before
            prev = apply_event(conn, EventSpec(timestamp=d * day + 100, type="talk", trigger_type="t", parent_event_id=prev,
                                               truth={"actor": "john", "target": "mary", "tone": "cold"},
                                               participants=[("john", "actor"), ("mary", "target")]))
        origin = earliest_cause(conn, prev)
        self.assertEqual((origin["event_id"], origin["day"]), (first, 1))
        self.assertEqual([c["day"] for c in causes(conn, prev)], [1, 2, 3, 4, 5])

    def test_late_events_in_a_simulated_week_trace_back_to_day_one(self):
        r = reader()
        late = [row[0] for row in r.execute(
            "SELECT event_id FROM events WHERE timestamp >= ? AND type IN ('talk','steal','tell','confront')", (5 * 1440,))]
        reached = [e for e in late if (earliest_cause(r, e) or {}).get("day") == 1]
        self.assertTrue(late)
        self.assertGreater(len(reached), 0)  # long-term continuity: memories from day 1 still shape day 6 and 7

    def test_unknown_events_are_reported(self):
        with self.assertRaises(KeyError):
            explain_event(social_world(), 12345)


if __name__ == "__main__":
    unittest.main()
