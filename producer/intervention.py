"""The producer's side of an intervention: the proposal, its ledger and budget, and what it hands to the world.

    InterventionProposal  ->  Ledger.admit(...)  ->  world.interventions.apply(proposal.world_view())

The ledger is the producer's own record (a JSONL file, append only): every proposal with its season, arc, purpose and cost,
whether the world took it, and why not when it did not. That is where `purpose` lives. The world gets the `WorldIntervention` and
an opaque id; it never receives, and so cannot record, a purpose, an arc or a season. The weekly budget is enforced here, because
the cost of an intervention is the producer's matter, not a fact about the town.

The producer controls the topology of opportunity and nothing else: it cannot make anybody win, love, fear or respect, and the
vocabulary it can speak (contracts/intervention.py, world/interventions.py) has no word for any of that.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from contracts.base import to_dict
from contracts.intervention import InterventionProposal
from world import interventions

WEEK_BUDGET = 6      # units of intervention per seven days
COSTS = {"announce_gathering": 2, "deliver_parcel": 1, "open_seat": 3, "announce_visitor": 1, "cast_role": 1}


@dataclass
class Verdict:
    admitted: bool
    reason: str = ""
    event_id: int | None = None


@dataclass
class Ledger:
    """Append-only: what was proposed, why, what it cost, and what the world made of it."""

    path: Path | None = None
    entries: list[dict] = field(default_factory=list)
    week_budget: int = WEEK_BUDGET
    decisions: list[dict] = field(default_factory=list)   # what the producer chose, including to do nothing (never the world's)

    def spent(self, day: int) -> int:
        return sum(e["budget_cost"] for e in self.entries if e["admitted"] and day - 6 <= e["day"] <= day)

    def admit(self, conn: sqlite3.Connection, p: InterventionProposal, now: int) -> Verdict:
        """Judge a proposal (budget, then the world's vocabulary and rules); if it passes, the world hears it."""
        day = now // 1440
        if p.budget_cost < COSTS.get(p.type, 99):
            reason = f"costs {COSTS.get(p.type)} at least, offered {p.budget_cost}"
        elif self.spent(day) + p.budget_cost > self.week_budget:
            reason = f"over the week's budget ({self.spent(day)} of {self.week_budget} spent)"
        else:
            reason = "; ".join(interventions.problems(conn, p.world_view()))
        event_id = None if reason else interventions.apply(conn, p.world_view(), now)
        self._record(p, now, not reason, reason, event_id)
        return Verdict(not reason, reason, event_id)

    def fork(self) -> "Ledger":
        """A copy to imagine with: the same spending and budget, no file, and nothing it does reaches this one."""
        return Ledger(None, [dict(e) for e in self.entries], self.week_budget)

    def decide(self, day: int, action: str, reason: str, **detail) -> None:
        """Keep a decision of the producer's own: to act, or on purpose not to (silence is a decision, not a gap)."""
        d = {"day": day, "action": action, "reason": reason, **detail}
        self.decisions.append(d)
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.with_suffix(".decisions.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps(d, ensure_ascii=False, sort_keys=True) + "\n")

    def _record(self, p: InterventionProposal, now: int, admitted: bool, reason: str, event_id: int | None) -> None:
        entry = {**to_dict(p), "proposal_hash": p.hash(), "day": now // 1440, "admitted": admitted, "reason": reason,
                 "event_id": event_id}
        self.entries.append(entry)
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")

    @classmethod
    def load(cls, path: Path) -> "Ledger":
        lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
        return cls(path, [json.loads(x) for x in lines if x.strip()])
