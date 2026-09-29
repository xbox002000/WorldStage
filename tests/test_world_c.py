"""World C: attention, items, money, accusations, the seed layer and rule motives."""
from __future__ import annotations

import json
import unittest
from collections import Counter

from agent.volition import VolitionDecider
from contracts.seed import ExternalEvent, SeedEffect
from world.attention import LOUD, QUIET, noticers
from world.db import connect, init_db
from world.events import Change, EventSpec, apply_event
from world.intent import Intent, validate
from world.items import misplace, notice_missing
from world.rules import resolve
from world.seed import build_world
from world.seeds import SEED_VARS, adapt, check_effects, load_feed
from world.simulation import Simulation
from world.snapshot import snapshot_hash
from world.state import WorldError, audit


def fresh(seed: int = 3):
    conn = connect()
    init_db(conn, seed)
    build_world(conn, seed)
    return conn


def put(conn, now: int, **where: str) -> None:
    """Move people (test setup, still through an event)."""
    apply_event(conn, EventSpec(timestamp=now, type="setup", trigger_type="rule",
                                changes=[Change("person", p, "location_id", value=loc) for p, loc in where.items()]))


def act(conn, it: Intent, now: int) -> dict:
    validate(conn, it)
    eid = apply_event(conn, resolve(conn, it, now, "decision"))
    return json.loads(conn.execute("SELECT truth FROM events WHERE event_id = ?", (eid,)).fetchone()[0])


def run(seed: int, feed: str | None, days: int = 14):
    conn = fresh(seed)
    d = VolitionDecider(seed)
    Simulation(conn, d, d, set(), feed=feed).run(days)
    return conn


class StartingWorldTests(unittest.TestCase):
    def test_the_town_starts_with_a_true_secret(self):
        conn = fresh()
        ring = conn.execute("SELECT owner_person_id, rightful_owner_id FROM objects WHERE id = 'ring_mei'").fetchone()
        self.assertEqual(tuple(ring), ("yun", "mei"))
        self.assertEqual(conn.execute("SELECT type FROM events").fetchall()[0][0], "backstory")
        self.assertEqual(audit(conn), [])

    def test_props_wait_offstage(self):
        conn = fresh()
        rows = conn.execute("SELECT status, owner_person_id, location_id FROM objects WHERE id IN "
                            "('ticket', 'parrot', 'package', 'dog')").fetchall()
        self.assertEqual({tuple(r) for r in rows}, {("offstage", None, None)})


class AttentionTests(unittest.TestCase):
    def test_loud_acts_are_seen_by_everyone_quiet_ones_by_few(self):
        conn = fresh()
        everyone = {r[0] for r in conn.execute("SELECT id FROM people WHERE status <> 'inactive'")} - {"dog"}  # people notice; animals sense
        self.assertEqual(set(noticers(conn, "apartment", 100, "x", LOUD)), everyone)
        quiet = [len(noticers(conn, "apartment", t, "x", QUIET)) for t in range(100, 140)]
        self.assertLess(sum(quiet) / len(quiet), 4)
        self.assertEqual(noticers(conn, "apartment", 100, "x", QUIET), noticers(conn, "apartment", 100, "x", QUIET))


class ItemTests(unittest.TestCase):
    def setUp(self):
        self.conn = fresh()
        put(self.conn, 10, ming="cafe", jun="cafe", tao="cafe")

    def test_a_lost_thing_taken_by_one_person_can_be_blamed_on_another(self):
        c = self.conn
        apply_event(c, misplace(c, "ming", "wallet_ming", 20))
        put(c, 30, ming="office")
        truth = act(c, Intent("jun", "take", "wallet_ming"), 40)
        self.assertEqual(truth["rightful_owner"], "ming")
        apply_event(c, notice_missing(c, "ming", "wallet_ming", 50))
        guess = json.loads(c.execute("SELECT truth FROM events WHERE type = 'notice_missing'").fetchone()[0])
        self.assertIn(guess["suspect"], ("jun", "tao"))
        self.assertEqual(guess["suspect_guilty"], guess["suspect"] == "jun")
        self.assertEqual(audit(c), [])

    def test_accusation_outcomes_follow_world_truth(self):
        c = self.conn
        apply_event(c, misplace(c, "ming", "wallet_ming", 20))
        act(c, Intent("jun", "take", "wallet_ming"), 40)
        apply_event(c, notice_missing(c, "ming", "wallet_ming", 50))
        mem = c.execute("SELECT m.memory_id, c.subject FROM memories m JOIN claims c USING (claim_id) "
                        "WHERE m.observer_id = 'ming' AND c.act = 'take'").fetchone()
        outcome = act(c, Intent("ming", "accuse", mem["subject"], memory_id=mem["memory_id"]), 60)["outcome"]
        self.assertIn(outcome, ("caught", "denied") if mem["subject"] == "jun" else ("false",))
        with self.assertRaises(WorldError):  # the argument has been had
            validate(c, Intent("ming", "accuse", mem["subject"], memory_id=mem["memory_id"]))

    def test_people_only_accuse_over_what_was_done_to_them(self):
        c = self.conn
        apply_event(c, misplace(c, "ming", "wallet_ming", 20))
        act(c, Intent("jun", "take", "wallet_ming"), 40)
        seen = c.execute("SELECT memory_id FROM memories m JOIN claims c USING (claim_id) "
                         "WHERE m.observer_id = 'tao' AND c.act = 'take' AND c.subject = 'jun'").fetchone()
        if seen:
            with self.assertRaises(WorldError):
                validate(c, Intent("tao", "accuse", "jun", memory_id=seen[0]))

    def test_giving_back_restores_the_owner(self):
        c = self.conn
        apply_event(c, misplace(c, "ming", "wallet_ming", 20))
        act(c, Intent("jun", "take", "wallet_ming"), 40)
        act(c, Intent("jun", "give", "wallet_ming"), 50)
        self.assertEqual(c.execute("SELECT owner_person_id FROM objects WHERE id = 'wallet_ming'").fetchone()[0], "ming")


