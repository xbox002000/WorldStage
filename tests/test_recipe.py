"""World recipes: a genre is a composition of primitives, checked by a compiler; the core engine is shared."""
from __future__ import annotations

import dataclasses
import unittest
from unittest import mock

from agent.volition import VolitionDecider
from contracts.recipe import LAYERS, WorldRecipe
from world import recipes
from world.db import connect, init_db
from world.recipes import LIBRARY, RecipeError, compile_recipe, compiled, load_recipe
from world.ruleset import ruleset_manifest
from world.seed import build_world
from world.simulation import Simulation
from world.state import audit


def recipe(**over) -> WorldRecipe:
    return dataclasses.replace(load_recipe("town_v1"), **over)


def run(r: WorldRecipe, days: int = 3):
    with mock.patch.object(recipes, "load_recipe", lambda rid="town_v1": r):
        recipes.compiled.cache_clear()
        try:
            conn = connect()
            init_db(conn, 3)
            build_world(conn, 3)
            d = VolitionDecider(3)
            Simulation(conn, d, d, set(), feed="synthetic_v1").run(days)
            return conn
        finally:
            recipes.compiled.cache_clear()


class CompilerTests(unittest.TestCase):
    def test_the_town_compiles_in_precedence_order(self):
        c = compiled("town_v1")
        layers = [LAYERS.index(LIBRARY[p].layer) for p in c.order]
        self.assertEqual(layers, sorted(layers))
        self.assertLessEqual(c.budget_used, c.budget_limit)
        self.assertEqual(compile_recipe(load_recipe("town_v1")).compiled_hash, c.compiled_hash)

    def test_over_the_role_budget_is_refused(self):
        with self.assertRaises(RecipeError):
            compile_recipe(recipe(accents=["props.parrot", "props.animals", "seeds.external", "gossip.drift"]))

    def test_a_primitive_without_code_is_refused(self):
        with self.assertRaises(RecipeError):
            compile_recipe(recipe(pillars=["items.ownership", "cultivation"]))

    def test_a_missing_requirement_is_refused(self):
        with self.assertRaises(RecipeError):
            compile_recipe(recipe(pillars=["items.ownership", "gossip.drift"], base=["events", "claims", "attention",
                                                                                    "schedule", "volition", "goals", "money.debt"]))

    def test_exclusive_mechanics_are_refused_and_conditional_ones_warned(self):
        on = {k: dataclasses.replace(v, implemented=True) for k, v in LIBRARY.items()}
        with mock.patch.dict(recipes.LIBRARY, on):
            with self.assertRaises(RecipeError):
                compile_recipe(recipe(narrative=["rebirth", "time_loop"]))
            ok = compile_recipe(recipe(narrative=["rebirth", "system"], accents=[]))
            self.assertTrue(ok.warnings)

    def test_recipes_are_part_of_the_ruleset(self):
        self.assertIn("world/recipes/town_v1.json", ruleset_manifest()["files"])


class SharedCoreTests(unittest.TestCase):
    def test_leaving_out_a_primitive_turns_its_rules_off_and_nothing_else_breaks(self):
        bare = recipe(pillars=["items.ownership", "gossip.drift"], accents=[],
                      base=["events", "claims", "attention", "schedule", "volition", "goals", "items.accusation"])
        conn = run(bare)
        kinds = {r[0] for r in conn.execute("SELECT DISTINCT type FROM events")}
        self.assertNotIn("seed", kinds)
        self.assertNotIn("parrot_speaks", kinds)
        rent = conn.execute("SELECT COUNT(*) FROM event_deltas WHERE entity_id LIKE 'arrears.%'").fetchone()[0]
        self.assertEqual(rent, 0)
        self.assertEqual(audit(conn), [])

    def test_the_full_town_runs_its_primitives(self):
        conn = run(load_recipe("town_v1"))
        kinds = {r[0] for r in conn.execute("SELECT DISTINCT type FROM events")}
        self.assertIn("seed", kinds)


if __name__ == "__main__":
    unittest.main()
