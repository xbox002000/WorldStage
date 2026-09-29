"""Replay check: rebuild a recorded world from its own seed and its recorded model answers, and compare.

If the rebuilt world is byte-for-byte the recorded one (same snapshot hash), the run is reproducible: every choice
was either a rule, a seeded roll or an answer that is on record.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from agent.decision import GeminiDecider, SeededDecider
from agent.llm import FallbackClient, LLMClient
from agent.llm_cache import LLMCache
from channel.daily import DEFAULT_ACTIVE
from world.db import connect, init_db
from world.reader import open_world_reader
from world.seed import build_world
from world.simulation import Simulation
from world.snapshot import snapshot_hash


def recorded_models(conn: sqlite3.Connection) -> list[tuple[str, str]]:
    """(provider, model) pairs that answered, in the order a replay should try them (Gemini first)."""
    rows = conn.execute("SELECT DISTINCT provider, model FROM llm_cache ORDER BY provider = 'gemini' DESC, provider, model")
    return [(r["provider"], r["model"]) for r in rows]


def replay_check(world_db: str | Path, active_ids: tuple[str, ...] = DEFAULT_ACTIVE) -> dict:
    src = open_world_reader(world_db)
    try:
        seed = src.execute("SELECT value FROM meta WHERE key = 'world_seed'").fetchone()[0]
        days = src.execute("SELECT COUNT(*) FROM events WHERE type = 'day_end'").fetchone()[0]
        cache = LLMCache(src)
        models = recorded_models(src)
        target = snapshot_hash(src)

        fresh = connect(":memory:")
        init_db(fresh, seed)
        build_world(fresh, seed)
        clients = [LLMClient(m, provider=p, mode="replay", cache=cache) for p, m in models]
        client = FallbackClient(clients) if clients else None
        active = GeminiDecider(client) if client else SeededDecider(seed)
        sim = Simulation(fresh, active, SeededDecider(seed), set(active_ids) if client else set())
        sim.run(days)
        rebuilt = snapshot_hash(fresh)
        return {"identical": rebuilt == target, "days": days, "recorded_answers": src.execute("SELECT COUNT(*) FROM llm_cache").fetchone()[0],
                "models": [m for _, m in models], "recorded": target, "rebuilt": rebuilt}
    finally:
        src.close()
