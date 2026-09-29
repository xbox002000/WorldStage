"""The capability layer: provider selection, swappable visual / spatial / audio / composition providers, the MCP
adapter, and the Render -> Diagnose -> Repair loop."""
from __future__ import annotations

import ast
import dataclasses
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from audio.backend import SilentAudioBackend, SynthAudioBackend
from capability.defaults import default_registry
from capability.mcp_adapter import VISUAL_MOCK, McpVisualProvider
from capability.mcp_client import McpError, McpStdioClient
from capability.registry import CapabilityRegistry, NoProvider
from contracts.backends import ShotRequest
from contracts.base import from_dict, to_dict
from contracts.capability import Policy, ProviderManifest, Requirement
from contracts.render_request import Take, make_request
from narrative.spatial import compile_spatial
from production import db as prod
from production.pipeline import make_episodes, produce
from production.provenance import trace_take
from production.shots import render_shot
from render.mock_clip import FFMPEG_DIR, MockClipBackend
from render.whitebox import WhiteboxSpatialBackend, raycast
from tests.world_fixture import build_specs, compile_all, world_path
from world.reader import open_world_reader

ROOT = Path(__file__).resolve().parent.parent
HAS_FFMPEG = (FFMPEG_DIR / "ffmpeg.exe").exists() or (FFMPEG_DIR / "ffmpeg").exists()


class Fake:
    """A provider that only has a manifest (and, if asked, a fixed answer)."""

    def __init__(self, manifest: ProviderManifest, up: bool = True, take: Take | None = None) -> None:
        self._m, self._up, self._take, self.calls = manifest, up, take, 0
        self.name = manifest.provider_id

    def manifest(self):
        return self._m

    def available(self):
        return (True, "") if self._up else (False, "no key")

    def toolchain(self):
        return {"model": self.name}

    def generate(self, request, shot, dest):
        self.calls += 1
        if self._take is None:
            raise RuntimeError("the service answered 500")
        return dataclasses.replace(self._take, request_hash=request.request_hash)


def visual(pid: str, features=("t2v",), **kw) -> ProviderManifest:
    return ProviderManifest(pid, "1", ["visual.generate"], list(features), transport=kw.pop("transport", "local"),
                            local=kw.pop("local", True), deterministic=True, **kw)


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.reg = CapabilityRegistry()
        self.reg.register(Fake(visual("cheap", ("t2v", "depth"), max_seconds=5, quality=0.2)))
        self.reg.register(Fake(visual("good", ("t2v", "i2v", "depth", "reference_image"), max_seconds=10, quality=0.9)))
        self.reg.register(Fake(visual("paid", ("t2v", "i2v", "depth", "pose"), max_seconds=10, quality=1.0,
                                      local=False, transport="http", cost_per_second=0.05)))
        self.reg.register(Fake(visual("keyless", ("t2v", "depth")), up=False))

    def test_providers_that_cannot_do_the_job_are_left_out_with_a_reason(self):
        sel = self.reg.select(Requirement("visual.generate", ["depth", "i2v"], 8))
        self.assertEqual(sel.chosen, ["good"])
        why = {r.provider_id: r.reason for r in sel.rejected}
        self.assertIn("lacks i2v", why["cheap"])
        self.assertIn("budget", why["paid"])  # $0 policy by default
        self.assertIn("lacks i2v", why["keyless"])

    def test_availability_and_length_limits(self):
        why = {r.provider_id: r.reason for r in self.reg.select(Requirement("visual.generate", ["depth"], 8)).rejected}
        self.assertIn("5s limit", why["cheap"])
        self.assertEqual(why["keyless"], "unavailable: no key")

    def test_policy_orders_the_fallback_chain(self):
        req = Requirement("visual.generate", ["t2v"], 4)
        self.assertEqual(self.reg.select(req).chosen, ["good", "cheap"])  # both free: better quality first
        self.assertEqual(self.reg.select(req, Policy(max_cost=1.0, prefer="quality")).chosen, ["paid", "good", "cheap"])
        self.assertEqual(self.reg.select(req, Policy(max_cost=1.0, allow_remote=False)).chosen, ["good", "cheap"])
        self.assertEqual(self.reg.select(req, Policy(order=["cheap"])).chosen, ["cheap", "good"])
        self.assertEqual(self.reg.select(req, Policy(deny=["good"])).chosen, ["cheap"])

    def test_selection_is_deterministic_and_hashed(self):
        req = Requirement("visual.generate", ["t2v"], 4)
        self.assertEqual(self.reg.select(req).selection_hash, self.reg.select(req).selection_hash)
        with self.assertRaises(NoProvider):
            self.reg.choose(Requirement("visual.generate", ["pose"], 4))

    def test_the_default_registry_covers_every_capability_with_two_providers_where_it_matters(self):
        cat = default_registry(lambda h: None).catalog()
        self.assertEqual(cat["audio.score"], ["silence", "synth"])
        self.assertEqual(cat["composition.render"], ["ffmpeg-compose", "hyperframes"])
        self.assertEqual(cat["spatial.control"], ["whitebox"])
        self.assertEqual(cat["visual.generate"], ["mock-clip"])


