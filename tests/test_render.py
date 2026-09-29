from __future__ import annotations

import dataclasses
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from contracts.packet import Camera, ShotCharacter
from narrative.color import avatar_color, ink_for, luminance
from render.hyperframes_backend import CLI, GSAP, FFMPEG_DIR
from render.packet_html import (MAX_BACKGROUND, OFFSETS, ZOOM, build_plan, build_project, per_row, render_html, to_srt)
from tests.world_fixture import compile_all

CROWD = [ShotCharacter(f"p{i}", f"人{i}", f"char_p{i}", "actor" if i == 0 else "target" if i == 1 else "witness",
                       "left" if i == 0 else "right" if i == 1 else "background", "watch", "uneasy") for i in range(10)]


def crowded(packet, shot_type, movement="static"):
    shot = dataclasses.replace(packet.shots[0], characters=CROWD, camera=Camera(shot_type, movement, 35))
    locks = dict(packet.continuity_locks.characters)
    for c in CROWD:
        locks[c.id] = dataclasses.replace(next(iter(locks.values())), asset_id=c.asset_id)
    return dataclasses.replace(packet, shots=[shot], continuity_locks=dataclasses.replace(packet.continuity_locks, characters=locks))


class LayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.packet = compile_all()[0]

    def screen_positions(self, plan):
        for shot in plan["shots"]:
            for cam in (shot["cam"], shot["cam_end"]):
                for p in shot["people"]:
                    yield cam["x"] + cam["scale"] * p["x"], cam["y"] + cam["scale"] * p["y"], cam["scale"]

    def test_crowds_stay_inside_the_frame_at_every_zoom_and_orientation(self):
        for orientation in ("portrait", "landscape"):
            packet = compile_all(orientation=orientation)[0]
            w, h = packet.canvas.width, packet.canvas.height
            for shot_type in ZOOM:
                for movement in ("static", "slow_push_in"):
                    plan = build_plan(crowded(packet, shot_type, movement))
                    for x, y, scale in self.screen_positions(plan):
                        margin = 42 * scale  # an avatar's radius on screen
                        self.assertTrue(margin <= x <= w - margin, (orientation, shot_type, movement, x))
                        self.assertTrue(60 <= y <= h, (orientation, shot_type, movement, y))

    def test_only_a_handful_of_onlookers_are_drawn_and_the_rest_counted(self):
        plan = build_plan(crowded(self.packet, "wide"))
        shot = plan["shots"][0]
        drawn_onlookers = [p for p in shot["people"] if p["bg"]]
        self.assertLessEqual(len(drawn_onlookers), MAX_BACKGROUND)
        self.assertGreater(len(drawn_onlookers), 0)
        self.assertEqual(shot["more"], 8 - len(drawn_onlookers))  # 10 people, 2 principals, 8 onlookers
        self.assertEqual(len(shot["people"]), 2 + len(drawn_onlookers))

    def test_rows_get_shorter_as_the_camera_gets_closer(self):
        widths = [per_row(1080, z) for z in (1.0, 1.3, 1.7, 2.0)]
        self.assertEqual(widths, sorted(widths, reverse=True))
        self.assertGreaterEqual(min(widths), 1)

    def test_principals_keep_their_fixed_places(self):
        plan = build_plan(crowded(self.packet, "close_up"))
        left, right = plan["shots"][0]["people"][:2]
        self.assertLess(left["x"], right["x"])
        self.assertEqual(set(OFFSETS), {"left", "right"})

    def test_onlookers_carry_no_feeling_label(self):
        plan = build_plan(crowded(self.packet, "wide"))
        self.assertEqual({p["id"] for p in plan["people"] if p["emotions"]}, {"p0", "p1"})


class HtmlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.packet = compile_all()[0]

    def test_the_timeline_is_seek_safe(self):
        html = render_html(self.packet)
        self.assertNotIn("tl.call(", html.replace("(tl.call would not survive a seek)", ""))
        self.assertIn("window.__timelines", html)

    def test_same_packet_same_html_and_a_score_only_when_given(self):
        self.assertEqual(render_html(self.packet), render_html(self.packet))
        self.assertNotIn("<audio", render_html(self.packet))
        with_score = render_html(self.packet, with_score=True)
        self.assertIn('<audio id="score" src="assets/score.wav"', with_score)
        self.assertIn(f'data-duration="{self.packet.qa.total_seconds}"', with_score)

    def test_every_shot_has_its_own_caption_and_hud(self):
        html = render_html(self.packet)
        self.assertEqual(html.count('"caption"'), len(self.packet.shots))
        for shot in self.packet.shots:
            self.assertIn(shot.caption, html)

    def test_subtitles_are_written_from_the_plan(self):
        srt = to_srt(self.packet)
        self.assertEqual(srt.count("-->"), len(self.packet.subtitle_plan))
        for cue in self.packet.subtitle_plan:
            self.assertIn(cue.text, srt)

    def test_the_recap_appears_on_the_title_card(self):
        from narrative.compiler import compile_packet
        from tests.world_fixture import build_specs
        packet = compile_packet(build_specs()[0], recap="上集：阿明當面質問阿濤")
        self.assertIn("前情提要：", render_html(packet))
        self.assertIn("上集：阿明當面質問阿濤", render_html(packet))

    def test_project_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = build_project(self.packet, Path(tmp) / "p", GSAP, score=b"RIFFxxxx")
            self.assertEqual({p.name for p in out.iterdir()}, {"index.html", "meta.json", "subtitles.srt", "gsap.min.js", "assets"})
            self.assertEqual((out / "assets" / "score.wav").read_bytes(), b"RIFFxxxx")

    @unittest.skipUnless(CLI.exists(), "hyperframes is not installed")
    def test_hyperframes_lint_accepts_the_generated_project(self):
        env = {**os.environ, "HYPERFRAMES_SKIP_SKILLS": "1", "PATH": str(FFMPEG_DIR) + os.pathsep + os.environ["PATH"]}
        with tempfile.TemporaryDirectory() as tmp:
            out = build_project(self.packet, Path(tmp) / "p", GSAP, score=b"RIFFxxxx")
            r = subprocess.run([str(CLI), "lint", str(out)], capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
        self.assertEqual(r.returncode, 0, r.stdout[-600:] + r.stderr[-300:])


class ColourTests(unittest.TestCase):
    CAST = sorted(["ming", "mei", "jun", "lan", "hao", "yun", "kai", "ning", "tao", "rui"])

    def test_no_two_people_share_a_look_and_all_read_under_white_text(self):
        colours = [avatar_color(pid, i) for i, pid in enumerate(self.CAST)]
        hues = sorted(int(c.split("(")[1].split(",")[0]) for c in colours)
        gaps = [b - a for a, b in zip(hues, hues[1:])] + [hues[0] + 360 - hues[-1]]
        self.assertGreaterEqual(min(gaps), 15)
        for c in colours:
            self.assertGreaterEqual(1.05 / (luminance(c) + 0.05), 4.2, c)
            self.assertEqual(ink_for(c), "#ffffff")

    def test_colours_are_stable_and_a_lighter_legacy_colour_gets_dark_ink(self):
        self.assertEqual(avatar_color("ming", 3), avatar_color("ming", 3))
        self.assertNotEqual(avatar_color("ming", 3), avatar_color("ming", 4))
        self.assertEqual(ink_for("hsl(60, 55%, 52%)"), "#0d1117")  # the old pale yellow-green

    def test_the_lock_records_the_colour_actually_drawn(self):
        packet = compile_all()[0]
        plan = build_plan(packet)
        for person in plan["people"]:
            lock = packet.continuity_locks.characters[person["id"]]
            self.assertIn(f"avatar_color={person['color']}", lock.identity_lock)


if __name__ == "__main__":
    unittest.main()
