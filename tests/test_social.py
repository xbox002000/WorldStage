from __future__ import annotations

import json
import unittest

from contracts.claim import DENY, FALSE, PARTIAL, TRUE, UNKNOWN, Claim
from tests.helpers import social_world
from world.claims import evaluate
from world.confront import confrontable, validate_confront
from world.events import apply_event
from world.intent import Intent, intent_hash, intent_sort_key, parse_intent, validate
from world.rules import resolve
from world.snapshot import snapshot_hash
from world.social import BELIEF_EFFECT, classify_confrontation, listener_confidence
from world.state import WorldError, audit


def do(conn, ts, intent):
    """Validate, resolve and commit one intent, exactly as the simulator does."""
    validate(conn, intent)
    return apply_event(conn, resolve(conn, intent, ts, "decision"))


def cid(conn, claim):
    return conn.execute("SELECT claim_id FROM claims WHERE claim_hash = ?", (claim.hash(),)).fetchone()[0]


def told_memory(conn, listener, teller):
    return conn.execute("SELECT memory_id FROM memories WHERE observer_id=? AND source_type='told_by' AND source_id=? "
                        "ORDER BY memory_id LIMIT 1", (listener, teller)).fetchone()[0]


def trust(conn, a, b):
    return conn.execute("SELECT trust FROM relationships WHERE actor_id=? AND target_id=?", (a, b)).fetchone()[0]


def truth_of(conn, event_id):
    return json.loads(conn.execute("SELECT truth FROM events WHERE event_id=?", (event_id,)).fetchone()[0])


STOLE = Claim("tom", "steal", "phone")


