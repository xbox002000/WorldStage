from __future__ import annotations

import ast
import dataclasses
import os
import shutil
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path

from agent.decision import SeededDecider
from contracts.base import canonical_json
from contracts.packet import QARequirements
from contracts.render_request import Take
from narrative.compiler import compile_packet
from narrative.scene_spec import build_scene_specs, validate_spec
from narrative.selector import select_top
from production import db as prod
from production.pipeline import produce
from production.provenance import ProvenanceError, trace_take
from production.qa import preflight
from render.hyperframes_backend import FFMPEG_DIR
from tests.world_fixture import SEED, build_specs, compile_all, reader, world_path
from world.db import connect, init_db
from world.events import Change, EventSpec, apply_event
from world.reader import open_world_reader
from world.seed import build_world
from world.simulation import Simulation
from world.snapshot import snapshot_hash

ROOT = Path(__file__).resolve().parent.parent
FFMPEG = FFMPEG_DIR / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
FFPROBE = FFMPEG_DIR / ("ffprobe.exe" if os.name == "nt" else "ffprobe")


def other_world(seed: int, days: int = 7) -> str:
    path = os.path.join(tempfile.mkdtemp(prefix="worldfx_"), "world.db")
    conn = connect(path)
    init_db(conn, seed)
    build_world(conn, seed)
    d = SeededDecider(seed)
    Simulation(conn, d, d, set()).run(days)
    conn.close()
    return path


class CompilerDeterminismTests(unittest.TestCase):
    def test_same_world_same_style_gives_byte_identical_packets(self):
        a = [canonical_json(p) for p in compile_all()]
        b = [canonical_json(p) for p in compile_all()]
        self.assertEqual(a, b)

    def test_two_independently_built_worlds_give_identical_specs_and_packets(self):
        r = open_world_reader(other_world(SEED))
        specs = build_scene_specs(r, select_top(r, 3)[0])
        self.assertEqual([canonical_json(s) for s in specs], [canonical_json(s) for s in build_specs()])
        self.assertEqual([canonical_json(compile_packet(s)) for s in specs], [canonical_json(p) for p in compile_all()])

    def test_asset_ids_are_fixed_per_person_place_and_prop(self):
        seen: dict[str, tuple] = {}
        for packet in compile_all():
            for pid, lock in packet.continuity_locks.characters.items():
                self.assertEqual(lock.asset_id, f"char_{pid}")
                self.assertEqual(seen.setdefault(pid, (lock.asset_id, lock.identity_lock)), (lock.asset_id, lock.identity_lock))
            for lid, lock in packet.continuity_locks.locations.items():
                self.assertEqual(lock.asset_id, f"loc_{lid}")
            for shot in packet.shots:
                for c in shot.characters:
                    self.assertEqual(c.asset_id, f"char_{c.id}")
                for p in shot.props:
                    self.assertEqual(p.asset_id, f"prop_{p.id}")

    def test_spec_validation_and_provenance_fields(self):
        r = reader()
        for spec in build_specs():
            validate_spec(r, spec)
            self.assertEqual(sorted(spec.source.source_event_ids), sorted(b.event_id for b in spec.beats))
            self.assertTrue(spec.source.world_snapshot_hash.startswith("sha256:"))
            self.assertEqual(spec.source.world_snapshot_hash, snapshot_hash(r))


