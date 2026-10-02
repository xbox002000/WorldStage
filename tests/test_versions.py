"""Versions are kept in one place, apart (contracts/versions.py), and the code agrees with it."""
from __future__ import annotations

import re
import unittest
from pathlib import Path

from contracts import audience, character, episode_plan, intervention, opportunity, persona, runtime, seed
from contracts.versions import VERSIONS
from world import db

ROOT = Path(__file__).resolve().parent.parent


class Versions(unittest.TestCase):
    def test_the_code_declares_what_the_registry_says(self):
        self.assertEqual(db.SCHEMA_VERSION, VERSIONS["db_schema"])
        self.assertEqual(character.CHARACTER_VERSION, VERSIONS["character_contract"])
        self.assertEqual(persona.PERSONA_VERSION, VERSIONS["persona_contract"])
        self.assertEqual(seed.SEED_VERSION, VERSIONS["seed_contract"])
        self.assertEqual(intervention.INTERVENTION_VERSION, VERSIONS["intervention_contract"])
        self.assertEqual(audience.AUDIENCE_VERSION, VERSIONS["audience_contract"])
        self.assertEqual(runtime.RUNTIME_VERSION, VERSIONS["runtime"])
        from narrative.dramaturgy import METRIC_VERSION
        from narrative.payoff import METRIC_VERSION as PAYOFF
        self.assertEqual(METRIC_VERSION, VERSIONS["dramaturgy_metric"])
        self.assertEqual(PAYOFF, VERSIONS["payoff_metric"])
        from narrative.opportunity import MODEL_VERSION
        from narrative.pacing import PACING_VERSION
        self.assertEqual(opportunity.OPPORTUNITY_VERSION, VERSIONS["opportunity_contract"])
        self.assertEqual(MODEL_VERSION, VERSIONS["opportunity_model"])
        self.assertEqual(PACING_VERSION, VERSIONS["pacing_model"])
        from narrative.episode_planner import PLANNER_VERSION
        self.assertEqual(episode_plan.EPISODE_PLAN_VERSION, VERSIONS["episode_plan_contract"])
        self.assertEqual(PLANNER_VERSION, VERSIONS["episode_planner"])
        from contracts.episode_packet import EPISODE_PACKET_VERSION
        self.assertEqual(EPISODE_PACKET_VERSION, VERSIONS["episode_packet_contract"])
        from narrative.state import STATE_VERSION
        self.assertEqual(STATE_VERSION, VERSIONS["narrative_state"])
        from narrative.speech import SPEECH_VERSION
        self.assertEqual(SPEECH_VERSION, VERSIONS["speech_model"])
        from narrative.inner_state import INNER_VERSION
        self.assertEqual(INNER_VERSION, VERSIONS["inner_state"])
        from narrative.debt import DEBT_VERSION
        from narrative.novelty import NOVELTY_VERSION
        self.assertEqual(NOVELTY_VERSION, VERSIONS["novelty_model"])
        self.assertEqual(DEBT_VERSION, VERSIONS["debt_model"])
        from contracts.bible import BIBLE_VERSION
        self.assertEqual(BIBLE_VERSION, VERSIONS["bible_contract"])
        from narrative.lint import LINT_VERSION
        self.assertEqual(LINT_VERSION, VERSIONS["script_lint"])
        from agent.cognition import PROMPT_V3_VERSION
        from world.content.jianghu_drama import DRAMA_VERSION
        self.assertEqual(DRAMA_VERSION, VERSIONS["jianghu_drama_content"])
        self.assertEqual(PROMPT_V3_VERSION, VERSIONS["cognition_prompt"])
        from world.domains.impression import IMPRESSION_VERSION
        self.assertEqual(IMPRESSION_VERSION, VERSIONS["impression_model"])

    def test_the_payoff_metric_is_a_draft_until_it_is_frozen(self):
        self.assertTrue(VERSIONS["payoff_metric"].endswith("v0.1"))
        self.assertTrue(VERSIONS["opportunity_model"].endswith("v0.1") and VERSIONS["pacing_model"].endswith("v0.1"))

    def test_every_migration_up_to_the_schema_exists_and_none_beyond(self):
        files = sorted(p.name for p in (ROOT / "world" / "migrations").glob("v*.sql"))
        numbers = [int(re.match(r"v(\d+)", f).group(1)) for f in files if re.match(r"v(\d+)", f)]
        self.assertEqual(max(numbers), db.SCHEMA_VERSION)
        self.assertEqual(sorted(numbers), list(range(1, db.SCHEMA_VERSION + 1)))

    def test_each_kind_of_version_has_its_own_entry(self):
        self.assertEqual(len(set(map(str, VERSIONS.values()))) >= 5, True)
        self.assertTrue(all(isinstance(k, str) and k for k in VERSIONS))


if __name__ == "__main__":
    unittest.main()