class TellTests(unittest.TestCase):
    def setUp(self):
        self.conn = social_world()
        self.theft = do(self.conn, 10, Intent("tom", "steal", "phone"))  # john and mary see it
        do(self.conn, 11, Intent("ben", "move", "cafe"))
        self.stole_id = cid(self.conn, STOLE)

    def tell(self, ts, actor, target, mode, **kw):
        return do(self.conn, ts, Intent(actor, "tell", target, mode=mode, claim_id=self.stole_id, **kw))

    def test_truth_is_passed_on_with_provenance_and_effect(self):
        before = trust(self.conn, "ben", "tom")
        e = self.tell(20, "john", "ben", "truth")
        t = truth_of(self.conn, e)
        self.assertEqual((t["mode"], t["verdict"], t["incident"], t["depends_on"]), ("truth", TRUE, self.theft, [self.theft]))
        mem = self.conn.execute("SELECT * FROM memories WHERE observer_id='ben' AND source_type='told_by'").fetchone()
        self.assertEqual((mem["source_id"], mem["about_event_id"], mem["claim_id"]), ("john", self.theft, self.stole_id))
        self.assertAlmostEqual(mem["confidence"], listener_confidence(0.2), places=2)
        src = self.conn.execute("SELECT derived_from_memory_id FROM memory_sources WHERE memory_id=?", (mem["memory_id"],)).fetchone()
        self.assertIsNotNone(src)  # the chain of who-told-whom is on record
        self.assertAlmostEqual(trust(self.conn, "ben", "tom"), before + BELIEF_EFFECT[("steal", "affirm")] * mem["confidence"], places=4)
        self.assertEqual(audit(self.conn), [])

    def test_lie_flips_the_claim_and_helps_the_accused(self):
        before = trust(self.conn, "ben", "tom")
        e = self.tell(20, "john", "ben", "lie")
        t = truth_of(self.conn, e)
        self.assertEqual((t["verdict"], t["asserted_claim"]["polarity"]), (FALSE, DENY))
        roles = {(r["subject"], r["act"], r["role"]) for r in self.conn.execute(
            "SELECT c.subject, c.act, ec.role FROM event_claims ec JOIN claims c USING (claim_id) WHERE ec.event_id=?", (e,))}
        self.assertIn(("john", "deceive", "truth"), roles)  # the world records that john deceived ben
        self.assertIn(("tom", "steal", "asserted"), roles)
        self.assertGreater(trust(self.conn, "ben", "tom"), before)
        self.assertEqual(evaluate(self.conn, Claim("tom", "steal", "phone", DENY), self.theft), FALSE)

    def test_distortion_downplays_and_is_partial(self):
        e = self.tell(20, "john", "ben", "distortion")
        t = truth_of(self.conn, e)
        self.assertEqual((t["verdict"], t["asserted_claim"]["act"]), (PARTIAL, "take"))

    def test_omission_names_what_is_kept_back(self):
        do(self.conn, 15, Intent("mary", "talk", "john", "hostile"))  # john now also holds a speech claim
        hidden = cid(self.conn, Claim("mary", "speak_hostile", "john"))
        e = self.tell(20, "john", "ben", "omission", withheld=(hidden,))
        t = truth_of(self.conn, e)
        self.assertEqual(t["verdict"], TRUE)
        roles = [(r["role"]) for r in self.conn.execute("SELECT role FROM event_claims WHERE event_id=? ORDER BY role", (e,))]
        self.assertIn("withheld", roles)
        self.assertIn("conceal", [r[0] for r in self.conn.execute(
            "SELECT c.act FROM event_claims ec JOIN claims c USING (claim_id) WHERE ec.event_id=? AND ec.role='truth'", (e,))])

    def test_speaker_who_denies_their_own_act_does_not_break_the_delta_rules(self):
        # tom lies about himself: subject == actor, so two causes hit the same listener->speaker trust field.
        e = do(self.conn, 20, Intent("tom", "tell", "ben", mode="lie", claim_id=self.stole_id))
        deltas = self.conn.execute("SELECT COUNT(*) FROM event_deltas WHERE event_id=? AND entity_id='ben:tom' AND field='trust'", (e,)).fetchone()[0]
        self.assertEqual(deltas, 1)
        self.assertGreater(trust(self.conn, "ben", "tom"), 0.2)

    def test_confidence_tracks_trust_in_the_speaker(self):
        self.assertLess(listener_confidence(-0.6), listener_confidence(0.0))
        self.assertLess(listener_confidence(0.0), listener_confidence(0.8))
        self.assertTrue(0.10 <= listener_confidence(-1.0) and listener_confidence(1.0) <= 0.95)

    def test_relaying_a_rumour_keeps_the_chain(self):
        self.tell(20, "john", "ben", "truth")
        do(self.conn, 21, Intent("anna", "move", "cafe"))
        do(self.conn, 22, Intent("ben", "tell", "anna", mode="truth", claim_id=self.stole_id))
        anna = self.conn.execute("SELECT memory_id, about_event_id FROM memories WHERE observer_id='anna' AND source_type='told_by'").fetchone()
        self.assertEqual(anna["about_event_id"], self.theft)  # still about the original theft
        chain = self.conn.execute("SELECT derived_from_memory_id FROM memory_sources WHERE memory_id=?", (anna["memory_id"],)).fetchone()[0]
        ben = self.conn.execute("SELECT observer_id, source_id FROM memories WHERE memory_id=?", (chain,)).fetchone()
        self.assertEqual((ben["observer_id"], ben["source_id"]), ("ben", "john"))

    def test_illegal_tells_and_intents(self):
        with self.assertRaises(WorldError):
            validate(self.conn, Intent("john", "tell", "ben", mode="lie", claim_id=self.stole_id + 999))
        with self.assertRaises(WorldError):
            validate(self.conn, Intent("john", "tell", "anna", mode="truth", claim_id=self.stole_id))  # anna is at home
        with self.assertRaises(WorldError):
            validate(self.conn, Intent("john", "tell", "ben", mode="truth"))  # no claim named
        parsed = parse_intent("john", {"action": "tell", "target": "ben", "mode": "lie", "claim_id": "7",
                                       "withheld_claim_id": 3, "actor": "mary"})
        self.assertEqual((parsed.actor, parsed.claim_id, parsed.withheld), ("john", 7, (3,)))
        with self.assertRaises(WorldError):
            parse_intent("john", {"action": "tell", "claim_id": "seven"})


