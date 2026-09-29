"""Animals perceive without language: they sense, never hold a claim, act by their own policy, can be a point of view."""
from __future__ import annotations

import json
import unittest

from agent.volition import VolitionDecider
from tests.test_world_c import act, fresh, put
from world.events import Change, EventSpec, apply_event
from world.intent import Intent, validate
from world.simulation import Simulation
from world.state import WorldError, audit


def with_dog(seed: int = 3):
    c = fresh(seed)
    apply_event(c, EventSpec(timestamp=5, type="setup", trigger_type="rule",
                             changes=[Change("person", "dog", "status", value="active"),
                                      Change("person", "dog", "location_id", value="cafe")]))
    return c


class AnimalRuleTests(unittest.TestCase):
    def test_the_dog_waits_offstage_until_a_seed_brings_it(self):
        c = fresh()
        self.assertEqual(c.execute("SELECT status FROM people WHERE id = 'dog'").fetchone()[0], "inactive")
        conn = fresh(260931)
        d = VolitionDecider(260931)
        Simulation(conn, d, d, set(), feed="synthetic_v1").run(13)
        self.assertEqual(conn.execute("SELECT status FROM people WHERE id = 'dog'").fetchone()[0], "active")

    def test_animals_cannot_speak_and_people_do_not_bark(self):
        c = with_dog()
        put(c, 10, ming="cafe")
        for it in (Intent("dog", "talk", "ming", "warm"), Intent("dog", "accuse", "ming", memory_id=1),
                   Intent("ming", "bark", "dog"), Intent("ming", "talk", "dog", "warm")):
            with self.assertRaises(WorldError):
                validate(c, it)
        validate(c, Intent("dog", "bark", "ming"))

    def test_an_animal_senses_but_never_holds_a_claim(self):
        from world.animals import with_senses
        from world.rules import resolve
        c = with_dog()
        put(c, 10, ming="cafe", jun="cafe")
        it = Intent("ming", "talk", "jun", "hostile")
        validate(c, it)
        spec = with_senses(c, resolve(c, it, 30, "decision"))
        apply_event(c, spec)
        self.assertEqual(c.execute("SELECT COUNT(*) FROM memories WHERE observer_id = 'dog' AND claim_id IS NOT NULL").fetchone()[0], 0)
        percept = c.execute("SELECT belief FROM memories WHERE observer_id = 'dog'").fetchone()[0]
        self.assertIn("阿明", percept)  # it knows who by smell and voice, not what was said
        self.assertGreater(c.execute("SELECT fear FROM relationships WHERE actor_id = 'dog' AND target_id = 'ming'").fetchone()[0], 0)

    def test_a_dog_can_carry_a_thing_off_and_people_blame_each_other(self):
        from world.animals import with_senses
        from world.items import misplace, notice_missing
        from world.rules import resolve
        c = with_dog()
        put(c, 10, ming="cafe", tao="cafe")
        apply_event(c, misplace(c, "ming", "wallet_ming", 20))
        put(c, 30, ming="office", tao="office")
        take = Intent("dog", "take", "wallet_ming")
        validate(c, take)
        apply_event(c, with_senses(c, resolve(c, take, 40, "decision")))
        self.assertEqual(c.execute("SELECT owner_person_id FROM objects WHERE id = 'wallet_ming'").fetchone()[0], "dog")
        apply_event(c, notice_missing(c, "ming", "wallet_ming", 50))
        t = json.loads(c.execute("SELECT truth FROM events WHERE type = 'notice_missing'").fetchone()[0])
        self.assertEqual((t["suspect"], t["suspect_guilty"]), ("tao", False))  # the dog did it; Ming suspects Tao
        self.assertEqual(audit(c), [])

    def test_a_long_run_with_the_dog_stays_consistent(self):
        conn = fresh(260934)
        d = VolitionDecider(260934)
        Simulation(conn, d, d, set(), feed="synthetic_v1").run(20)
        self.assertEqual(audit(conn), [])
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM memories WHERE observer_id = 'dog' AND claim_id IS NOT NULL").fetchone()[0], 0)
        self.assertGreater(conn.execute("SELECT COUNT(*) FROM memories WHERE observer_id = 'dog'").fetchone()[0], 0)


class AnimalPointOfViewTests(unittest.TestCase):
    def test_the_director_tells_it_through_the_one_who_saw_but_cannot_speak(self):
        from narrative.arcs import Arc, load_events
        from narrative.direction import plan_direction
        from narrative.scene_spec import build_scene_specs
        from narrative.selector import Candidate
        from narrative.spatial import compile_spatial
        from narrative.threads import derive_threads
        from world.animals import with_senses
        from world.items import misplace, notice_missing
        from world.rules import resolve
        c = with_dog()
        put(c, 10, ming="cafe", tao="cafe")
        apply_event(c, misplace(c, "ming", "wallet_ming", 20))
        put(c, 30, ming="office", tao="office")
        take = Intent("dog", "take", "wallet_ming")
        apply_event(c, with_senses(c, resolve(c, take, 40, "decision")))
        apply_event(c, notice_missing(c, "ming", "wallet_ming", 50))
        thread = next(t for t in derive_threads(c) if t.thread_id == "item:wallet_ming")
        events = load_events(c)
        evs = tuple(events[i] for i in thread.event_ids)
        spec = build_scene_specs(c, [Candidate(Arc(evs, max(evs, key=lambda e: e.importance), "thread"), 1.0, {}, 1.0)])[0]
        self.assertTrue(spec.characters["dog"].asset_id.startswith("animal_"))
        plan = plan_direction(c, spec, thread)
        self.assertEqual((plan.focalization.focalizer, plan.focalization.kind), ("dog", "animal"))
        self.assertTrue(any(s.angle == "ground" for s in plan.shots))
        self.assertTrue(all(cue.dialogue != "full" for cue in plan.sound))  # a dog hears voices, not words
        staged = compile_spatial(spec)
        dog = [p for b in staged.beats for p in b.placements if p.id == "dog"]
        self.assertTrue(dog and all(p.height == 0.5 for p in dog))


if __name__ == "__main__":
    unittest.main()