class BoundaryTests(unittest.TestCase):
    PROVIDERS = {"render.hyperframes_backend", "render.mock_clip", "render.ffmpeg_compose", "render.whitebox",
                 "audio.backend", "audio.synth", "capability.mcp_adapter", "capability.mcp_client"}

    def _imports(self, path: Path) -> list[str]:
        out = []
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.module:
                out.append(node.module)
            elif isinstance(node, ast.Import):
                out += [a.name for a in node.names]
        return out

    def test_production_code_names_no_provider(self):
        offenders = [f"{p.name}: {m}" for p in (ROOT / "production").glob("*.py") for m in self._imports(p)
                     if m in self.PROVIDERS]
        self.assertEqual(offenders, [])

    def test_contracts_and_the_world_know_nothing_of_providers_or_mcp(self):
        for folder in ("contracts", "world", "narrative"):
            offenders = [f"{p.name}: {m}" for p in (ROOT / folder).rglob("*.py") for m in self._imports(p)
                         if m.split(".")[0] in ("capability", "render", "audio")]
            self.assertEqual(offenders, [], folder)

    def test_no_provider_specific_field_in_the_render_request(self):
        from contracts.render_request import RenderRequest
        fields = {f.name for f in dataclasses.fields(RenderRequest)}
        self.assertFalse(fields & {"hyperframes", "chrome", "comfyui", "prompt"})


class WhiteboxTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan = compile_spatial(build_specs()[0])

    def test_controls_are_deterministic_pngs(self):
        wb = WhiteboxSpatialBackend()
        a, b = wb.controls(self.plan, 0, 0, 90, 160), wb.controls(self.plan, 0, 0, 90, 160)
        self.assertEqual(a, b)
        self.assertTrue(a["depth"].startswith(b"\x89PNG") and a["mask"].startswith(b"\x89PNG"))

    def test_the_camera_sees_the_people_it_frames(self):
        beat = self.plan.beats[0]
        for i, cam in enumerate(beat.cameras):
            depth, which, ids = raycast(self.plan, 0, i, 90, 160)
            seen = {ids[k] for k in set(which.flatten().tolist()) if k >= 0}
            with self.subTest(camera=cam.shot):
                self.assertLessEqual(set(cam.subjects), seen)


@unittest.skipUnless(HAS_FFMPEG, "local ffmpeg not installed")
class MockClipAndDiagnoseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cap_"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def shot(self, seed: int) -> ShotRequest:
        return ShotRequest("s01", "a test shot", 2.0, 270, 480, 30, seed)

    def test_same_request_same_bytes_and_frozen_clips_are_diagnosed(self):
        from production.shot_qa import diagnose
        mock = MockClipBackend()
        req = make_request(kind="shot", backend=mock.name, backend_version="1", parameters={}, packet_hash="sha256:p",
                           seed=0, asset_hashes={}, toolchain=mock.toolchain())
        seen = set()
        for seed in range(8):
            a = mock.generate(req, self.shot(seed), self.tmp / f"a{seed}.mp4")
            b = mock.generate(req, self.shot(seed), self.tmp / f"b{seed}.mp4")
            self.assertEqual(a.artifact_hash, b.artifact_hash)
            codes = [f.code for f in diagnose(a, self.shot(seed), FFMPEG_DIR)]
            self.assertEqual(codes, ["FROZEN_FRAMES"] if mock.frozen(self.shot(seed)) else [], seed)
            seen.add(mock.frozen(self.shot(seed)))
        self.assertEqual(seen, {True, False})  # the sample covers both outcomes

    def test_a_missing_clip_is_a_provider_error(self):
        from production.shot_qa import diagnose
        codes = [f.code for f in diagnose(Take("h", "failed", error="HTTP 500"), self.shot(0), FFMPEG_DIR)]
        self.assertEqual(codes, ["PROVIDER_ERROR"])


