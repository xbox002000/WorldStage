"""Decision records (agent/trace.py): the events of worlds with exchanges say why a choice was made, and saying so
changes nothing about what happens."""
from __future__ import annotations

import json
import unittest

from agent.trace import bias_keys, build
from agent.volition import TEMPERATURE, VolitionDecider
from world.db import connect, init_db
from world.events import Change, EventSpec, apply_event
from world.intent import Intent
from world.seed import build_world
from world.simulation import Simulation


def run(recipe: str, seed: int, days: int, trace: bool):
    conn = connect()
    init_db(conn, seed)
    build_world(conn, seed, recipe)
    d = VolitionDecider(seed)
    sim = Simulation(conn, d, d, set(), feed="synthetic_v1")
    sim.trace = trace and sim.trace
    sim.run(days)
    return conn


def stream(conn) -> list:
    """Every event, in order, with what it said except the record of why."""
    out = []
    for r in conn.execute("SELECT event_id, type, timestamp, location_id, importance, truth FROM events ORDER BY event_id"):
        t = json.loads(r["truth"])
        t.pop("influences", None)
        out.append((r["event_id"], r["type"], r["timestamp"], r["location_id"], r["importance"], json.dumps(t, sort_keys=True)))
    return out


def setvar(conn, key: str, value: float) -> None:
    cur = conn.execute("SELECT value FROM world_vars WHERE key = ?", (key,)).fetchone()
    apply_event(conn, EventSpec(timestamp=0, type="setup", trigger_type="rule", location_id=None,
                                changes=[Change("var", key, "value", delta=value - (cur[0] if cur else 0.0))]))


class Recording(unittest.TestCase):
    def test_recording_changes_nothing(self):
        for recipe, seed in (("town_life_v1", 3), ("town_in_jianghu_v1", 5)):
            on, off = run(recipe, seed, 6, True), run(recipe, seed, 6, False)
            self.assertTrue(on.execute("SELECT COUNT(*) FROM events WHERE json_extract(truth,'$.influences') IS NOT NULL").fetchone()[0] > 50)
            self.assertEqual(off.execute("SELECT COUNT(*) FROM events WHERE json_extract(truth,'$.influences') IS NOT NULL").fetchone()[0], 0)
            self.assertEqual(stream(on), stream(off), recipe)

    def test_worlds_without_exchanges_are_not_touched(self):
        conn = run("town_v1", 3, 4, True)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM events WHERE json_extract(truth,'$.influences') IS NOT NULL").fetchone()[0], 0)

    def test_a_record_is_a_distribution(self):
        conn = run("town_life_v1", 3, 8, True)
        rows = [json.loads(r[0])["influences"] for r in conn.execute(
            "SELECT truth FROM events WHERE json_extract(truth,'$.influences') IS NOT NULL")]
        self.assertTrue(rows)
        for inf in rows:
            self.assertTrue(0.0 < inf["p"] <= 1.0)
            ps = [o["p"] for o in inf["options"]]
            self.assertLessEqual(sum(ps), 1.0 + 0.003)  # each rounded to three places
            self.assertLessEqual(len(ps), 3)
            self.assertIn(inf["p"], ps)  # the chosen one is always shown
        answers = [i for i in rows if i.get("situation", {}).get("kind") == "reply"]
        self.assertTrue(answers)
        self.assertTrue(all(isinstance(a["situation"]["to"], int) for a in answers))  # what it answered, as an event id


class Factors(unittest.TestCase):
    def setUp(self):
        self.conn = connect()
        init_db(self.conn, 3)
        build_world(self.conn, 3, "town_life_v1")

    def test_bias_keys(self):
        self.assertEqual(bias_keys(None), {"withdraw"})
        self.assertEqual(bias_keys(Intent("a", "accuse", "b")), {"accuse"})
        self.assertEqual(bias_keys(Intent("a", "talk", "b", "hostile", reason="reply:retort")), {"retort", "defend"})
        self.assertEqual(bias_keys(Intent("a", "talk", "b", "warm", reason="reply:apologize")), {"apologize"})
        self.assertEqual(bias_keys(Intent("a", "move", "park")), set())

    def test_a_held_self_model_that_leans_the_options_is_named(self):
        setvar(self.conn, "psy.ming.self.cannot_trust", 1.0)
        accuse, idle = Intent("ming", "accuse", "mei"), None
        scored = [(0.5, idle), (0.4, accuse)]
        rec = build(self.conn, "ming", scored, accuse, TEMPERATURE, 600)
        f = [x for x in rec["factors"] if x["kind"] == "self_model"]
        self.assertEqual([(x["key"], x["leans"]) for x in f], [("cannot_trust", {"accuse": 0.3})])
        # a self-model that leans nothing in play is not named
        setvar(self.conn, "psy.ming.self.on_my_own", 1.0)
        rec2 = build(self.conn, "ming", [(0.5, Intent("ming", "move", "park")), (0.4, Intent("ming", "work"))],
                     Intent("ming", "work"), TEMPERATURE, 600)
        self.assertNotIn("factors", rec2)

    def test_a_goal_that_pushed_the_option_is_named(self):
        it = Intent("ming", "talk", "mei", "cold", reason="goal:ming:1")
        rec = build(self.conn, "ming", [(0.5, None), (0.9, it)], it, TEMPERATURE, 600)
        self.assertIn({"kind": "goal", "slot": "ming:1"}, rec["factors"])

    def test_the_body_is_named_when_it_is_worked_up(self):
        setvar(self.conn, "body.arousal.ming", 0.8)
        setvar(self.conn, "body.arousal_at.ming", 600)
        rec = build(self.conn, "ming", [(0.5, None), (0.4, Intent("ming", "accuse", "mei"))], None, TEMPERATURE, 600)
        body = [x for x in rec["factors"] if x["kind"] == "body"]
        self.assertEqual(len(body), 1)
        self.assertGreater(body[0]["arousal"], 0.5)
        self.assertIn("control", body[0])
        # calm and rested: nothing to say
        rec = build(self.conn, "mei", [(0.5, None)], None, TEMPERATURE, 600)
        self.assertNotIn("factors", rec)

    def test_losing_control_carries_the_body_that_caused_it(self):
        from agent.volition import seizure
        setvar(self.conn, "body.arousal.ming", 1.0)
        setvar(self.conn, "body.arousal_at.ming", 600)
        seized = None
        for minute in range(600, 700):  # a seizure is a chance, decided by the seed: find the minute it happens
            seized = seizure(self.conn, "ming", minute, ["mei"])
            if seized is not None:
                break
        self.assertIsNotNone(seized)
        self.assertTrue(seized.trace["seized"])
        self.assertEqual(seized.trace["factors"][0]["kind"], "body")


if __name__ == "__main__":
    unittest.main()
