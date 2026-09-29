from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest

from tests.helpers import seeded
from world.db import SCHEMA_VERSION, connect, init_db, migrate, schema_version
from world.events import Change, EventSpec, MemorySpec, apply_event
from world.reader import open_world_reader
from world.ruleset import ROOT, ruleset_hash, ruleset_manifest
from world.snapshot import snapshot_hash, snapshot_manifest, world_revision, world_time
from world.state import WorldError, audit


def some_events(conn):
    apply_event(conn, EventSpec(timestamp=10, type="a", trigger_type="t",
                                changes=[Change("person", "john", "energy", delta=-5)]))
    apply_event(conn, EventSpec(timestamp=20, type="b", trigger_type="t",
                                changes=[Change("relationship", "john:mary", "trust", delta=-0.25)]))


class RevisionAndTimeTests(unittest.TestCase):
    def test_revision_and_time_only_move_with_events(self):
        conn = seeded()
        self.assertEqual((world_revision(conn), world_time(conn)), (0, 0))
        some_events(conn)
        self.assertEqual((world_revision(conn), world_time(conn)), (2, 20))
        with self.assertRaises(WorldError):
            apply_event(conn, EventSpec(timestamp=1, type="late", trigger_type="t"))  # time cannot go back
        self.assertEqual((world_revision(conn), world_time(conn)), (2, 20))

    def test_event_ids_are_never_reused_and_history_is_immutable(self):
        conn = seeded()
        some_events(conn)
        with self.assertRaises(sqlite3.DatabaseError):
            conn.execute("DELETE FROM events WHERE event_id = 2")
        sql = conn.execute("SELECT sql FROM sqlite_master WHERE name='events'").fetchone()[0]
        self.assertIn("AUTOINCREMENT", sql)

    def test_one_transaction_is_one_event(self):
        conn = seeded()
        before = world_revision(conn)
        apply_event(conn, EventSpec(timestamp=1, type="x", trigger_type="t", changes=[
            Change("person", "john", "energy", delta=-1), Change("person", "john", "hunger", delta=1),
            Change("person", "mary", "energy", delta=-1)]))
        self.assertEqual(world_revision(conn), before + 1)


class SnapshotTests(unittest.TestCase):
    def test_hash_is_stable_and_sensitive(self):
        a, b = seeded(), seeded()
        some_events(a)
        some_events(b)
        self.assertEqual(snapshot_hash(a), snapshot_hash(b))
        apply_event(b, EventSpec(timestamp=30, type="c", trigger_type="t",
                                 changes=[Change("person", "tom", "energy", delta=-1)]))
        self.assertNotEqual(snapshot_hash(a), snapshot_hash(b))
        m_a, m_b = snapshot_manifest(a), snapshot_manifest(b)
        changed = {t for t in m_a["tables"] if m_a["tables"][t] != m_b["tables"][t]}
        self.assertEqual(changed, {"people", "events", "event_deltas"})  # says exactly which tables differ

    def test_insertion_order_does_not_matter(self):
        def build(order):
            conn = connect()
            init_db(conn, 1)
            conn.execute("INSERT INTO locations VALUES ('home','Home',0,0,5,'[]')")
            for pid in order:
                conn.execute("INSERT INTO people VALUES (?,?,?,100,100,10,'g','calm','{}','active')", (pid, pid, "home"))
            return conn

        self.assertEqual(snapshot_hash(build(["a", "b", "c"])), snapshot_hash(build(["c", "a", "b"])))

    def test_json_layout_is_normalised(self):
        def build(tags):
            conn = connect()
            init_db(conn, 1)
            conn.execute("INSERT INTO locations VALUES ('home','Home',0.5,0,5,?)", (tags,))
            return conn

        self.assertEqual(snapshot_hash(build('["a", "b"]')), snapshot_hash(build('["a","b"]')))

    def test_audit_is_clean_after_normal_events(self):
        conn = seeded()
        some_events(conn)
        self.assertEqual(audit(conn), [])


