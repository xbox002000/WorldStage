from __future__ import annotations

import sqlite3
import unittest

from tests.helpers import seeded
from world.db import mutation


def insert_event(conn, ts=10, parent=None, etype="t"):
    return conn.execute(
        "INSERT INTO events(timestamp, type, location_id, parent_event_id, trigger_type) VALUES (?,?,?,?,?)",
        (ts, etype, "home", parent, "test"),
    ).lastrowid


def insert_delta(conn, event_id, field, old, new, delta, kind="numeric"):
    conn.execute(
        "INSERT INTO event_deltas(event_id, entity_type, entity_id, field, old_value, new_value, delta_value, value_kind) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (event_id, "person", "john", field, old, new, delta, kind),
    )


class SchemaTests(unittest.TestCase):
    def setUp(self):
        self.conn = seeded()

    def tearDown(self):
        self.conn.close()

    def test_foreign_keys_enforced(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("INSERT INTO people VALUES ('x','X','nowhere',1,0,0,'g','c','{}','active')")

    def test_relationship_range_and_self_edge(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("INSERT INTO relationships(actor_id, target_id) VALUES ('john','john')")
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("INSERT INTO relationships(actor_id, target_id, trust) VALUES ('john','tom',2)")

    def test_object_single_owner(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("INSERT INTO objects(id, name, owner_person_id, location_id) VALUES ('o','O','john','home')")

    def test_numeric_delta_must_add_up(self):
        with mutation(self.conn):
            e = insert_event(self.conn)
            insert_delta(self.conn, e, "money_cents", 12000, 11500, -500)
        with self.assertRaises(sqlite3.DatabaseError), mutation(self.conn):
            e = insert_event(self.conn, 11)
            insert_delta(self.conn, e, "energy", 100, 80, -30)

    def test_numeric_delta_rejects_text(self):
        # Regression: CAST('abc' AS REAL) is 0.0 in SQLite, so a CAST-based check lets this through.
        with self.assertRaises(sqlite3.DatabaseError), mutation(self.conn):
            e = insert_event(self.conn)
            insert_delta(self.conn, e, "energy", "abc", "abc", "abc")

    def test_set_delta_cannot_carry_delta_value(self):
        with self.assertRaises(sqlite3.DatabaseError), mutation(self.conn):
            e = insert_event(self.conn)
            insert_delta(self.conn, e, "goal", "a", "b", 1, kind="set")

    def test_history_is_append_only(self):
        with mutation(self.conn):
            e = insert_event(self.conn)
            insert_delta(self.conn, e, "energy", 100, 90, -10)
            self.conn.execute(
                "INSERT INTO memories(observer_id, event_id, belief, confidence, created_at) VALUES ('john',?,'b',0.9,10)", (e,)
            )
        for sql in (
            "UPDATE events SET type='x'",
            "DELETE FROM events",
            "UPDATE event_deltas SET new_value=99",
            "DELETE FROM event_deltas",
            "UPDATE memories SET confidence=0.1",
            "DELETE FROM memories",
        ):
            with self.subTest(sql=sql), self.assertRaises(sqlite3.DatabaseError), mutation(self.conn):
                self.conn.execute(sql)

    def test_parent_must_exist_and_not_be_later(self):
        with mutation(self.conn):
            parent = insert_event(self.conn, 20)
            insert_event(self.conn, 21, parent)
        with self.assertRaises(sqlite3.DatabaseError), mutation(self.conn):
            insert_event(self.conn, 19, parent)
        with self.assertRaises(sqlite3.DatabaseError), mutation(self.conn):
            insert_event(self.conn, 30, 999999)

    def test_writes_outside_mutation_are_refused(self):
        with self.assertRaises(sqlite3.DatabaseError):
            insert_event(self.conn)
        # Seeding is allowed before the first event, updates never are.
        with self.assertRaises(sqlite3.DatabaseError):
            self.conn.execute("UPDATE people SET money_cents = 1 WHERE id = 'john'")
        with self.assertRaises(sqlite3.DatabaseError):
            self.conn.execute("DELETE FROM people WHERE id = 'john'")

    def test_no_seeding_after_first_event(self):
        with mutation(self.conn):
            insert_event(self.conn)
        with self.assertRaises(sqlite3.DatabaseError):
            self.conn.execute("INSERT INTO people VALUES ('new','New','home',1,0,0,'g','c','{}','active')")


if __name__ == "__main__":
    unittest.main()