class MoneyTests(unittest.TestCase):
    def test_lend_and_repay_keep_the_books(self):
        c = fresh()
        put(c, 10, kai="cafe", lan="cafe")
        before = {r[0]: r[1] for r in c.execute("SELECT id, money_cents FROM people")}
        act(c, Intent("kai", "lend", "lan"), 20)
        self.assertEqual(c.execute("SELECT debt_cents FROM relationships WHERE actor_id='lan' AND target_id='kai'").fetchone()[0], 3000)
        act(c, Intent("lan", "repay", "kai"), 30)
        after = {r[0]: r[1] for r in c.execute("SELECT id, money_cents FROM people")}
        self.assertEqual(before, after)
        self.assertEqual(audit(c), [])


class SeedLayerTests(unittest.TestCase):
    def test_effects_outside_the_closed_vocabulary_are_refused(self):
        with self.assertRaises(ValueError):
            check_effects([SeedEffect("set_var", key="arrears.jun", value=0)])
        with self.assertRaises(ValueError):
            check_effects([SeedEffect("news", audience="the villain", text="x")])

    def test_seeds_never_touch_feelings_relationships_or_actions(self):
        conn = run(5, "synthetic_v1")
        seeds = [r[0] for r in conn.execute("SELECT event_id FROM events WHERE type IN ('seed', 'seed_wears_off')")]
        self.assertTrue(seeds)
        kinds = {(r[0], r[1]) for r in conn.execute(
            f"SELECT entity_type, field FROM event_deltas WHERE event_id IN ({','.join(map(str, seeds))})")}
        for etype, field in kinds:
            self.assertIn(etype, ("var", "object", "person"), (etype, field))
        people = {(r[0], r[1]) for r in conn.execute(
            f"SELECT entity_id, field FROM event_deltas WHERE entity_type = 'person' AND event_id IN ({','.join(map(str, seeds))})")}
        self.assertTrue(people <= {("dog", "status"), ("dog", "location_id")}, people)  # only an animal turning up
        for etype, field in kinds:
            if etype == "var":
                self.assertTrue(field == "value")
        keys = {r[0] for r in conn.execute(
            f"SELECT entity_id FROM event_deltas WHERE entity_type = 'var' AND event_id IN ({','.join(map(str, seeds))})")}
        self.assertTrue(all(k in SEED_VARS or k.startswith("revert.") for k in keys), keys)

    def test_seed_events_carry_their_provenance(self):
        conn = run(5, "synthetic_v1", days=4)
        for (truth,) in conn.execute("SELECT truth FROM events WHERE type = 'seed'"):
            t = json.loads(truth)
            for key in ("external_event_id", "candidate_hash", "feed_hash", "external_event_hash"):
                self.assertTrue(t[key], key)

    def test_a_prop_already_in_town_is_not_brought_in_twice(self):
        conn = run(5, "synthetic_v1", days=3)
        again = ExternalEvent("x", "synthetic", 3, "again", "exotic_pet_escape")
        self.assertEqual(adapt(conn, again).status, "rejected")

    def test_the_feed_loads_and_every_topic_has_an_adapter(self):
        conn = fresh()
        for ev in load_feed("synthetic_v1").events:
            self.assertNotIn("no adapter", adapt(conn, ev).reason)


class AutonomyTests(unittest.TestCase):
    """The self-checks the architecture asks for."""

    def test_same_world_same_seed_replays_exactly(self):
        self.assertEqual(snapshot_hash(run(7, "synthetic_v1", 5)), snapshot_hash(run(7, "synthetic_v1", 5)))

    def test_same_feed_in_a_different_world_gives_a_different_story(self):
        def story(conn):
            return [tuple(r) for r in conn.execute(
                "SELECT type, json_extract(truth, '$.actor'), json_extract(truth, '$.target') FROM events "
                "WHERE type IN ('take', 'give', 'accuse', 'confront', 'tell', 'lend', 'cash_prize')")]
        self.assertNotEqual(story(run(7, "synthetic_v1", 8)), story(run(8, "synthetic_v1", 8)))

    def test_same_world_with_and_without_outside_events_differs(self):
        def dist(conn):
            return Counter(r[0] for r in conn.execute("SELECT type FROM events"))
        self.assertNotEqual(dist(run(7, None, 8)), dist(run(7, "synthetic_v1", 8)))

    def test_rule_motives_are_deterministic(self):
        conn = fresh()
        put(conn, 10, ming="cafe", jun="cafe", tao="cafe")
        d = VolitionDecider(3)
        self.assertEqual(d.decide(conn, "ming", 700), d.decide(conn, "ming", 700))


if __name__ == "__main__":
    unittest.main()
