from __future__ import annotations

import json
import sqlite3
import unittest

from tests.helpers import dump_state, seeded
from world.db import mutation
from world.events import Change, EventSpec, MemorySpec, apply_event
from world.state import WorldError, audit, relationship_history


def betray(ts: int, parent: int | None = None) -> EventSpec:
    """Mary lies to John. John believes her, Tom saw through it."""
    return EventSpec(
        timestamp=ts, type="lie", trigger_type="social", location_id="cafe", parent_event_id=parent,
        importance=0.7, truth={"actor": "mary", "act": "lied", "about": "the money"},
        participants=[("mary", "actor"), ("john", "target"), ("tom", "witness")],
        changes=[Change("relationship", "tom:mary", "trust", delta=-0.5)],
        memories=[
            MemorySpec("john", "Mary told me the truth", 0.9),
            MemorySpec("tom", "Mary lied to John", 0.9),
            MemorySpec("mary", "I lied to John", 1.0),
        ],
    )


class ApplyEventTests(unittest.TestCase):
    def setUp(self):
        self.conn = seeded()

    def tearDown(self):
        self.conn.close()

    def test_event_delta_state_and_memory_commit_together(self):
        eid = apply_event(self.conn, EventSpec(
            timestamp=5, type="purchase", trigger_type="rule", location_id="cafe",
            participants=[("john", "actor")],
            changes=[Change("person", "john", "money_cents", delta=-500), Change("person", "john", "hunger", delta=-8)],
            memories=[MemorySpec("john", "I bought coffee", 1.0)],
        ))
        john = self.conn.execute("SELECT * FROM people WHERE id='john'").fetchone()
        self.assertEqual((john["money_cents"], john["hunger"]), (11500, 2))
        d = self.conn.execute(
            "SELECT old_value, new_value, delta_value FROM event_deltas WHERE event_id=? AND field='money_cents'", (eid,)
        ).fetchone()
        self.assertEqual(tuple(d), (12000, 11500, -500))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM memories WHERE event_id=?", (eid,)).fetchone()[0], 1)
        self.assertEqual(audit(self.conn), [])

    def test_failed_event_leaves_no_trace(self):
        before = dump_state(self.conn)
        with self.assertRaises(sqlite3.IntegrityError):  # money would go negative
            apply_event(self.conn, EventSpec(
                timestamp=5, type="purchase", trigger_type="rule",
                changes=[Change("person", "mary", "hunger", delta=-5), Change("person", "john", "money_cents", delta=-99999)],
                memories=[MemorySpec("john", "x", 1.0)],
            ))
        self.assertEqual(dump_state(self.conn), before)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM mutation_guard").fetchone()[0], 0)

    def test_illegal_changes_are_rejected(self):
        bad = {
            "unknown person": Change("person", "sarah", "energy", delta=-1),
            "unknown relationship": Change("relationship", "john:tom", "trust", delta=0.1),
            "unknown field": Change("person", "john", "schedule", value="{}"),
            "unknown entity type": Change("planet", "mars", "energy", delta=1),
            "value on numeric": Change("person", "john", "energy", value=5),
            "delta on set": Change("person", "john", "goal", delta=1),
            "float on int field": Change("person", "john", "energy", delta=1.5),
            "malformed id": Change("relationship", "john", "trust", delta=0.1),
        }
        for name, ch in bad.items():
            with self.subTest(name), self.assertRaises(WorldError):
                apply_event(self.conn, EventSpec(timestamp=1, type="t", trigger_type="t", changes=[ch]))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0], 0)

    def test_unknown_participant_or_observer_rejected(self):
        with self.assertRaises(sqlite3.IntegrityError):
            apply_event(self.conn, EventSpec(timestamp=1, type="t", trigger_type="t", participants=[("sarah", "actor")]))
        with self.assertRaises(sqlite3.IntegrityError):
            apply_event(self.conn, EventSpec(timestamp=1, type="t", trigger_type="t", memories=[MemorySpec("sarah", "x", 1.0)]))

    def test_out_of_range_value_rejected(self):
        with self.assertRaises(sqlite3.IntegrityError):
            apply_event(self.conn, EventSpec(
                timestamp=1, type="t", trigger_type="t",
                changes=[Change("relationship", "john:mary", "trust", delta=0.6)],  # 0.6 + 0.6 > 1
            ))

    def test_time_cannot_go_backwards(self):
        apply_event(self.conn, EventSpec(timestamp=10, type="a", trigger_type="t"))
        with self.assertRaises(WorldError):
            apply_event(self.conn, EventSpec(timestamp=9, type="b", trigger_type="t"))

    def test_ownership_transfer_in_one_event(self):
        apply_event(self.conn, EventSpec(
            timestamp=3, type="steal", trigger_type="social",
            changes=[Change("object", "phone", "owner_person_id", value="john")],
        ))
        self.assertEqual(self.conn.execute("SELECT owner_person_id FROM objects").fetchone()[0], "john")
        # Dropping it on the floor needs owner and location changed together to satisfy the CHECK.
        apply_event(self.conn, EventSpec(
            timestamp=4, type="drop", trigger_type="social",
            changes=[Change("object", "phone", "owner_person_id", value=None), Change("object", "phone", "location_id", value="cafe")],
        ))
        row = self.conn.execute("SELECT owner_person_id, location_id FROM objects").fetchone()
        self.assertEqual(tuple(row), (None, "cafe"))
        self.assertEqual(audit(self.conn), [])

    def test_belief_diverges_from_truth_and_between_observers(self):
        eid = apply_event(self.conn, betray(10))
        truth = json.loads(self.conn.execute("SELECT truth FROM events WHERE event_id=?", (eid,)).fetchone()[0])
        self.assertEqual(truth["act"], "lied")
        beliefs = dict(self.conn.execute("SELECT observer_id, belief FROM memories WHERE event_id=?", (eid,)).fetchall())
        self.assertEqual(beliefs["john"], "Mary told me the truth")
        self.assertEqual(beliefs["tom"], "Mary lied to John")
        self.assertNotEqual(beliefs["john"], beliefs["tom"])

    def test_relationship_history_traces_to_cause_chain(self):
        e1 = apply_event(self.conn, betray(10))
        e2 = apply_event(self.conn, EventSpec(
            timestamp=20, type="discovery", trigger_type="social", parent_event_id=e1,
            changes=[Change("relationship", "john:mary", "trust", delta=-0.9)],
            memories=[MemorySpec("john", "Mary lied to me", 0.95)],
        ))
        hist = relationship_history(self.conn, "john", "mary", "trust")
        self.assertEqual([(h["event_id"], h["old_value"], h["new_value"]) for h in hist], [(e2, 0.6, -0.3)])
        self.assertEqual(hist[0]["parent_event_id"], e1)
        parent = self.conn.execute("SELECT type FROM events WHERE event_id=?", (e1,)).fetchone()[0]
        self.assertEqual(parent, "lie")

    def test_audit_detects_state_edited_without_event(self):
        apply_event(self.conn, EventSpec(
            timestamp=1, type="t", trigger_type="t", changes=[Change("person", "john", "energy", delta=-10)],
        ))
        self.assertEqual(audit(self.conn), [])
        # Simulate someone bypassing the service by faking the guard.
        self.conn.execute("INSERT INTO mutation_guard VALUES (1)")
        self.conn.execute("UPDATE people SET energy = 3 WHERE id = 'john'")
        self.conn.execute("DELETE FROM mutation_guard")
        problems = audit(self.conn)
        self.assertEqual([(p.entity_id, p.field) for p in problems], [("john", "energy")])

    def test_replay_is_deterministic(self):
        def run() -> list[tuple]:
            conn = seeded(world_seed=7)
            e1 = apply_event(conn, betray(10))
            apply_event(conn, EventSpec(
                timestamp=20, type="discovery", trigger_type="social", parent_event_id=e1,
                changes=[Change("relationship", "john:mary", "trust", delta=-0.9), Change("person", "john", "emotion", value="angry")],
            ))
            return dump_state(conn)

        self.assertEqual(run(), run())


if __name__ == "__main__":
    unittest.main()
