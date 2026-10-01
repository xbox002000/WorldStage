"""Producer interventions: the producer controls the topology of opportunity and nothing else, and the world never hears why."""
from __future__ import annotations

import dataclasses
import json
import tempfile
import unittest
from pathlib import Path

from contracts.intervention import InterventionProposal, WorldIntervention
from producer.intervention import COSTS, WEEK_BUDGET, Ledger
from world import interventions
from world.db import connect, init_db
from world.events import Change, EventSpec, apply_event
from world.seed import build_world
from world.snapshot import table_hash

FORBIDDEN_WORLD_KEYS = {"purpose", "arc_id", "season_id", "budget_cost", "arc", "season", "proposal_hash"}
OUTCOME_WORDS = ("win", "lose", "outcome", "respect", "love", "fear", "feel", "relationship", "verdict", "result")


def saga():
    conn = connect()
    init_db(conn, 3)
    build_world(conn, 3, "jianghu_saga_v1")
    return conn


def proposal(kind="announce_gathering", id_="iv1", target="", params=None, day=0, cost=None, purpose="讓主角在眾人面前證明自己", **kw):
    params = params if params is not None else {"announce_gathering": {"kind": "tournament", "place": "qingyun", "day": "3"},
                                                 "deliver_parcel": {"object": "manual_secret"},
                                                 "open_seat": {"day": "5"}, "announce_visitor": {"place": "qingyun", "day": "4"}}[kind]
    return InterventionProposal(id_, "S1", "A07", kind, target, params, day, COSTS[kind] if cost is None else cost, purpose, **kw)


def deliver_target(kind):
    return {"deliver_parcel": "hao", "open_seat": "chief_disciple"}.get(kind, "")


class TheDoor(unittest.TestCase):
    def setUp(self):
        self.c = saga()

    def say(self, kind, id_=None, **kw):
        p = proposal(kind, id_=id_ or f"iv-{kind}", target=deliver_target(kind), **kw)
        return interventions.apply(self.c, p.world_view(), 1500)

    def test_each_opportunity_is_one_event_with_an_opaque_id_and_nothing_of_why(self):
        for i, kind in enumerate(("announce_gathering", "deliver_parcel", "open_seat")):
            eid = interventions.apply(self.c, proposal(kind, id_=f"iv{i}", target=deliver_target(kind)).world_view(), 1500 + i)
            truth = json.loads(self.c.execute("SELECT truth FROM events WHERE event_id = ?", (eid,)).fetchone()[0])
            self.assertEqual(truth["source"], "producer")
            self.assertEqual(truth["intervention_id"], f"iv{i}")
            self.assertEqual(set(truth) & FORBIDDEN_WORLD_KEYS, set())
        everything = " ".join(r[0] for r in self.c.execute("SELECT truth FROM events"))
        self.assertNotIn("證明自己", everything)  # the purpose is nowhere in the world's history
        self.assertNotIn("A07", everything)
        self.assertEqual([m["kind"] for m in interventions.made(self.c)], ["announce_gathering", "deliver_parcel", "open_seat"])

    def test_the_town_hears_it_in_the_worlds_own_words(self):
        self.say("announce_gathering")
        heard = [r[0] for r in self.c.execute("SELECT belief FROM memories WHERE observer_id = 'ming' ORDER BY memory_id DESC LIMIT 1")]
        self.assertIn("比武大會", heard[0])
        self.assertEqual(self.c.execute("SELECT source_type FROM memories WHERE observer_id = 'ming' ORDER BY memory_id DESC LIMIT 1").fetchone()[0],
                         "external_rumor")

    def test_a_parcel_arrives_and_a_seat_opens_and_nothing_else_changes(self):
        before = {t: table_hash(self.c, t) for t in ("people", "relationships", "goals", "personas")}
        self.say("deliver_parcel")
        self.say("open_seat", id_="iv2")
        row = self.c.execute("SELECT owner_person_id, rightful_owner_id, status FROM objects WHERE id = 'manual_secret'").fetchone()
        self.assertEqual(tuple(row), ("hao", "hao", "normal"))
        seat = self.c.execute("SELECT status, decide_by, holder_id FROM seats WHERE seat_id = 'chief_disciple'").fetchone()
        self.assertEqual(tuple(seat), ("vacant", 5, "ming"))  # the seat is open; who holds it is not touched
        for t, h in before.items():  # nobody's state, relationships or goals were touched
            self.assertEqual(table_hash(self.c, t), h, t)

    def test_what_is_not_in_the_vocabulary_is_refused(self):
        w = lambda **k: dataclasses.replace(proposal("announce_gathering").world_view(), **k)  # noqa: E731
        cases = {
            "closed vocabulary": w(type="make_hero_win"),
            "outside the vocabulary": w(params={"kind": "tournament", "place": "qingyun", "day": "3", "winner": "ming"}),
            "missing": w(params={"kind": "tournament"}),
            "not the producer": w(source="showrunner"),
            "not a day ahead": w(params={"kind": "tournament", "place": "qingyun", "day": "0"}),
            "no place": w(params={"kind": "tournament", "place": "mars", "day": "3"}),
            "no gathering of kind": w(params={"kind": "wedding", "place": "qingyun", "day": "3"}),
        }
        for want, wi in cases.items():
            bad = "; ".join(interventions.problems(self.c, wi))
            self.assertIn(want, bad, (want, bad))
        with self.assertRaises(ValueError):
            interventions.apply(self.c, w(type="make_hero_win"), 1500)

    def test_things_must_exist_and_be_free_to_move(self):
        a = interventions.problems(self.c, proposal("deliver_parcel", target="nobody").world_view())
        self.assertIn("nobody in the town", "; ".join(a))
        self.say("deliver_parcel")
        again = interventions.problems(self.c, proposal("deliver_parcel", id_="iv2", target="tao").world_view())
        self.assertIn("not waiting offstage", "; ".join(again))
        self.assertIn("no seat", "; ".join(interventions.problems(self.c, proposal("open_seat", target="throne").world_view())))
        self.say("open_seat")
        self.assertIn("already open", "; ".join(interventions.problems(self.c, proposal("open_seat", id_="iv3", target="chief_disciple").world_view())))
        self.assertIn("waiting outside", "; ".join(interventions.problems(self.c, proposal("announce_visitor", target="ming").world_view())))

    def test_an_id_is_used_once(self):
        self.say("announce_gathering", id_="once")
        self.assertIn("already made", "; ".join(interventions.problems(self.c, proposal("announce_gathering", id_="once").world_view())))


