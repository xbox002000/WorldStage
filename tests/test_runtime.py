"""World Runtime: the world's events played out in space and time. Same history, same runtime version: same state
hash; seeking back and forth is the same as going straight there; the runtime never contradicts the world; every
hand-off has an event behind it; engines only play it (runtime/export.py:sample is the rule)."""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from agent.volition import VolitionDecider
from narrative.compiler import compile_packet
from narrative.direction import plan_direction
from narrative.performance import plan_performance
from runtime.export import export, sample
from runtime.world_runtime import WorldRuntime
from tests.test_director_reality import dog_story
from tests.test_world_c import fresh
from world.simulation import Simulation

ROOT = Path(__file__).resolve().parent.parent
GODOT = ROOT / "tools" / "godot" / "Godot_v4.7.2-stable_win64_console.exe"


class RuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = fresh(260934)
        d = VolitionDecider(260934)
        Simulation(cls.c, d, d, set(), feed="synthetic_v1").run(6)
        cls.rt = WorldRuntime(cls.c)

    def test_the_same_history_gives_the_same_runtime_state(self):
        again = WorldRuntime(self.c)
        for rev in (self.rt.frames[10].revision, self.rt.frames[-1].revision):
            self.assertEqual(again.state_at(rev).state_hash, self.rt.state_at(rev).state_hash)
        ids = [f.revision for f in self.rt.frames[-40:]]
        self.assertEqual(again.trace(ids).trace_hash, self.rt.trace(ids).trace_hash)

    def test_seeking_back_and_forth_is_the_same_as_going_straight_there(self):
        late, early = self.rt.frames[-1].revision, self.rt.frames[len(self.rt.frames) // 3].revision
        direct = self.rt.state_at(late).state_hash
        self.rt.state_at(early)  # seek back
        self.assertEqual(self.rt.state_at(late).state_hash, direct)  # and forward again
        self.assertEqual(self.rt.state_at(early).revision, early)

    def test_the_runtime_never_contradicts_the_world(self):
        self.assertEqual(self.rt.check(), [])
        # after every event, who holds what is what the world's own deltas say
        for f in self.rt.frames[::25]:
            for oid, (holder, *_rest) in f.things.items():
                row = self.c.execute("SELECT new_value FROM event_deltas WHERE entity_type = 'object' AND entity_id = ? "
                                     "AND field = 'owner_person_id' AND event_id <= ? ORDER BY delta_id DESC LIMIT 1",
                                     (oid, f.revision)).fetchone()
                first = self.c.execute("SELECT old_value FROM event_deltas WHERE entity_type = 'object' AND "
                                       "entity_id = ? AND field = 'owner_person_id' ORDER BY delta_id LIMIT 1", (oid,)).fetchone()
                truth = row[0] if row else (first[0] if first else self.c.execute(
                    "SELECT owner_person_id FROM objects WHERE id = ?", (oid,)).fetchone()[0])
                self.assertEqual(holder, truth or "", f"{oid} after event {f.revision}")

    def test_every_hand_off_has_an_event_and_a_body_part(self):
        self.assertTrue(self.rt.interactions)
        for i in self.rt.interactions:
            self.assertIsNotNone(self.c.execute("SELECT 1 FROM events WHERE event_id = ?", (i.event_id,)).fetchone())
            self.assertLessEqual(i.start, i.contact)
            self.assertLessEqual(i.contact, i.complete)
            self.assertIn(i.hand, ("right", "mouth"))


class RuntimeInProductionTests(unittest.TestCase):
    def test_the_dog_takes_it_in_its_mouth_and_the_packet_knows_when(self):
        c, thread, spec = dog_story()
        rt = WorldRuntime(c)
        trace = rt.trace([b.event_id for b in spec.beats])
        take = next(i for i in trace.interactions if i.actor == "dog")
        self.assertEqual((take.action, take.hand), ("pickup", "mouth"))
        plan = plan_direction(c, spec, thread, focalizer="dog")
        packet = compile_packet(spec, direction=plan, performance=plan_performance(c, spec, plan), runtime=trace)
        self.assertEqual(packet.runtime_hash, trace.trace_hash)
        shot = next(s for s in packet.shots if s.interactions)
        self.assertTrue(0.15 <= shot.moment <= 0.85)

    def test_an_engine_plays_the_trace_and_changes_nothing(self):
        c, thread, spec = dog_story()
        rt = WorldRuntime(c)
        place = spec.beats[0].location.id
        with tempfile.TemporaryDirectory() as tmp:
            doc = export(c, rt.trace([b.event_id for b in spec.beats]), place, Path(tmp) / "trace.json", focus=["dog"])
            self.assertTrue(doc["entities"])
            wallet = next(e for e in doc["entities"] if e["id"] == "wallet_ming")
            carried = [k for k in wallet["keys"] if k[5] == "carried"]
            for k in carried:  # a carried thing is where its holder is
                self.assertEqual(sample(doc, "wallet_ming", k[0] + 0.01), sample(doc, k[6], k[0] + 0.01))
            if not GODOT.exists():
                self.skipTest("Godot is not installed in tools/godot")
            out = Path(tmp) / "samples.json"
            subprocess.run([str(GODOT), "--headless", "--path", str(ROOT / "runtime" / "godot"), "--",
                            f"--trace={Path(tmp) / 'trace.json'}", "--mode=verify", f"--out={out}"],
                           capture_output=True, timeout=180)
            got = json.loads(out.read_text(encoding="utf-8"))
            worst = max(abs(sample(doc, e, float(t))[0] - xy[0]) + abs(sample(doc, e, float(t))[1] - xy[1])
                        for t, row in got.items() for e, xy in row.items())
            self.assertLess(worst, 1e-3)


if __name__ == "__main__":
    unittest.main()
