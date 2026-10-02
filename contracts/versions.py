"""Versions, kept apart: the database schema, each contract and each metric move on their own, so "v6" never has to mean
the database in one sentence and the character contract in the next. The numbers here are what the code declares today;
tests/test_versions.py reads the code and fails when they disagree, so changing one is a deliberate act in two places.
"""
from __future__ import annotations

VERSIONS = {
    "db_schema": 8,                       # world/db.py SCHEMA_VERSION
    "character_contract": 1,              # contracts/character.py CHARACTER_VERSION
    "persona_contract": 1,                # contracts/persona.py PERSONA_VERSION
    "seed_contract": 1,                   # contracts/seed.py SEED_VERSION
    "intervention_contract": 1,           # contracts/intervention.py INTERVENTION_VERSION
    "audience_contract": 1,               # contracts/audience.py AUDIENCE_VERSION
    "runtime": "runtime-0.2",             # contracts/runtime.py RUNTIME_VERSION
    "dramaturgy_metric": "dramaturgy_metric_v1",   # narrative/dramaturgy.py METRIC_VERSION (frozen)
    "payoff_metric": "payoff_metric_v0.1",         # narrative/payoff.py METRIC_VERSION (a draft)
    "opportunity_contract": 1,            # contracts/opportunity.py OPPORTUNITY_VERSION
    "opportunity_model": "opportunity_model_v0.1",  # narrative/opportunity.py MODEL_VERSION (a draft)
    "pacing_model": "pacing_v0.1",                  # narrative/pacing.py PACING_VERSION (a draft)
    "episode_plan_contract": 1,           # contracts/episode_plan.py EPISODE_PLAN_VERSION
    "episode_planner": "episode_planner_v0.2",      # narrative/episode_planner.py PLANNER_VERSION (a draft)
    "episode_packet_contract": 1,        # contracts/episode_packet.py EPISODE_PACKET_VERSION
    "speech_model": "speech_v0.1",                  # narrative/speech.py SPEECH_VERSION (a draft; a read model)
    "narrative_state": "narrative_state_v0.1",      # narrative/state.py STATE_VERSION (a draft; a read model)
    "inner_state": "inner_state_v0.1",              # narrative/inner_state.py INNER_VERSION (a draft; a read model)
    "novelty_model": "novelty_v0.1",                # narrative/novelty.py NOVELTY_VERSION (a draft)
    "debt_model": "debt_model_v0.1",                # narrative/debt.py DEBT_VERSION (a draft; a read model, not used by the director)
    "bible_contract": "bible_v0.1",                 # contracts/bible.py BIBLE_VERSION (a draft; the cast and places a provider is told about)
    "script_lint": "script_lint_v0.1",              # narrative/lint.py LINT_VERSION (a draft; a read model: the ruler for an episode as writing)
    "impression_model": "impression_v0.1",          # world/domains/impression.py IMPRESSION_VERSION (a draft; primitive social.impression)
    "jianghu_drama_content": "jianghu_drama_content_v0.1",  # world/content/jianghu_drama.py DRAMA_VERSION (a draft; the jianghu pack with names and a jianghu past)
    "cognition_prompt": "cognition_prompt_v3",     # agent/cognition.py PROMPT_V3_VERSION (v3 adds the words said out loud) (v1, the default, is the prompt the recorded worlds were asked)
}