class ProductionCannotTouchTheWorldTests(unittest.TestCase):
    FORBIDDEN = {"world.events", "world.db", "world.rules", "world.simulation", "world.seed", "world.intent"}

    def test_production_side_modules_never_import_the_writers(self):
        offenders = []
        for folder in ("production", "render", "narrative"):
            for path in (ROOT / folder).glob("*.py"):
                for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                    names = []
                    if isinstance(node, ast.ImportFrom) and node.module:
                        names = [node.module]
                    elif isinstance(node, ast.Import):
                        names = [a.name for a in node.names]
                    offenders += [f"{path.name}: {n}" for n in names if n in self.FORBIDDEN]
        self.assertEqual(offenders, [])

    def test_only_the_production_db_module_opens_writable_sqlite_files(self):
        offenders = []
        for folder in ("production", "render", "narrative"):
            for path in (ROOT / folder).glob("*.py"):
                if "sqlite3.connect(" in path.read_text(encoding="utf-8") and path.name != "db.py":
                    offenders.append(f"{folder}/{path.name}")
        self.assertEqual(offenders, [])

    def test_the_channel_orchestrator_is_where_the_two_sides_meet(self):
        text = (ROOT / "channel" / "daily.py").read_text(encoding="utf-8")
        self.assertIn("from world.simulation import Simulation", text)  # it may write the world (on a copy)...
        self.assertIn("from production import db as prod", text)  # ...and it is the only one that also drives production
        for folder in ("production", "render", "narrative"):
            for path in (ROOT / folder).glob("*.py"):
                self.assertNotIn("from channel", path.read_text(encoding="utf-8"), path.name)  # nothing depends back on it

    def test_running_the_pipeline_leaves_the_world_unchanged(self):
        r = reader()
        before = snapshot_hash(r)
        with tempfile.TemporaryDirectory() as tmp:
            produce(world_path(), os.path.join(tmp, "p.db"), Path(tmp) / "out", top=3, render=False, exclude_used=False)
        self.assertEqual(snapshot_hash(reader()), before)


class ProductionDbTests(unittest.TestCase):
    def test_content_addressed_rows_are_immutable_and_saves_are_idempotent(self):
        conn = prod.open_production_db()
        spec, packet = build_specs()[0], compile_all()[0]
        prod.save_scene_spec(conn, spec)
        prod.save_scene_spec(conn, spec)
        prod.save_packet(conn, packet)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM scene_specs").fetchone()[0], 1)
        for sql in ("UPDATE scene_specs SET spec_json='{}'", "UPDATE packets SET packet_json='{}'"):
            with self.subTest(sql), self.assertRaises(sqlite3.DatabaseError):
                conn.execute(sql)
        self.assertEqual(prod.load_packet(conn, packet.packet_hash), packet)

    def test_ready_take_lookup(self):
        conn = prod.open_production_db()
        spec, packet = build_specs()[0], compile_all()[0]
        from render.hyperframes_backend import HyperFramesBackend
        backend = HyperFramesBackend(lambda h: packet)
        request = backend.make_request(packet)
        prod.save_scene_spec(conn, spec)
        prod.save_packet(conn, packet)
        prod.save_request(conn, request)
        self.assertIsNone(prod.ready_take(conn, request.request_hash))
        prod.record_take(conn, Take(request.request_hash, "failed", error="boom"))
        self.assertIsNone(prod.ready_take(conn, request.request_hash))  # failures are never reused
        tid = prod.record_take(conn, Take(request.request_hash, "ready", artifact_path="x.mp4", artifact_hash="sha256:a"))
        self.assertEqual(prod.ready_take(conn, request.request_hash).take_id, tid)


class ProvenanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="prov_")
        cls.world = os.path.join(cls.tmp, "world.db")
        shutil.copyfile(world_path(), cls.world)
        cls.prod_db = os.path.join(cls.tmp, "p.db")
        produce(cls.world, cls.prod_db, Path(cls.tmp) / "out", top=3, render=False, exclude_used=False)

    def chain(self, world_path_):
        conn = sqlite3.connect(self.prod_db)
        conn.row_factory = sqlite3.Row
        take_id = conn.execute("SELECT MIN(take_id) FROM takes").fetchone()[0]
        return trace_take(conn, open_world_reader(world_path_), take_id)

    def test_take_traces_back_to_world_events(self):
        chain = self.chain(self.world)
        for key in ("request_hash", "packet_hash", "scene_hash", "history_hash"):
            self.assertTrue(chain[key].startswith("sha256:"))
        self.assertTrue(chain["source_event_ids"])
        self.assertEqual((chain["snapshot_checked"], chain["snapshot_ok"], chain["world_moved_on_by"]), (True, True, 0))

    def test_chain_stays_verifiable_after_the_world_moves_on(self):
        moved = os.path.join(self.tmp, "moved.db")
        shutil.copyfile(self.world, moved)
        conn = connect(moved)
        apply_event(conn, EventSpec(timestamp=10**7, type="later", trigger_type="t",
                                    changes=[Change("person", "ming", "energy", delta=-1)]))
        conn.close()
        chain = self.chain(moved)
        self.assertEqual((chain["snapshot_checked"], chain["snapshot_ok"], chain["world_moved_on_by"]), (False, None, 1))

    def test_a_different_world_is_detected(self):
        with self.assertRaises(ProvenanceError):
            self.chain(other_world(SEED + 1))


