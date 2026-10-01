"""A word gets an answer (social.exchange), and what is worth watching can be found and read back.

- Replies are ordinary decisions: each answers the previous turn, from the one it was said to, in the same place, and
  the world's clock never runs backwards; walking out keeps its reason; the same seed gives the same world.
- The runtime says every line in turn (voice bookings) and all its invariants still hold.
- Lines, scenes and the dramaturgy analysis are read models: they change nothing and cite only real events.
- The cafe has a seat for everyone at lunch.
"""
from __future__ import annotations

import json
import unittest

from agent.volition import VolitionDecider
from world.db import connect, init_db
from world.seed import build_world
from world.simulation import Simulation
from world.snapshot import snapshot_hash

SEED = 260934


def _world(days: int):
    c = connect()
    init_db(c, SEED)
    build_world(c, SEED, "town_spatial_v1")
    d = VolitionDecider(SEED)
    Simulation(c, d, d, set(), feed="synthetic_v1").run(days)
    return c


class ExchangeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = _world(2)
        cls.rows = cls.c.execute("SELECT * FROM events ORDER BY event_id").fetchall()

    def test_replies_happen_and_each_answers_the_turn_before(self):
        replies = 0
        prev = None
        for r in self.rows:
            t = json.loads(r["truth"])
            reason = t.get("reason") or ""
            if reason.startswith("reply:") and r["type"] == "talk":
                replies += 1
                self.assertIsNotNone(prev)
                p = json.loads(prev["truth"])
                self.assertEqual(t["actor"], p["target"], r["event_id"])  # answered by the one it was said to
                self.assertEqual(t["target"], p["actor"], r["event_id"])
                self.assertEqual(r["location_id"], prev["location_id"])
            if r["type"] in ("talk", "accuse", "confront") and not reason.startswith("intervene:"):
                prev = r
            elif r["type"] not in ("goal_change", "reflection") and not reason.startswith("intervene:"):
                prev = None
        self.assertGreater(replies, 10)

    def test_the_clock_never_runs_backwards(self):
        ts = [r["timestamp"] for r in self.rows]
        self.assertEqual(ts, sorted(ts))

    def test_walking_out_keeps_its_reason(self):
        outs = [r for r in self.rows if r["type"] == "move" and json.loads(r["truth"]).get("reason") == "reply:storm_off"]
        for r in outs:
            self.assertNotEqual(json.loads(r["truth"])["from"], json.loads(r["truth"])["to"])

    def test_same_seed_same_world(self):
        other = _world(1)
        mine = connect()
        init_db(mine, SEED)
        build_world(mine, SEED, "town_spatial_v1")
        d = VolitionDecider(SEED)
        Simulation(mine, d, d, set(), feed="synthetic_v1").run(1)
        self.assertEqual(snapshot_hash(other), snapshot_hash(mine))

    def test_the_runtime_says_each_line_in_turn_and_its_laws_hold(self):
        from runtime.world_runtime import WorldRuntime
        rt = WorldRuntime(self.c)
        rt.advance()
        for k, rows in rt.invariants().items():
            self.assertEqual(rows, [], k)
        says = sorted((a for a in rt.actions if a.kind == "say"), key=lambda a: a.start)
        self.assertTrue(says)
        by_voice: dict[str, list] = {}
        for a in says:  # nobody says two things at once, nor talks over the one speaking to them
            for who in (a.actor, a.target):
                for s, e in by_voice.get(who, []):
                    self.assertFalse(a.start < e - 1e-6 and s < a.end - 1e-6, (a.event_id, who))
                by_voice.setdefault(who, []).append((a.start, a.end))


class ReadModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = _world(1)
        cls.before = snapshot_hash(cls.c)
        cls.events = {r[0] for r in cls.c.execute("SELECT event_id FROM events")}

    def test_every_social_event_has_a_line(self):
        from narrative.lines import line
        names = {r[0]: r[1] for r in self.c.execute("SELECT id, name FROM people")}
        for eid, etype, truth in self.c.execute("SELECT event_id, type, truth FROM events WHERE type IN "
                                                "('talk', 'tell', 'confront', 'accuse')"):
            got = line(eid, etype, truth, names)
            self.assertTrue(got and got["say"], (eid, etype))
            self.assertNotIn("{", got["say"])

    def test_scenes_are_made_of_real_events_and_start_with_an_opener(self):
        from narrative.scenes import OPENERS, scenes
        found = scenes(self.c)
        self.assertTrue(found)
        for s in found:
            self.assertTrue(set(s["events"]) <= self.events)
            first = self.c.execute("SELECT type FROM events WHERE event_id = ?", (s["events"][0],)).fetchone()[0]
            self.assertIn(first, OPENERS)
        self.assertEqual(snapshot_hash(self.c), self.before)

    def test_dramaturgy_only_reads_and_cites_real_events(self):
        from narrative.dramaturgy import analyse
        rep = analyse(self.c)
        self.assertTrue(rep["situations"])
        for s in rep["situations"]:
            self.assertTrue(set(s["events"]) <= self.events, s)
            self.assertTrue(s["question"].endswith("？"))
            self.assertLessEqual(s["potential"], 1.0)
        self.assertEqual(snapshot_hash(self.c), self.before)


class CafeTests(unittest.TestCase):
    def test_a_seat_for_everyone_at_lunch(self):
        from narrative.layouts import LAYOUTS
        from world.seed import PEOPLE
        seats = [k for k in LAYOUTS["cafe"]["anchors"] if ".seat" in k]
        self.assertGreaterEqual(len(seats), len(PEOPLE) + 5)

    def test_people_talking_stand_close_enough_to_talk(self):
        from narrative.layouts import LAYOUTS
        for loc, lay in LAYOUTS.items():
            for a, b in lay.get("pairs", []):
                (xa, ya, _), (xb, yb, _) = lay["anchors"][a], lay["anchors"][b]
                self.assertLessEqual(((xa - xb) ** 2 + (ya - yb) ** 2) ** 0.5, 2.0, (loc, a, b))

    def test_a_bar_stool_faces_the_bar(self):
        from runtime.world_runtime import WorldRuntime
        from narrative.layouts import LAYOUTS
        lay = LAYOUTS["cafe"]
        self.assertEqual(WorldRuntime._facing(lay, "cafe.counter.seat_1", *lay["anchors"]["cafe.counter.seat_1"][:2]), 90.0)


if __name__ == "__main__":
    unittest.main()
