"""Goal dynamics and who-knows-what: goals change only by events that name their cause."""
from __future__ import annotations

import json
import sqlite3
import unittest

from agent.volition import VolitionDecider
from contracts.claim import Claim
from narrative.knowledge import knowledge_of
from narrative.threads import derive_threads
from tests.test_world_c import act, fresh, put
from world.events import EventSpec, apply_event
from world.goals import find, goals_of, overnight
from world.intent import Intent
from world.items import misplace, notice_missing
from world.simulation import Simulation
from world.state import audit


def goal_events(conn) -> list[dict]:
    return [dict(json.loads(t), event_id=i, parent=p) for i, t, p in
            conn.execute("SELECT event_id, truth, parent_event_id FROM events WHERE type = 'goal_change' ORDER BY event_id")]


def after(conn, event_id: int) -> None:
    from world.goals import after_event
    for spec in after_event(conn, event_id):
        apply_event(conn, spec)


class GoalStateTests(unittest.TestCase):
    def test_personas_start_with_goals_and_goals_only_change_by_events(self):
        conn = fresh()
        self.assertEqual(find(conn, "yun", "keep_secret")["object"], "yun:take:ring_mei")
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute("UPDATE goals SET status = 'completed' WHERE person_id = 'yun'")

    def test_a_long_run_keeps_goals_consistent_with_history(self):
        conn = fresh(260933)
        d = VolitionDecider(260933)
        Simulation(conn, d, d, set(), feed="synthetic_v1").run(10)
        self.assertEqual(audit(conn), [])
        self.assertTrue(goal_events(conn))
        for g in goal_events(conn):
            if g["to"] in ("formed", "transformed") and g["cause_event"]:
                self.assertEqual(g["parent"], g["cause_event"])


class GoalLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.c = fresh()
        put(self.c, 10, ming="cafe", jun="cafe", tao="cafe")
        apply_event(self.c, misplace(self.c, "ming", "wallet_ming", 20))
        act(self.c, Intent("jun", "take", "wallet_ming"), 40)
        eid = apply_event(self.c, notice_missing(self.c, "ming", "wallet_ming", 50))
        after(self.c, eid)

    def test_missing_a_thing_forms_a_goal_to_recover_it(self):
        g = find(self.c, "ming", "recover", obj="wallet_ming")
        self.assertIsNotNone(g)
        self.assertEqual(goal_events(self.c)[-1]["why"], "發現東西不見了")

    def test_a_denial_turns_recovering_into_exposing_and_a_false_charge_breeds_a_grudge(self):
        c = self.c
        mem = c.execute("SELECT m.memory_id, c.subject FROM memories m JOIN claims c USING (claim_id) "
                        "WHERE m.observer_id = 'ming' AND c.act = 'take'").fetchone()
        eid = c.execute("SELECT MAX(event_id) FROM events").fetchone()[0]
        outcome = act(c, Intent("ming", "accuse", mem["subject"], memory_id=mem["memory_id"]), 60)["outcome"]
        after(c, c.execute("SELECT MAX(event_id) FROM events WHERE type = 'accuse'").fetchone()[0])
        if outcome == "denied":
            expose = find(c, "ming", "expose", mem["subject"], "wallet_ming")
            self.assertIsNotNone(expose)
            self.assertEqual(expose["parent"].split(":")[0], "ming")
            self.assertIsNone(find(c, "ming", "recover", obj="wallet_ming"))  # it became the new goal
        elif outcome == "false":
            accused = mem["subject"]
            self.assertTrue(find(c, accused, "revenge", "ming") or find(c, accused, "clear_name", "ming"))
        else:
            self.assertIsNone(find(c, "ming", "recover", obj="wallet_ming"))
        self.assertGreater(c.execute("SELECT MAX(event_id) FROM events").fetchone()[0], eid)

    def test_getting_it_back_completes_the_goal(self):
        c = self.c
        act(c, Intent("jun", "give", "wallet_ming"), 70)
        after(c, c.execute("SELECT MAX(event_id) FROM events WHERE type = 'give'").fetchone()[0])
        self.assertIsNone(find(c, "ming", "recover", obj="wallet_ming"))
        self.assertEqual(goal_events(c)[-1]["to"], "completed")

    def test_revenge_cools_down(self):
        c = self.c
        act(c, Intent("tao", "talk", "jun", "neutral"), 55)
        from world.goals import GoalWriter
        w = GoalWriter(c, 60, None)
        w.form("tao", "revenge", "jun", "", 0.6, 0, "test")
        for spec in w.out:
            apply_event(c, spec)
        for spec in overnight(c, 6, 6 * 1440 + 1439):
            apply_event(c, spec)
        self.assertIsNone(find(c, "tao", "revenge", "jun"))
        self.assertEqual(audit(c), [])


class KnowledgeTests(unittest.TestCase):
    def test_the_owner_of_a_missing_thing_is_in_the_dark_until_told(self):
        c = fresh()
        put(c, 10, ming="cafe", jun="cafe")
        apply_event(c, misplace(c, "ming", "wallet_ming", 20))
        put(c, 30, ming="office")
        act(c, Intent("jun", "take", "wallet_ming"), 40)
        t = next(t for t in derive_threads(c) if t.thread_id == "item:wallet_ming")
        k = knowledge_of(c, t)
        self.assertIn("jun", k.knows)
        self.assertIn("ming", k.unaware)
        self.assertGreater(k.gap, 0)
        taken = c.execute("SELECT event_id FROM events WHERE type = 'take'").fetchone()[0]
        self.assertTrue(knowledge_of(c, t, {taken}).irony)  # the audience saw it; the owner does not know

    def test_honest_slips_in_retelling_are_not_lies(self):
        conn = fresh(260930)
        d = VolitionDecider(260930)
        Simulation(conn, d, d, set(), feed="synthetic_v1").run(10)
        slips = [json.loads(t) for (t,) in conn.execute(
            "SELECT truth FROM events WHERE type = 'tell' AND json_extract(truth, '$.misremembered') = 1")]
        self.assertTrue(slips)
        self.assertTrue(all(s["mode"] in ("truth", "omission") for s in slips))


if __name__ == "__main__":
    unittest.main()
