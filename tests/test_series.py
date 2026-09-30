from __future__ import annotations

import dataclasses
import json
import unittest
from pathlib import Path

from contracts.base import from_dict
from contracts.migrate import migrate_packet, migrate_request, migrate_scene_spec
from contracts.packet import ProductionPacket
from contracts.packet import verify as verify_packet
from contracts.scene_spec import SceneSpec, finalize
from contracts.scene_spec import verify as verify_spec
from narrative.arcs import Arc, build_arcs, load_events, without
from narrative.compiler import caption, compile_packet
from narrative.continuity import closure, connects
from narrative.scene_spec import build_scene_specs, validate_spec
from narrative.selector import CONTINUITY_BONUS, rank_arcs, select_daily, select_top
from production import db as prod
from production import series
from tests.helpers import social_world
from tests.test_social import STOLE, cid, do, told_memory
from tests.world_fixture import build_specs, reader
from world.events import Change, EventSpec, apply_event
from world.intent import Intent

FIXTURES = Path(__file__).parent / "fixtures"


def lie_story(finish: bool = True):
    """theft -> lie -> the truth from someone else -> (optionally) the exposure. Returns (conn, event ids)."""
    conn = social_world()
    ids = {"theft": do(conn, 10, Intent("tom", "steal", "phone"))}
    do(conn, 11, Intent("ben", "move", "cafe"))
    sid = cid(conn, STOLE)
    ids["lie"] = do(conn, 20, Intent("john", "tell", "ben", mode="lie", claim_id=sid))
    word = told_memory(conn, "ben", "john")
    ids["truth"] = do(conn, 30, Intent("mary", "tell", "ben", mode="truth", claim_id=sid))
    if finish:
        ids["exposure"] = do(conn, 40, Intent("ben", "confront", "john", memory_id=word))
    return conn, ids


def incident_arc(conn) -> Arc:
    return next(a for a in build_arcs(load_events(conn)) if a.kind == "incident")


class ArcTests(unittest.TestCase):
    def test_incident_arc_collects_the_lie_the_rumour_and_the_exposure(self):
        conn, ids = lie_story()
        arc = incident_arc(conn)
        self.assertEqual(list(arc.ids), [ids["theft"], ids["lie"], ids["truth"], ids["exposure"]])
        self.assertEqual(arc.peak.id, ids["exposure"])  # the most important beat carries the arc
        self.assertEqual(arc.key, ("incident", ids["theft"]))

    def test_a_small_incident_is_not_an_arc(self):
        conn = social_world()
        do(conn, 10, Intent("tom", "steal", "phone"))
        do(conn, 11, Intent("ben", "move", "cafe"))
        do(conn, 20, Intent("john", "tell", "ben", mode="lie", claim_id=cid(conn, STOLE)))
        self.assertEqual([a for a in build_arcs(load_events(conn)) if a.kind == "incident"], [])  # only two events

    def test_large_incidents_are_capped_and_stay_in_time_order(self):
        events = load_events(lie_story()[0])
        arc = incident_arc(lie_story()[0])
        self.assertLessEqual(len(arc.events), 6)
        self.assertEqual(list(arc.ids), sorted(arc.ids))
        self.assertTrue(all(e.id in events for e in arc.events))

    def test_without_trims_shown_events_and_keeps_the_new_peak(self):
        conn, ids = lie_story()
        arc = incident_arc(conn)
        trimmed = without(arc, {ids["theft"], ids["lie"]})
        self.assertEqual(list(trimmed.ids), [ids["truth"], ids["exposure"]])
        self.assertEqual(trimmed.peak.id, ids["exposure"])
        self.assertIsNone(without(arc, set(arc.ids) - {ids["exposure"]}))  # too little that is new
        moved = without(arc, {ids["exposure"]})
        self.assertNotEqual(moved.peak.id, ids["exposure"])  # a peak already shown is replaced


