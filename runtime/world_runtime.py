"""World Runtime: plays the world's recorded events out in space and time, deterministically and read-only.

    rt = WorldRuntime(conn)            # reads the world's whole history once
    rt.state_at(revision)              # where everyone and everything is after that event (RuntimeSnapshot)
    rt.trace(event_ids)                # the movements and hand-offs that make those events happen (RuntimeTrace)
    rt.check()                         # disagreements with the world: must be []

The world decides *what* happens (a take moves the wallet into Ming's hands). The runtime decides only *how it
looks in space*: where Ming stood, the walk to the wallet, the reach, the moment of contact, which hand. Who holds
what is always read from the world's own deltas, so the runtime can never contradict it. Positions come from the
white-box layouts (narrative/layouts.py) and a seeded choice of spot (world/rng.py), so the same world, layouts and
runtime version always give the same state hash.
"""
from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass, field

from contracts.runtime import (RUNTIME_VERSION, RuntimeAction, RuntimeInteraction, RuntimeSnapshot, RuntimeTrace,
                               RuntimeTransform, stamp_snapshot, stamp_trace)
from narrative.layouts import LAYOUTS
from narrative.spatial import template_for
from world.rng import rng as make_rng

WALK = 1.2  # m/s
TROT = 1.6  # an animal
REACH = 0.6  # seconds to reach down and take hold
NEAR = 0.45  # how close you stand to a thing to pick it up
TALK = 1.0  # conversational distance
SOCIAL = ("talk", "tell", "confront", "accuse", "lend", "repay", "bark", "challenge", "duel")


@dataclass
class _Body:
    place: str = ""
    x: float = 0.0
    y: float = 0.0
    yaw: float = 0.0
    pose: str = "offstage"


@dataclass
class _Thing:
    holder: str = ""
    place: str = ""
    x: float = 0.0
    y: float = 0.0
    part: str = ""


@dataclass
class _Frame:
    """Everything after one event, frozen."""
    revision: int
    time: int
    bodies: dict[str, tuple] = field(default_factory=dict)
    things: dict[str, tuple] = field(default_factory=dict)


def _dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _yaw(a: tuple[float, float], b: tuple[float, float]) -> float:
    return round(math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])) % 360, 3)


