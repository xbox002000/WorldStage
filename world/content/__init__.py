"""World content: the cast, places and things a recipe runs on, kept apart from the rules.

`town_v1` is the original town (its data still lives in world/seed.py). Other content is a module here that
provides the same names (LOCATIONS, EDGES, PEOPLE, PERSONAS, TRAITS, OBJECTS, ...) plus SCHEDULES, INITIAL_GOALS,
EXTRA_VARS and a backstory; `build_content_world` builds any of them with the same rules.
"""
from __future__ import annotations

import importlib
import json
import sqlite3
from pathlib import Path

from world.rng import rng as make_rng


def content_module(name: str):
    return importlib.import_module(f"world.content.{name}")


def home_of(conn: sqlite3.Connection, pid: str) -> str:
    """Where someone sleeps: their own home if the content gives one, else the first place tagged home."""
    row = conn.execute("SELECT json_extract(traits, '$.home') FROM personas WHERE person_id = ?", (pid,)).fetchone()
    if row and row[0]:
        return row[0]
    row = conn.execute("SELECT id FROM locations WHERE tags LIKE '%\"home\"%' ORDER BY id LIMIT 1").fetchone()
    return row[0] if row else conn.execute("SELECT id FROM locations ORDER BY id LIMIT 1").fetchone()[0]


def content_names() -> list[str]:
    """Every content module here (world/content/<name>.py), in a fixed order."""
    import pkgutil
    return sorted(m.name for m in pkgutil.iter_modules([str(Path(__file__).parent)]) if not m.name.startswith("_"))


def layout_alias(location_id: str) -> str | None:
    """Which white-box layout template stages a place of any content (narrative/layouts.py)."""
    for name in content_names():
        alias = getattr(content_module(name), "LAYOUTS", {}).get(location_id)
        if alias:
            return alias
    return None


def build_content_world(conn: sqlite3.Connection, world_seed: int, recipe: str, c) -> None:
    from world.goals import initial_rows
    from world.psyche import keys_for
    rng = make_rng(world_seed, 0, "world", "seed_world")
    conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('recipe', ?)", (recipe,))
    for lid, name, x, y, cap, tags in c.LOCATIONS:
        conn.execute("INSERT INTO locations VALUES (?,?,?,?,?,?)", (lid, name, x, y, cap, json.dumps(tags)))
    for a, b, minutes in c.EDGES:
        conn.execute("INSERT INTO location_edges VALUES (?,?,?)", (a, b, minutes))
        conn.execute("INSERT INTO location_edges VALUES (?,?,?)", (b, a, minutes))
    for pid, name, goal in c.PEOPLE:
        home = c.TRAITS[pid]["home"]
        conn.execute("INSERT INTO people VALUES (?,?,?,?,?,?,?,?,?,?)",
                     (pid, name, home, 100, rng.randint(3000, 12000), rng.randint(20, 50), goal, "calm",
                      json.dumps({str(k): v for k, v in c.SCHEDULES[pid].items()}), "active"))
        conn.execute("INSERT INTO personas(person_id, text, traits) VALUES (?,?,?)",
                     (pid, c.PERSONAS[pid], json.dumps(c.TRAITS[pid], sort_keys=True)))
    ids = [p[0] for p in c.PEOPLE]
    for a in ids:
        for b in ids:
            if a != b:
                trust, affection, rivalry = c.relation(a, b, rng)
                conn.execute("INSERT INTO relationships(actor_id, target_id, trust, affection, rivalry) VALUES (?,?,?,?,?)",
                             (a, b, trust, affection, rivalry))
    for oid, name, owner, value, tags in c.OBJECTS:
        conn.execute("INSERT INTO objects(id, name, owner_person_id, rightful_owner_id, value_cents, tags) VALUES (?,?,?,?,?,?)",
                     (oid, name, owner, owner, value, json.dumps(tags)))
    variables = dict(c.WORLD_VARS)
    for pid in ids:
        variables.update(keys_for(pid))
        variables.update(c.EXTRA_VARS(pid))
        variables[f"arrears.{pid}"] = 0.0
    variables.update({f"missing.{o[0]}": 0.0 for o in c.OBJECTS})
    variables.update({f"revert.{k}": -1.0 for k in ("price_food", "visibility", "job_security")})
    from world.seed import _profiles_and_domains
    content = c.__name__.rsplit(".", 1)[1]
    variables.update(_profiles_and_domains(conn, content, ids))
    for key, value in sorted(variables.items()):
        conn.execute("INSERT INTO world_vars(key, value) VALUES (?,?)", (key, value))
    for row in initial_rows(ids, c.INITIAL_GOALS):
        conn.execute("INSERT INTO goals(person_id, slot, kind, target, object, status, priority, since_day, setbacks, parent) "
                     "VALUES (?,?,?,?,?,?,?,?,?,?)", row)
    c.backstory(conn)
