from __future__ import annotations

import unittest

from agent.decision import SeededDecider
from narrative.arcs import build_arcs, load_events
from narrative.scene_spec import build_spec, dumps, validate_spec
from narrative.selector import rank_arcs, select_top
from tests.helpers import seeded
from world.db import connect, init_db
from world.events import Change, EventSpec, MemorySpec, apply_event
from world.intent import Intent
from world.rules import last_event_between, resolve
from world.seed import build_world
from world.simulation import Simulation


def talk(conn, ts, a, b, tone):
    spec = resolve(conn, Intent(a, "talk", b, tone), ts, "decision")
    return apply_event(conn, spec)


def feud_world():
    """john and mary escalate over four beats; tom only talks pleasantly with mary."""
    conn = seeded(john_at="cafe", all_pairs=True)
    ids = [talk(conn, 10, "john", "mary", "neutral"), talk(conn, 20, "mary", "john", "cold"),
           talk(conn, 30, "john", "mary", "hostile"), talk(conn, 40, "mary", "john", "hostile")]
    return conn, ids


class ArcTests(unittest.TestCase):
    def test_witnesses_are_not_causal_parents(self):
        conn = seeded(john_at="cafe", all_pairs=True)  # phone belongs to mary
        steal = apply_event(conn, resolve(conn, Intent("tom", "steal", "phone"), 5, "decision"))
        # john and mary: john only witnessed the theft, so it must not be their causal parent.
        self.assertIsNone(last_event_between(conn, "john", "mary"))
        self.assertEqual(last_event_between(conn, "tom", "mary"), steal)

    def test_arc_follows_one_pair_and_orders_causes_first(self):
        conn, ids = feud_world()
        events = load_events(conn)
        arcs = build_arcs(events)
        top = max(arcs, key=lambda a: len(a.events))
        self.assertEqual({e.pair for e in top.events}, {frozenset({"john", "mary"})})
        self.assertEqual(list(top.ids), sorted(top.ids))
        self.assertLessEqual(len(top.events), 7)

    def test_escalating_feud_outranks_pleasantries(self):
        conn, ids = feud_world()
        pleasant = talk(conn, 50, "tom", "mary", "neutral")
        ranked, _ = rank_arcs(conn, {"john", "mary"})
        self.assertIn(ranked[0].arc.peak.id, ids)
        self.assertGreater(ranked[0].score, [c.score for c in ranked if c.arc.peak.id == pleasant][0])

    def test_selection_has_no_shared_events_or_pairs(self):
        conn, _ = feud_world()
        chosen, _ = select_top(conn, 5)
        seen: set[int] = set()
        pairs = set()
        for c in chosen:
            self.assertFalse(seen & set(c.arc.ids))
            self.assertNotIn(c.arc.peak.pair, pairs)
            seen |= set(c.arc.ids)
            pairs.add(c.arc.peak.pair)


class SceneSpecTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        conn = connect()
        init_db(conn, 184729)
        build_world(conn, 184729)
        d = SeededDecider(184729)
        Simulation(conn, d, d, set()).run(7)
        cls.conn = conn

    def test_top3_spec_is_valid_and_ids_are_stable(self):
        chosen, _ = select_top(self.conn, 3)
        self.assertEqual(len(chosen), 3)
        spec = build_spec(self.conn, chosen)
        validate_spec(self.conn, spec)
        assets: dict[str, str] = {}
        for scene in spec["scenes"]:
            for shot in scene["shots"]:
                for ch in shot["characters"]:
                    self.assertEqual(assets.setdefault(ch["id"], ch["asset_id"]), f"char_{ch['id']}")
        events = [e for s in spec["scenes"] for e in s["arc_event_ids"]]
        self.assertEqual(len(events), len(set(events)))

    def test_spec_is_deterministic(self):
        a = dumps(build_spec(self.conn, select_top(self.conn, 3)[0]))
        b = dumps(build_spec(self.conn, select_top(self.conn, 3)[0]))
        self.assertEqual(a, b)

    def test_validation_catches_bad_ids(self):
        spec = build_spec(self.conn, select_top(self.conn, 1)[0])
        spec["scenes"][0]["shots"][0]["characters"][0]["id"] = "sarah"
        with self.assertRaises(ValueError):
            validate_spec(self.conn, spec)


if __name__ == "__main__":
    unittest.main()
