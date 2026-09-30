"""Space: the runtime's bodies go round furniture and each other, turn, sit and stand, put their feet down and take
things in a fixed order; the camera only stands where a camera can; a world simulated in its space only lets people
witness what they could see or hear, and stays deterministic; the god view's save says what everyone feels, wants and
holds."""
from __future__ import annotations

import json
import math
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from agent.volition import VolitionDecider
from narrative.compiler import compile_packet
from narrative.direction import plan_direction
from narrative.layouts import LAYOUTS
from narrative.performance import plan_performance
from runtime.camera import Stage
from runtime.nav import RADIUS, blocks, grid
from runtime.perception import RuntimeSpace, _seg_box
from runtime.physics import audit
from runtime.stage import export_scene
from runtime.world_runtime import WorldRuntime
from tests.test_director_reality import dog_story
from world.db import connect, init_db
from world.ruleset import ruleset_manifest
from world.seed import build_world
from world.simulation import Simulation
from world.snapshot import snapshot_hash
from world.space import detach, oracle

ROOT = Path(__file__).resolve().parent.parent


def _inside_grown(template: str, x: float, y: float, pad: float) -> str:
    for o in LAYOUTS[template]["objects"]:
        if not blocks(o):
            continue
        w, d = o.size[0], o.size[1]
        if abs(x - o.position[0]) < w / 2 + pad and abs(y - o.position[1]) < d / 2 + pad:
            return o.id
    return ""


class NavigationTests(unittest.TestCase):
    def test_a_walk_goes_round_the_furniture_and_straight_when_nothing_is_in_the_way(self):
        g = grid("cafe")
        path = g.path((8.5, 1.0), (2.2, 3.0))  # the door to a seat behind a table
        self.assertGreater(len(path), 2)
        for a, b in zip(path, path[1:]):
            for k in range(1, 20):
                x, y = a[0] + (b[0] - a[0]) * k / 20, a[1] + (b[1] - a[1]) * k / 20
                if math.hypot(x - path[-1][0], y - path[-1][1]) > 0.6:  # the last step is into the seat
                    self.assertEqual(_inside_grown("cafe", x, y, RADIUS * 0.8), "", (x, y))
        self.assertEqual(g.path((5.0, 1.2), (6.0, 1.4)), [(5.0, 1.2), (6.0, 1.4)])

    def test_a_standing_body_is_walked_round(self):
        g = grid("park")
        path = g.path((2.0, 1.5), (7.0, 1.5), others=((4.5, 1.5),))
        self.assertGreater(len(path), 2)
        self.assertTrue(all(math.hypot(p[0] - 4.5, p[1] - 1.5) >= 0.45 for p in path))


class RuntimeSpaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c, thread, cls.spec = dog_story()
        cls.rt = WorldRuntime(cls.c)
        cls.trace = cls.rt.trace([b.event_id for b in cls.spec.beats])
        packets = {}
        for name, who, strategy in (("A", "ming", "mystery"), ("B", "dog", "irony"), ("C", "omniscient", "irony")):
            plan = plan_direction(cls.c, cls.spec, thread, focalizer=who, strategy=strategy)
            packets[name] = compile_packet(cls.spec, direction=plan, performance=plan_performance(cls.c, cls.spec, plan),
                                           runtime=cls.trace)
        cls.tmp = tempfile.TemporaryDirectory()
        cls.doc = export_scene(cls.c, cls.trace, packets, Path(cls.tmp.name) / "scene.json")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_nobody_walks_through_anything_jumps_or_takes_hold_out_of_reach(self):
        r = audit(self.doc)
        for k in ("jump", "in_obstacle", "thing_in_obstacle", "reach_gap"):
            self.assertEqual(r[k]["incidents"], 0, (k, r[k]["examples"]))
        for k in ("body_overlap", "snap_turn"):
            self.assertEqual(r[k]["on_screen"], 0, (k, r[k]["examples"]))

    def test_every_body_keeps_one_clock(self):
        for ts in self.rt._times.values():
            self.assertEqual(ts, sorted(ts))

    def test_a_thing_is_targeted_reached_touched_lifted_and_never_in_two_places(self):
        self.assertTrue(self.trace.tracks)
        for k in self.trace.tracks:
            self.assertLessEqual(k.approach_start, k.reach_start)
            self.assertLessEqual(k.reach_start, k.contact)
            self.assertLessEqual(k.contact, k.complete)
            if k.action == "pickup":
                keys = [(t, tr) for t, tr in self.rt.by_entity[k.target] if abs(t - k.contact) < 1e-6]
                self.assertTrue(keys and keys[-1][1].pose == "lift" and keys[-1][1].holder == k.actor)
                self.assertAlmostEqual(keys[-1][1].x, k.point[0], places=3)  # it leaves the floor where it lay
                if k.actor == "dog":
                    self.assertGreaterEqual(k.sniff, 0)  # an animal smells it first

    def test_feet_are_planted_along_the_path_and_never_in_furniture(self):
        steps = [s for s in self.rt.steps if s.entity == "ming"]
        self.assertTrue(steps)
        for s in steps:
            self.assertLessEqual(s.land, s.lift)
            self.assertEqual(_inside_grown(s.place if s.place in LAYOUTS else "cafe", s.x, s.y, 0.0), "")
            p = self.rt.position("ming", (s.land + s.lift) / 2)
            self.assertLess(math.hypot(p[1] - s.x, p[2] - s.y), 0.75)  # under the body while it is planted

    def test_every_shot_can_physically_exist(self):
        st = Stage(self.doc)
        for cuts in self.doc["cuts"].values():
            for cut in cuts["shots"]:
                sol = cut["camera"]["solution"]
                self.assertTrue(sol["legal"], cut["camera"])
                for key in cut["camera"]["keys"]:
                    pos = key[1:4]
                    for lo, hi in st.solid.get(cut["place"], []):
                        self.assertFalse(lo[0] < pos[0] < hi[0] and lo[1] < pos[1] < hi[1] and pos[2] < hi[2],
                                         (cut["subject"], pos))