class RulesetTests(unittest.TestCase):
    def test_ruleset_hash_is_stable_and_covers_the_kernel(self):
        self.assertEqual(ruleset_hash(), ruleset_hash())
        files = ruleset_manifest()["files"]
        for required in ("world/rules.py", "world/schema.sql", "contracts/claim.py", "world/migrations/v002.sql"):
            self.assertIn(required, files)
        self.assertTrue(all(h.startswith("sha256:") for h in files.values()))


class ReaderTests(unittest.TestCase):
    def test_reader_cannot_write_and_sees_committed_wal_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "world.db")
            conn = connect(path)
            init_db(conn, 1)
            conn.execute("INSERT INTO locations VALUES ('home','Home',0,0,5,'[]')")
            conn.execute("INSERT INTO people VALUES ('john','John','home',100,100,10,'g','calm','{}','active')")
            reader = open_world_reader(path)
            self.assertEqual(reader.execute("SELECT COUNT(*) FROM people").fetchone()[0], 1)
            apply_event(conn, EventSpec(timestamp=1, type="x", trigger_type="t",
                                        changes=[Change("person", "john", "energy", delta=-7)]))
            self.assertEqual(reader.execute("SELECT energy FROM people").fetchone()[0], 93)  # WAL is not ignored
            for sql in ("UPDATE people SET energy = 1", "DELETE FROM events", "INSERT INTO meta VALUES ('k','v')",
                        "CREATE TABLE evil(x)", "INSERT INTO mutation_guard VALUES (1)"):
                with self.subTest(sql), self.assertRaises(sqlite3.OperationalError):
                    reader.execute(sql)
            reader.close()
            conn.close()


def _insert_v1_rows(conn):
    conn.execute("INSERT INTO meta VALUES ('world_seed','1')") if not conn.execute(
        "SELECT 1 FROM meta WHERE key='world_seed'").fetchone() else None
    conn.execute("INSERT INTO locations VALUES ('home','Home',0,0,5,'[]')")
    for pid in ("john", "mary"):
        conn.execute("INSERT INTO people VALUES (?,?,?,100,100,10,'g','calm','{}','active')", (pid, pid.title(), "home"))
    conn.execute("BEGIN")
    conn.execute("INSERT INTO mutation_guard VALUES (1)")
    conn.execute("INSERT INTO events(timestamp,type,location_id,trigger_type,truth) VALUES (5,'x','home','t','{}')")
    conn.execute("INSERT INTO memories(observer_id,event_id,belief,confidence,created_at) VALUES ('john',1,'old',0.9,5)")
    conn.execute("DELETE FROM mutation_guard")
    conn.execute("COMMIT")


class MigrationTests(unittest.TestCase):
    def v1_database(self):
        conn = connect()
        with open(os.path.join(ROOT, "world", "migrations", "v001_schema.sql"), encoding="utf-8") as f:
            conn.executescript(f.read())
        _insert_v1_rows(conn)
        return conn

    def test_old_database_migrates_and_keeps_its_data(self):
        conn = self.v1_database()
        self.assertEqual(schema_version(conn), 1)
        self.assertEqual(migrate(conn), SCHEMA_VERSION)
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(memories)")}
        self.assertTrue({"claim_id", "about_event_id", "source_type", "source_id"} <= cols)
        row = conn.execute("SELECT belief, source_type FROM memories").fetchone()
        self.assertEqual(tuple(row), ("old", "direct_observation"))
        apply_event(conn, EventSpec(timestamp=6, type="y", trigger_type="t", memories=[MemorySpec("mary", "new", 1.0)]))
        self.assertEqual(audit(conn), [])
        self.assertEqual(migrate(conn), SCHEMA_VERSION)  # idempotent

    def test_migrated_and_fresh_databases_hash_the_same(self):
        migrated = self.v1_database()
        migrate(migrated)
        fresh = connect()
        init_db(fresh, 1)
        _insert_v1_rows(fresh)
        self.assertEqual(snapshot_hash(migrated), snapshot_hash(fresh))


if __name__ == "__main__":
    unittest.main()