@unittest.skipUnless(FFMPEG.exists(), "local ffmpeg not installed")
class PreflightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="qa_"))
        cls.packet = compile_all()[0]
        q = cls.packet.qa

        def clip(name, w, h, fps, seconds, audio=False):
            cmd = [str(FFMPEG), "-v", "error", "-f", "lavfi", "-i", f"color=c=black:s={w}x{h}:r={fps}:d={seconds}"]
            if audio:
                cmd += ["-f", "lavfi", "-i", f"anullsrc=r=44100:cl=mono:d={seconds}", "-shortest"]
            cmd += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(cls.tmp / name), "-y"]
            subprocess.run(cmd, check=True)
            return cls.tmp / name

        cls.good = clip("good.mp4", q.width, q.height, q.fps, q.total_seconds, audio=True)
        cls.silent = clip("silent.mp4", q.width, q.height, q.fps, q.total_seconds)
        cls.small = clip("small.mp4", 320, 568, q.fps, q.total_seconds)
        cls.short = clip("short.mp4", q.width, q.height, q.fps, 3)
        cls.slow = clip("slow.mp4", q.width, q.height, 24, q.total_seconds)
        cls.audio = clip("audio.mp4", q.width, q.height, q.fps, q.total_seconds, audio=True)

    def test_a_correct_video_passes(self):
        r = preflight(self.packet, self.good, FFPROBE)
        self.assertTrue(r.passed, r.checks)
        self.assertEqual(r.status, "deterministic_pass")

    def test_each_hard_condition_fails_independently(self):
        cases = {"resolution": self.small, "duration": self.short, "fps": self.slow}
        for check, media in cases.items():
            with self.subTest(check):
                r = preflight(self.packet, media, FFPROBE)
                self.assertFalse(r.passed)
                self.assertFalse(r.checks[check])
        missing = preflight(self.packet, self.tmp / "nope.mp4", FFPROBE)
        self.assertFalse(missing.checks["file_exists"])
        self.assertFalse(missing.passed)

    def test_audio_is_required_only_when_the_packet_says_so(self):
        self.assertTrue(self.packet.qa.require_audio)  # compiled packets carry a score
        self.assertFalse(preflight(self.packet, self.silent, FFPROBE).checks["audio"])
        self.assertTrue(preflight(self.packet, self.audio, FFPROBE).checks["audio"])
        quiet = dataclasses.replace(self.packet, qa=dataclasses.replace(self.packet.qa, require_audio=False))
        self.assertTrue(preflight(quiet, self.silent, FFPROBE).checks["audio"])

    def test_unknown_assets_and_broken_timelines_fail(self):
        bad_assets = dataclasses.replace(self.packet, qa=dataclasses.replace(self.packet.qa, required_asset_ids=["char_ghost"]))
        self.assertFalse(preflight(bad_assets, self.good, FFPROBE).checks["assets_known"])
        gap = list(self.packet.shots)
        gap[1] = dataclasses.replace(gap[1], start_seconds=gap[1].start_seconds + 5)
        self.assertFalse(preflight(dataclasses.replace(self.packet, shots=gap), self.good, FFPROBE).checks["timeline"])
        cues = list(self.packet.subtitle_plan)
        cues[0] = dataclasses.replace(cues[0], end=cues[0].start)
        self.assertFalse(preflight(dataclasses.replace(self.packet, subtitle_plan=cues), self.good, FFPROBE).checks["subtitles"])


if __name__ == "__main__":
    unittest.main()
