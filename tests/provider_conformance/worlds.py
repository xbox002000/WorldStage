"""Worlds for the conformance fixtures and the Bible tests. Test and script support only: production code may not build or
run worlds (tests/test_production.py), which is why the recipe form of the Bible lives here and not in production/bible.py."""
from __future__ import annotations

import sqlite3

from contracts.bible import Bible
from production.bible import build_bible
from world.db import connect, init_db
from world.seed import build_world


def world_from_recipe(recipe: str, seed: int = 1) -> sqlite3.Connection:
    """A new in-memory world from a recipe, nothing simulated yet (enough for a Bible: cast, costumes, places)."""
    conn = connect()
    init_db(conn, seed)
    build_world(conn, seed, recipe)
    return conn


def bible_for_recipe(recipe: str, seed: int = 1, **kwargs) -> Bible:
    conn = world_from_recipe(recipe, seed)
    try:
        return build_bible(conn, **kwargs)
    finally:
        conn.close()


def played_world(recipe: str = "jianghu_story_v1", seed: int = 17, days: int = 8) -> sqlite3.Connection:
    """The short story world the samples come from: rule agents with volition, the greedy producer, `days` days."""
    from agent.volition import VolitionDecider
    from producer.director import Director
    from world.simulation import Simulation
    conn = world_from_recipe(recipe, seed)
    decider = VolitionDecider(seed)
    Simulation(conn, decider, decider, set(), feed="synthetic_v1", producer=Director("greedy", seed)).run(days)
    return conn