class ConfrontTests(unittest.TestCase):
    """The story the channel is built on: a lie, it travels, someone catches it."""

    def setUp(self):
        self.conn = social_world()
        self.theft = do(self.conn, 10, Intent("tom", "steal", "phone"))
        do(self.conn, 11, Intent("ben", "move", "cafe"))
        self.stole_id = cid(self.conn, STOLE)
        self.lie = do(self.conn, 20, Intent("john", "tell", "ben", mode="lie", claim_id=self.stole_id))
        self.johns_word = told_memory(self.conn, "ben", "john")

    def hears_the_truth_from_mary(self):
        self.truth_tell = do(self.conn, 30, Intent("mary", "tell", "ben", mode="truth", claim_id=self.stole_id))

    def test_no_confrontation_without_grounds(self):
        self.assertEqual(confrontable(self.conn, "ben"), [])
        with self.assertRaises(WorldError):
            validate_confront(self.conn, "ben", "john", self.johns_word)

    def test_the_newer_account_supersedes_the_older_one_as_grounds(self):
        self.hears_the_truth_from_mary()
        options = {o["target"] for o in confrontable(self.conn, "ben")}
        self.assertEqual(options, {"john"})  # mary's later, equally believed account is what ben now goes on
        with self.assertRaises(WorldError):
            validate_confront(self.conn, "ben", "mary", told_memory(self.conn, "ben", "mary"))

    def test_hearing_the_lie_last_makes_the_honest_one_the_target(self):
        conn = social_world()
        do(conn, 10, Intent("tom", "steal", "phone"))
        do(conn, 11, Intent("ben", "move", "cafe"))
        sid = cid(conn, STOLE)
        do(conn, 15, Intent("mary", "tell", "ben", mode="truth", claim_id=sid))
        do(conn, 20, Intent("john", "tell", "ben", mode="lie", claim_id=sid))
        self.assertEqual({o["target"] for o in confrontable(conn, "ben")}, {"mary"})
        before = trust(conn, "mary", "ben")
        e = do(conn, 30, Intent("ben", "confront", "mary", memory_id=told_memory(conn, "ben", "mary")))
        self.assertEqual(truth_of(conn, e)["outcome"], "unfounded")  # a misunderstanding: the liar won
        self.assertLess(trust(conn, "mary", "ben"), before - 0.2)

    def test_a_first_hand_sighting_outweighs_later_hearsay(self):
        # mary saw the theft herself (confidence 0.95). Even if she later hears a denial, her own memory stays live.
        do(self.conn, 21, Intent("john", "tell", "mary", mode="lie", claim_id=self.stole_id))  # mary is told the opposite
        opts = {(o["target"], o["grounds"].polarity) for o in confrontable(self.conn, "mary")}
        self.assertEqual(opts, {("john", "affirm")})  # her own sighting is the grounds for challenging john

    def test_lie_travels_and_is_exposed(self):
        self.hears_the_truth_from_mary()
        john_before, mary_before = trust(self.conn, "ben", "john"), trust(self.conn, "ben", "mary")
        e = do(self.conn, 40, Intent("ben", "confront", "john", memory_id=self.johns_word))
        t = truth_of(self.conn, e)
        self.assertEqual((t["outcome"], t["verdict"], t["incident"], t["tell_event"]), ("lie_exposed", FALSE, self.theft, self.lie))
        self.assertLess(trust(self.conn, "ben", "john"), john_before - 0.5)
        self.assertEqual(trust(self.conn, "ben", "mary"), mary_before)  # the honest one is untouched
        row = self.conn.execute("SELECT parent_event_id, importance FROM events WHERE event_id=?", (e,)).fetchone()
        self.assertEqual((row["parent_event_id"], row["importance"]), (self.lie, 0.95))
        held = {(r["subject"], r["act"], r["polarity"]) for r in self.conn.execute(
            "SELECT c.subject, c.act, c.polarity FROM memories m JOIN claims c USING (claim_id) WHERE m.observer_id='ben'")}
        self.assertIn(("john", "deceive", "affirm"), held)  # ben now believes john deceived him
        self.assertEqual(self.conn.execute("SELECT emotion FROM people WHERE id='john'").fetchone()[0], "ashamed")
        # onlookers (tom, mary) drew their own conclusion about john
        self.assertLess(trust(self.conn, "tom", "john"), 0.2)
        self.assertEqual(audit(self.conn), [])

    def test_a_relayed_falsehood_is_a_mistake_not_a_lie(self):
        do(self.conn, 21, Intent("anna", "move", "cafe"))
        do(self.conn, 22, Intent("ben", "tell", "anna", mode="truth", claim_id=cid(self.conn, Claim("tom", "steal", "phone", DENY))))
        annas_word = told_memory(self.conn, "anna", "ben")
        do(self.conn, 23, Intent("mary", "tell", "anna", mode="truth", claim_id=self.stole_id))
        e = do(self.conn, 24, Intent("anna", "confront", "ben", memory_id=annas_word))
        t = truth_of(self.conn, e)
        self.assertEqual((t["outcome"], t["verdict"]), ("misinformed", FALSE))
        self.assertGreater(trust(self.conn, "anna", "ben"), 0.2 - 0.06)  # only a small dent

    def test_concealment_is_exposed_when_the_told_part_was_true(self):
        do(self.conn, 25, Intent("mary", "talk", "john", "hostile"))
        hidden = cid(self.conn, Claim("mary", "speak_hostile", "john"))
        do(self.conn, 26, Intent("anna", "move", "cafe"))
        do(self.conn, 27, Intent("john", "tell", "anna", mode="omission", claim_id=self.stole_id, withheld=(hidden,)))
        do(self.conn, 28, Intent("tom", "tell", "anna", mode="distortion", claim_id=self.stole_id))  # then "tom only took it"
        e = do(self.conn, 29, Intent("anna", "confront", "john", memory_id=told_memory(self.conn, "anna", "john")))
        t = truth_of(self.conn, e)
        self.assertEqual((t["outcome"], t["verdict"]), ("concealment_exposed", TRUE))
        learned = {(r["subject"], r["act"]) for r in self.conn.execute(
            "SELECT c.subject, c.act FROM memories m JOIN claims c USING (claim_id) "
            "WHERE m.observer_id='anna' AND m.event_id=? AND m.source_type='told_by'", (e,))}
        self.assertIn(("mary", "speak_hostile"), learned)  # what john held back is now known

    def test_each_memory_can_be_challenged_only_once(self):
        self.hears_the_truth_from_mary()
        do(self.conn, 40, Intent("ben", "confront", "john", memory_id=self.johns_word))
        with self.assertRaises(WorldError):
            validate_confront(self.conn, "ben", "john", self.johns_word)

    def test_illegal_confrontations(self):
        self.hears_the_truth_from_mary()
        cases = {
            "memory not told by the target": ("ben", "tom", self.johns_word),
            "someone else's memory": ("mary", "john", self.johns_word),
            "unknown memory": ("ben", "john", 999999),
            "no memory named": ("ben", "john", None),
            "yourself": ("ben", "ben", self.johns_word),
            "stranger": ("ben", "sarah", self.johns_word),
        }
        for name, (a, b, m) in cases.items():
            with self.subTest(name), self.assertRaises(WorldError):
                validate_confront(self.conn, a, b, m)
        do(self.conn, 41, Intent("ben", "move", "home"))
        with self.assertRaises(WorldError):
            validate_confront(self.conn, "ben", "john", self.johns_word)  # ben walked away

    def test_the_whole_story_replays_to_the_same_world(self):
        def story():
            conn = social_world()
            do(conn, 10, Intent("tom", "steal", "phone"))
            do(conn, 11, Intent("ben", "move", "cafe"))
            sid = cid(conn, STOLE)
            do(conn, 20, Intent("john", "tell", "ben", mode="lie", claim_id=sid))
            word = told_memory(conn, "ben", "john")
            do(conn, 30, Intent("mary", "tell", "ben", mode="truth", claim_id=sid))
            do(conn, 40, Intent("ben", "confront", "john", memory_id=word))
            return snapshot_hash(conn)

        self.assertEqual(story(), story())