class ScoringTests(unittest.TestCase):
    def test_an_exposed_lie_is_a_revelation_a_hanging_lie_is_tension(self):
        conn, _ = lie_story(finish=True)
        ranked, _ = rank_arcs(conn)
        top = next(c for c in ranked if c.arc.kind == "incident")
        self.assertEqual((top.breakdown["revelation"], top.breakdown["unresolved_tension"]), (1.0, 0.3))

        conn2, _ = lie_story(finish=False)
        top2 = next(c for c in rank_arcs(conn2)[0] if c.arc.kind == "incident")
        self.assertEqual((top2.breakdown["revelation"], top2.breakdown["unresolved_tension"]), (0.5, 1.0))

    def test_the_exposure_story_outranks_plain_small_talk(self):
        conn, _ = lie_story()
        do(conn, 50, Intent("anna", "move", "cafe"))
        do(conn, 51, Intent("anna", "talk", "tom", "cold"))
        do(conn, 52, Intent("tom", "talk", "anna", "cold"))
        ranked, _ = rank_arcs(conn)
        self.assertEqual(ranked[0].arc.kind, "incident")

    def test_weights_come_from_the_style_and_change_the_ranking(self):
        conn, _ = lie_story()
        base = rank_arcs(conn)[0][0].score
        no_revelation = {k: (0.0 if k == "revelation" else v) for k, v in
                         __import__("contracts.stylepack", fromlist=["SCORE_WEIGHTS_V1"]).SCORE_WEIGHTS_V1.items()}
        self.assertLess(rank_arcs(conn, weights=no_revelation)[0][0].score, base)


class ContinuityTests(unittest.TestCase):
    def test_a_follow_up_depends_on_what_was_already_shown(self):
        conn, ids = lie_story()
        events = load_events(conn)
        arc = without(incident_arc(conn), {ids["theft"], ids["lie"]})
        evidence = connects(conn, events, arc, {ids["theft"], ids["lie"]})
        self.assertEqual(evidence["kind"], "causal")
        self.assertIn(ids["lie"], closure(events, {ids["exposure"]}))  # confrontation -> the lie it exposes

    def test_nothing_shown_means_no_continuity(self):
        conn, _ = lie_story()
        events = load_events(conn)
        self.assertIsNone(connects(conn, events, incident_arc(conn), set()))
        self.assertIsNone(connects(conn, events, incident_arc(conn), {987654}))

    def test_state_lineage_links_arcs_that_touch_the_same_relationship(self):
        conn = social_world()

        def cold_talk(ts, a, b):
            return apply_event(conn, EventSpec(
                timestamp=ts, type="talk", trigger_type="t", truth={"tone": "cold"},
                participants=[(a, "actor"), (b, "target")],
                changes=[Change("relationship", f"{b}:{a}", "trust", delta=-0.1)]))

        first = cold_talk(10, "john", "mary")  # shown in an earlier episode
        second = cold_talk(20, "john", "mary")  # no parent link: only the shared relationship connects them
        events = load_events(conn)
        arc = Arc((events[second],), events[second])
        self.assertEqual(connects(conn, events, arc, {first})["kind"], "state")

    def test_routine_changes_do_not_count_as_a_storyline(self):
        conn = social_world()
        moved = apply_event(conn, EventSpec(timestamp=10, type="move", trigger_type="t",
                                            changes=[Change("person", "john", "energy", delta=-2)]))
        later = apply_event(conn, EventSpec(timestamp=20, type="talk", trigger_type="t", truth={"tone": "cold"},
                                            participants=[("john", "actor"), ("mary", "target")],
                                            changes=[Change("person", "john", "energy", delta=-2)]))
        events = load_events(conn)
        self.assertIsNone(connects(conn, events, Arc((events[later],), events[later]), {moved}))


class SelectionTests(unittest.TestCase):
    def test_follow_ups_get_the_continuity_bonus(self):
        conn, ids = lie_story()
        shown = {ids["theft"], ids["lie"]}
        follow_up = next(c for c in rank_arcs(conn, exclude=shown)[0] if c.arc.kind == "incident")
        self.assertIsNotNone(follow_up.continuity)
        self.assertAlmostEqual(follow_up.score - follow_up.base_score, CONTINUITY_BONUS, places=4)

    def test_selection_never_repeats_events_or_stories(self):
        r = reader()
        first, _ = select_top(r, 3)
        used = {i for c in first for i in c.arc.ids}
        second, _ = select_top(r, 3, exclude=used)
        self.assertFalse(used & {i for c in second for i in c.arc.ids})
        keys = [c.arc.key for c in second]
        self.assertEqual(len(keys), len(set(keys)))

    def test_daily_choice_prefers_the_latest_days(self):
        r = reader()
        cand, events = select_daily(r, day=6)
        self.assertIsNotNone(cand)
        self.assertGreaterEqual(cand.arc.peak.day, 5)
        again, _ = select_daily(r, day=6)
        self.assertEqual(cand.arc.ids, again.arc.ids)  # deterministic