class RuntimeInvariantTests(unittest.TestCase):
    """The runtime's laws: one body, one thing at a time per resource; no teleports; no walk faster than a body can;
    one thing per mouth; the cinema's clock never changes the runtime's speed."""

    @classmethod
    def setUpClass(cls):
        cls.c = connect()
        init_db(cls.c, 55)
        build_world(cls.c, 55, "town_spatial_v1")
        d = VolitionDecider(55)
        Simulation(cls.c, d, d, set(), feed="synthetic_v1").run(3)
        detach(cls.c)
        cls.rt = WorldRuntime(cls.c)

    def test_every_invariant_holds_over_the_whole_history(self):
        inv = self.rt.invariants()
        for k, rows in inv.items():
            self.assertEqual(rows, [], k)
        self.assertEqual(self.rt.check(), [])

    def test_the_scheduler_refuses_two_exclusive_actions_at_once(self):
        from runtime.scheduler import ActionScheduler, SchedulingConflict
        s = ActionScheduler()
        s.book("ming", ("move",), 10.0, 12.0, "walk", 1)
        s.book("ming", ("voice",), 11.0, 11.5, "talk", 1)  # walk and talk: different resources
        with self.assertRaises(SchedulingConflict):
            s.book("ming", ("move", "hands"), 11.0, 11.6, "pick up", 2)  # walking and reaching down at once
        self.assertEqual(s.free("ming", "move"), 12.0)

    def test_a_scene_clock_only_shifts_runtime_time_never_compresses_it(self):
        from runtime.export import timeline, to_play
        tl = timeline([100.0, 5000.0, 90000.0], anchor=100.0)
        self.assertAlmostEqual(to_play(90000.0, tl) - to_play(5000.0, tl), 85000.0)
        from runtime.world_runtime import TROT, WALK
        for who, keys in self.rt.by_entity.items():
            for (ta, a), (tb, b) in zip(keys, keys[1:]):
                if a.pose == "walk" and tb - ta > 0.05:
                    v = math.hypot(b.x - a.x, b.y - a.y) / (tb - ta)
                    self.assertLessEqual(v, (TROT if who in self.rt._animals else WALK) + 0.05, who)

    def test_at_night_the_residents_sleep_in_their_own_rooms(self):
        lay = LAYOUTS["apartment"]
        beds = {n: lay["anchors"][n][:2] for n in lay["sleep"]}
        night = [f for f in self.rt.frames if f.time % 1440 >= 1439]
        self.assertTrue(night)
        f = night[-1]
        at_home = {p: v for p, v in f.bodies.items() if v[0] == "apartment" and p not in self.rt._animals}
        self.assertTrue(at_home)
        spots = [(round(v[1], 2), round(v[2], 2)) for v in at_home.values()]
        self.assertEqual(len(spots), len(set(spots)))  # nobody shares a bed
        on_a_bed = sum(any(math.hypot(x - bx, y - by) < 0.1 for bx, by in beds.values()) for x, y in spots)
        self.assertGreaterEqual(on_a_bed, len(spots) - 1)


