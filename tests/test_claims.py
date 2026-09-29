from __future__ import annotations

import sqlite3
import unittest

from contracts.claim import DENY, FALSE, PARTIAL, TRUE, UNKNOWN, Claim, distort, negate
from tests.helpers import seeded
from world.claims import evaluate
from world.db import mutation
from world.events import ClaimSpec, EventSpec, MemorySpec, apply_event
from world.intent import Intent
from world.rules import resolve
from world.state import WorldError


def theft(conn, ts=5):
    return apply_event(conn, resolve(conn, Intent("tom", "steal", "phone"), ts, "decision"))


class ClaimTests(unittest.TestCase):
    def setUp(self):
        self.conn = seeded(all_pairs=True)

    def tearDown(self):
        self.conn.close()

    def test_steal_records_truth_and_beliefs_reference_the_same_claim(self):
        eid = theft(self.conn)
        truth = self.conn.execute(
            "SELECT c.subject, c.act, c.object FROM event_claims ec JOIN claims c USING (claim_id) "
            "WHERE ec.event_id=? AND ec.role='truth'", (eid,)).fetchall()
        self.assertEqual([tuple(t) for t in truth], [("tom", "steal", "phone")])
        ids = {r[0] for r in self.conn.execute("SELECT DISTINCT claim_id FROM memories WHERE event_id=?", (eid,))}
        self.assertEqual(len(ids), 1)  # everyone who saw it holds the same proposition

    def test_evaluate_true_false_partial_unknown(self):
        eid = theft(self.conn)
        stole = Claim("tom", "steal", "phone")
        cases = {
            "exact": (stole, TRUE),
            "lie (polarity flip)": (negate(stole), FALSE),
            "distortion (same family)": (distort(stole), PARTIAL),
            "different object": (Claim("tom", "steal", "wallet"), PARTIAL),
            "someone else": (Claim("john", "steal", "phone"), UNKNOWN),
            "unrelated act": (Claim("tom", "speak_warm", "mary"), UNKNOWN),
        }
        for name, (claim, expected) in cases.items():
            with self.subTest(name):
                self.assertEqual(evaluate(self.conn, claim, eid), expected)
                self.assertEqual(evaluate(self.conn, claim), expected)

    def test_evaluate_can_be_scoped_to_one_event(self):
        a = theft(self.conn, 5)
        b = apply_event(self.conn, EventSpec(timestamp=6, type="x", trigger_type="t",
                                             claims=[ClaimSpec(Claim("john", "steal", "phone"))]))
        self.assertEqual(evaluate(self.conn, Claim("john", "steal", "phone"), a), UNKNOWN)
        self.assertEqual(evaluate(self.conn, Claim("john", "steal", "phone"), b), TRUE)

    def test_omission_keeps_withheld_claim_and_reports_true(self):
        kept, hidden = Claim("tom", "steal", "phone"), Claim("tom", "borrow", "wallet")
        eid = apply_event(self.conn, EventSpec(
            timestamp=5, type="x", trigger_type="t",
            claims=[ClaimSpec(kept, "truth"), ClaimSpec(hidden, "truth"), ClaimSpec(kept, "asserted"), ClaimSpec(hidden, "withheld")]))
        self.assertEqual(evaluate(self.conn, kept, eid), TRUE)  # what was said is true
        withheld = self.conn.execute(
            "SELECT COUNT(*) FROM event_claims WHERE event_id=? AND role='withheld'", (eid,)).fetchone()[0]
        self.assertEqual(withheld, 1)  # ...but something was held back, and it is on record

    def test_same_proposition_is_one_row_and_true_in_many_events(self):
        theft(self.conn, 5)
        self.conn.execute("SELECT 1")
        apply_event(self.conn, EventSpec(timestamp=6, type="again", trigger_type="t",
                                         claims=[ClaimSpec(Claim("tom", "steal", "phone"))]))
        rows = self.conn.execute("SELECT COUNT(*) FROM claims WHERE subject='tom' AND act='steal'").fetchone()[0]
        links = self.conn.execute("SELECT COUNT(*) FROM event_claims WHERE role='truth' AND claim_id="
                                  "(SELECT claim_id FROM claims WHERE subject='tom' AND act='steal')").fetchone()[0]
        self.assertEqual((rows, links), (1, 2))

    def test_general_belief_needs_a_source(self):
        general = Claim("mary", "steal", "phone")
        with self.assertRaises(WorldError):
            apply_event(self.conn, EventSpec(timestamp=1, type="x", trigger_type="t", memories=[
                MemorySpec("john", "Mary is a thief", 0.6, claim=general, about_self=False)]))
        first = theft(self.conn, 2)
        apply_event(self.conn, EventSpec(timestamp=3, type="x", trigger_type="t", memories=[
            MemorySpec("john", "Mary is a thief", 0.6, claim=general, about_self=False, source_type="inference",
                       derived_from_events=[first])]))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM memory_sources").fetchone()[0], 1)

    def test_told_by_must_name_a_real_person(self):
        with self.assertRaises(WorldError):
            apply_event(self.conn, EventSpec(timestamp=1, type="x", trigger_type="t", memories=[
                MemorySpec("john", "hearsay", 0.5, claim=Claim("tom", "steal", "phone"), source_type="told_by", source_id="sarah")]))

    def test_claims_are_append_only_and_need_a_mutation(self):
        theft(self.conn)
        with self.assertRaises(sqlite3.DatabaseError):
            self.conn.execute("UPDATE claims SET polarity='deny'")
        with self.assertRaises(sqlite3.DatabaseError):
            self.conn.execute("INSERT INTO claims(claim_hash, subject, act, object, polarity) VALUES ('h','a','steal','b','affirm')")
        with self.assertRaises(sqlite3.DatabaseError), mutation(self.conn):
            self.conn.execute("DELETE FROM event_claims")

    def test_claim_contract_rejects_unknown_act_and_hashes_by_content(self):
        with self.assertRaises(ValueError):
            Claim("a", "teleport", "b")
        self.assertEqual(Claim("a", "steal", "b").hash(), Claim("a", "steal", "b").hash())
        self.assertNotEqual(Claim("a", "steal", "b").hash(), Claim("a", "steal", "b", DENY).hash())


if __name__ == "__main__":
    unittest.main()
