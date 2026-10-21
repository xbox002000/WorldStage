"""Space as a sense: the world asks it one kind of question, "could this person have perceived that?".

With the `space.perception` primitive, a world is simulated inside its own space (runtime/perception.py answers):
being in the same place is no longer enough to witness an act. You have to be within sight of it (range, field of
view, no wall or tree in between), or within earshot of a quiet word, or, for an animal, within smell of a thing.
A thing lying on the floor is only something you can take if you have seen (or smelt) it.

The answer is deterministic: it comes from the World Runtime, a pure function of the world's history and the
white-box layouts, whose code is part of the ruleset hash. Space never writes the world; the rules still decide.
"""
from __future__ import annotations

import sqlite3
from typing import Protocol


class SpatialOracle(Protocol):
    def weight(self, observer: str, key: str, now: int) -> float:
        """How well `observer` could perceive the act `key` ("kind:actor:target") at minute `now`: 0 = not at all."""
        ...

    def perceives_thing(self, observer: str, oid: str, now: int) -> bool: ...


_ORACLES: dict[int, tuple[sqlite3.Connection, SpatialOracle]] = {}


def attach(conn: sqlite3.Connection, oracle: SpatialOracle) -> None:
    _ORACLES[id(conn)] = (conn, oracle)


def detach(conn: sqlite3.Connection) -> None:
    _ORACLES.pop(id(conn), None)


def oracle(conn: sqlite3.Connection) -> SpatialOracle | None:
    hit = _ORACLES.get(id(conn))
    return hit[1] if hit is not None and hit[0] is conn else None


def now_of(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT MAX(timestamp) FROM events").fetchone()
    return row[0] or 0
