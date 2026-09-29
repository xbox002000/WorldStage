from __future__ import annotations

import unittest

from tests.helpers import seeded
from world.events import Change, EventSpec, apply_event
from world.intent import Intent, parse_intent, validate
from world.state import WorldError


class ValidatorTests(unittest.TestCase):
    def setUp(self):
        self.conn = seeded()
        self.conn.execute("UPDATE locations SET tags='[\"food\"]' WHERE id='cafe'")  # seeding phase: allowed
        self.conn.execute("UPDATE locations SET tags='[\"home\"]' WHERE id='home'")

    def tearDown(self):
        self.conn.close()

    def rejects(self, intent: Intent) -> str:
        with self.assertRaises(WorldError) as cm:
            validate(self.conn, intent)
        return str(cm.exception)

    def test_legal_intents_pass(self):
        validate(self.conn, Intent("john", "move", "cafe"))
        validate(self.conn, Intent("mary", "talk", "tom", "warm"))
        validate(self.conn, Intent("mary", "eat"))
        validate(self.conn, Intent("tom", "steal", "phone"))

    def test_illegal_intents_are_rejected(self):
        cases = {
            "unknown actor": Intent("ghost", "move", "cafe"),
            "unknown action": Intent("john", "fly", "cafe"),
            "unknown location": Intent("john", "move", "moon"),
            "unreachable location": (self.conn.execute("INSERT INTO locations VALUES ('far','Far',9,9,5,'[]')"),
                                     Intent("john", "move", "far"))[1],
            "invented person": Intent("mary", "talk", "sarah", "warm"),
            "talk to self": Intent("mary", "talk", "mary", "warm"),
            "person elsewhere": Intent("john", "talk", "mary", "warm"),
            "bad tone": Intent("mary", "talk", "tom", "furious"),
            "invented object": Intent("tom", "steal", "sword"),
            "own object": Intent("mary", "steal", "phone"),
            "no food here": Intent("john", "eat"),
            "no work here": Intent("mary", "work"),
        }
        for name, intent in cases.items():
            with self.subTest(name):
                self.rejects(intent)

    def test_owner_must_be_present_to_steal(self):
        apply_event(self.conn, EventSpec(
            timestamp=1, type="move", trigger_type="t", changes=[Change("person", "mary", "location_id", value="home")],
        ))
        self.assertIn("owner is not here", self.rejects(Intent("tom", "steal", "phone")))

    def test_poor_actor_cannot_eat_and_full_place_refuses(self):
        apply_event(self.conn, EventSpec(
            timestamp=1, type="spend", trigger_type="t", changes=[Change("person", "tom", "money_cents", delta=-4500)],
        ))
        self.assertIn("money", self.rejects(Intent("tom", "eat")))
        self.conn.execute("INSERT INTO locations VALUES ('closet','Closet',9,9,0,'[]')")
        self.conn.execute("INSERT INTO location_edges VALUES ('home','closet',1)")
        self.assertIn("full", self.rejects(Intent("john", "move", "closet")))

    def test_parse_intent_never_trusts_model_for_actor(self):
        it = parse_intent("john", {"actor": "mary", "action": "talk", "target": "tom", "tone": "warm", "priority": 9})
        self.assertEqual((it.actor, it.priority), ("john", 1.0))
        with self.assertRaises(WorldError):
            parse_intent("john", "not a dict")  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
