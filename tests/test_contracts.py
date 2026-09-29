from __future__ import annotations

import dataclasses
import json
import unittest
from pathlib import Path

from contracts.base import canonical_json, content_hash, from_dict, hash_without, schema_for, to_dict
from contracts.generate_schemas import CONTRACTS, OUT, render_all
from contracts.packet import ProductionPacket
from contracts.packet import verify as verify_packet
from contracts.render_request import RenderRequest, Toolchain, make_request
from contracts.scene_spec import SceneSpec
from contracts.scene_spec import verify as verify_spec
from contracts.stylepack import SUSPENSE_V1, StylePack
from tests.world_fixture import build_specs, compile_all


class CanonicalTests(unittest.TestCase):
    def test_canonical_json_is_order_and_whitespace_independent(self):
        self.assertEqual(canonical_json({"b": 1, "a": [1.0000001, "é"]}), canonical_json({"a": [1.0000001, "é"], "b": 1}))
        self.assertEqual(canonical_json({"a": 1.23456789}), '{"a":1.234568}')

    def test_unicode_is_normalised(self):
        self.assertEqual(content_hash("é"), content_hash("é"))  # precomposed vs combining


class SchemaFileTests(unittest.TestCase):
    def test_committed_schemas_match_the_dataclasses(self):
        for name, text in render_all().items():
            path = OUT / f"{name}.schema.json"
            self.assertTrue(path.exists(), f"{path} missing: run python -m contracts.generate_schemas")
            self.assertEqual(path.read_text(encoding="utf-8").replace("\r\n", "\n"), text, f"{name} schema drifted")

    def test_schemas_are_valid_json_with_required_fields(self):
        schema = schema_for(ProductionPacket)
        packet_def = schema["$defs"]["ProductionPacket"]
        self.assertIn("shots", packet_def["required"])
        self.assertNotIn("packet_hash", packet_def["required"])  # has a default
        self.assertLessEqual({"scene_spec", "production_packet", "render_request", "take", "stylepack", "tell_intent",
                              "external_event", "seed_candidate"}, set(CONTRACTS))


class RoundTripTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec = build_specs()[0]
        cls.packet = compile_all()[0]

    def test_scene_spec_round_trips_and_verifies(self):
        back = from_dict(SceneSpec, json.loads(canonical_json(self.spec)))
        self.assertEqual(back, self.spec)
        self.assertTrue(verify_spec(back))

    def test_packet_round_trips_and_verifies(self):
        back = from_dict(ProductionPacket, json.loads(canonical_json(self.packet)))
        self.assertEqual(back, self.packet)
        self.assertTrue(verify_packet(back))

    def test_any_edit_breaks_the_hash(self):
        edited = dataclasses.replace(self.spec, title="tampered")
        self.assertFalse(verify_spec(edited))
        shots = [dataclasses.replace(self.packet.shots[0], caption="tampered")] + list(self.packet.shots[1:])
        self.assertFalse(verify_packet(dataclasses.replace(self.packet, shots=shots)))

    def test_hash_excludes_only_itself(self):
        self.assertEqual(self.spec.scene_hash, hash_without(self.spec, "scene_hash"))
        self.assertNotEqual(content_hash(to_dict(self.spec)), self.spec.scene_hash)  # including it would differ


class RenderRequestTests(unittest.TestCase):
    TOOLCHAIN = Toolchain("0.8.91", "ffmpeg 9.0.2", "chrome 152", "libx264")

    def request(self, **over):
        args = dict(kind="episode_master", backend="hyperframes", backend_version="0.8.91",
                    parameters={"fps": "30", "quality": "looks"}, packet_hash="sha256:p", seed=0,
                    asset_hashes={"char_a": "sha256:1", "gsap": "sha256:2"}, toolchain=self.TOOLCHAIN)
        args.update(over)
        return make_request(**args)

    def test_hash_is_stable_and_order_independent(self):
        a = self.request()
        b = self.request(asset_hashes={"gsap": "sha256:2", "char_a": "sha256:1"})
        self.assertEqual(a.request_hash, b.request_hash)
        self.assertTrue(a.request_hash.startswith("sha256:"))

    def test_every_input_changes_the_hash(self):
        base = self.request().request_hash
        changes = [dict(kind="shot"), dict(backend="wan"), dict(backend_version="0.9"), dict(parameters={"fps": "24", "quality": "looks"}),
                   dict(packet_hash="sha256:q"), dict(seed=1), dict(asset_hashes={"char_a": "sha256:9", "gsap": "sha256:2"}),
                   dict(toolchain=Toolchain("0.8.91", "ffmpeg 9.0.3", "chrome 152", "libx264")),
                   dict(toolchain=Toolchain("0.8.91", "ffmpeg 9.0.2", "chrome 153", "libx264"))]
        for change in changes:
            with self.subTest(change):
                self.assertNotEqual(base, self.request(**change).request_hash)

    def test_request_verifies_and_round_trips(self):
        req = self.request()
        self.assertEqual(hash_without(req, "request_hash"), req.request_hash)
        self.assertEqual(from_dict(RenderRequest, json.loads(canonical_json(req))), req)


class StylePackTests(unittest.TestCase):
    def test_style_pack_changes_packet_and_is_recorded(self):
        spec = build_specs()[0]
        from narrative.compiler import compile_packet
        base = compile_packet(spec, SUSPENSE_V1)
        slower = compile_packet(spec, dataclasses.replace(SUSPENSE_V1, version=2, duration_scale=1.5))
        self.assertNotEqual(base.packet_hash, slower.packet_hash)
        self.assertEqual(base.stylepack.hash, SUSPENSE_V1.hash())
        self.assertEqual(slower.stylepack.version, 2)
        self.assertGreater(slower.qa.total_seconds, base.qa.total_seconds)


if __name__ == "__main__":
    unittest.main()