class CaptionAndCompileTests(unittest.TestCase):
    def test_the_lie_story_reads_as_a_story(self):
        conn, ids = lie_story()
        chosen = [next(c for c in rank_arcs(conn)[0] if c.arc.kind == "incident")]
        spec = build_scene_specs(conn, chosen)[0]
        validate_spec(conn, spec)
        self.assertTrue(all(b.incident == ids["theft"] for b in spec.beats[1:]))
        packet = compile_packet(spec)
        captions = [s.caption for s in packet.shots]
        self.assertTrue(any("撒了謊" in c for c in captions))
        self.assertTrue(any("揭穿" in c for c in captions))
        self.assertEqual(packet.shots[-1].camera.shot_type, "close_up")  # the exposure gets the close-up
        self.assertTrue(verify_packet(packet))

    def test_every_beat_type_compiles(self):
        from narrative.compiler import BEATS
        for (event_type, variant) in BEATS:
            self.assertIn(event_type, ("talk", "steal", "tell", "confront", "take", "misplace", "find", "give",
                                       "notice_missing", "accuse", "lend", "repay", "parrot_speaks", "seed", "duel", "train"))
        specs = build_specs()
        for spec in specs:
            compile_packet(spec)  # no beat in the fixture world may break the compiler


class SeriesTests(unittest.TestCase):
    def setUp(self):
        self.conn = prod.open_production_db()
        self.spec = build_specs()[0]
        prod.save_scene_spec(self.conn, self.spec)
        series.record_episode(self.conn, scene_hash=self.spec.scene_hash, take_id=None, title=self.spec.title, sim_day=1,
                              arc_kind="pair", score=0.5, continuity=None, qa_status="ok", recap="")

    def follow_up(self, title="next"):
        spec = finalize(dataclasses.replace(self.spec, title=title, scene_id="next"))
        return spec

    def test_used_events_are_those_of_shown_episodes(self):
        self.assertEqual(series.used_event_ids(self.conn), set(self.spec.source.source_event_ids))
        self.conn.execute("UPDATE episodes SET status='rejected'")
        self.assertEqual(series.used_event_ids(self.conn), set())  # a rejected episode is not "shown"

    def test_recap_reminds_viewers_of_the_earlier_episode_with_the_same_people(self):
        recap = series.build_recap(self.conn, self.follow_up())
        peak = next(b for b in self.spec.beats if b.event_id == self.spec.peak_event_id)
        names = {pid: p.name for pid, p in self.spec.characters.items()}
        self.assertEqual(recap, caption(peak, names))

    def test_recap_ignores_unrelated_episodes_and_the_episode_itself(self):
        self.assertEqual(series.build_recap(self.conn, self.spec), "")  # itself
        stranger = finalize(dataclasses.replace(self.spec, scene_id="x", characters={}, beats=[
            dataclasses.replace(b, participants=[dataclasses.replace(p, id="nobody") for p in b.participants])
            for b in self.spec.beats]))
        self.assertEqual(series.build_recap(self.conn, stranger), "")

    def test_recap_lengthens_the_title_card_and_is_deterministic(self):
        spec = self.follow_up()
        recap = series.build_recap(self.conn, spec)
        with_recap, without_recap = compile_packet(spec, recap=recap), compile_packet(spec)
        self.assertGreater(with_recap.episode.title_seconds, without_recap.episode.title_seconds)
        self.assertEqual(with_recap.shots[0].start_seconds, with_recap.episode.title_seconds)
        self.assertEqual(recap, series.build_recap(self.conn, spec))

    def test_production_db_upgrades_an_older_file(self):
        import os
        import sqlite3
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "old.db")
            old = sqlite3.connect(path)
            old.executescript("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);"
                              "INSERT INTO meta VALUES ('schema_version','1');"
                              "CREATE TABLE scene_specs (scene_hash TEXT PRIMARY KEY, world_revision INTEGER NOT NULL,"
                              " history_hash TEXT NOT NULL, spec_json TEXT NOT NULL, created_at INTEGER NOT NULL);"
                              "CREATE TABLE takes (take_id INTEGER PRIMARY KEY);"
                              "CREATE TABLE episodes (episode_id INTEGER PRIMARY KEY AUTOINCREMENT, scene_hash TEXT NOT NULL,"
                              " take_id INTEGER, title TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'draft', created_at INTEGER NOT NULL);")
            old.commit()
            old.close()
            upgraded = prod.open_production_db(path)
            cols = {r["name"] for r in upgraded.execute("PRAGMA table_info(episodes)")}
            self.assertTrue({"sim_day", "arc_kind", "score", "continuity_json", "qa_status", "recap"} <= cols)
            self.assertEqual(upgraded.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0],
                             str(prod.SCHEMA_VERSION))
            tables = {r[0] for r in upgraded.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            self.assertTrue({"provider_selections", "visual_failures", "repair_requests"} <= tables)  # v3
            upgraded.close()


class MigrationTests(unittest.TestCase):
    def test_v2_scene_spec_loads_as_v3(self):
        data = json.loads((FIXTURES / "legacy_scene_spec_v2.json").read_text(encoding="utf-8"))
        self.assertEqual(data["version"], 2)
        spec = finalize(from_dict(SceneSpec, migrate_scene_spec(data)))
        self.assertEqual(spec.version, 3)
        self.assertTrue(verify_spec(spec))
        old_tones = [b.get("tone") for b in data["beats"]]
        self.assertEqual([b.variant for b in spec.beats], old_tones)  # `tone` became `variant`, values preserved
        self.assertTrue(all(b.detail is None and b.incident is None for b in spec.beats))

    def test_v1_packet_loads_as_current(self):
        data = json.loads((FIXTURES / "legacy_packet_v1.json").read_text(encoding="utf-8"))
        self.assertEqual(data["version"], 1)
        migrated = from_dict(ProductionPacket, migrate_packet(data))
        self.assertEqual(migrated.version, 4)
        self.assertEqual(migrated.direction_hash, "")
        self.assertTrue(all(s.function == "" and s.dialogue == "full" for s in migrated.shots))
        self.assertTrue(all(s.scale == "" and s.subject_id == "" and s.transition == "" for s in migrated.shots))
        self.assertEqual(len(migrated.shots), len(data["shots"]))
        self.assertEqual(migrated.packet_hash, "")  # a migrated document is new: it gets stamped when re-finalised

    def test_v1_render_request_gains_the_audio_toolchain_field(self):
        data = {"version": 1, "toolchain": {"hyperframes": "1", "ffmpeg": "f", "chrome": "c", "encoder": "e"}, "request_hash": "x"}
        migrated = migrate_request(data)
        self.assertEqual((migrated["version"], migrated["toolchain"]["audio"], migrated["request_hash"]), (2, "", ""))

    def test_unknown_versions_are_refused(self):
        for fn in (migrate_scene_spec, migrate_packet, migrate_request):
            with self.assertRaises(ValueError):
                fn({"version": 99, "beats": [], "audio_plan": {"cues": []}, "toolchain": {}})

    def test_stored_old_specs_are_migrated_on_load(self):
        conn = prod.open_production_db()
        data = json.loads((FIXTURES / "legacy_scene_spec_v2.json").read_text(encoding="utf-8"))
        conn.execute("INSERT INTO scene_specs(scene_hash, world_revision, history_hash, spec_json, created_at) VALUES (?,?,?,?,0)",
                     (data["scene_hash"], data["source"]["world_revision"], data["source"]["history_hash"], json.dumps(data)))
        spec = prod.load_scene_spec(conn, data["scene_hash"])
        self.assertEqual(spec.version, 3)
        self.assertTrue(verify_spec(spec))


if __name__ == "__main__":
    unittest.main()