class RuleTests(unittest.TestCase):
    def test_outcome_classification(self):
        cases = [
            (FALSE, "lie", [], "lie_exposed"), (PARTIAL, "distortion", [], "distortion_exposed"),
            (FALSE, "distortion", [], "lie_exposed"), (PARTIAL, "lie", [], "distortion_exposed"),
            (FALSE, "truth", [], "misinformed"), (PARTIAL, "omission", [], "misinformed"),
            (TRUE, "omission", [5], "concealment_exposed"), (TRUE, "truth", [], "unfounded"),
            (TRUE, "lie", [], "unfounded"), (UNKNOWN, "lie", [], "inconclusive"),
        ]
        for verdict, mode, withheld, expected in cases:
            with self.subTest((verdict, mode, withheld)):
                self.assertEqual(classify_confrontation(verdict, mode, withheld), expected)

    def test_intents_that_differ_only_in_claim_or_memory_have_distinct_keys(self):
        a = Intent("john", "tell", "ben", mode="lie", claim_id=1)
        b = Intent("john", "tell", "ben", mode="lie", claim_id=2)
        c = Intent("john", "confront", "ben", memory_id=1)
        d = Intent("john", "confront", "ben", memory_id=2)
        keys = {intent_sort_key(10, i) for i in (a, b, c, d)}
        self.assertEqual(len(keys), 4)
        self.assertEqual(intent_hash(a), intent_hash(Intent("john", "tell", "ben", reason="x", mode="lie", claim_id=1)))


if __name__ == "__main__":
    unittest.main()