@unittest.skipUnless(HAS_FFMPEG, "local ffmpeg not installed")
class McpTests(unittest.TestCase):
    def test_protocol_handshake_and_tool_discovery(self):
        client = McpStdioClient(VISUAL_MOCK, cwd=str(ROOT))
        try:
            self.assertEqual(client.server_info["name"], "visual-mock")
            self.assertEqual(set(client.tools), {"capability_manifest", "visual_generate"})
            with self.assertRaises(McpError):
                client.request("no/such_method")
        finally:
            client.close()

    def test_an_mcp_provider_gives_the_same_clip_as_the_local_one(self):
        remote, local = McpVisualProvider("visual-mock", VISUAL_MOCK), MockClipBackend()
        tmp = Path(tempfile.mkdtemp(prefix="mcp_"))
        try:
            m = remote.manifest()
            self.assertEqual((m.provider_id, m.transport), ("mcp:visual-mock", "mcp"))
            self.assertEqual(m.features, local.manifest().features)  # discovered, not configured
            shot = ShotRequest("s02", "x", 2.0, 270, 480, 30, 5)
            req = make_request(kind="shot", backend=m.provider_id, backend_version=m.version, parameters={},
                               packet_hash="sha256:p", seed=5, asset_hashes={}, toolchain=remote.toolchain())
            a = remote.generate(req, shot, tmp / "remote.mp4")
            b = local.generate(req, shot, tmp / "local.mp4")
            self.assertEqual(a.status, "ready")
            self.assertEqual(a.request_hash, req.request_hash)
            self.assertEqual(a.artifact_hash, b.artifact_hash)
        finally:
            remote.close()
            shutil.rmtree(tmp, ignore_errors=True)

    def test_a_dead_server_is_just_an_unavailable_provider(self):
        reg = CapabilityRegistry()
        reg.register(McpVisualProvider("gone", ["python", "-c", "import sys; sys.exit(3)"], timeout=10))
        reg.register(MockClipBackend())
        sel = reg.select(Requirement("visual.generate", ["t2v"], 2))
        self.assertEqual(sel.chosen, ["mock-clip"])
        self.assertIn("mcp:gone", [r.provider_id for r in sel.rejected])


@unittest.skipUnless(HAS_FFMPEG, "local ffmpeg not installed")
class RepairLoopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="repair_"))
        cls.packet = compile_all()[0]
        cls.spec = build_specs()[0]

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def conn(self):
        conn = prod.open_production_db()
        prod.save_scene_spec(conn, self.spec)
        prod.save_packet(conn, self.packet)
        return conn

    def small(self):
        """The packet at a small canvas, so the loop runs fast."""
        from contracts.packet import Canvas, finalize
        return finalize(dataclasses.replace(self.packet, canvas=Canvas(270, 480, 30)))

    def test_a_frozen_take_is_diagnosed_reseeded_and_repaired(self):
        conn, packet = self.conn(), self.small()
        prod.save_packet(conn, packet)
        from production.shots import base_seed
        shot = packet.shots[1]

        class FreezesOnFirstSeed(MockClipBackend):
            def frozen(self, s):
                return s.seed == base_seed(packet, shot)

        reg = CapabilityRegistry()
        reg.register(FreezesOnFirstSeed())
        out = render_shot(conn, packet, shot, reg, self.tmp)
        self.assertTrue(out.ok)
        self.assertEqual(out.attempts, 2)
        self.assertEqual(out.failures[0].code, "FROZEN_FRAMES")
        self.assertEqual(out.repairs[0].ops, ["reseed"])
        rows = conn.execute("SELECT r.next_request_hash, t.status FROM repair_requests r JOIN takes t "
                            "ON t.request_hash = r.parent_request_hash ORDER BY r.attempt").fetchall()
        self.assertTrue(all(r["next_request_hash"] for r in rows))
        self.assertEqual({r["status"] for r in rows}, {"rejected"})  # a failed take is never a cache hit
        self.assertEqual(conn.execute("SELECT code FROM visual_failures").fetchone()[0], "FROZEN_FRAMES")

    def test_a_failing_provider_falls_back_to_the_next(self):
        conn, packet = self.conn(), self.small()
        prod.save_packet(conn, packet)
        reg = CapabilityRegistry()
        broken = Fake(visual("broken", ("t2v", "depth"), quality=0.9))
        reg.register(broken)
        reg.register(MockClipBackend(defect_rate=0.0))
        out = render_shot(conn, packet, packet.shots[0], reg, self.tmp)
        self.assertTrue(out.ok)
        self.assertEqual((out.provider, broken.calls), ("mock-clip", 1))
        self.assertEqual([f.code for f in out.failures], ["PROVIDER_ERROR"])
        self.assertEqual(out.repairs[0].ops, ["fallback_provider"])

    def test_the_loop_gives_up_after_its_attempts(self):
        conn, packet = self.conn(), self.small()
        prod.save_packet(conn, packet)
        reg = CapabilityRegistry()
        reg.register(MockClipBackend(defect_rate=1.0))  # always frozen
        out = render_shot(conn, packet, packet.shots[0], reg, self.tmp, max_attempts=2)
        self.assertFalse(out.ok)
        self.assertEqual(out.attempts, 2)
        last = conn.execute("SELECT next_request_hash FROM repair_requests ORDER BY attempt DESC LIMIT 1").fetchone()
        self.assertIsNone(last[0])


