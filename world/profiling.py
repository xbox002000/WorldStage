"""Where the time goes: inclusive milliseconds per layer of a simulated day, measured, never used to decide anything.

    sim = Simulation(...); sim.run(30); sim.profile.report()

Sections (inclusive: a section's time includes the sections it calls):
  day              the whole day
  decide           the deciders choosing (rule agent, character agent)
  reply            answers and bystanders (agent/reply.py)
  apply.validate   the validator
  apply.resolve    the rules turning an intent into an event
  apply.effects    domain packs and animals adding to an event
  apply.write      apply_event: the transaction
  after            consequences of an event (mechanics, goals, domain packs)
  upkeep           the night: upkeep, props, missing things, goals, reflections, domain nights
  upkeep.psyche    nightly reflection
  space.runtime    the World Runtime catching up with the history (navigation, bodies), when space is a sense
  space.query      the questions the world asks space (who could see or hear what)
"""
from __future__ import annotations

import time
from collections import Counter
from contextlib import contextmanager


class Profile:
    def __init__(self) -> None:
        self.ms: Counter = Counter()
        self.calls: Counter = Counter()
        self.days: list[dict] = []  # per day: section -> ms
        self._mark: Counter = Counter()

    @contextmanager
    def section(self, name: str):
        t0 = time.perf_counter()
        try:
            yield
        finally:
            self.ms[name] += (time.perf_counter() - t0) * 1000.0
            self.calls[name] += 1

    def wrap(self, obj, attr: str, name: str) -> None:
        """Time every call of obj.attr under `name` (for objects the simulation does not own, such as space)."""
        fn = getattr(obj, attr)
        prof = self

        def timed(*a, **k):
            with prof.section(name):
                return fn(*a, **k)
        setattr(obj, attr, timed)

    def end_day(self, day: int) -> None:
        delta = {k: round(v - self._mark.get(k, 0.0), 1) for k, v in self.ms.items() if v - self._mark.get(k, 0.0) > 0}
        self.days.append({"day": day, **delta})
        self._mark = Counter(self.ms)

    def report(self) -> dict:
        total = self.ms.get("day", 0.0) or 1.0
        return {"total_ms": round(total, 1),
                "sections": {k: {"ms": round(v, 1), "share": round(v / total, 3), "calls": self.calls[k]}
                             for k, v in sorted(self.ms.items(), key=lambda kv: -kv[1])},
                "days": self.days}
