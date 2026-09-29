from __future__ import annotations

import json
import sqlite3
from collections import Counter
from typing import Protocol

from world.events import apply_event
from world.intent import Intent, intent_sort_key, validate
from world.rules import resolve
from world.state import WorldError

DAY = 1440
DECISION_SLOTS = (730, 1090, 1270)  # after arrivals at cafe, park and home
UPKEEP_SLOT = 1439


class Decider(Protocol):
    def decide(self, conn: sqlite3.Connection, actor: str, now: int) -> Intent | None: ...


class Simulation:
    """Event-driven day loop. Scheduled actions are rules; social choices go to a tiered decider."""

    def __init__(self, conn: sqlite3.Connection, active: Decider, ambient: Decider, active_ids: set[str]) -> None:
        self.conn = conn
        self.active = active
        self.ambient = ambient
        self.active_ids = active_ids
        self.stats: Counter = Counter()

    def run(self, days: int) -> None:
        start = self.conn.execute("SELECT COALESCE(MAX(timestamp), 0) FROM events").fetchone()[0] // DAY
        for day in range(start, start + days):
            self.run_day(day)

    def run_day(self, day: int) -> None:
        ids = [r["id"] for r in self.conn.execute("SELECT id FROM people ORDER BY id")]
        schedules = {r["id"]: json.loads(r["schedule"]) for r in self.conn.execute("SELECT id, schedule FROM people")}
        slots = sorted({int(s) for sched in schedules.values() for s in sched} | set(DECISION_SLOTS))
        for slot in slots:
            now = day * DAY + slot
            scripted = []
            for pid in ids:
                spec = schedules[pid].get(str(slot))
                if spec:
                    scripted.append(self._scripted_intent(pid, spec))
            for intent in sorted((i for i in scripted if i is not None), key=lambda i: intent_sort_key(now, i)):
                self._apply(intent, now, "schedule")
            if slot in DECISION_SLOTS:
                for pid in ids:
                    self._decide(pid, now)
        self._upkeep(ids, day * DAY + UPKEEP_SLOT)

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
        apply_event(self.conn, resolve(self.conn, intent, now, trigger))
        self.stats[f"applied_{intent.action}"] += 1

    def _upkeep(self, ids: list[str], now: int) -> None:
        """Overnight: everyone goes home, sleeps and gets hungry. One event per person."""
        from world.events import Change, EventSpec

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