@unittest.skipUnless(HAS_FFMPEG, "local ffmpeg not installed")
class ShotsRouteTests(unittest.TestCase):
    """The whole second route: whitebox depth -> mock clips (repaired) -> ffmpeg composition + synth score."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="route_"))
        cls.world = str(cls.tmp / "world.db")
        shutil.copyfile(world_path(), cls.world)
        cls.prod_db = str(cls.tmp / "p.db")
        conn = prod.open_production_db(cls.prod_db)
        reg = default_registry(lambda h: prod.load_packet(conn, h), workdir=cls.tmp / "work")
        cls.results = produce(cls.world, cls.prod_db, cls.tmp / "out", top=1, orientation="landscape",
                              quality="draft", route="shots", registry=reg, prod_conn=conn)
        cls.conn = conn

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_the_episode_passes_the_same_qa_as_the_procedural_one(self):
        (r,) = self.results
        self.assertTrue(r.qa_status.startswith("deterministic_pass"), r.qa_status)
        self.assertEqual(r.providers["composition.render"], "ffmpeg-compose")
        self.assertEqual(r.providers["audio.score"], "synth")
        self.assertEqual(r.providers["visual.generate"], ["mock-clip"])
        self.assertTrue(all(o.ok for o in r.shots))

    def test_every_shot_request_carries_its_depth_control(self):
        rows = self.conn.execute("SELECT request_json FROM render_requests").fetchall()
        shots = [json.loads(r[0]) for r in rows if json.loads(r[0])["kind"] == "shot"]
        self.assertTrue(shots)
        self.assertTrue(all("control:depth" in s["asset_hashes"] for s in shots))

    def test_the_episode_traces_back_to_the_world(self):
        (r,) = self.results
        chain = trace_take(self.conn, open_world_reader(self.world), r.take_id)
        self.assertEqual(chain["scene_hash"], r.scene_hash)
        self.assertTrue(chain["source_event_ids"])

    def test_the_story_is_the_same_on_both_routes(self):
        (r,) = self.results
        self.assertEqual(r.packet_hash, compile_all(top=1, orientation="landscape")[0].packet_hash)


class AudioSwapTests(unittest.TestCase):
    def test_the_composition_request_pins_whichever_audio_provider_it_was_given(self):
        packet = compile_all()[0]
        from render.hyperframes_backend import HyperFramesBackend
        hf = HyperFramesBackend(lambda h: packet)
        if not hf.available()[0]:
            self.skipTest("hyperframes not installed")
        synth = hf.make_request(packet)
        hf_silent = HyperFramesBackend(lambda h: packet, audio=SilentAudioBackend())
        silent = hf_silent.make_request(packet)
        self.assertEqual((synth.parameters["score"], silent.parameters["score"]), ("synth", "silence"))
        self.assertNotEqual(synth.asset_hashes["score"], silent.asset_hashes["score"])
        self.assertNotEqual(synth.request_hash, silent.request_hash)
        self.assertIsInstance(SynthAudioBackend().manifest(), ProviderManifest)


class ContractRoundTripTests(unittest.TestCase):
    def test_new_contracts_round_trip(self):
        m = visual("x", ("t2v",))
        self.assertEqual(from_dict(ProviderManifest, json.loads(json.dumps(to_dict(m)))), m)
        reg = CapabilityRegistry()
        reg.register(Fake(m))
        sel = reg.select(Requirement("visual.generate", ["t2v"], 2))
        from contracts.capability import Selection
        self.assertEqual(from_dict(Selection, json.loads(json.dumps(to_dict(sel)))), sel)


if __name__ == "__main__":
    unittest.main()
