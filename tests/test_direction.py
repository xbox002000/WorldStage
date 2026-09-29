"""DirectorPlan: what the audience should know, through whose eyes, and why each shot and cut exists."""
from __future__ import annotations

import json
import unittest

from contracts.base import canonical_json, from_dict
from contracts.director import DirectorPlan, verify
from narrative.direction import plan_direction
from narrative.director import select_thread
from narrative.scene_spec import build_scene_specs
from narrative.threads import derive_threads
from tests.test_world_c import act, fresh, put
from world.events import apply_event
from world.intent import Intent
from world.items import misplace, notice_missing
from world.snapshot import snapshot_hash
from tests.test_threads_spatial import world_path
from world.reader import open_world_reader
from narrative.arcs import Arc, load_events
from narrative.selector import Candidate


def lost_wallet_scene():
    """Ming leaves his wallet; Jun, who was not there, picks it up; Ming wrongly suspects Tao."""
    c = fresh()
    put(c, 10, ming="cafe", tao="cafe", jun="park")
    apply_event(c, misplace(c, "ming", "wallet_ming", 20))
    put(c, 30, ming="office", tao="office", jun="cafe")
    act(c, Intent("jun", "take", "wallet_ming"), 40)
    apply_event(c, notice_missing(c, "ming", "wallet_ming", 50))
    thread = next(t for t in derive_threads(c) if t.thread_id == "item:wallet_ming")
    events = load_events(c)
    evs = tuple(events[i] for i in thread.event_ids)
    cand = Candidate(Arc(evs, max(evs, key=lambda e: e.importance), "thread"), 1.0, {}, 1.0)
    return c, build_scene_specs(c, [cand])[0], thread


class DirectionTests(unittest.TestCase):
    def test_the_audience_is_shown_what_the_owner_does_not_know(self):
        c, spec, thread = lost_wallet_scene()
        p = plan_direction(c, spec, thread)
        self.assertEqual(p.knowledge.strategy, "irony")
        self.assertEqual(p.focalization.focalizer, "ming")
        take = next(i for i, b in enumerate(spec.beats) if b.event_type == "take")
        self.assertNotIn(take, p.focalization.in_scope)  # Ming was not there
        self.assertIn(take, p.focalization.audience_only)
        self.assertIn("reveal", p.beats[take].functions)
        reveal = [s for s in p.shots if s.beat_index == take and s.function == "reveal" and s.scale == "CU"]
        self.assertEqual(reveal[0].subject, "jun")  # the audience sees who did it

    def test_every_shot_and_cut_says_why(self):
        c, spec, thread = lost_wallet_scene()
        p = plan_direction(c, spec, thread)
        self.assertTrue(all(s.reason and s.function for s in p.shots))
        self.assertEqual(len(p.cuts), len(p.shots) + 1)  # one reason per cut, and a final hold
        self.assertEqual({b.event_id for b in p.beats}, {b.event_id for b in spec.beats})  # nothing invented

    def test_planning_is_deterministic_read_only_and_round_trips(self):
        c, spec, thread = lost_wallet_scene()
        before = snapshot_hash(c)
        a, b = plan_direction(c, spec, thread), plan_direction(c, spec, thread)
        self.assertEqual(a.plan_hash, b.plan_hash)
        self.assertTrue(verify(a))
        self.assertEqual(from_dict(DirectorPlan, json.loads(canonical_json(a))).plan_hash, a.plan_hash)
        self.assertEqual(snapshot_hash(c), before)

    def test_the_director_plans_every_daily_pick(self):
        w = open_world_reader(world_path())
        shown = set()
        for day in range(10):
            cand, thread, _ = select_thread(w, day, shown)
            if cand is None:
                continue
            spec = build_scene_specs(w, [cand], [f"d{day}"])[0]
            p = plan_direction(w, spec, thread, shown)
            self.assertTrue(p.shots)
            shown |= set(cand.arc.ids)
        w.close()


if __name__ == "__main__":
    unittest.main()
