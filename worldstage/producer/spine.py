"""The main line: a table of beats that pulls the world along without forcing it (plot engine, phase 1).

A beat is a target, not an event. It names the episode it belongs to, the storyline it carries, whether it must be hit, and
which kinds of real event would fulfil it. It is fulfilled only by an event that really happened in world.db; nothing here
writes the world. The pull is the producer's own: `SpineDirector` is the greedy Director (producer/director.py) with one change,
the order in which it weighs the stories the world is already half-making: a story of the kind an open beat needs is looked at
first. Everything still goes through the same shaper, the same closed vocabulary and `Ledger.admit`, and the world still rolls the
dice. A beat the world did not reach is reported as missed, never faked.

Storylines bind to people as the world casts them: the first event that fulfils a line's first beat names its cast (actor and
target), and every later beat of that line has to involve one of them.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from worldstage.producer.director import Director

EPISODE_DAYS = 7


@dataclass(frozen=True)
class MainBeat:
    beat_id: str
    episode: int                 # 1-based
    line: str                    # A | B
    role: str                    # trigger | escalation | midpoint | crisis | climax | aftermath
    must_hit: bool
    types: tuple[str, ...]       # the kinds of world event that fulfil it
    pull: str = ""               # the Opportunity kind the producer looks at first while this beat is open ("" = no pull)
    note: str = ""               # what the beat is for, in a writer's words


LINES = {"A": "恩怨線：猜疑、指控與比武", "B": "情感線：示好、告白與失落"}
GRIEVANCE = ("steal", "take", "misplace", "notice_missing", "shove", "confront", "accuse", "duel")
HEART = ("flirt", "praise", "confession", "regret", "decline_offer")

BEATS: tuple[MainBeat, ...] = (
    MainBeat("E1-A", 1, "A", "trigger", True, ("steal", "take", "misplace", "notice_missing", "shove", "confront", "accuse"), "reversal",
             "something is taken, lost or said that one of them cannot let go"),
    MainBeat("E1-B", 1, "B", "trigger", True, ("flirt", "confession"), "triangle", "somebody reaches out to somebody"),
    MainBeat("E2-A", 2, "A", "escalation", True, ("confront", "accuse", "shove", "duel", "tell"), "reversal",
             "the grievance is said aloud, or spreads"),
    MainBeat("E2-B", 2, "B", "midpoint", True, ("flirt", "confession", "praise", "regret", "confront"), "triangle",
             "the feeling is tested: answered, refused or seen by the wrong person"),
    MainBeat("E3-A", 3, "A", "climax", True, GRIEVANCE + ("regret",), "reversal", "it comes to a head in front of others"),
    MainBeat("E3-B", 3, "B", "aftermath", False, HEART + ("talk",), "", "what the feeling has cost, and who is left with it"),
)


@dataclass
class Binding:
    beat: MainBeat
    event_id: int | None = None
    cast: tuple[str, ...] = ()
    day: int | None = None
    reason: str = ""


@dataclass
class SpineResult:
    bindings: dict[str, Binding] = field(default_factory=dict)
    casts: dict[str, set[str]] = field(default_factory=dict)

    def missed(self, must_only: bool = True) -> list[str]:
        return [b for b, x in self.bindings.items() if x.event_id is None and (x.beat.must_hit or not must_only)]


def _events(conn: sqlite3.Connection, types: tuple[str, ...], first_day: int, last_day: int, min_importance: float) -> list[tuple]:
    marks = ",".join("?" * len(types))
    rows = conn.execute(f"SELECT event_id, type, timestamp, importance FROM events WHERE type IN ({marks}) AND timestamp >= ? AND timestamp < ?"
                        f" AND importance >= ? ORDER BY importance DESC, event_id", (*types, first_day * 1440, (last_day + 1) * 1440,
                                                                                     min_importance)).fetchall()
    return rows


def _people(conn: sqlite3.Connection, event_id: int) -> tuple[str, ...]:
    return tuple(p for (p,) in conn.execute("SELECT person_id FROM event_participants WHERE event_id = ? AND role IN ('actor', 'target', 'victim')"
                                            " ORDER BY role, person_id", (event_id,)))


def fulfil(conn: sqlite3.Connection, beats: tuple[MainBeat, ...] = BEATS, episode_days: int = EPISODE_DAYS, first_day: int = 0,
           min_importance: float = 0.3, used: set[int] | None = None) -> SpineResult:
    """Bind every beat to the one real event that fulfils it best (most important; a line's later beats must share its cast)."""
    res = SpineResult()
    used = set(used or ())
    for beat in sorted(beats, key=lambda b: (b.episode, b.line)):
        lo = first_day + (beat.episode - 1) * episode_days
        hi = lo + episode_days - 1
        cast = res.casts.get(beat.line)
        other = set().union(*(c for k, c in res.casts.items() if k != beat.line)) if res.casts else set()
        best = None
        for eid, etype, ts, imp in _events(conn, beat.types, lo, hi, min_importance):
            if eid in used:
                continue
            who = _people(conn, eid)
            if not who:
                continue
            if cast is not None and not (set(who) & cast):
                continue
            if cast is None and set(who) <= other:      # a new line is about somebody else, so that two lines are interwoven, not one
                continue
            best = (eid, who, ts // 1440)
            break
        b = Binding(beat)
        if best is None:
            b.reason = "the world did not reach it in this episode"
        else:
            b.event_id, b.cast, b.day = best
            used.add(best[0])
            res.casts.setdefault(beat.line, set()).update(best[1])
        res.bindings[beat.beat_id] = b
    return res


class SpineDirector(Director):
    """The greedy Director, looking first at the kind of story the open beats of the current episode need."""

    def __init__(self, strategy: str = "greedy", seed: int = 0, beats: tuple[MainBeat, ...] = BEATS, episode_days: int = EPISODE_DAYS,
                 **kw) -> None:
        super().__init__(strategy, seed, **kw)
        self.beats, self.episode_days = beats, episode_days
        self.pulls: list[tuple[int, str, str]] = []      # (day, beat_id, opportunity kind): what it looked at first, and why

    def _open_pulls(self, conn: sqlite3.Connection, day: int) -> list[MainBeat]:
        ep = day // self.episode_days + 1
        now = [b for b in self.beats if b.episode == ep and b.pull]
        if not now:
            return []
        got = fulfil(conn, tuple(b for b in self.beats if b.episode <= ep), self.episode_days)
        return [b for b in now if got.bindings[b.beat_id].event_id is None]

    def _ranked(self, conn, ops, day):
        ranked = super()._ranked(conn, ops, day)
        wanted = [b for b in self._open_pulls(conn, day)]
        kinds = [b.pull for b in wanted]
        if not kinds or not ranked:
            return ranked
        first = sorted(ranked, key=lambda o: 0 if o.kind in kinds else 1)    # stable: the Director's own order within each group
        if first[0].kind in kinds:
            b = wanted[kinds.index(first[0].kind)]
            self.pulls.append((day, b.beat_id, first[0].kind))
        return first
