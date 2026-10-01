"""The producer's threads: which stories it is tending, and how each stands (producer's own state, never the world's).

A thread is an opportunity the producer has taken up. It is not a plan to be carried out: it says "there is something here", and
it ends in whatever way the world ends it. A hero who has had their moment is done for a while (`completed`); one who lost the
very bout the story was about is also done (`failed`: a defeat is a story too); one nothing has happened to for a good while goes
`dormant`. After either end the person rests for REST_DAYS, so that the producer does not keep asking the same person for another
one.

`protected` is the other half: the people whose own story the world is already making (a triangle in the making) are not cast as
actors in someone else's, because that is the world's drama and a part leaning them would be the producer's hand on it.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

REST_DAYS = 5
DORMANT_AFTER = 10
STALL_DAYS = 7        # an arc the producer has done something for, and in which nothing has been played since, is given up
ABANDON_REST = 12     # ... and not taken up again for this long
PROTECT_AT = 0.15     # a triangle at least this worth watching is the world's own, and left alone


@dataclass
class Thread:
    opportunity_id: str
    kind: str
    protagonist: str
    others: list[str]
    opened: int
    last_action: int
    status: str = "active"          # active | completed | failed | dormant | abandoned
    ended: int = -1


class Threads:
    def __init__(self) -> None:
        self.by_id: dict[str, Thread] = {}
        self.last_focus: dict[str, int] = {}      # protagonist -> the last day they were the focus
        self._seen_events = -1
        self._payoffs: set[tuple[str, int]] = set()
        self.found: list[dict] = []               # every payoff seen so far (what has been told: the pattern memory's input)

    def take_up(self, op, day: int, acted: bool = True) -> Thread:
        t = self.by_id.get(op.opportunity_id)
        if t is None:
            t = self.by_id[op.opportunity_id] = Thread(op.opportunity_id, op.kind, op.protagonist, list(op.others), day, day)
        if t.status != "active":       # taken up again after it ended: a new telling, so nothing before it counts
            t.opened, t.ended = day, -1
        t.status = "active"
        if acted:                      # only something done for the story counts as tending it; noticing that it needs nothing does not
            t.last_action = day
            self.last_focus[op.protagonist] = day
        return t

    def resting(self, pid: str, day: int) -> bool:
        return any(t.protagonist == pid and t.status in ("completed", "failed") and day - t.ended < REST_DAYS for t in self.by_id.values())

    def waited(self, pid: str, day: int, cap: int = 14) -> int:
        return cap if pid not in self.last_focus else min(cap, day - self.last_focus[pid])

    def settle(self, conn: sqlite3.Connection, day: int) -> None:
        """Close what the world has closed, from what really happened."""
        n = conn.execute("SELECT COUNT(*) FROM events WHERE type IN ('duel', 'confession', 'succession')").fetchone()[0]
        if n != self._seen_events:
            self._seen_events = n
            from narrative import payoff
            self.found = payoff.payoffs(conn)
            self._payoffs = {(p["protagonist"], p["day"]) for p in self.found}
        for t in self.by_id.values():
            if t.status != "active":
                continue
            if any(who == t.protagonist and d >= t.opened for who, d in self._payoffs):
                t.status, t.ended = "completed", day
            elif t.kind == "reversal" and conn.execute(
                    "SELECT 1 FROM events WHERE type = 'duel' AND timestamp >= ? AND json_extract(truth, '$.loser') = ? AND "
                    "json_extract(truth, '$.winner') IN (%s) LIMIT 1" % ",".join("?" * len(t.others)),
                    (t.opened * 1440, t.protagonist, *t.others)).fetchone():
                t.status, t.ended = "failed", day
            elif day - t.last_action >= STALL_DAYS and not self._played(conn, t):
                t.status, t.ended = "abandoned", day      # nothing came of it: not rescued with more, given up
            elif day - t.last_action >= DORMANT_AFTER:
                t.status = "dormant"

    @staticmethod
    def _played(conn: sqlite3.Connection, t: Thread) -> bool:
        """Has anything of this story been played since it was taken up: a bout, a courtship, a vote involving them?"""
        who = [t.protagonist, *t.others]
        for r in conn.execute("SELECT truth FROM events WHERE type IN ('duel', 'flirt', 'confession', 'succession') AND timestamp >= ?", (t.opened * 1440,)):
            tr = json.loads(r[0])
            if t.protagonist in {tr.get(k) for k in ("winner", "loser", "actor", "target")} or (t.kind == "succession" and tr.get("winner")):
                return True
        return False

    def blocked(self, opportunity_id: str, day: int) -> bool:
        t = self.by_id.get(opportunity_id)
        return t is not None and t.status == "abandoned" and day - t.ended < ABANDON_REST

    def active(self) -> list[Thread]:
        return [t for t in self.by_id.values() if t.status == "active"]


def protected(opportunities) -> set[str]:
    """People whose own story is already under way (the ones in a triangle worth watching): not to be cast in somebody else's."""
    out: set[str] = set()
    for o in opportunities:
        if o.kind == "triangle" and o.potential >= PROTECT_AT:
            out |= {o.protagonist, *o.others}
    return out
