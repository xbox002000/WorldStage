from __future__ import annotations

import unittest

from contracts.base import from_dict, schema_for, to_dict
from contracts.claim import FALSE, PARTIAL, TRUE, Claim
from contracts.tell import TELL_MODES, TellIntent
from tests.helpers import seeded
from world.claims import claim_id, evaluate
from world.db import mutation
from world.events import apply_event
from world.intent import Intent
from world.rules import resolve
from world.state import WorldError
from world.tell import asserted_claim, held_claim_ids, validate_tell


class TellTests(unittest.TestCase):
    def setUp(self):
        self.conn = seeded(john_at="cafe", all_pairs=True)  # john, mary, tom all at the cafe
        self.theft = apply_event(self.conn, resolve(self.conn, Intent("tom", "steal", "phone"), 5, "decision"))
        self.talk = apply_event(self.conn, resolve(self.conn, Intent("tom", "talk", "john", "warm"), 6, "decision"))
        with mutation(self.conn):
            self.stole = claim_id(self.conn, Claim("tom", "steal", "phone"))
            self.spoke = claim_id(self.conn, Claim("tom", "speak_warm", "john"))
        self.john = held_claim_ids(self.conn, "john")

    def tell(self, mode, source=None, withheld=()):
        return TellIntent("john", "mary", mode, source or self.stole, list(withheld))

    def test_john_holds_what_he_witnessed(self):
        self.assertTrue({self.stole, self.spoke} <= self.john)

    def test_each_mode_evaluates_as_designed(self):
        expected = {"truth": TRUE, "lie": FALSE, "distortion": PARTIAL}
        for mode, verdict in expected.items():
            with self.subTest(mode):
                t = self.tell(mode)
                validate_tell(self.conn, t)
                self.assertEqual(evaluate(self.conn, asserted_claim(self.conn, t), self.theft), verdict)

    def test_omission_says_something_true_and_names_what_it_hides(self):
        t = self.tell("omission", withheld=[self.spoke])
        validate_tell(self.conn, t)
        self.assertEqual(asserted_claim(self.conn, t), Claim("tom", "steal", "phone"))
        self.assertEqual(evaluate(self.conn, asserted_claim(self.conn, t), self.theft), TRUE)

    def test_a_claim_the_actor_does_not_hold_is_rejected(self):
        with mutation(self.conn):
            unknown = claim_id(self.conn, Claim("mary", "steal", "phone"))
        with self.assertRaises(WorldError):
            validate_tell(self.conn, self.tell("truth", source=unknown))

    def test_illegal_tells_are_rejected(self):
        bad = {
            "unknown mode": self.tell("gossip"),
            "withhold without omission": self.tell("truth", withheld=[self.spoke]),
            "omission hiding nothing": self.tell("omission"),
            "withholding the source itself": self.tell("omission", withheld=[self.stole]),
            "withholding an unheld claim": self.tell("omission", withheld=[999]),
            "tell self": TellIntent("john", "john", "truth", self.stole, []),
            "tell a stranger": TellIntent("john", "sarah", "truth", self.stole, []),
        }
        for name, intent in bad.items():
            with self.subTest(name), self.assertRaises(WorldError):
                validate_tell(self.conn, intent)

    def test_not_in_the_same_place_is_rejected(self):
        far = seeded(all_pairs=True)  # john at home, tom and mary at the cafe
        apply_event(far, resolve(far, Intent("tom", "steal", "phone"), 5, "decision"))
        with mutation(far):
            cid = claim_id(far, Claim("tom", "steal", "phone"))
        with self.assertRaises(WorldError):
            validate_tell(far, TellIntent("mary", "john", "truth", cid, []))

    def test_contract_round_trips_and_has_a_schema(self):
        t = self.tell("lie")
        self.assertEqual(from_dict(TellIntent, to_dict(t)), t)
        self.assertEqual(set(TELL_MODES), {"truth", "omission", "lie", "distortion"})
        self.assertIn("mode", schema_for(TellIntent)["$defs"]["TellIntent"]["required"])


if __name__ == "__main__":
    unittest.main()
