"""A forged cast becomes a world: install, build, replay, and the relations it starts with."""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from agent.volition import VolitionDecider
from world.content.forged import install_cast, show_path
from world.db import connect, init_db
from world.forge import find_modern, forge_cast
from world.recipes import load_recipe, unregister_recipe
from world.seed import build_world
from world.simulation import Simulation

ROOT = Path(__file__).resolve().parent.parent


def _events(conn):
    return [tuple(row) for row in conn.execute(
        "SELECT event_id, timestamp, type, location_id, trigger_type, importance, truth FROM events ORDER BY event_id")]


def _deltas(conn):
    return [tuple(row) for row in conn.execute(
        "SELECT event_id, entity_type, entity_id, field, old_value, new_value, delta_value FROM event_deltas ORDER BY delta_id")]


class ForgedWorld(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="forged_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.recipes = []

    def tearDown(self):
        for recipe_id in self.recipes:
            unregister_recipe(recipe_id)

    def _install(self, name, cast):
        folder = install_cast(name, cast, root=self.tmp)
        self.recipes.append(f"forged_{name}")
        return folder

    def _world(self, name, seed):
        conn = connect()
        init_db(conn, seed)
        build_world(conn, seed, f"forged_{name}")
        return conn

    def _run(self, conn, seed, days):
        decider = VolitionDecider(seed)
        Simulation(conn, decider, decider, set()).run(days)

    def test_install_builds_runs_and_replays(self):
        cast = forge_cast(7, 8, "jianghu")
        folder = self._install("replay", cast)
        base = load_recipe("jianghu_drama_v1")
        got = load_recipe("forged_replay")
        self.assertEqual(got.base, base.base)
        self.assertEqual(got.core, base.core)
        self.assertEqual(got.pillars, base.pillars)
        self.assertEqual(got.accents, base.accents)
        self.assertEqual(got.content, show_path(folder))
        first = self._world("replay", 7)
        second = self._world("replay", 7)
        self._assert_initial(first, cast)
        self._assert_initial(second, cast)
        self.assertEqual(_events(first), _events(second))
        self._run(first, 7, 3)
        self._run(second, 7, 3)
        self.assertGreater(len(_events(first)), 3)
        self.assertEqual(_events(first), _events(second))
        self.assertEqual(_deltas(first), _deltas(second))
        from narrative.lint import MODERN_WORDS
        text = " ".join(row[6] for row in _events(first) if row[2] == "backstory")
        self.assertEqual(find_modern(text, MODERN_WORDS), [])

    def test_a_different_cast_has_a_different_hash(self):
        self._install("h1", forge_cast(1, 6, "jianghu"))
        self._install("h2", forge_cast(2, 6, "jianghu"))
        a = dict(self._world("h1", 1).execute("SELECT key, value FROM meta"))
        b = dict(self._world("h2", 1).execute("SELECT key, value FROM meta"))
        self.assertTrue(a["cast_hash"].startswith("sha256:"))
        self.assertNotEqual(a["cast_hash"], b["cast_hash"])
        self.assertNotEqual(a["cast_dir"], b["cast_dir"])

    def test_the_command_installs_and_a_minor_stays_out_of_romance(self):
        from character_forge import main
        name = "grok_cli_fw"
        folder = ROOT / "out" / "forge" / name
        self.addCleanup(shutil.rmtree, folder, ignore_errors=True)
        code = main(["--seed", "4", "--size", "6", "--era", "jianghu", "--install", name])
        self.assertEqual(code, 0)
        self.recipes.append(f"forged_{name}")
        self.assertTrue((folder / "profiles.json").is_file())
        self.assertEqual(load_recipe(f"forged_{name}").recipe_id, f"forged_{name}")

        cast = forge_cast(11, 8, "jianghu", locks={"0": {"age": 15}})
        self.assertEqual(cast.people[0].age, 15)
        self.assertFalse(cast.people[0].romance_eligible)
        for crush in cast.relations["crushes"]:
            self.assertNotIn("p0", (crush["from"], crush["to"]))
        self._install("minor", cast)
        conn = self._world("minor", 11)
        rows = conn.execute(
            "SELECT attraction FROM relationships WHERE actor_id = ? OR target_id = ?", ("p0", "p0")).fetchall()
        self.assertTrue(rows)
        for row in rows:
            self.assertEqual(row["attraction"], 0)
        self._run(conn, 11, 3)
        for row in conn.execute("SELECT type, truth FROM events WHERE type IN ('flirt', 'confession', 'date')"):
            truth = json.loads(row["truth"])
            self.assertNotIn("p0", (truth.get("actor"), truth.get("target"), truth.get("victim")))
        for row in conn.execute(
                "SELECT attraction FROM relationships WHERE actor_id = ? OR target_id = ?", ("p0", "p0")):
            self.assertEqual(row["attraction"], 0)

    def _assert_initial(self, conn, cast):
        meta = dict(conn.execute("SELECT key, value FROM meta"))
        self.assertIn("cast_dir", meta)
        self.assertIn("cast_hash", meta)
        self.assertEqual(conn.execute("SELECT name FROM factions WHERE faction_id = 'qingyun'").fetchone()[0], "青雲門")
        self.assertEqual(conn.execute("SELECT title FROM seats WHERE seat_id = 'chief_disciple'").fetchone()[0], "首席弟子")
        rel = cast.relations
        self.assertGreaterEqual(len(rel["nemeses"]), 1)
        self.assertGreaterEqual(len(rel["secrets"]), 1)
        self.assertGreaterEqual(len(rel["crushes"]), 1)
        self.assertGreaterEqual(len(rel["underestimated"]), 1)
        for pair in rel["nemeses"]:
            for actor, target in ((pair["a"], pair["b"]), (pair["b"], pair["a"])):
                row = conn.execute(
                    "SELECT resentment, rivalry FROM relationships WHERE actor_id = ? AND target_id = ?",
                    (actor, target)).fetchone()
                self.assertGreaterEqual(row["resentment"], 0.5)
                self.assertGreaterEqual(row["rivalry"], 0.5)
        for crush in rel["crushes"]:
            forward = conn.execute(
                "SELECT attraction FROM relationships WHERE actor_id = ? AND target_id = ?",
                (crush["from"], crush["to"])).fetchone()["attraction"]
            back = conn.execute(
                "SELECT attraction FROM relationships WHERE actor_id = ? AND target_id = ?",
                (crush["to"], crush["from"])).fetchone()["attraction"]
            self.assertGreaterEqual(forward, 0.4)
            self.assertEqual(back, 0)
        for secret in rel["secrets"]:
            holder = secret["holder"]
            oid = f"keepsake_{holder}"
            obj = conn.execute("SELECT owner_person_id, rightful_owner_id FROM objects WHERE id = ?", (oid,)).fetchone()
            self.assertEqual(obj["owner_person_id"], holder)
            self.assertEqual(obj["rightful_owner_id"], secret["kept_from"])
            missing = conn.execute("SELECT value FROM world_vars WHERE key = ?", (f"missing.{oid}",)).fetchone()[0]
            self.assertEqual(missing, 1.0)
            moved = conn.execute(
                "SELECT new_value FROM event_deltas WHERE entity_type = 'object' AND entity_id = ? AND field = 'owner_person_id'",
                (oid,)).fetchone()
            self.assertEqual(moved["new_value"], holder)
        for item in rel["underestimated"]:
            pid = item["id"]
            skill = conn.execute("SELECT value FROM world_vars WHERE key = ?", (f"skill.{pid}",)).fetchone()[0]
            avg = conn.execute(
                "SELECT AVG(estimate) FROM relationships WHERE target_id = ? AND actor_id != ?", (pid, pid)).fetchone()[0]
            self.assertGreater(skill - avg, 0.15)


if __name__ == "__main__":
    unittest.main()