class TheVocabulary(unittest.TestCase):
    def test_nothing_in_it_can_name_an_outcome_a_feeling_or_a_verdict(self):
        self.assertEqual(sorted(interventions.PARAMS), ["announce_gathering", "announce_visitor", "cast_role", "deliver_parcel", "open_seat"])
        words = set().union(*interventions.PARAMS.values()) | set(interventions.PARAMS) | set(interventions.KINDS)
        for w in words:
            self.assertFalse(any(o in w for o in OUTCOME_WORDS), w)

    def test_the_part_the_world_is_told_has_no_field_for_why(self):
        told = {f.name for f in dataclasses.fields(WorldIntervention)}
        self.assertEqual(told & FORBIDDEN_WORLD_KEYS, set())
        self.assertEqual(told, {"intervention_id", "type", "target", "params", "source"})
        full = proposal()
        self.assertEqual(full.world_view(), WorldIntervention("iv1", "announce_gathering", "", dict(full.params), "producer"))
        self.assertNotIn("purpose", json.dumps(dataclasses.asdict(full.world_view())))


class TheLedger(unittest.TestCase):
    def setUp(self):
        self.c = saga()
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "producer" / "ledger.jsonl"
        self.ledger = Ledger(self.path)

    def tearDown(self):
        self.dir.cleanup()

    def test_an_admitted_proposal_reaches_the_world_and_the_purpose_stays_in_the_ledger(self):
        v = self.ledger.admit(self.c, proposal(), 1500)
        self.assertTrue(v.admitted)
        self.assertIsNotNone(v.event_id)
        entry = self.ledger.entries[0]
        self.assertEqual((entry["purpose"], entry["arc_id"], entry["admitted"], entry["event_id"]), ("讓主角在眾人面前證明自己", "A07", True, v.event_id))
        self.assertTrue(entry["proposal_hash"].startswith("sha256:"))
        again = Ledger.load(self.path)
        self.assertEqual(again.entries, self.ledger.entries)  # kept, and readable later

    def test_the_week_has_a_budget_and_a_refusal_says_why(self):
        self.assertTrue(self.ledger.admit(self.c, proposal("open_seat", id_="a", target="chief_disciple"), 1500).admitted)   # 3
        self.assertTrue(self.ledger.admit(self.c, proposal("announce_gathering", id_="b"), 1501).admitted)                   # 2 -> 5
        v = self.ledger.admit(self.c, proposal("announce_visitor", id_="c", target="ming"), 1502)                           # 1 more is 6
        self.assertFalse(v.admitted)  # refused for the world's reasons first (nobody outside), and the budget still holds
        self.assertTrue(self.ledger.admit(self.c, proposal("deliver_parcel", id_="d", target="hao"), 1503).admitted)        # 6
        v = self.ledger.admit(self.c, proposal("announce_gathering", id_="e", params={"kind": "assessment", "place": "qingyun", "day": "9"}), 1504)
        self.assertFalse(v.admitted)
        self.assertIn("budget", v.reason)
        self.assertEqual(self.ledger.spent(1500 // 1440), WEEK_BUDGET)
        self.assertEqual(self.ledger.admit(self.c, proposal("announce_gathering", id_="f", params={"kind": "assessment", "place": "qingyun", "day": "9"}), 8 * 1440).admitted, True)  # a new week

    def test_a_refusal_is_recorded_and_changes_nothing(self):
        n = self.c.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        v = self.ledger.admit(self.c, proposal("announce_gathering", params={"kind": "tournament", "place": "mars", "day": "3"}), 1500)
        self.assertFalse(v.admitted)
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM events").fetchone()[0], n)
        self.assertEqual((self.ledger.entries[0]["admitted"], "no place" in self.ledger.entries[0]["reason"]), (False, True))

    def test_an_underpriced_proposal_is_refused(self):
        v = self.ledger.admit(self.c, proposal("open_seat", target="chief_disciple", cost=1), 1500)
        self.assertFalse(v.admitted)
        self.assertIn("costs", v.reason)


if __name__ == "__main__":
    unittest.main()
