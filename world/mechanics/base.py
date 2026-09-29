"""The mechanic interface. Five hooks, all deterministic, none of which may change state except through events."""
from __future__ import annotations

import sqlite3

from contracts.base import to_dict
from contracts.mechanic import MechanicSpec, NarrativeMechanicPack
from world.events import EventSpec, apply_event
from world.intent import Intent


class Mechanic:
    def __init__(self, spec: MechanicSpec) -> None:
        self.spec = spec
        self.target = spec.target

    def on_dawn(self, conn: sqlite3.Connection, day: int) -> None:
        """Start of a day: may apply events (issue a quest, ...)."""

    def options(self, conn: sqlite3.Connection, actor: str, now: int) -> list[tuple[float, Intent]]:
        """Extra choices this mechanic gives a character right now, with their scores."""
        return []

    def bias(self, conn: sqlite3.Connection, actor: str, now: int,
             scored: list[tuple[float, Intent | None]]) -> list[tuple[float, Intent | None]]:
        """How the mechanic shifts a character's motives. Returns the (possibly re-scored) options."""
        return scored

    def after_event(self, conn: sqlite3.Connection, event_id: int) -> None:
        """React to something that happened: check a quest, record a reward (by applying events)."""


def record_pack(conn: sqlite3.Connection, pack: NarrativeMechanicPack, timestamp: int, extra: dict | None = None) -> int:
    """Write which mechanics this world runs with into the world's own history."""
    return apply_event(conn, EventSpec(
        timestamp=timestamp, type="mechanic", trigger_type="rule", importance=0.0,
        truth={"pack": to_dict(pack), "pack_hash": pack.hash(), **(extra or {})}))
