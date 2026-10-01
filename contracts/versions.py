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
}
