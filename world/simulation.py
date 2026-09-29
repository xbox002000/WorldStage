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
PRELUDE = ("backstory", "mechanic", "awakening")  # set-up events that may precede a day without being part of one
MISPLACE_RATE = 0.06  # chance per carried item per departure, times the person's absent_minded trait


class Decider(Protocol):
    def decide(self, conn: sqlite3.Connection, actor: str, now: int) -> Intent | None: ...


class Simulation:
    """Event-driven day loop. Scheduled actions are rules; social choices go to a tiered decider.

    Every day ends with a `day_end` event, so a world can always tell which days are complete and resume from
    the next one. A day interrupted half-way cannot be resumed: restore the last good copy of the database.
    """

    def __init__(self, conn: sqlite3.Connection, active: Decider, ambient: Decider, active_ids: set[str],
                 feed: str | None = None, mechanics: list | None = None) -> None:
        self.conn = conn
        self.feed = feed  # name of the outside-event feed (world/feeds/*.json); None = a closed town
        self.economy = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'world_vars'").fetchone() is not None
        if mechanics is None and self.economy:
            from world.mechanics import mechanics_of
            mechanics = mechanics_of(conn)  # the pack recorded in the world itself
        self.mechanics = mechanics or []
        from agent.animal import AnimalDecider
        from world.animals import animal_ids
        self.animals = animal_ids(conn) if self.economy else set()
        self.animal_decider = AnimalDecider(self.seed if hasattr(self, "seed") else
                                            conn.execute("SELECT value FROM meta WHERE key = 'world_seed'").fetchone()[0])
        from world.recipes import compiled, recipe_of
        self.primitives = set(compiled(recipe_of(conn)).order) if self.economy else set()
        for d in {id(active): active, id(ambient): ambient}.values():
            if hasattr(d, "mechanics"):
                d.mechanics = self.mechanics
        self.active = active
        self.ambient = ambient
        self.active_ids = active_ids
        self.stats: Counter = Counter()
        self.seed = conn.execute("SELECT value FROM meta WHERE key = 'world_seed'").fetchone()[0]

    # -- days ----------------------------------------------------------------------------------------------------
    def next_day(self) -> int:
        """The first day that has not been simulated. Raises if the last day was left unfinished."""
        last_any = self.conn.execute(
            f"SELECT MAX(timestamp) FROM events WHERE type NOT IN ({','.join('?' * len(PRELUDE))})", PRELUDE).fetchone()[0]
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
        if self.feed and "seeds.external" in self.primitives:
            from world.seeds import SeedLayer
            for cand in SeedLayer(self.conn, self.feed).dawn(day):
                self.stats[f"seed_{cand.status}"] += 1
        for m in self.mechanics:
            m.on_dawn(self.conn, day)
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
            if slot in DECISION_SLOTS and "props.parrot" in self.primitives:
                from world.props import parrot_events
                for spec in parrot_events(self.conn, base):
                    self._after(apply_event(self.conn, spec))
                    self.stats["parrot_speaks"] += 1
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
        if pid in self.animals:
            if self.conn.execute("SELECT status FROM people WHERE id = ?", (pid,)).fetchone()[0] == "inactive":
                return
            intent = self.animal_decider.decide(self.conn, pid, now)
            self.stats["animal_decisions"] += 1
            if intent is not None:
                self._apply(intent, now, "decision")
            return
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
        if intent.action == "move" and "items.ownership" in self.primitives:
            self._maybe_misplace(intent.actor, now)
        spec = resolve(self.conn, intent, now, trigger)
        if self.primitives & {"reputation", "sect_factions"}:
            from world.jianghu import with_jianghu_effects
            spec = with_jianghu_effects(self.conn, spec, self.primitives)
        if self.animals:
            from world.animals import with_senses
            spec = with_senses(self.conn, spec)
        event_id = apply_event(self.conn, spec)
        self.stats[f"applied_{intent.action}"] += 1
        if intent.action == "tell":
            self.stats[f"tell_{intent.mode}"] += 1
        elif intent.action == "confront":
            self.stats[f"confront_{spec.truth['outcome']}"] += 1
        self._after(event_id)

    def _after(self, event_id: int) -> None:
        """What follows from an event without anyone choosing it: mechanics react, goals are reviewed."""
        for m in self.mechanics:
            m.after_event(self.conn, event_id)
        if "goals" in self.primitives:
            from world.goals import after_event
            for spec in after_event(self.conn, event_id):
                apply_event(self.conn, spec)
                self.stats["goal_changes"] += 1

    def _maybe_misplace(self, pid: str, now: int) -> None:
        """Leaving a place, an absent-minded person may leave something behind. Nobody decides this."""
        from world.items import misplace
        from world.attention import world_seed
        row = self.conn.execute("SELECT traits FROM personas WHERE person_id = ?", (pid,)).fetchone()
        absent = json.loads(row[0]).get("absent_minded", 0.0) if row else 0.0
        for obj in self.conn.execute(
            "SELECT id, tags FROM objects WHERE owner_person_id = ? AND status = 'normal' ORDER BY id", (pid,)).fetchall():
            tags = json.loads(obj["tags"])
            if "fixed" in tags or "animal" in tags:
                continue
            if make_rng(world_seed(self.conn), now, f"{pid}:{obj['id']}", "misplace").random() < MISPLACE_RATE * absent:
                apply_event(self.conn, misplace(self.conn, pid, obj["id"], now))
                self.stats["misplaced"] += 1

    def _upkeep(self, ids: list[str], now: int) -> None:
        """Overnight: everyone goes home, pays rent, sleeps and gets hungry (one event per person); then props do
        what they do, and people notice what they no longer have."""
        for pid in ids:
            if pid in self.animals:
                continue  # an animal sleeps where it is; hunger and rent are people's business
            p = self.conn.execute("SELECT * FROM people WHERE id = ?", (pid,)).fetchone()
            changes = []
            from world.content import home_of
            home = home_of(self.conn, pid)
            if p["location_id"] != home:
                changes.append(Change("person", pid, "location_id", value=home))
            if p["energy"] < 100:
                changes.append(Change("person", pid, "energy", delta=min(60, 100 - p["energy"])))
            if p["hunger"] < 100:
                changes.append(Change("person", pid, "hunger", delta=min(30, 100 - p["hunger"])))
            if "money.rent" in self.primitives:
                from world.money import rent_changes
                changes += rent_changes(self.conn, pid)
            if changes:
                apply_event(self.conn, EventSpec(
                    timestamp=now, type="upkeep", trigger_type="rule", location_id=home,
                    importance=0.0, truth={"actor": pid}, participants=[(pid, "actor")], changes=changes,
                ))
        if not self.economy:
            return
        from world.items import missing_items, notice_missing
        from world.props import overnight
        if "props.animals" in self.primitives:
            from world.props import feed_animals
            for spec in feed_animals(self.conn, now):
                apply_event(self.conn, spec)
                self.stats["feed_pet"] += 1
        for pid in ids:
            for spec in overnight(self.conn, pid, now):
                if spec.type == "feed_pet" and "props.animals" not in self.primitives:
                    continue
                apply_event(self.conn, spec)
                self.stats[spec.type] += 1
        for pid in ids if "items.ownership" in self.primitives else []:
            for obj in missing_items(self.conn, pid):
                self._after(apply_event(self.conn, notice_missing(self.conn, pid, obj["id"], now)))
                self.stats["noticed_missing"] += 1
        from world.goals import overnight as goals_overnight
        for spec in (goals_overnight(self.conn, now // 1440, now) if "goals" in self.primitives else []):
            apply_event(self.conn, spec)
            self.stats["goal_changes"] += 1
        if "psyche" in self.primitives:
            from world.psyche import reflect
            for pid in ids:
                spec = reflect(self.conn, pid, now // 1440, now)
                if spec is not None:
                    apply_event(self.conn, spec)
                    self.stats["reflections"] += 1
