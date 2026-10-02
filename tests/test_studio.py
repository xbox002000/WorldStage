"""The control room: what the exporter writes, what the page is made of, and that going on adds a day."""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from channel.studio import Studio
from render.studio.build import HERE

ROOT = Path(__file__).resolve().parent.parent


class Exporting(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="studio_"))
        cls.studio = Studio(cls.tmp, 17, 6)
        cls.doc = json.loads((cls.tmp / "studio.json").read_text(encoding="utf-8"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_one_record_per_day_with_what_the_page_shows(self):
        self.assertEqual(self.doc["meta"]["days"], 6)
        self.assertEqual([d["day"] for d in self.doc["days"]], list(range(6)))
        for d in self.doc["days"]:
            self.assertEqual(set(d), {"day", "state", "pacing", "episode", "producer", "payoffs", "events"})
            self.assertIn(d["pacing"]["phase"], ("calm", "warm", "peak"))
            self.assertEqual(set(d["producer"]), {"decisions", "entries", "spent_week"})

    def test_an_episode_carries_its_question_its_scenes_and_what_each_scene_said(self):
        eps = [d["episode"] for d in self.doc["days"] if d["episode"]]
        self.assertTrue(eps)
        for ep in eps:
            self.assertTrue(ep["core_question"])
            self.assertTrue(ep["people_names"])
            for b in ep["beats"]:
                self.assertTrue(all("caption" in e and "clock" in e for e in b["events"]))

    def test_every_day_the_producer_either_acts_or_says_why_it_keeps_still(self):
        for d in self.doc["days"]:
            self.assertTrue(d["producer"]["decisions"], d["day"])
            for x in d["producer"]["decisions"]:
                self.assertIn(x["action"], ("intervene", "silence"))
                self.assertTrue(x["reason"])

    def test_the_people_carry_what_the_people_tab_shows(self):
        self.assertTrue(self.doc["people"])
        for p in self.doc["people"]:
            self.assertTrue({"id", "name", "ability", "crowd", "debt", "debt_parts", "payoffs", "ties", "emotion"} <= set(p))

    def test_the_page_is_made_and_opens_from_the_file_system_too(self):
        site = self.tmp / "site"
        for name in ("index.html", "studio.css", "studio.js", "studio.json", "studio-data.js"):
            self.assertTrue((site / name).exists(), name)
        self.assertTrue((site / "studio-data.js").read_text(encoding="utf-8").startswith("window.STUDIO = "))
        html = (site / "index.html").read_text(encoding="utf-8")
        for ref in ("studio.css", "studio.js", "studio-data.js"):
            self.assertIn(ref, html)

    def test_the_same_world_is_in_3d_and_every_scene_knows_when_and_where_it_was(self):
        self.assertIsNotNone(self.doc["world3d"])
        self.assertTrue((self.tmp / "site" / "world" / "index.html").exists())
        self.assertTrue((self.tmp / "site" / "world" / "world.json").exists())
        for d in self.doc["days"]:
            for b in (d["episode"] or {"beats": []})["beats"]:
                for e in b["events"]:
                    self.assertIn("t", e)
                    self.assertIn("place_id", e)
                    self.assertEqual(e["t"] // 86400, e["day"])

    def test_a_world_without_minds_has_no_trace_of_them(self):
        """tests/test_mind_view.py is about a world whose people have an LLM; this one has none, and nothing of that shows."""
        self.assertNotIn("minds", self.doc)
        self.assertNotIn("mind", self.doc["meta"])
        for d in self.doc["days"]:
            for b in (d["episode"] or {"beats": []})["beats"]:
                self.assertFalse(any("mind" in e for e in b["events"]))
            for g in (d["episode"] or {"grammar": []})["grammar"]:
                self.assertFalse(any("mind" in e for e in g["events"]))
        world = json.loads((self.tmp / "site" / "world" / "world.json").read_text(encoding="utf-8")) if (self.tmp / "site" / "world" / "world.json").exists() \
            else json.loads((self.tmp / "world.json").read_text(encoding="utf-8"))
        self.assertFalse(any("mind" in e for e in world["events"]))
        self.assertIsNone(self.studio.mind)
        self.assertEqual((self.studio.minds, self.studio.mind_by_event), ([], {}))

    def test_going_on_adds_a_day_and_leaves_the_earlier_ones(self):
        before = json.dumps(self.studio.days[:6], sort_keys=True)
        tl_before = json.loads(json.dumps(self.doc["timeline"]))
        self.studio.advance(1)
        self.assertEqual(len(self.studio.days), 7)
        self.assertEqual(json.dumps(self.studio.days[:6], sort_keys=True), before)
        after = json.loads((self.tmp / "studio.json").read_text(encoding="utf-8"))
        self.assertEqual(after["meta"]["days"], 7)
        # the timeline grows by a day too, and the days already told are not rewritten
        self.assertEqual(after["timeline"]["days"], 7)
        for pid, row in tl_before["people"].items():
            for key in ("mood", "emo", "role"):
                self.assertEqual(after["timeline"]["people"][pid][key][:6], row[key][:6], (pid, key))
                self.assertEqual(len(after["timeline"]["people"][pid][key]), 7)
            self.assertEqual(after["timeline"]["people"][pid]["ev"][:len(row["ev"])], row["ev"])
        self.assertEqual([e for e in after["timeline"]["events"] if e["d"] < 6], tl_before["events"])

    # -- the character timeline (phase 5) ---------------------------------------------------------------------------------------------
    def test_the_timeline_has_a_row_per_person_and_a_cell_per_day(self):
        from channel.studio import TIMELINE_KINDS, VALENCE
        tl = self.doc["timeline"]
        self.assertEqual(tl["days"], 6)
        self.assertEqual(set(tl["people"]), {p["id"] for p in self.doc["people"]})
        keys = {f"{e['id']}:{e['k']}" for e in tl["events"]}
        self.assertEqual(len(keys), len(tl["events"]))                           # one record per (event, kind)
        for pid, row in tl["people"].items():
            self.assertEqual({len(row["mood"]), len(row["emo"]), len(row["role"])}, {6}, pid)
            self.assertTrue(set(row["role"]) <= set("LS."), pid)
            self.assertTrue(all(-1.0 <= m <= 1.0 for m in row["mood"]), pid)
            self.assertTrue(all(e in VALENCE for e in row["emo"]), pid)
            self.assertTrue(set(row["ev"]) <= keys, pid)
            self.assertEqual(row["ev"], sorted(row["ev"], key=lambda k: next((e["t"], e["id"]) for e in tl["events"] if f"{e['id']}:{e['k']}" == k)))
        self.assertTrue(all(e["k"] in TIMELINE_KINDS and e["k"] != "turn" for e in tl["events"]))

    def test_a_lead_is_at_most_one_person_a_day_and_only_in_an_episode(self):
        tl = self.doc["timeline"]
        for d in range(6):
            roles = {pid: row["role"][d] for pid, row in tl["people"].items()}
            self.assertLessEqual(list(roles.values()).count("L"), 1, d)
            ep = self.doc["days"][d]["episode"]
            if ep is None:
                self.assertEqual(set(roles.values()), {"."}, d)
            else:
                self.assertEqual({p for p, r in roles.items() if r in "LS"}, set(ep["people"]) & set(tl["people"]), d)

    def test_every_moment_and_turn_can_be_jumped_to_by_day_and_scene(self):
        tl = self.doc["timeline"]
        moments = list(tl["events"]) + [t for row in tl["people"].values() for t in row["turns"]]
        for m in moments:
            self.assertTrue(0 <= m["d"] < 6, m)
            self.assertEqual(m["t"] // 86400, m["d"], m)
            self.assertIn(":", m["c"])
            ev_id = m["id"] if "id" in m else m["e"]
            row = self.studio.conn.execute("SELECT timestamp FROM events WHERE event_id = ?", (ev_id,)).fetchone()
            self.assertIsNotNone(row, m)                                          # it points at an event of the world
            self.assertEqual(row[0] // 1440, m["d"], m)
            if "plid" in m:
                self.assertIn(m["plid"], tl["places"])
            if "b" in m:                                                          # the scene it is in must really be a filmed scene of that day showing it
                ep = self.doc["days"][m["d"]]["episode"]
                beat = next(b for b in ep["beats"] if b["index"] == m["b"])
                self.assertTrue(beat["shoot"])
                self.assertIn(ev_id, beat["event_ids"])
        for e in tl["events"]:
            self.assertTrue(e["w"] and set(e["w"]) <= set(tl["people"]), e)
            self.assertTrue(e["cap"], e)
        for pid, row in tl["people"].items():
            for t in row["turns"]:
                self.assertIn(t["o"], tl["people"])
                self.assertIn(t["f"], ("affection", "respect"))
                self.assertIn(t["y"], (-1, 1))
                self.assertEqual(t["y"] > 0, t["z"] > 0)

    def test_the_timeline_stays_a_small_part_of_the_file(self):
        from contracts.base import canonical_json
        rest = {k: v for k, v in self.doc.items() if k != "timeline"}
        self.assertLessEqual(len(canonical_json(self.doc["timeline"])), 0.25 * len(canonical_json(rest)))


class Timeline(unittest.TestCase):
    """The character timeline is a read model: the same world tells the same timeline, and telling it never writes to the world."""

    def test_the_same_world_tells_the_same_timeline_and_the_timeline_never_writes(self):
        import sqlite3
        from unittest import mock
        from contracts.base import canonical_json

        writes: list = []
        real = Studio._timeline_day

        def watched(studio, *a, **k):
            writing = (sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE, sqlite3.SQLITE_CREATE_TABLE, sqlite3.SQLITE_DROP_TABLE,
                       sqlite3.SQLITE_ALTER_TABLE, sqlite3.SQLITE_CREATE_INDEX, sqlite3.SQLITE_CREATE_TEMP_TABLE)
            studio.conn.set_authorizer(lambda action, *x: (writes.append(action) or sqlite3.SQLITE_OK) if action in writing else sqlite3.SQLITE_OK)
            try:
                return real(studio, *a, **k)
            finally:
                studio.conn.set_authorizer(None)

        out = []
        for _ in range(2):
            tmp = Path(tempfile.mkdtemp(prefix="studio_tl_"))
            self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
            with mock.patch.object(Studio, "_timeline_day", watched):
                s = Studio(tmp, 23, 4, recipe="jianghu_story_v1")
            out.append(canonical_json(s.timeline()))
        self.assertEqual(writes, [])
        self.assertEqual(out[0], out[1])
        self.assertEqual(json.loads(out[0])["days"], 4)


class Worlds(unittest.TestCase):
    def test_a_world_is_made_from_a_preset_listed_and_the_front_door_points_at_it(self):
        from channel.studio import Hub
        tmp = Path(tempfile.mkdtemp(prefix="hub_"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        hub = Hub(tmp)
        key = hub.make("town", 3, 2)
        self.assertEqual(key, "town-3")
        self.assertTrue((tmp / key / "site" / "index.html").exists())
        cat = json.loads((tmp / "worlds.json").read_text(encoding="utf-8"))
        self.assertEqual([w["key"] for w in cat["worlds"]], [key])
        self.assertTrue(cat["worlds"][0]["live"])
        self.assertIn("jianghu", cat["presets"])
        hub.front_door(key)
        self.assertIn(f"{key}/site/index.html", (tmp / "index.html").read_text(encoding="utf-8"))

    def test_a_world_left_by_an_earlier_run_is_listed_but_cannot_go_on(self):
        from channel.studio import Hub
        tmp = Path(tempfile.mkdtemp(prefix="hub_"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        Hub(tmp).make("town", 4, 1)
        later = Hub(tmp)
        rows = later.catalog()
        self.assertEqual([(r["key"], r["live"]) for r in rows], [("town-4", False)])

    def test_an_unknown_preset_is_refused_and_the_days_are_bounded(self):
        from channel.studio import Hub
        tmp = Path(tempfile.mkdtemp(prefix="hub_"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        with self.assertRaises(ValueError):
            Hub(tmp).make("nowhere")


class Page(unittest.TestCase):
    def test_the_script_is_valid_javascript(self):
        try:
            r = subprocess.run(["node", "--check", str(HERE / "studio.js")], capture_output=True, text=True, timeout=60)
        except FileNotFoundError:
            self.skipTest("node is not installed")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_the_page_only_reads(self):
        js = (HERE / "studio.js").read_text(encoding="utf-8")
        self.assertEqual(js.count("method: \"POST\""), 2)            # the two things it can ask: go on, and make another world
        self.assertIn("advance?n=", js)
        self.assertIn("/new?", js)
        self.assertNotIn("XMLHttpRequest", js)

    def test_the_page_has_the_timeline_and_every_kind_of_moment_has_its_word(self):
        from channel.studio import GOAL_TO, LOVE, OUTBURSTS, TIMELINE_KINDS, TURN_FIELDS
        js = (HERE / "studio.js").read_text(encoding="utf-8")
        html = (HERE / "index.html").read_text(encoding="utf-8")
        self.assertIn('data-v="timeline"', html)
        self.assertIn('id="timelineView"', html)
        self.assertIn("window.STUDIO", js)                                   # works from file:// (the data is a script), no fetch of a local json for it
        for kind in TIMELINE_KINDS:
            self.assertRegex(js, rf"\b{kind}: \[\"", kind)                   # its name and its mark
        for code in (*LOVE, *OUTBURSTS, *GOAL_TO, *TURN_FIELDS, "found", "join", "leave", "change", "accepted", "declined"):
            self.assertIn(code, js, code)
        for need in ("renderTimeline", "tlJump", "超出範圍", "沒有時間軸的資料"):    # jump to day and scene; a hint outside the 3D replay; an older world without the data
            self.assertIn(need, js, need)

    def test_the_page_shows_a_mind_only_where_the_data_has_one(self):
        js = (HERE / "studio.js").read_text(encoding="utf-8")
        for need in ("mindNote", "mindBlock", "dayMinds", "innerCard", "focusMind", "D.meta.mind", "(D.minds && D.minds.items) || []", "只能看，不能再走"):
            self.assertIn(need, js, need)
        self.assertIn("if (!m) { if (el) el.remove(); return; }", js)         # no mind in the data: no note
        self.assertIn("if (!list.length) return \"\"", js)                      # no mind that day: no card
        self.assertIn("if (!all.length) return \"\"", js)                       # no mind for this person: no heart-voice card
        html = (HERE / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("LLM", html)                                          # the page itself has nothing of it: only the script, from the data

    def test_a_blank_3d_frame_always_says_why(self):
        from render.studio import build as B
        html = (B.HERE / "index.html").read_text(encoding="utf-8")
        js = (B.HERE / "studio.js").read_text(encoding="utf-8")
        self.assertIn('id="worldNote"', html)
        for need in ("watchFrame", 'location.protocol === "file:"', "frameReload", "超過 10 秒沒有回應"):
            self.assertIn(need, js, need)

    def test_the_page_speaks_the_words_of_the_planner(self):
        from contracts.episode_plan import GRAMMAR_STEPS, INTENTS, STAGES
        js = (HERE / "studio.js").read_text(encoding="utf-8")
        for word in (*INTENTS, *STAGES, *GRAMMAR_STEPS):
            self.assertIn(word, js, word)


if __name__ == "__main__":
    unittest.main()