class PerceptionTests(unittest.TestCase):
    def test_a_tree_or_a_wall_hides_what_is_behind_it(self):
        tree = (7.5, 8.5, 6.5, 7.5)  # park.tree1
        self.assertTrue(_seg_box((6.0, 7.0), (10.0, 7.0), tree))
        self.assertFalse(_seg_box((6.0, 5.0), (10.0, 5.0), tree))

    def test_sight_needs_range_field_of_view_and_a_clear_line(self):
        c, _thread, _spec = dog_story()
        space = RuntimeSpace(c)
        where = {"a": ("park", 6.0, 7.0, 0.0, "stand")}
        space._where = lambda who, t: where.get(who)  # an observer placed by hand, facing +x
        space._species = lambda pid: "human"
        self.assertEqual(space.sees("a", "park", 10.0, 7.0, 0), 0.0)  # the tree is in the way
        self.assertGreater(space.sees("a", "park", 7.0, 5.5, 0), 0.0)  # in front, clear
        self.assertEqual(space.sees("a", "park", 3.0, 7.0, 0), 0.0)  # behind the observer's back
        self.assertEqual(space.sees("a", "cafe", 6.5, 7.0, 0), 0.0)  # another place
        self.assertEqual(space.sees("a", "park", 6.0 + 20, 7.0, 0), 0.0)  # too far

    def test_a_world_in_its_space_is_deterministic_and_only_lets_people_witness_what_they_could_perceive(self):
        hashes, witnessed = [], []
        for _ in range(2):
            c = connect()
            init_db(c, 55)
            build_world(c, 55, "town_spatial_v1")
            d = VolitionDecider(55)
            Simulation(c, d, d, set(), feed="synthetic_v1").run(3)
            space = oracle(c)
            self.assertIsNotNone(space)
            hashes.append(snapshot_hash(c))
            for eid, ts, etype, truth in c.execute("SELECT event_id, timestamp, type, truth FROM events WHERE type IN "
                                                   "('misplace', 'take', 'give', 'tell') ORDER BY event_id"):
                d_ = json.loads(truth)
                for w in [r[0] for r in c.execute("SELECT person_id FROM event_participants WHERE event_id = ? AND "
                                                  "role = 'witness'", (eid,))]:
                    key = f"{etype}:{d_.get('actor')}:{d_.get('object') or d_.get('target') or ''}"
                    witnessed.append(space.weight(w, key, ts) > 0)
            detach(c)
        self.assertEqual(hashes[0], hashes[1])
        self.assertTrue(all(witnessed))

    def test_the_runtime_is_part_of_the_ruleset(self):
        files = ruleset_manifest()["files"]
        for f in ("runtime/world_runtime.py", "runtime/nav.py", "runtime/perception.py", "narrative/layouts.py"):
            self.assertIn(f, files)


class GodViewTests(unittest.TestCase):
    def test_the_save_says_what_everyone_feels_wants_holds_and_does(self):
        from runtime.godview import export_world
        c, _thread, spec = dog_story()
        day = c.execute("SELECT timestamp FROM events WHERE event_id = ?", (spec.beats[2].event_id,)).fetchone()[0] // 1440
        with tempfile.TemporaryDirectory() as tmp:
            doc = export_world(c, Path(tmp) / "world.json", day, day)
            self.assertTrue(doc["events"] and doc["entities"])
            self.assertIn("ming", doc["people"])
            ming = doc["people"]["ming"]
            self.assertTrue(ming["timeline"]["emotion"] and ming["memories"])
            self.assertTrue(all(doc["t0"] - 1.0 <= k[0] for e in doc["entities"] for k in e["keys"]))
            self.assertEqual(doc["cuts"], {})  # nothing directed: the world as it is
            from render.godview.build import build
            site = build(Path(tmp) / "world.json", Path(tmp) / "site")
            self.assertTrue((site / "godview.js").exists() and (site / "assets" / "dog.glb").exists())

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_the_page_code_parses(self):
        subprocess.run([shutil.which("node"), "--check", str(ROOT / "render" / "godview" / "godview.js")], check=True)


if __name__ == "__main__":
    unittest.main()
