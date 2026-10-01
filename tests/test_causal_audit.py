"""The causal audit (narrative/causal_audit.py): a choice a self-model leaned can be followed back to the events that
made the self-model, and a broken chain is found."""
from __future__ import annotations

import json
import unittest

from agent.volition import VolitionDecider
from narrative.causal_audit import audit, experiences, interpretations, three_memories, trace
from world.db import connect, init_db
from world.events import Change, EventSpec, apply_event
from world.seed import build_world
from world.simulation import Simulation


def lived(recipe: str, seed: int, days: int):
    conn = connect()
    init_db(conn, seed)
    build_world(conn, seed, recipe)
    d = VolitionDecider(seed)
    Simulation(conn, d, d, set(), feed="synthetic_v1").run(days)
    return conn


class Audit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.conn = lived("town_life_v1", 3, 30)

    def test_the_sample_of_chains_is_whole(self):
        a = audit(self.conn, 20, seed=1)
        self.assertEqual(a["checked"], 20)  # there are plenty of choices a self-model was leaning
        self.assertEqual(a["whole"], 20, a["failures"][:1])

    def test_a_chain_goes_from_a_choice_to_raw_events(self):
        eid = self.conn.execute("SELECT event_id FROM events WHERE json_extract(truth,'$.influences.factors') LIKE '%self_model%' "
                                "ORDER BY event_id LIMIT 1 OFFSET 100").fetchone()[0]
        chain = trace(self.conn, eid)
        link = chain["links"][0]
        self.assertTrue(chain["whole"])
        self.assertEqual(link["kind"], "self_model")
        formed = self.conn.execute("SELECT type, timestamp FROM events WHERE event_id = ?", (link["formed_by"],)).fetchone()
        self.assertEqual(formed["type"], "reflection")
        self.assertLess(formed["timestamp"], self.conn.execute("SELECT timestamp FROM events WHERE event_id = ?", (eid,)).fetchone()[0])
        for b in link["because"]:  # every experience behind it is a real event the person was part of, before the reflection
            self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM event_participants WHERE event_id = ? AND person_id = ?",
                                               (b["event"], chain["actor"])).fetchone()[0] > 0, True)
        self.assertTrue(link["because"])

    def test_three_memories(self):
        who = next(r[0] for r in self.conn.execute("SELECT person_id FROM character_profiles ORDER BY person_id")
                   if interpretations(self.conn, r[0]))
        m = three_memories(self.conn, who)
        self.assertTrue(m["facts"] and m["experiences"] and m["interpretations"])
        i = m["interpretations"][0]
        self.assertTrue(i["because"])
        self.assertTrue(all(b["kind"] == {"cannot_trust": "betrayal", "always_blamed": "wronged", "on_my_own": "failure",
                                          "some_are_kind": "kindness", "world_is_hostile": "hostility"}[i["key"]] for b in i["because"]))
        # the experiences of one night add up to what the reflection says about it
        e = experiences(self.conn, who)[0]
        r = json.loads(self.conn.execute("SELECT truth FROM events WHERE event_id = ?", (e["reflection"],)).fetchone()[0])
        self.assertAlmostEqual(sum(w for ev, w in r["experienced"][e["kind"]]), r["experiences"][e["kind"]], places=2)

    def test_an_event_with_no_record_has_no_chain(self):
        eid = self.conn.execute("SELECT event_id FROM events WHERE type = 'backstory'").fetchone()[0]
        self.assertIsNone(trace(self.conn, eid))
        self.assertIsNone(trace(self.conn, 10 ** 9))

    def test_a_broken_chain_is_found(self):
        """A choice that claims a self-model nobody ever formed cannot be traced."""
        conn = lived("town_life_v1", 3, 1)
        pid = "ming"
        eid = apply_event(conn, EventSpec(
            timestamp=2000, type="talk", trigger_type="decision", location_id="cafe", importance=0.1,
            truth={"actor": pid, "target": "mei", "tone": "hostile",
                   "influences": {"p": 0.5, "options": [{"action": "talk", "p": 0.5}],
                                  "factors": [{"kind": "self_model", "key": "cannot_trust", "strength": 1.0, "leans": {"accuse": 0.3}}]}},
            participants=[(pid, "actor"), ("mei", "target")]))
        chain = trace(conn, eid)
        self.assertFalse(chain["whole"])
        self.assertIn("no reflection formed", chain["links"][0]["problems"][0])
        a = audit(conn, 5)
        self.assertEqual((a["checked"], a["whole"]), (1, 0))

    def test_old_worlds_have_nothing_to_audit_and_that_is_not_a_failure(self):
        conn = lived("town_v1", 3, 5)
        self.assertEqual(audit(conn, 20), {"candidates": 0, "checked": 0, "whole": 0, "failures": []})
        self.assertEqual(experiences(conn, "ming"), [])  # their reflections never listed events


if __name__ == "__main__":
    unittest.main()
