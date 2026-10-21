"""The fact ledger and what each person knows of it, derived from world.db (read only). Phase 1 of the plot engine.

A fact is one event of the world that a story may stand on: what happened (the world's truth), when, where, who was in it. Who
*knows* a fact is not decided here: it is read from the world's own record of belief. A person knows a fact from the moment they
have a memory of it, either because they saw it (`memories.event_id`, direct observation) or because somebody told them
(`memories.about_event_id`: told_by, inference, rumour); the one who did it always knows. A victim who was not there does not
know until somebody tells them.

`KnowledgeGate` is the generation-time check: a scene is written only from the facts each of its people knows at the scene's
time, and a line that uses or quotes a fact its speaker does not know is refused before the scene is accepted.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field

from worldstage.runtime.godview import _names, caption

DAY = 1440
# kinds of event too routine to be a fact a story stands on
ROUTINE = frozenset({"move", "upkeep", "eat", "day_end", "reflection", "goal_change", "train", "circles"})
MIN_IMPORTANCE = 0.3


@dataclass(frozen=True)
class Fact:
    fact_id: int                 # = events.event_id
    ts: int
    type: str
    location: str
    actor: str
    target: str
    participants: tuple[str, ...]
    summary: str                 # the world's truth in one sentence
    claim_text: str              # the words a person would use for it (truth.text), "" when it has none
    importance: float
    truth: dict = field(default_factory=dict, compare=False, hash=False)

    @property
    def day(self) -> int:
        return self.ts // DAY


@dataclass(frozen=True)
class Knowing:
    since: int          # the time they came to know it
    how: str            # did_it | direct_observation | told_by | inference | external_rumor
    belief: str         # what they believe happened, in their own words


class FactLedger:
    def __init__(self, conn: sqlite3.Connection, min_importance: float = MIN_IMPORTANCE, until: int | None = None) -> None:
        self.conn = conn
        self.names = _names(conn)
        self.facts: dict[int, Fact] = {}
        q = "SELECT event_id, timestamp, type, COALESCE(location_id, ''), importance, truth FROM events WHERE importance >= ?"
        args: list = [min_importance]
        if until is not None:
            q += " AND timestamp <= ?"
            args.append(until)
        parts: dict[int, list[str]] = {}
        for eid, pid in conn.execute("SELECT event_id, person_id FROM event_participants ORDER BY event_id, person_id"):
            parts.setdefault(eid, []).append(pid)
        for eid, ts, etype, loc, imp, truth in conn.execute(q + " ORDER BY event_id", args):
            if etype in ROUTINE:
                continue
            t = json.loads(truth)
            target = t.get("target") or t.get("victim") or t.get("suspect") or ""
            target = target if target in self.names else ""
            self.facts[eid] = Fact(eid, ts, etype, loc, t.get("actor", ""), target, tuple(parts.get(eid, ())),
                                   caption(etype, t, self.names.get(loc, loc), self.names), t.get("text") or "", imp, t)
        self.knowing: dict[str, dict[int, Knowing]] = {}
        for f in self.facts.values():
            if f.actor:
                self._learn(f.actor, f.fact_id, Knowing(f.ts, "did_it", f.summary))
        for obs, eid, about, belief, how, created in conn.execute(
                "SELECT observer_id, event_id, about_event_id, belief, source_type, created_at FROM memories ORDER BY memory_id"):
            fid = about if (about is not None and how != "direct_observation") else eid
            if fid in self.facts:
                self._learn(obs, fid, Knowing(created, how, belief))

    def _learn(self, pid: str, fid: int, k: Knowing) -> None:
        have = self.knowing.setdefault(pid, {})
        if fid not in have or k.since < have[fid].since:
            have[fid] = k

    # -- questions ------------------------------------------------------------------------------------------------------
    def knows(self, pid: str, fid: int, at: int) -> bool:
        k = self.knowing.get(pid, {}).get(fid)
        return k is not None and k.since <= at

    def known(self, pid: str, at: int) -> list[Fact]:
        return [self.facts[f] for f, k in sorted(self.knowing.get(pid, {}).items()) if k.since <= at]

    def how(self, pid: str, fid: int) -> Knowing | None:
        return self.knowing.get(pid, {}).get(fid)

    def who_knows(self, fid: int, at: int) -> list[str]:
        return sorted(p for p, ks in self.knowing.items() if fid in ks and ks[fid].since <= at)

    def name(self, pid: str) -> str:
        return self.names.get(pid, pid)

    def window(self, first_day: int, last_day: int) -> list[Fact]:
        return [f for f in self.facts.values() if first_day <= f.day <= last_day]


@dataclass(frozen=True)
class Violation:
    code: str           # K1 unknown fact used, K2 fact from the future, K3 an unknown fact's words quoted, K4 acts on an unknown fact
    severity: str       # severe | warn
    speaker: str
    fact_id: int
    detail: str


class KnowledgeGate:
    """What each person in a scene may say or act on, at the scene's time."""

    def __init__(self, ledger: FactLedger) -> None:
        self.ledger = ledger

    def allowed(self, pid: str, at: int) -> dict[int, Knowing]:
        return {f.fact_id: self.ledger.how(pid, f.fact_id) for f in self.ledger.known(pid, at)}

    def check_line(self, speaker: str, text: str, uses: list[int], at: int) -> list[Violation]:
        out: list[Violation] = []
        L = self.ledger
        for fid in uses:
            f = L.facts.get(fid)
            if f is None:
                out.append(Violation("K1", "severe", speaker, fid, "no such fact in the ledger"))
            elif f.ts > at:
                out.append(Violation("K2", "severe", speaker, fid, f"{L.name(speaker)} speaks of what has not happened yet: {f.summary}"))
            elif not L.knows(speaker, fid, at):
                out.append(Violation("K1", "severe", speaker, fid, f"{L.name(speaker)} does not know: {f.summary}"))
        # the words of a fact they do not know must not come out of their mouth, whatever `uses` claims
        # (words are theirs if any fact they know carries them: the same thing can be done once and told many times)
        mine = None
        seen: set[str] = set()
        for f in L.facts.values():
            words = f.claim_text
            if len(words) < 5 or words not in text or words in seen or f.ts > at or L.knows(speaker, f.fact_id, at):
                continue
            if mine is None:
                mine = " ".join(f"{g.claim_text} {L.how(speaker, g.fact_id).belief} {g.summary}" for g in L.known(speaker, at))
            if words not in mine:
                seen.add(words)
                out.append(Violation("K3", "severe", speaker, f.fact_id, f"{L.name(speaker)} quotes what they do not know: {words}"))
        return out

    def check_act(self, actor: str, fact: Fact) -> list[Violation]:
        """An act may stand only on what its actor knew when they did it (truth.depends_on: the events it was chosen from)."""
        out = []
        for dep in fact.truth.get("depends_on") or []:
            c = self.ledger.conn
            did = c.execute("SELECT 1 FROM event_participants WHERE event_id = ? AND person_id = ? AND role = 'actor'", (dep, actor)).fetchone()
            saw = c.execute("SELECT 1 FROM memories WHERE observer_id = ? AND (event_id = ? OR about_event_id = ?) AND created_at <= ?",
                            (actor, dep, dep, fact.ts)).fetchone()
            if not (did or saw):
                out.append(Violation("K4", "severe", actor, fact.fact_id, f"act {fact.fact_id} stands on event {dep}, which its actor did not know"))
        return out
