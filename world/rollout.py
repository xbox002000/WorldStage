"""Imagining: run a copy of the world forward under *other luck*, to see what might come of something (never the world itself).

A producer that wants to know "what would come of arranging this?" must not be handed the answer. The world is deterministic: the
same seed run again is the real future, and a producer that read that future would be choosing outcomes, which is the one thing it
may not do. So:

  - the copy is a separate in-memory database; the real world is read (backed up) and never written;
  - from the copy's first moment on, every die is rolled from a different seed, the *imagined luck*. The people, the history, the
    relationships and every rule are the real ones, so what comes back is "how this tends to go", a probability, not the answer;
  - the real world's own seed is refused as imagined luck (`ImaginedLuckIsTheWorlds`), and a test holds that line.

`imagine` returns the copy after `days` imagined days; what to make of it is the caller's (producer/forecast.py).
"""
from __future__ import annotations

import sqlite3
from typing import Callable


class ImaginedLuckIsTheWorlds(ValueError):
    """Imagining with the world's own seed would show the real future, not a possible one."""


def world_seed(conn: sqlite3.Connection) -> str:
    return conn.execute("SELECT value FROM meta WHERE key = 'world_seed'").fetchone()[0]


def copy_of(conn: sqlite3.Connection) -> sqlite3.Connection:
    from world.db import connect
    mem = connect()
    conn.backup(mem)
    return mem


class _Says:
    """The imagined producer: says what it is told to at the dawn of one day, as the real one would."""

    def __init__(self, day: int, say: Callable[[sqlite3.Connection, int], None] | None) -> None:
        self.day, self.say = day, say

    def dawn(self, conn: sqlite3.Connection, day: int, now: int) -> None:
        if day == self.day and self.say is not None:
            self.say(conn, now)


def imagine(clean: sqlite3.Connection, day: int, days: int, luck: int,
            say: Callable[[sqlite3.Connection, int], None] | None = None) -> sqlite3.Connection:
    """`clean` is the world as it stood at the start of `day` (before anything of the day). Copy it, change the luck, let `say` speak
    at that day's dawn, and run `days` days. Returns the copy; `clean` is untouched."""
    if str(luck) == world_seed(clean):
        raise ImaginedLuckIsTheWorlds(str(luck))
    from agent.volition import VolitionDecider
    from world.simulation import Simulation
    mem = copy_of(clean)
    mem.execute("UPDATE meta SET value = ? WHERE key = 'world_seed'", (str(luck),))  # the copy's luck only; this is not the world's
    d = VolitionDecider(luck)
    Simulation(mem, d, d, set(), feed="synthetic_v1", producer=_Says(day, say)).run(days)
    return mem
