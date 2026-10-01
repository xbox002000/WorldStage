"""Character agents: people live by habit and think at wake points; a mind can only pick among the world's own
options; the budget holds; without a mind, or with a broken one, the rule agent decides; what a mind sees is only
what that person could know."""
from __future__ import annotations

import json
import unittest

from agent.cognition import CharacterAgent, cognitive_state, wake_reasons
from agent.volition import VolitionDecider
from contracts.base import from_dict, to_dict
from contracts.cognition import CognitiveState
from world.db import connect, init_db
from world.recipes import BASE, register_recipe, unregister_recipe
from contracts.recipe import WorldRecipe
from world.seed import build_world
from world.simulation import Simulation

RECIPE = WorldRecipe(recipe_id="town_mind_test", title="town_mind_test", content="town_v1", core="everyday_life",
                     pillars=["items.ownership", "money.rent", "gossip.drift"],
                     base=BASE + ["psyche", "items.accusation", "money.debt", "social.exchange", "social.topics", "life.work"])


class FirstOption:
    """A stub mind: always the first option, and it remembers what it was shown."""
    model = "stub"

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def generate_json(self, prompt: str, schema: dict, temperature: float = 0.8) -> dict:
        self.prompts.append(prompt)
        return {"option": 0, "reason": "照我的個性", "inner": "其實我很累"}


class Broken:
    model = "broken"

    def generate_json(self, prompt, schema, temperature=0.8):
        raise RuntimeError("no quota")


def run(agent_client, budget=6, days=2, seed=8):
    c = connect()
    init_db(c, seed)
    build_world(c, seed, "town_mind_test")
    agent = CharacterAgent(VolitionDecider(seed), agent_client, budget=budget)
    Simulation(c, agent, agent, set()).run(days)
    return c, agent


class CharacterAgentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        register_recipe(RECIPE)
        cls.mind = FirstOption()
        cls.c, cls.agent = run(cls.mind)

    @classmethod
    def tearDownClass(cls):
        unregister_recipe(RECIPE.recipe_id)

    def test_minds_wake_only_at_wake_points_and_within_budget(self):
        self.assertGreater(self.agent.stats["agent"], 0)
        self.assertGreater(self.agent.stats["rule"], self.agent.stats["agent"])  # most of life is habit
        self.assertTrue(all(n <= 6 for n in self.agent.used.values()))
        self.assertTrue(all(entry["wake"] for entry in self.agent.log))

    def test_a_mind_sees_who_it_is_and_only_the_world_s_options(self):
        prompt = self.mind.prompts[0]
        state = from_dict(CognitiveState, json.loads(prompt[prompt.index("{"):prompt.rindex("}") + 1]))
        self.assertTrue(state.core.get("人生的問題"))
        self.assertTrue(state.options)
        self.assertEqual([o.n for o in state.options], list(range(len(state.options))))
        chosen = [e for e in self.agent.log if "chose" in e]
        self.assertTrue(chosen)
        agent_events = self.c.execute("SELECT COUNT(*) FROM events WHERE json_extract(truth, '$.reason') LIKE 'agent:%'").fetchone()[0]
        self.assertGreater(agent_events, 0)  # the choices became ordinary events, through the validator

    def test_a_mind_knows_only_what_the_person_could_know(self):
        c = self.c
        pid = "yun"
        state = cognitive_state(c, pid, 2000, [(0.0, None)], ["test"])
        truth_of_others = {p.id for p in state.people}
        here = {r[0] for r in c.execute("SELECT id FROM people WHERE location_id = (SELECT location_id FROM people WHERE id = ?) "
                                        "AND id <> ? AND status = 'active'", (pid, pid))}
        self.assertLessEqual(truth_of_others, here)
        blob = json.dumps(to_dict(state), ensure_ascii=False)
        self.assertNotIn("rightful_owner", blob)

    def test_without_a_mind_or_with_a_broken_one_the_rules_decide(self):
        c1, a1 = run(None, days=2)  # day 0 of this world has no wake point; day 1 does
        c2, a2 = run(Broken(), days=2)
        self.assertEqual(a1.stats["agent"], 0)
        self.assertGreater(a2.stats["agent_failed"], 0)
        from world.snapshot import table_hash
        self.assertEqual(table_hash(c1, "events"), table_hash(c2, "events"))  # the broken mind changed nothing

    def test_wake_points_come_from_the_person_s_life(self):
        c = self.c
        reasons = {r for e in self.agent.log for r in e["wake"]}
        self.assertTrue(reasons)
        self.assertEqual(wake_reasons(c, "ming", 3000, [(0.0, None)]) is not None, True)


if __name__ == "__main__":
    unittest.main()
