"""Characters over time: slow layers move only with repeated experience, heal with scars, and can be explained."""
from __future__ import annotations

import json
import unittest

from agent.volition import VolitionDecider
from tests.test_world_c import fresh, put
from world.events import Change, EventSpec, apply_event
from world.intent import Intent
from world.psyche import ADAPTIVE, reflect, trait
from world.simulation import Simulation
from world.state import audit
from narrative.timelines import character_timeline, relationship_timeline, state_at, why_changed

DAY = 1440


def lied_to(conn, pid: str, day: int, by: str = "yun") -> None:
    """Test fixture: on `day`, `pid` confronts someone and finds out they were lied to."""
    apply_event(conn, EventSpec(timestamp=day * DAY + 700, type="confront", trigger_type="decision", importance=0.9,
                                truth={"actor": pid, "target": by, "outcome": "lie_exposed"},
                                participants=[(pid, "actor"), (by, "target")]))


def helped(conn, pid: str, day: int, by: str = "rui") -> None:
    apply_event(conn, EventSpec(timestamp=day * DAY + 720, type="lend", trigger_type="decision", importance=0.4,
                                truth={"actor": by, "target": pid}, participants=[(by, "actor"), (pid, "target")]))


def night(conn, pid: str, day: int) -> None:
    spec = reflect(conn, pid, day, day * DAY + 1439)
    if spec is not None:
        apply_event(conn, spec)


class SlowLayerTests(unittest.TestCase):
    def test_one_betrayal_changes_nothing_slow_repetition_does(self):
        c = fresh()
        lied_to(c, "mei", 0)
        night(c, "mei", 0)
        self.assertEqual(trait(c, "mei", "vigilance"), ADAPTIVE["vigilance"])
        lied_to(c, "mei", 1)
        night(c, "mei", 1)
        self.assertGreater(trait(c, "mei", "vigilance"), ADAPTIVE["vigilance"])
        self.assertLess(trait(c, "mei", "trust_default"), ADAPTIVE["trust_default"])

    def test_values_have_inertia(self):
        c = fresh()
        for d in range(2):
            lied_to(c, "mei", d)
            night(c, "mei", d)
        self.assertEqual(trait(c, "mei", "value.security"), 0.4)  # two bad days do not change what she values
        for d in range(2, 6):
            lied_to(c, "mei", d)
            night(c, "mei", d)
        self.assertGreater(trait(c, "mei", "value.security"), 0.4)

    def test_healing_is_real_but_leaves_a_scar(self):
        c = fresh()
        for d in range(5):
            lied_to(c, "mei", d)
            night(c, "mei", d)
        hurt = trait(c, "mei", "vigilance")
        for d in range(5, 30):
            helped(c, "mei", d)
            night(c, "mei", d)
        healed = trait(c, "mei", "vigilance")
        self.assertLess(healed, hurt)
        self.assertGreater(healed, ADAPTIVE["vigilance"])  # not back to who she was

    def test_the_self_model_forms_from_history(self):
        c = fresh()
        for d in range(4):
            lied_to(c, "mei", d)
            night(c, "mei", d)
        self.assertEqual(trait(c, "mei", "self.cannot_trust"), 1.0)
        mem = c.execute("SELECT belief FROM memories WHERE observer_id = 'mei' AND belief LIKE '我開始覺得%'").fetchone()
        self.assertIsNotNone(mem)

    def test_core_disposition_never_changes(self):
        c = fresh(260931)
        before = c.execute("SELECT person_id, traits FROM personas ORDER BY person_id").fetchall()
        d = VolitionDecider(260931)
        Simulation(c, d, d, set(), feed="synthetic_v1").run(8)
        self.assertEqual([tuple(r) for r in before],
                         [tuple(r) for r in c.execute("SELECT person_id, traits FROM personas ORDER BY person_id")])


class HistoryShapesChoiceTests(unittest.TestCase):
    def test_the_same_person_in_the_same_situation_chooses_differently_after_a_history(self):
        c = fresh()
        put(c, 10, mei="cafe", yun="cafe")
        d = VolitionDecider(3)
        first = d.options(c, "mei", 700)
        apply_event(c, EventSpec(timestamp=20, type="setup", trigger_type="rule", changes=[
            Change("var", "psy.mei.cynicism", "value", delta=0.5), Change("var", "psy.mei.withdrawal", "value", delta=0.5)]))
        later = d.options(c, "mei", 700)
        self.assertNotEqual([round(s, 4) for s, _ in first], [round(s, 4) for s, _ in later])
        self.assertGreater(later[0][0], first[0][0])  # she would rather keep to herself now


class TimelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = fresh(260931)
        d = VolitionDecider(260931)
        Simulation(cls.c, d, d, set(), feed="synthetic_v1").run(10)

    def test_state_rebuilt_from_the_log_matches_the_world(self):
        for pid in ("ming", "mei", "tao"):
            rebuilt = state_at(self.c, pid, 9)
            for k, v in rebuilt.items():
                self.assertAlmostEqual(v, trait(self.c, pid, k), places=6)

    def test_relationship_timeline_is_the_event_log(self):
        steps = relationship_timeline(self.c, "mei", "yun")
        now = self.c.execute("SELECT trust FROM relationships WHERE actor_id = 'mei' AND target_id = 'yun'").fetchone()[0]
        if steps:
            self.assertAlmostEqual(steps[-1]["new"], now, places=6)
        self.assertNotEqual(
            self.c.execute("SELECT trust FROM relationships WHERE actor_id = 'mei' AND target_id = 'yun'").fetchone()[0],
            self.c.execute("SELECT trust FROM relationships WHERE actor_id = 'yun' AND target_id = 'mei'").fetchone()[0])

    def test_why_someone_changed_cites_what_happened(self):
        w = why_changed(self.c, "ming", -1, 9)
        for b in w["because"]:
            self.assertTrue(b["because_of"] or b["shifted"])
        self.assertTrue(character_timeline(self.c, "ming"))
        self.assertEqual(audit(self.c), [])


if __name__ == "__main__":
    unittest.main()
