"""The A/B episode in the packet: the plan's A story, B story and ordinary moment become the shots of one ProductionPacket.

The packet is compiled by the same code as ever; what a packet cannot say (which plan beat and story line a shot is) is in an
EpisodePacketMap beside it. Off (no composition) nothing differs from before; on, the length budget cuts texture first, then B, never A.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from contracts import episode_packet as cep
from contracts.base import canonical_json, from_dict, to_dict
from contracts.episode_plan import INTENTS
from contracts.packet import ProductionPacket
from narrative import episode_planner as P
from narrative.arcs import load_events
from narrative.dramaturgy import analyse
from production import episode_packet as EK
from tests.test_episode_planner import produced

MODEL_WORDS = ("cinematic", "8k", "4k", "bokeh", "lens", "photorealistic", "hyperreal", "masterpiece", "unreal engine")
PROVENANCE = ("packet_hash", "scene_hash", "compiler", "direction_hash", "performance_hash", "runtime_hash")

_FIXED: list = []


def setUpModule():
    """HEAD bug, worked around for the test only: the faction domain's `describe` for `succession` and `found_faction` is "{who}...",
    but a packet's caption fills {a}, {b} and {thing} (narrative/compiler.py), so a packet that holds either event raises KeyError('who').
    Two words in world/domains/factions.py fix it; this work is not allowed to touch that file, so the test patches and restores."""
    from world.domains import all_domains
    for d in all_domains():
        for k, v in list(d.styles.items()):
            if "{who}" in (v.describe or ""):
                _FIXED.append((d, k, v))
                d.styles[k] = dataclasses.replace(v, describe=v.describe.replace("{who}", "{a}"))


def tearDownModule():
    for d, k, v in _FIXED:
        d.styles[k] = v
    _FIXED.clear()


def projected(packet) -> str:
    """The packet without its provenance hashes (they cover the code, and contracts/*.py is part of the code: adding a contract moves
    every packet's hash without moving a single shot)."""
    data = to_dict(packet)
    for k in PROVENANCE:
        data.pop(k, None)
    return canonical_json(data)


class Composed(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = produced(17, 4)
        cls.sit = analyse(cls.c)["situations"]
        cls.days = {}
        for day in range(4):
            m = P.material(cls.c, day, set(), (), P.AB)
            if m.arc is None:
                continue
            comp = EK.compose(cls.c, m, set(), day, cls.sit, P.AB, budget=1e9)
            packet = EK.compile_arc(cls.c, comp.arc, m.thread, set(), comp.intents)
            cls.days[day] = (m, comp, packet, EK.build_map(packet, comp))
        cls.with_b = [d for d, (_, comp, _, _) in cls.days.items() if any(b.story == "B" for b in EK.filmed_beats(comp.plan))]
        cls.with_tex = [d for d, (_, comp, _, _) in cls.days.items() if any(b.story == "texture" for b in EK.filmed_beats(comp.plan))]

    def test_the_fixture_has_days_with_a_b_story_and_with_texture(self):
        self.assertTrue(self.with_b and self.with_tex, (self.with_b, self.with_tex))

    def test_every_shot_speaks_the_closed_vocabulary_and_never_a_models(self):
        for day, (_, _, packet, _) in self.days.items():
            for s in packet.shots:
                self.assertIn(s.function, INTENTS, (day, s.shot_id))
                self.assertEqual(s.intent.split(":")[0], s.function, (day, s.shot_id, s.intent))
                text = f"{s.intent} {s.direction_note}".lower()
                self.assertFalse([w for w in MODEL_WORDS if w in text], (day, s.shot_id, text))

    def test_the_map_names_every_shot_its_beat_and_its_story_and_agrees_with_the_packet(self):
        for day, (_, comp, packet, emap) in self.days.items():
            self.assertEqual(EK.check_map(packet, emap), [], day)
            self.assertTrue(cep.verify(emap))
            self.assertEqual(emap.packet_hash, packet.packet_hash)
            self.assertEqual(emap.plan_hash, comp.plan.plan_hash)
            beats = {b.index: b for b in comp.plan.beats}
            for r in emap.shots:
                self.assertEqual(r.story, beats[r.beat_index].story)
                self.assertIn(r.event_id, beats[r.beat_index].event_ids)
                self.assertTrue(beats[r.beat_index].shoot)

    def test_the_shots_follow_the_plans_beat_order_with_the_b_and_texture_scenes_in_it(self):
        for day, (_, comp, packet, emap) in self.days.items():
            order = [r.beat_index for r in emap.shots]
            self.assertEqual(order, sorted(order), day)
            filmed = EK.filmed_beats(comp.plan)
            self.assertEqual([b.index for b in filmed], sorted(b.index for b in filmed))
            # the packet's scenes are the filmed beats' events, in the plan's order
            seen = list(dict.fromkeys(s.event_id for s in packet.shots))
            plan_events = list(dict.fromkeys(i for b in filmed for i in b.event_ids))
            self.assertEqual(seen, [i for i in plan_events if i in seen], day)
        day = self.with_b[0]
        _, comp, _, emap = self.days[day]
        self.assertIn("B", {r.story for r in emap.shots})
        a_events = {i for b in EK.filmed_beats(comp.plan) if b.story == "A" for i in b.event_ids}
        b_events = {r.event_id for r in emap.shots if r.story == "B"}
        self.assertFalse(a_events & b_events)

    def test_a_beat_the_director_kept_no_shot_of_is_reported_not_lost(self):
        for day, (_, comp, _, emap) in self.days.items():
            self.assertEqual(len(emap.beats), len(EK.filmed_beats(comp.plan)))
            self.assertEqual(sum(b.shots for b in emap.beats), len(emap.shots))
            for b in emap.beats:
                if not b.shots:
                    self.assertTrue(b.note)

    def test_the_a_storys_peak_is_always_filmed(self):
        for day, (m, comp, packet, _) in self.days.items():
            self.assertIn(m.arc.peak.id, {s.event_id for s in packet.shots}, day)

    def test_it_is_deterministic(self):
        day = max(self.days)
        m, comp, packet, emap = self.days[day]
        again = EK.compose(self.c, m, set(), day, self.sit, P.AB, budget=1e9)
        packet2 = EK.compile_arc(self.c, again.arc, m.thread, set(), again.intents)
        self.assertEqual((again.plan.plan_hash, packet2.packet_hash, EK.build_map(packet2, again).map_hash),
                         (comp.plan.plan_hash, packet.packet_hash, emap.map_hash))

    def test_the_map_round_trips_through_json(self):
        _, _, _, emap = self.days[max(self.days)]
        self.assertEqual(from_dict(cep.EpisodePacketMap, json.loads(canonical_json(emap))), emap)

    def test_a_reaction_beat_is_told_after_the_beat_it_reacts_to(self):
        for day, (_, comp, _, _) in self.days.items():
            for b in EK.filmed_beats(comp.plan):
                if b.derived:
                    owner = next(x for x in EK.filmed_beats(comp.plan) if not x.derived and set(x.event_ids) & set(b.event_ids))
                    self.assertEqual(EK.intents_for(comp.plan)[b.event_ids[0]][-1], b.intent)
                    self.assertLess(owner.index, b.index)


class LengthBudget(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = produced(17, 4)
        cls.sit = analyse(cls.c)["situations"]
        cls.day, cls.m = None, None
        for day in range(4):
            m = P.material(cls.c, day, set(), (), P.AB)
            if m.arc is not None and m.secondary is not None and m.texture is not None and len(m.secondary.events) == 2:
                cls.day, cls.m = day, m
                break
        assert cls.m is not None, "the fixture needs a day with a two-scene B story and texture"
        cls.seconds = []
        for sec, tex in EK._variants(cls.m):
            plan = P.plan_episode(cls.c, cls.m.arc, cls.m.thread, set(), cls.day, cls.m.kind, cls.m.payoff, cls.m.steps, cls.sit, P.AB, sec, tex)
            arc = EK.arc_in_plan_order(load_events(cls.c), plan, cls.m.arc)
            cls.seconds.append(EK.body_seconds(EK.compile_arc(cls.c, arc, cls.m.thread, set(), EK.intents_for(plan))))

    def compose(self, budget):
        return EK.compose(self.c, self.m, set(), self.day, self.sit, P.AB, budget=budget)

    def stories(self, comp):
        return [b.story for b in EK.filmed_beats(comp.plan)]

    def test_there_are_four_ways_to_film_it_and_each_is_shorter_than_the_last(self):
        full, no_tex, b_last, only_a = self.seconds
        self.assertGreater(full, no_tex)
        self.assertGreaterEqual(no_tex, b_last)
        self.assertGreaterEqual(b_last, only_a)
        self.assertGreater(full, only_a)

    def test_within_the_budget_nothing_is_cut(self):
        comp = self.compose(self.seconds[0])
        self.assertEqual(comp.trimmed, [])
        self.assertFalse(comp.over_budget)
        self.assertEqual(comp.plan.plan_hash, comp.source_plan.plan_hash)
        self.assertEqual(comp.body_seconds, self.seconds[0])

    def test_texture_goes_first(self):
        comp = self.compose(self.seconds[1])          # exactly what the episode is without its ordinary moment
        self.assertEqual([t.story for t in comp.trimmed], ["texture"])
        self.assertNotIn("texture", self.stories(comp))
        self.assertIn("B", self.stories(comp))
        self.assertLessEqual(comp.body_seconds, self.seconds[1])
        self.assertNotEqual(comp.plan.plan_hash, comp.source_plan.plan_hash)

    def test_then_the_b_story_the_earlier_scene_before_the_rest(self):
        full, no_tex, b_last, only_a = self.seconds
        if b_last < no_tex:
            comp = self.compose(b_last)               # room for one B scene only
            self.assertEqual(self.stories(comp).count("B"), 1)
            self.assertEqual([t.story for t in comp.trimmed], ["texture", "B"])
            kept = {i for b in EK.filmed_beats(comp.plan) if b.story == "B" for i in b.event_ids}
            self.assertEqual(kept, {self.m.secondary.events[-1].id})        # the B story's later scene stays
        comp = self.compose(only_a)
        self.assertNotIn("B", self.stories(comp))
        self.assertNotIn("texture", self.stories(comp))
        self.assertFalse(comp.over_budget)

    def test_b_is_never_cut_while_texture_is_still_there(self):
        for budget in range(0, int(self.seconds[0]) + 2):
            comp = self.compose(float(budget))
            stories = {t.story for t in comp.trimmed}
            if "B" in stories:
                self.assertIn("texture", stories, budget)

    def test_the_a_story_is_never_cut_and_is_reported_when_it_alone_is_too_long(self):
        source = self.compose(1e9)
        a_events = {i for b in EK.filmed_beats(source.plan) if b.story == "A" for i in b.event_ids}
        comp = self.compose(0.5)
        self.assertEqual({i for b in EK.filmed_beats(comp.plan) if b.story == "A" for i in b.event_ids}, a_events)
        self.assertEqual(set(self.stories(comp)), {"A"})
        self.assertTrue(comp.over_budget)
        self.assertEqual({t.story for t in comp.trimmed}, {"texture", "B"})

    def test_the_default_budget_is_the_longest_single_story_episode_filmed_today(self):
        self.assertEqual(EK.BODY_SECONDS_BUDGET, 30.0)


class Off(unittest.TestCase):
    """Without a composition nothing differs: the packet is what the documented steps make, and the map is absent."""

    @classmethod
    def setUpClass(cls):
        cls.c = produced(17, 4)
        cls.tmp = tempfile.mkdtemp(prefix="epk_")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def packet_of(self, conn, cand, thread, intents=None):
        from narrative.compiler import compile_packet
        from narrative.direction import plan_direction
        from narrative.performance import plan_performance
        from narrative.scene_spec import build_scene_specs
        from production import pipeline, series
        from contracts.stylepack import SUSPENSE_V1
        spec = build_scene_specs(self.c, [cand], ["day_01"])[0]
        recap = series.build_recap(conn, spec)
        direction = plan_direction(self.c, spec, thread, set(), intents=intents)
        performance = plan_performance(self.c, spec, direction)
        runtime = pipeline._runtime(self.c).trace([b.event_id for b in spec.beats])
        return compile_packet(spec, SUSPENSE_V1, "portrait", recap=recap, direction=direction, performance=performance, runtime=runtime)

    def test_make_episodes_without_a_composition_is_the_documented_steps_and_has_no_map(self):
        from narrative.director import select_thread
        from production import db as prod
        from production.pipeline import make_episodes
        cand, thread, _ = select_thread(self.c, 3, set())
        self.assertIsNotNone(cand)
        conn = prod.open_production_db(os.path.join(self.tmp, "off.db"))
        want = self.packet_of(conn, cand, thread)
        (got,) = make_episodes(self.c, conn, Path(self.tmp) / "off", [cand], scene_ids=["day_01"], render=False, threads=[thread])
        conn.close()
        self.assertEqual(got.packet_hash, want.packet_hash)
        self.assertIsNone(got.shot_map)

    def test_make_episodes_with_a_composition_makes_the_composed_packet_and_its_map(self):
        from narrative.selector import Candidate
        from production import db as prod
        from production.pipeline import make_episodes
        day = 2
        m = P.material(self.c, day, set(), (), P.AB)
        comp = EK.compose(self.c, m, set(), day, None, P.AB, budget=1e9)
        cand = Candidate(comp.arc, 0.5, {"episode_planner": 1.0})
        conn = prod.open_production_db(os.path.join(self.tmp, "on.db"))
        (got,) = make_episodes(self.c, conn, Path(self.tmp) / "on", [cand], scene_ids=["day_01"], render=False, threads=[m.thread],
                               intents=comp.intents, compositions=[comp])
        packet = prod.load_packet(conn, got.packet_hash)
        conn.close()
        self.assertEqual(got.packet_hash, self.packet_of_hash(comp, m))
        self.assertIsNotNone(got.shot_map)
        self.assertEqual(EK.check_map(packet, got.shot_map), [])
        self.assertEqual(got.shot_map.packet_hash, packet.packet_hash)

    def packet_of_hash(self, comp, m):
        from narrative.selector import Candidate
        from production import db as prod
        conn = prod.open_production_db(os.path.join(self.tmp, "ref.db"))
        try:
            return self.packet_of(conn, Candidate(comp.arc, 0.5, {"episode_planner": 1.0}), m.thread, comp.intents).packet_hash
        finally:
            conn.close()

    def test_a_composition_for_another_arc_is_refused(self):
        from narrative.director import select_thread
        from production import db as prod
        from production.pipeline import make_episodes
        m = P.material(self.c, 2, set(), (), P.AB)
        comp = EK.compose(self.c, m, set(), 2, None, P.AB, budget=1e9)
        cand, thread, _ = select_thread(self.c, 3, set())
        if tuple(cand.arc.ids) == tuple(comp.arc.ids):
            self.skipTest("the same arc")
        conn = prod.open_production_db(os.path.join(self.tmp, "bad.db"))
        with self.assertRaises(ValueError):
            make_episodes(self.c, conn, Path(self.tmp) / "bad", [cand], render=False, threads=[thread], compositions=[comp])
        conn.close()


class Fingerprint(unittest.TestCase):
    """What a packet made without a plan looks like, shot for shot (provenance hashes aside: they cover the code, and contracts/*.py is
    part of the code, so adding a contract moves every packet's hash without moving a shot). Recorded from the code before the A/B
    packet existed and again after: the same. If this fails the compile path (narrative/compiler.py, direction.py, the world) changed
    meaning: that may be right, but it is no longer this feature, so update it on purpose."""
    GOLDEN = "ab4a86644a85fd74a273763e"

    def test_the_thread_directors_packets_of_a_seeded_fortnight_are_unchanged(self):
        from narrative.compiler import compile_packet
        from narrative.direction import plan_direction
        from narrative.director import select_thread
        from narrative.scene_spec import build_scene_specs
        from agent.volition import VolitionDecider
        from producer.director import Director
        from world.db import connect, init_db
        from world.seed import build_world
        from world.simulation import Simulation
        c = connect()
        init_db(c, 17)
        build_world(c, 17, "jianghu_story_v1")
        d = VolitionDecider(17)
        sim = Simulation(c, d, d, set(), feed="synthetic_v1", producer=Director("greedy", 17))
        parts = []
        shown: set[int] = set()
        for day in range(4):          # a day at a time, the pick made on the world as it stood that evening
            sim.run(1)
            cand, thread, _ = select_thread(c, day, shown)
            if cand is None:
                parts.append("quiet")
                continue
            spec = build_scene_specs(c, [cand], ["episode"])[0]
            packet = compile_packet(spec, direction=plan_direction(c, spec, thread, set(shown)))
            parts.append(f"{len(packet.shots)}:{hashlib.sha256(projected(packet).encode()).hexdigest()[:16]}")
            shown |= set(cand.arc.ids)
        self.assertEqual(hashlib.sha256("|".join(parts).encode()).hexdigest()[:24], self.GOLDEN, parts)


class Daily(unittest.TestCase):
    def run_days(self, days=3, **kw):
        from channel.daily import DailyConfig, run_daily
        tmp = tempfile.mkdtemp(prefix="dailyepk_")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        cfg = DailyConfig(world_db=os.path.join(tmp, "world.db"), prod_db=os.path.join(tmp, "prod.db"), out_dir=os.path.join(tmp, "episodes"),
                          days=days, seed=17, init=True, render=False, world_c=True, feed="synthetic_v1", recipe="jianghu_story_v1", **kw)
        return tmp, run_daily(cfg)

    def test_it_is_off_by_default(self):
        from channel.daily import DailyConfig
        cfg = DailyConfig("w", "p", "o")
        self.assertFalse(cfg.episode_first)
        self.assertFalse(cfg.episode_ab)

    def test_the_a_b_packet_needs_the_planner_to_choose(self):
        from channel.daily import DailyConfig, run_daily
        with self.assertRaises(ValueError):
            run_daily(DailyConfig("w.db", "p.db", "o", world_c=True, episode_ab=True))
        with self.assertRaises(ValueError):
            run_daily(DailyConfig("w.db", "p.db", "o", episode_first=True, episode_ab=True))

    def test_a_composed_day_writes_its_packet_its_map_and_the_plan_it_followed(self):
        tmp, results = self.run_days(episode_first=True, episode_ab=True)
        made = [r for r in results if r.episode is not None]
        self.assertTrue(made)
        saw_extra = False
        for r in made:
            folder = Path(tmp) / "episodes" / f"day_{r.sim_day + 1:02d}"
            packet = from_dict(ProductionPacket, json.loads((folder / "packet.json").read_text(encoding="utf-8")))
            emap = from_dict(cep.EpisodePacketMap, json.loads((folder / "episode_packet_map.json").read_text(encoding="utf-8")))
            plan = json.loads((folder / "episode_plan.json").read_text(encoding="utf-8"))
            self.assertEqual(packet.packet_hash, r.episode.packet_hash)
            self.assertEqual(EK.check_map(packet, emap), [])
            self.assertEqual(emap.plan_hash, plan["plan_hash"])
            self.assertEqual(plan["options"]["ab_story"], True)
            self.assertLessEqual(emap.body_seconds, emap.budget_seconds + (0 if not emap.over_budget else 1e9))
            saw_extra = saw_extra or any(x.story != "A" for x in emap.shots)
        self.assertTrue(saw_extra, "no day of the fortnight filmed a B story or an ordinary moment")

    def test_without_the_option_a_day_writes_no_map(self):
        tmp, results = self.run_days(days=2, episode_first=True)
        for r in results:
            folder = Path(tmp) / "episodes" / f"day_{r.sim_day + 1:02d}"
            self.assertFalse((folder / "episode_packet_map.json").exists())


class Schema(unittest.TestCase):
    def test_the_committed_schema_is_the_contracts(self):
        from contracts.generate_schemas import OUT, render_all
        self.assertEqual((OUT / "episode_packet_map.schema.json").read_text(encoding="utf-8"), render_all()["episode_packet_map"])

    def test_the_packet_contract_did_not_move(self):
        """The map is beside the packet, not inside it: the packet's schema and version are what they were."""
        from contracts.packet import PACKET_VERSION
        self.assertEqual(PACKET_VERSION, 5)
        fields = {f.name for f in dataclasses.fields(ProductionPacket)}
        self.assertNotIn("beat_index", fields)
        from contracts.packet import Shot
        self.assertNotIn("story", {f.name for f in dataclasses.fields(Shot)})


if __name__ == "__main__":
    unittest.main()
