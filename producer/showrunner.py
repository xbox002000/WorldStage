"""The showrunner: plans seasons, and arranges opportunities for the people in them. It decides nothing about how it ends.

Each season (SEASON_DAYS) it takes a few people as its protagonists (in turn: whoever has gone longest without a season, and whose
world has a story in it), gives each one arc, and places a handful of opportunities on the days of it:

  underdog    somebody the others rate below what they have become. A doubter is cast among the others, a parcel with a
              manual arrives for them, a tournament is announced
  succession  somebody of a faction that has a seat. The seat is opened, and a rival is cast
  romance     somebody who is drawn to somebody. A suitor is cast towards the one they are drawn to

Everything it does goes through `Ledger.admit` (producer/intervention.py): a closed vocabulary, the world's own rules, a weekly
budget. It can arrange who might meet, what is announced, what arrives, what falls vacant, and whom a part is played towards. It
cannot make anybody win, love, fear or respect: it has no word for that. The plan is revised each morning from what has really
happened: a beat whose reason has gone is dropped, an arc whose hero has had their moment is closed, and one that has gone badly
is left to run its course (a defeat is also a story).

Strategies, so that what the producer adds can be measured and not assumed (producer_lab.py):
  full      every kind of opportunity
  stage     only gatherings and vacancies (the place and the occasion)
  cast      only roles
  parcel    only parcels
  random    the same kinds, the same days and the same cost as `full`, aimed at nobody in particular: the control that says how
            much of the effect is the aiming
The first version only records. It does not learn.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import replace
from pathlib import Path

from contracts.intervention import InterventionProposal
from contracts.season import Arc, Beat, SeasonPlan
from producer.intervention import COSTS, Ledger
from world.attention import var
from world.rng import rng as make_rng

SEASON_DAYS = 14
UNDERRATED = 0.12   # how far above what the others take them for somebody has to be to be an underdog
PROTAGONISTS = 2
STRATEGIES = {"full": None, "stage": {"announce_gathering", "open_seat"}, "cast": {"cast_role"}, "parcel": {"deliver_parcel"}, "random": None}


def _humans(conn: sqlite3.Connection) -> list[str]:
    from world.domains.factions import humans
    return humans(conn)


def _ability(conn: sqlite3.Connection, pid: str) -> float | None:
    return var(conn, f"skill.{pid}", None)


def _crowd(conn: sqlite3.Connection, pid: str) -> float:
    r = conn.execute("SELECT AVG(estimate) FROM relationships WHERE target_id = ? AND actor_id != ?", (pid, pid)).fetchone()[0]
    return 0.5 if r is None else r


class Showrunner:
    def __init__(self, strategy: str = "full", seed: int = 0, ledger: Ledger | None = None, plan_dir: Path | None = None,
                 season_days: int = SEASON_DAYS, protagonists: int = PROTAGONISTS) -> None:
        if strategy not in STRATEGIES:
            raise ValueError(f"no strategy {strategy!r}")
        self.strategy, self.seed = strategy, seed
        self.ledger = ledger if ledger is not None else Ledger()
        self.plan_dir = plan_dir
        self.season_days, self.n_protagonists = season_days, protagonists
        self.plans: list[SeasonPlan] = []
        self.last_lead: dict[str, int] = {}
        self.done: set[str] = set()          # beats already acted on (arc_id:index)
        self.closed: set[str] = set()        # arcs whose hero has had their moment
        self._checked = -1

    # -- the daily call (Simulation.producer) --------------------------------------------------------------------------
    def dawn(self, conn: sqlite3.Connection, day: int, now: int) -> None:
        if day % self.season_days == 0:
            self._plan(conn, day)
        self._close_finished(conn, day)
        if not self.plans:
            return
        plan = self.plans[-1]
        for arc in plan.arcs:
            if arc.arc_id in self.closed:
                continue
            for i, beat in enumerate(arc.beats):
                key = f"{arc.arc_id}:{i}"
                if key in self.done or plan.start_day + beat.day != day:
                    continue
                self.done.add(key)
                self._act(conn, plan, arc, i, beat, day, now)

    # -- planning ------------------------------------------------------------------------------------------------------
    def _plan(self, conn: sqlite3.Connection, day: int) -> None:
        k = len(self.plans) + 1
        sid = f"S{k}"
        arcs: list[Arc] = []
        chosen: set[str] = set()
        for pid in self._candidates(conn, day):
            if len(arcs) >= self.n_protagonists:
                break
            arc = self._arc(conn, f"{sid}-A{len(arcs) + 1}", pid, chosen)
            if arc is not None:
                arcs.append(arc)
                chosen |= {pid} | {b.target for b in arc.beats if b.type == "cast_role"}
                self.last_lead[pid] = k
        plan = SeasonPlan(sid, day, self.season_days, arcs, self.strategy)
        self.plans.append(plan)
        if self.plan_dir is not None:
            self.plan_dir.mkdir(parents=True, exist_ok=True)
            from contracts.base import to_dict
            (self.plan_dir / f"{sid}.json").write_text(json.dumps(to_dict(plan), ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")

    def _candidates(self, conn: sqlite3.Connection, day: int) -> list[str]:
        """Whoever has waited longest for a season, with the world's own say on who has a story in them (ties by a seeded order)."""
        from world.domains.romance import adult
        people = [p for p in _humans(conn) if adult(conn, p)]
        rng = make_rng(self.seed, day, "showrunner", "order")
        irony = lambda p: -((_ability(conn, p) or 0.0) - _crowd(conn, p))  # noqa: E731  (the most underrated first)
        return sorted(people, key=lambda p: (self.last_lead.get(p, 0), irony(p), rng.random()))

    def _arc(self, conn: sqlite3.Connection, arc_id: str, pid: str, taken: set[str]) -> Arc | None:
        from world.domains import factions as F
        from world.domains import romance as R
        if pid in taken:
            return None
        fid = F.faction_of(conn, pid)
        mates = [m for m in (F.members(conn, fid) if fid else []) if m != pid and m not in taken]
        skill = _ability(conn, pid)
        if skill is not None and skill >= 0.2 and mates and skill - _crowd(conn, pid) >= UNDERRATED:
            strong = max(mates, key=lambda m: ((_ability(conn, m) or 0.0), m))
            place = next((r[0] for r in conn.execute("SELECT id FROM locations WHERE tags LIKE '%\"training\"%' ORDER BY id")), "")
            beats = [Beat(0, "cast_role", strong, {"role": "doubter", "toward": pid, "until": f"+{self.season_days - 1}"}, "someone who looks down on them"),
                     Beat(1, "deliver_parcel", pid, {"object": "manual_secret"}, "a chance to get stronger in private"),
                     Beat(5, "announce_gathering", "", {"kind": "tournament", "place": place, "day": "+5"}, "the occasion where it could show")]
            return Arc(arc_id, "underdog", pid, beats, f"{pid} can do more than the others take them for")
        seat = conn.execute("SELECT seat_id, holder_id FROM seats WHERE faction_id = ? AND status = 'held' ORDER BY seat_id LIMIT 1", (fid,)).fetchone() if fid else None
        if seat is not None and seat["holder_id"] != pid and mates:
            rival = seat["holder_id"] if seat["holder_id"] in mates else mates[0]
            beats = [Beat(1, "open_seat", seat["seat_id"], {"day": "+7"}, "a place to fight for"),
                     Beat(2, "cast_role", rival, {"role": "rival", "toward": pid, "until": f"+{self.season_days - 3}"}, "someone to stand against")]
            return Arc(arc_id, "succession", pid, beats, f"{pid} could hold the seat")
        crush = conn.execute("SELECT target_id, attraction FROM relationships WHERE actor_id = ? AND attraction >= 0.25 ORDER BY attraction DESC, target_id LIMIT 1", (pid,)).fetchone()
        if crush is not None and not R.partners(conn, pid):
            others = [p for p in _humans(conn) if p not in (pid, crush[0]) and p not in taken and R.drawn_to(conn, p, crush[0])]
            if others:
                best = max(others, key=lambda p: (R.charm(conn, p), p))
                beats = [Beat(0, "cast_role", best, {"role": "suitor", "toward": crush[0], "until": f"+{self.season_days - 1}"}, "someone else who wants them")]
                return Arc(arc_id, "romance", pid, beats, f"{pid} is drawn to {crush[0]}")
        return None

    # -- acting --------------------------------------------------------------------------------------------------------
    def _act(self, conn: sqlite3.Connection, plan: SeasonPlan, arc: Arc, i: int, beat: Beat, day: int, now: int) -> None:
        allowed = STRATEGIES[self.strategy]
        if allowed is not None and beat.type not in allowed:
            return
        beat = self._aim(conn, beat, plan, arc, i)
        if beat is None:
            return
        params = {k: (str(day + int(v[1:])) if isinstance(v, str) and v.startswith("+") else v) for k, v in beat.params.items()}
        # the id is all the world is given of the proposal, so it says nothing of the season or the arc it belongs to
        opaque = "iv-" + hashlib.sha256(f"{self.seed}:{arc.arc_id}:{i}".encode()).hexdigest()[:10]
        prop = InterventionProposal(opaque, plan.season_id, arc.arc_id, beat.type, beat.target, params, day, COSTS[beat.type],
                                    beat.purpose, source="showrunner")
        self.ledger.admit(conn, prop, now)

    def _aim(self, conn: sqlite3.Connection, beat: Beat, plan: SeasonPlan, arc: Arc, i: int) -> Beat | None:
        """The control (`random`): the same kind of beat on the same day at the same cost, but aimed at nobody in particular."""
        if self.strategy != "random":
            return beat
        rng = make_rng(self.seed, plan.start_day + beat.day, f"{arc.arc_id}:{i}", "aim")
        people = _humans(conn)
        if beat.type == "cast_role":
            actor, toward = rng.sample(people, 2)
            return replace(beat, target=actor, params={**beat.params, "toward": toward})
        if beat.type == "deliver_parcel":
            return replace(beat, target=rng.choice(people))
        return beat  # a gathering or a vacancy has no one to aim at: the occasion itself is what it is

    def _close_finished(self, conn: sqlite3.Connection, day: int) -> None:
        """An arc is over when its hero has had their moment: no more is arranged for them."""
        if not self.plans:
            return
        plan = self.plans[-1]
        n = conn.execute("SELECT COUNT(*) FROM events WHERE type IN ('duel', 'confession', 'succession')").fetchone()[0]
        if n == self._checked:
            return  # nothing that could be a payoff has happened since the last look
        self._checked = n
        from narrative import payoff
        seen = {p["protagonist"] for p in payoff.payoffs(conn) if p["day"] >= plan.start_day}
        for arc in plan.arcs:
            if arc.protagonist in seen:
                self.closed.add(arc.arc_id)