class WorldRuntime:
    VERSION = RUNTIME_VERSION

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.seed = conn.execute("SELECT value FROM meta WHERE key = 'world_seed'").fetchone()[0]
        from world.ruleset import ruleset_hash
        self.ruleset = ruleset_hash()
        self.animals = {r[0] for r in conn.execute(
            "SELECT person_id FROM personas WHERE json_extract(traits, '$.species') IS NOT NULL "
            "AND json_extract(traits, '$.species') <> 'human'")}
        self.bodies: dict[str, _Body] = {}
        self.things: dict[str, _Thing] = {}
        self.frames: list[_Frame] = []
        self.actions: list[RuntimeAction] = []
        self.interactions: list[RuntimeInteraction] = []
        self.keys: list[tuple[float, RuntimeTransform]] = []
        self.world_holder: dict[int, dict[str, str]] = {}  # revision -> object -> holder, as the world records it
        self._start()
        self._play()

    # -- the first moment: everyone and everything as the world began ----------------------------------------------
    def _initial(self, etype: str, eid: str, fld: str, current):
        row = self.conn.execute("SELECT old_value FROM event_deltas WHERE entity_type = ? AND entity_id = ? AND "
                                "field = ? ORDER BY delta_id LIMIT 1", (etype, eid, fld)).fetchone()
        return row[0] if row else current

    def _start(self) -> None:
        for pid, loc, status in self.conn.execute("SELECT id, location_id, status FROM people ORDER BY id"):
            place = self._initial("person", pid, "location_id", loc) or ""
            st = self._initial("person", pid, "status", status)
            self.bodies[pid] = _Body()
            if place and st != "inactive":
                self._arrive(pid, place, 0, None, entering=False)
        for oid, owner, loc in self.conn.execute("SELECT id, owner_person_id, location_id FROM objects ORDER BY id"):
            holder = self._initial("object", oid, "owner_person_id", owner) or ""
            place = self._initial("object", oid, "location_id", loc) or ""
            t = _Thing(holder=holder, place="" if holder else place)
            if holder:
                t.part = "mouth" if holder in self.animals else "right"
            elif place:
                t.x, t.y = self._spot(place, oid, 0)
            self.things[oid] = t

    # -- positions --------------------------------------------------------------------------------------------------
    def _layout(self, place: str) -> dict:
        return LAYOUTS.get(template_for(place), LAYOUTS["cafe"])

    def _spot(self, place: str, who: str, event_id: int) -> tuple[float, float]:
        """A free place to stand, chosen by the world's seed, never where someone already is."""
        lay = self._layout(place)
        anchors = sorted(lay["anchors"].items())
        taken = [(b.x, b.y) for p, b in self.bodies.items() if b.place == place and p != who]
        free = [(n, a) for n, a in anchors if all(_dist((a[0], a[1]), t) > 0.7 for t in taken)] or anchors
        k = make_rng(self.seed, event_id, who, "runtime_spot").randrange(len(free))
        return round(free[k][1][0], 3), round(free[k][1][1], 3)

    def _door(self, place: str) -> tuple[float, float]:
        lay = self._layout(place)
        door = next((a for n, a in sorted(lay["anchors"].items()) if "door" in n), None)
        return (door[0], door[1]) if door else (0.5, 0.5)

    def _key(self, t: float, who: str) -> None:
        b = self.bodies[who]
        self.keys.append((round(t, 3), RuntimeTransform(who, b.place, round(b.x, 3), round(b.y, 3), round(b.yaw, 3),
                                                         b.pose)))

    def _thing_key(self, t: float, oid: str) -> None:
        th = self.things[oid]
        if th.holder:
            h = self.bodies[th.holder]
            tr = RuntimeTransform(oid, h.place, round(h.x, 3), round(h.y, 3), round(h.yaw, 3), "carried")
        else:
            tr = RuntimeTransform(oid, th.place, round(th.x, 3), round(th.y, 3), 0.0, "on_floor" if th.place else "offstage")
        self.keys.append((round(t, 3), tr))

    # -- moving bodies ----------------------------------------------------------------------------------------------
    def _walk(self, eid: int, who: str, to: tuple[float, float], t: float, why: str) -> float:
        b = self.bodies[who]
        frm = (b.x, b.y)
        d = _dist(frm, to)
        if d < 0.05:
            return t
        dur = round(d / (TROT if who in self.animals else WALK), 3)
        b.yaw = _yaw(frm, to)
        self.actions.append(RuntimeAction(eid, who, "walk_to", why, round(t, 3), round(t + dur, 3), b.place,
                                          [round(frm[0], 3), round(frm[1], 3)], [round(to[0], 3), round(to[1], 3)]))
        b.pose = "walk"
        self._key(t, who)
        b.x, b.y, b.pose = to[0], to[1], "stand"
        self._key(t + dur, who)
        return t + dur

    def _arrive(self, who: str, place: str, t: float, eid: int | None, entering: bool = True) -> float:
        b = self.bodies[who]
        b.place = place
        if entering and eid is not None:
            b.x, b.y = self._door(place)
            self.actions.append(RuntimeAction(eid, who, "enter", place, round(t, 3), round(t + 0.5, 3), place,
                                              [b.x, b.y], [b.x, b.y]))
            b.pose = "stand"
            return self._walk(eid, who, self._spot(place, who, eid), t + 0.5, "a place to be")
        b.x, b.y = self._spot(place, who, eid or 0)
        b.pose = "stand"
        self._key(t, who)
        return t

    def _leave(self, who: str, t: float, eid: int) -> float:
        b = self.bodies[who]
        if not b.place:
            return t
        t = self._walk(eid, who, self._door(b.place), t, "the way out")
        self.actions.append(RuntimeAction(eid, who, "exit", b.place, round(t, 3), round(t + 0.5, 3), b.place,
                                          [b.x, b.y], [b.x, b.y]))
        b.place, b.pose = "", "offstage"
        self._key(t + 0.5, who)
        return t + 0.5

    def _approach(self, eid: int, who: str, other: str, t: float) -> float:
        a, o = self.bodies[who], self.bodies[other]
        if not a.place or a.place != o.place:
            return t
        d = _dist((a.x, a.y), (o.x, o.y))
        if d > TALK + 0.3:
            k = (d - TALK) / d
            t = self._walk(eid, who, (a.x + (o.x - a.x) * k, a.y + (o.y - a.y) * k), t, other)
        a.yaw, o.yaw = _yaw((a.x, a.y), (o.x, o.y)), _yaw((o.x, o.y), (a.x, a.y))
        self.actions.append(RuntimeAction(eid, who, "face", other, round(t, 3), round(t + 0.4, 3), a.place))
        self._key(t, who)
        self._key(t, other)
        return t

    # -- one event --------------------------------------------------------------------------------------------------
    def _play(self) -> None:
        rows = self.conn.execute("SELECT event_id, timestamp, type, location_id, truth FROM events ORDER BY event_id").fetchall()
        deltas: dict[int, list] = {}
        for eid, etype, ent, fld, new in self.conn.execute(
                "SELECT event_id, entity_type, entity_id, field, new_value FROM event_deltas "
                "WHERE (entity_type = 'person' AND field IN ('location_id', 'status')) OR "
                "(entity_type = 'object' AND field IN ('owner_person_id', 'location_id')) ORDER BY delta_id"):
            deltas.setdefault(eid, []).append((etype, ent, fld, new))
        for eid, ts, etype, here, truth in rows:
            t = float(ts * 60)
            d = json.loads(truth)
            ch = deltas.get(eid, [])
            # people who come and go
            for etype_, ent, fld, new in ch:
                if etype_ == "person" and fld == "location_id" and ent in self.bodies:
                    if self.bodies[ent].place != (new or ""):
                        t2 = self._leave(ent, t, eid)
                        if new:
                            self._arrive(ent, new, t2, eid)
                elif etype_ == "person" and fld == "status" and ent in self.bodies:
                    if new == "inactive" and self.bodies[ent].place:
                        self._leave(ent, t, eid)
                    elif new != "inactive" and not self.bodies[ent].place:
                        loc = self.conn.execute("SELECT location_id FROM people WHERE id = ?", (ent,)).fetchone()[0]
                        after = next((n for e_, en, f_, n in ch if en == ent and f_ == "location_id"), None)
                        if after or loc:
                            self._arrive(ent, after or loc, t, eid)
            # things changing hands, as the world records them
            moves = {}
            for etype_, ent, fld, new in ch:
                if etype_ == "object" and ent in self.things:
                    moves.setdefault(ent, {})[fld] = new
            actor = d.get("actor")
            if etype in SOCIAL and actor in self.bodies:
                other = d.get("target") or d.get("victim")
                if other in self.bodies:
                    t = self._approach(eid, actor, other, t)
                    if etype == "duel":
                        for k in range(3):
                            self.interactions.append(RuntimeInteraction(eid, actor, "strike", other, t + k, t + k + 0.3,
                                                                        t + k + 0.6, "right"))
            for oid, m in sorted(moves.items()):
                self._hand_off(eid, oid, m, t, etype, actor, here)
            self.world_holder[eid] = {o: th.holder for o, th in self.things.items()}
            self.frames.append(_Frame(eid, ts,
                                      {p: (b.place, round(b.x, 3), round(b.y, 3), round(b.yaw, 3), b.pose)
                                       for p, b in self.bodies.items()},
                                      {o: (th.holder, th.part, th.place, round(th.x, 3), round(th.y, 3))
                                       for o, th in self.things.items()}))

    def _hand_off(self, eid: int, oid: str, m: dict, t: float, etype: str, actor: str | None, here: str | None) -> None:
        th = self.things[oid]
        old = th.holder
        new = m.get("owner_person_id", old) or ""
        if new == old:
            if "location_id" in m and not new:  # moved while on the floor (rare): it is simply there now
                th.place = m["location_id"] or ""
            return
        part = lambda who: "mouth" if who in self.animals else "right"  # noqa: E731
        if old and not new:  # dropped: it leaves the hand where the body stands
            b = self.bodies[old]
            start = t + 0.4
            self.interactions.append(RuntimeInteraction(eid, old, "drop", oid, start, start + 0.3, start + 0.6, part(old)))
            self.actions.append(RuntimeAction(eid, old, "detach", oid, start + 0.3, start + 0.3, b.place))
            ang = math.radians(b.yaw + 150)
            th.holder, th.part, th.place = "", "", m.get("location_id") or b.place or (here or "")
            th.x, th.y = round(b.x + 0.35 * math.cos(ang), 3), round(b.y + 0.35 * math.sin(ang), 3)
            self._thing_key(start + 0.6, oid)
            if etype == "misplace" and old in self.bodies and b.place:  # and they go on, unaware
                self._walk(eid, old, self._spot(b.place, old, eid + 1), start + 0.8, "going on")
            return
        if not old:  # picked up from where it lies
            b = self.bodies.get(new)
            if b is None:
                return
            t = self._walk(eid, new, (th.x + NEAR * math.cos(math.radians(th.x * 37 % 360)),
                                      th.y + NEAR * math.sin(math.radians(th.x * 37 % 360))), t, oid) if b.place == th.place else t
            b.yaw = _yaw((b.x, b.y), (th.x, th.y))
            self.actions.append(RuntimeAction(eid, new, "reach", oid, round(t, 3), round(t + REACH, 3), b.place))
            self.interactions.append(RuntimeInteraction(eid, new, "pickup", oid, round(t, 3), round(t + REACH * 0.8, 3),
                                                        round(t + REACH + 0.3, 3), part(new)))
            self.actions.append(RuntimeAction(eid, new, "attach", oid, round(t + REACH * 0.8, 3), round(t + REACH * 0.8, 3),
                                              b.place))
            th.holder, th.part, th.place = new, part(new), ""
            self._thing_key(t + REACH * 0.8, oid)
            return
        # from one body to another (given, stolen, won back)
        if old in self.bodies and new in self.bodies and self.bodies[old].place == self.bodies[new].place:
            t = self._approach(eid, new if etype == "steal" else old, old if etype == "steal" else new, t)
        kind = "grab" if etype == "steal" else "hand_over"
        self.interactions.append(RuntimeInteraction(eid, old, kind, oid, round(t, 3), round(t + 0.5, 3), round(t + 0.8, 3),
                                                    part(old)))
        self.interactions.append(RuntimeInteraction(eid, new, "receive", oid, round(t, 3), round(t + 0.5, 3),
                                                    round(t + 0.8, 3), part(new)))
        self.actions.append(RuntimeAction(eid, old, "detach", oid, round(t + 0.5, 3), round(t + 0.5, 3),
                                          self.bodies[old].place if old in self.bodies else ""))
        self.actions.append(RuntimeAction(eid, new, "attach", oid, round(t + 0.5, 3), round(t + 0.5, 3),
                                          self.bodies[new].place if new in self.bodies else ""))
        th.holder, th.part, th.place = new, part(new), ""
        self._thing_key(t + 0.5, oid)

    # -- reading it -------------------------------------------------------------------------------------------------
    def _frame(self, revision: int) -> _Frame | None:
        lo, hi, best = 0, len(self.frames) - 1, None
        while lo <= hi:  # the last frame at or before the revision
            mid = (lo + hi) // 2
            if self.frames[mid].revision <= revision:
                best, lo = self.frames[mid], mid + 1
            else:
                hi = mid - 1
        return best

    def state_at(self, revision: int) -> RuntimeSnapshot:
        f = self._frame(revision)
        if f is None:
            raise ValueError(f"no event at or before revision {revision}")
        transforms = [RuntimeTransform(p, *v) for p, v in sorted(f.bodies.items())]
        for o, (holder, part, place, x, y) in sorted(f.things.items()):
            if holder:
                hb = f.bodies[holder]
                transforms.append(RuntimeTransform(o, hb[0], hb[1], hb[2], hb[3], "carried"))
            else:
                transforms.append(RuntimeTransform(o, place, x, y, 0.0, "on_floor" if place else "offstage"))
        return stamp_snapshot(RuntimeSnapshot(
            self.VERSION, f.revision, f.time, self.ruleset, transforms,
            {o: v[0] for o, v in sorted(f.things.items())}, {o: v[1] for o, v in sorted(f.things.items())}))

    def trace(self, event_ids: list[int]) -> RuntimeTrace:
        ids = set(event_ids)
        times = [a.start for a in self.actions if a.event_id in ids] + [i.start for i in self.interactions if i.event_id in ids]
        lo = min(times) if times else 0.0
        hi = max([a.end for a in self.actions if a.event_id in ids] +
                 [i.complete for i in self.interactions if i.event_id in ids] or [0.0])
        before = self.state_at(min(ids) - 1) if ids and self._frame(min(ids) - 1) is not None else None
        return stamp_trace(RuntimeTrace(
            self.VERSION, sorted(ids), [a for a in self.actions if a.event_id in ids],
            [i for i in self.interactions if i.event_id in ids],
            [(t, k) for t, k in self.keys if lo <= t <= hi],
            before.transforms if before else [], dict(before.holders) if before else {}))

    def check(self) -> list[str]:
        """Every disagreement between the runtime and the world: who holds what after each event, and who is where."""
        out = []
        holders = {o: h for o, h in self.conn.execute("SELECT id, owner_person_id FROM objects")}
        last = self.frames[-1] if self.frames else None
        if last is not None:
            for o, (holder, *_rest) in last.things.items():
                if (holders.get(o) or "") != holder:
                    out.append(f"{o}: runtime says {holder!r}, world says {holders.get(o)!r}")
            for p, place, status in self.conn.execute("SELECT id, location_id, status FROM people"):
                if status != "inactive" and (place or "") != last.bodies[p][0]:
                    out.append(f"{p}: runtime at {last.bodies[p][0]!r}, world at {place!r}")
        for i in self.interactions:  # every hand-off has an event of the world behind it
            if not self.conn.execute("SELECT 1 FROM events WHERE event_id = ?", (i.event_id,)).fetchone():
                out.append(f"interaction without an event: {i}")
        return out
