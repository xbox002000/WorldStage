from __future__ import annotations

import json
import sqlite3
from collections import Counter
from typing import Protocol

from world.events import Change, EventSpec, apply_event
from world.intent import Intent, intent_sort_key, validate
from world.rng import rng as make_rng
from world.rules import resolve
from world.state import WorldError

DAY = 1440
DECISION_SLOTS = (730, 1090, 1270)  # after arrivals at cafe, park and home
UPKEEP_SLOT = 1439
JITTER_MAX = 25  # minutes: people never act on the dot


class Decider(Protocol):
    def decide(self, conn: sqlite3.Connection, actor: str, now: int) -> Intent | None: ...


class Simulation:
    """Event-driven day loop. Scheduled actions are rules; social choices go to a tiered decider.

    Every day ends with a `day_end` event, so a world can always tell which days are complete and resume from
    the next one. A day interrupted half-way cannot be resumed: restore the last good copy of the database.
    """

    def __init__(self, conn: sqlite3.Connection, active: Decider, ambient: Decider, active_ids: set[str]) -> None:
        self.conn = conn
        self.active = active
        self.ambient = ambient
        self.active_ids = active_ids
        self.stats: Counter = Counter()
        self.seed = conn.execute("SELECT value FROM meta WHERE key = 'world_seed'").fetchone()[0]

    # -- days ----------------------------------------------------------------------------------------------------
    def next_day(self) -> int:
        """The first day that has not been simulated. Raises if the last day was left unfinished."""
        last_any = self.conn.execute("SELECT MAX(timestamp) FROM events").fetchone()[0]
        if last_any is None:
            return 0
        last_end = self.conn.execute("SELECT MAX(timestamp) FROM events WHERE type = 'day_end'").fetchone()[0]
        if last_end is None or last_any > last_end:
            raise WorldError("the last simulated day is incomplete: restore the previous copy of the world")
        return last_end // DAY + 1

    def run(self, days: int) -> list[int]:
        start = self.next_day()
        done = list(range(start, start + days))
        for day in done:
            self.run_day(day)
        return done

    def run_day(self, day: int) -> None:
        ids = [r["id"] for r in self.conn.execute("SELECT id FROM people ORDER BY id")]
        schedules = {r["id"]: json.loads(r["schedule"]) for r in self.conn.execute("SELECT id, schedule FROM people")}
        slots = sorted({int(s) for sched in schedules.values() for s in sched} | set(DECISION_SLOTS))
        for i, slot in enumerate(slots):
            window = (slots[i + 1] if i + 1 < len(slots) else UPKEEP_SLOT) - slot
            base = day * DAY + slot
            scripted = []
            for pid in ids:
                spec = schedules[pid].get(str(slot))
                intent = self._scripted_intent(pid, spec) if spec else None
                if intent is not None:
                    scripted.append((self._stamp(pid, base, window), intent))
            for ts, intent in sorted(scripted, key=lambda s: intent_sort_key(s[0], s[1])):
                self._apply(intent, ts, "schedule")
            if slot in DECISION_SLOTS:
                # Each person decides at their own moment inside the slot; earlier deciders shape what later ones see.
                for ts, pid in sorted((self._stamp(p, base, window), p) for p in ids):
                    self._decide(pid, ts)
        self._upkeep(ids, day * DAY + UPKEEP_SLOT)
        apply_event(self.conn, EventSpec(timestamp=day * DAY + UPKEEP_SLOT, type="day_end", trigger_type="rule",
                                         importance=0.0, truth={"day": day}))

    def _stamp(self, pid: str, base: int, window: int) -> int:
        """A seed-determined minute inside the slot, never reaching the next slot's start."""
        span = min(JITTER_MAX, max(0, window - 1))
        return base + (make_rng(self.seed, base, pid, "jitter").randint(0, span) if span else 0)

    # -- actions -------------------------------------------------------------------------------------------------
    def _scripted_intent(self, pid: str, spec: str) -> Intent | None:
        action, _, target = spec.partition(":")
        if action == "move" and self.conn.execute(
            "SELECT location_id FROM people WHERE id = ?", (pid,)
        ).fetchone()[0] == target:
            return None  # already there
        return Intent(pid, action, target or None)

    def _decide(self, pid: str, now: int) -> None:
        tier = "active" if pid in self.active_ids else "ambient"
        intent = (self.active if tier == "active" else self.ambient).decide(self.conn, pid, now)
        self.stats[f"{tier}_decisions"] += 1
        if intent is not None:
            self._apply(intent, now, "decision")

    def _apply(self, intent: Intent, now: int, trigger: str) -> None:
        try:
            validate(self.conn, intent)
        except WorldError:
            self.stats[f"rejected_{trigger}"] += 1
            return
        spec = resolve(self.conn, intent, now, trigger)
        apply_event(self.conn, spec)
        self.stats[f"applied_{intent.action}"] += 1
        if intent.action == "tell":
            self.stats[f"tell_{intent.mode}"] += 1
        elif intent.action == "confront":
            self.stats[f"confront_{spec.truth['outcome']}"] += 1

    def _upkeep(self, ids: list[str], now: int) -> None:
        """Overnight: everyone goes home, sleeps and gets hungry. One event per person."""
        for pid in ids:
            p = self.conn.execute("SELECT * FROM people WHERE id = ?", (pid,)).fetchone()
            changes = []
            if p["location_id"] != "apartment":
                changes.append(Change("person", pid, "location_id", value="apartment"))
            if p["energy"] < 100:
                changes.append(Change("person", pid, "energy", delta=min(60, 100 - p["energy"])))
            if p["hunger"] < 100:
                changes.append(Change("person", pid, "hunger", delta=min(30, 100 - p["hunger"])))
            if changes:
                apply_event(self.conn, EventSpec(
                    timestamp=now, type="upkeep", trigger_type="rule", location_id="apartment",
                    importance=0.0, truth={"actor": pid}, participants=[(pid, "actor")], changes=changes,
                ))
