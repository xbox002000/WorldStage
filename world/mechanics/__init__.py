"""Narrative mechanics: story machinery that runs inside the world's rules (see docs/narrative_mechanics.md)."""
from __future__ import annotations

import json
import sqlite3

from contracts.base import from_dict
from contracts.mechanic import MechanicSpec, NarrativeMechanicPack
from world.mechanics.base import Mechanic


def build(spec: MechanicSpec) -> Mechanic:
    from world.mechanics.rebirth import Rebirth
    from world.mechanics.system import QuestSystem
    table = {"rebirth": Rebirth, "system": QuestSystem}
    if spec.id not in table:
        raise ValueError(f"unknown mechanic {spec.id!r}")
    return table[spec.id](spec)


def recorded_pack(conn: sqlite3.Connection) -> NarrativeMechanicPack | None:
    """The pack this world runs with, read back from its `mechanic` event (so a replay needs nothing else)."""
    row = conn.execute("SELECT truth FROM events WHERE type = 'mechanic' ORDER BY event_id DESC LIMIT 1").fetchone()
    return from_dict(NarrativeMechanicPack, json.loads(row[0])["pack"]) if row else None


def mechanics_of(conn: sqlite3.Connection) -> list[Mechanic]:
    pack = recorded_pack(conn)
    return [build(m) for m in pack.mechanics] if pack else []
