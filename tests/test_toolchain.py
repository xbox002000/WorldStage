from __future__ import annotations

import unittest

from world.snapshot import snapshot_manifest
from world.toolchain import lock_drift, simulation_toolchain, simulation_toolchain_hash
from tests.helpers import seeded


class ToolchainTests(unittest.TestCase):
    def test_fingerprint_names_python_sqlite_and_lock(self):
        tc = simulation_toolchain()
        self.assertEqual(set(tc), {"python", "sqlite", "lock"})
        self.assertTrue(tc["lock"].startswith("sha256:"))
        self.assertEqual(simulation_toolchain_hash(), simulation_toolchain_hash())

    def test_toolchain_is_not_part_of_the_world_snapshot(self):
        manifest = snapshot_manifest(seeded())
        self.assertNotIn("toolchain", str(manifest).lower())

    def test_installed_engine_dependencies_match_the_lock(self):
        # If this fails the environment drifted from requirements.lock: re-lock or reinstall before an experiment.
        self.assertEqual(lock_drift(), {})


if __name__ == "__main__":
    unittest.main()
