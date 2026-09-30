"""World Runtime: plays the world's recorded events out in space and time, deterministically and read-only.

    rt = WorldRuntime(conn)            # reads the world's whole history
    rt.advance()                       # plays whatever the world has recorded since (a simulation can run it along)
    rt.state_at(revision)              # where everyone and everything is after that event (RuntimeSnapshot)
    rt.trace(event_ids)                # the movements and hand-offs that make those events happen (RuntimeTrace)
    rt.position(who, t)                # where a body is at world second t, by the rule every engine plays
    rt.check()                         # disagreements with the world: must be []

The world decides *what* happens (a take moves the wallet into Ming's hands). The runtime decides only *how it
happens in space*: where Ming stood, the path to the wallet around the bench, the turn, the reach, the moment of
contact, which hand, every footfall. Who holds what is always read from the world's own deltas, so the runtime can
never contradict it.

Runtime 0.2 (after measuring 0.1 with runtime/physics.py: 63 jumps, 86 snap turns, 52 walks through furniture,
45 bodies inside each other):
- every body has its own clock, so two events in the same minute never make it do two things at once;
- walks go around every blocking box and every standing body (runtime/nav.py), and nobody is placed on top of
  anybody else or on a table;
- a body turns before it walks off, stands up before it leaves a seat and sits down when it reaches one;
- a thing is targeted, reached for (an animal sniffs first), touched, lifted to the hand or mouth, and falls when it
  is let go: it is never in two places (RuntimeActionTrack);
- people's feet are planted (RuntimeStep), so a presentation's feet cannot skate.
"""
from __future__ import annotations

import json
import math
import sqlite3
from bisect import bisect_right
from dataclasses import dataclass, field

from contracts.runtime import (RUNTIME_VERSION, RuntimeAction, RuntimeActionTrack, RuntimeInteraction,
                               RuntimeSnapshot, RuntimeStep, RuntimeTrace, RuntimeTransform, stamp_snapshot, stamp_trace)
from narrative.layouts import LAYOUTS
from narrative.spatial import template_for
from runtime.nav import grid
from runtime.scheduler import ActionScheduler
from world.rng import rng as make_rng

WALK = 1.2  # m/s
TROT = 1.6  # an animal
REACH = 0.6  # seconds from the start of the reach to contact
LIFT = 0.35  # contact -> attached
FALL = 0.3  # let go -> on the floor
SNIFF = 0.6  # an animal's nose goes down before its mouth does
RISE = SETTLE = 0.6  # standing up from a seat, sitting down on one
NEAR = 0.4  # how close you stand to a thing to pick it up
TALK = 1.0  # conversational distance
STEP = 0.65  # a walking person's step length
FOOT = 0.1  # a foot's distance from the body's centre line
CLEAR = 0.7  # nobody is placed closer than this to somebody else
TRIES = 120  # a walk waits up to a minute (in half seconds) for a way that passes nobody
SOCIAL = ("talk", "tell", "confront", "accuse", "lend", "repay", "bark", "challenge", "duel")
MOVING = ("walk", "turn", "rise", "settle", "lift", "fall")  # poses that change something before the next key


def turn_time(deg: float) -> float:
    return round(0.12 + abs(deg) / 360.0 * 0.6, 3)


def yaw_diff(a: float, b: float) -> float:
    return (b - a + 540.0) % 360.0 - 180.0


@dataclass
class _Body:
    place: str = ""
    x: float = 0.0
    y: float = 0.0
    yaw: float = 0.0
    pose: str = "offstage"  # the resting pose: stand | sit | offstage
    busy: float = 0.0  # world second from which this body is free to do the next thing


@dataclass
class _Thing:
    holder: str = ""
    place: str = ""
    x: float = 0.0
    y: float = 0.0
    part: str = ""
    busy: float = 0.0


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
        self.bodies: dict[str, _Body] = {}
        self.things: dict[str, _Thing] = {}
        self.frames: list[_Frame] = []
        self.actions: list[RuntimeAction] = []
        self.interactions: list[RuntimeInteraction] = []
        self.tracks: list[RuntimeActionTrack] = []
        self.steps: list[RuntimeStep] = []
        self.keys: list[tuple[float, RuntimeTransform]] = []
        self.by_entity: dict[str, list[tuple[float, RuntimeTransform]]] = {}
        self._times: dict[str, list[float]] = {}
        self.world_holder: dict[int, dict[str, str]] = {}  # revision -> object -> holder, as the world records it
        self.last_event = 0
        self.doorway: dict[str, float] = {}  # place -> when its door is clear again (one body through at a time)
        self.sched = ActionScheduler()  # every body's move / hands / voice, never double-booked
        self._eid = 0
        self._start()
        self.advance()

    @property
    def animals(self) -> set[str]:
        return {r[0] for r in self.conn.execute(
            "SELECT person_id FROM personas WHERE json_extract(traits, '$.species') IS NOT NULL "
            "AND json_extract(traits, '$.species') <> 'human'")}

    # -- the first moment: everyone and everything as the world began ----------------------------------------------
    def _initial(self, etype: str, eid: str, fld: str, current):
        row = self.conn.execute("SELECT old_value FROM event_deltas WHERE entity_type = ? AND entity_id = ? AND "
                                "field = ? ORDER BY delta_id LIMIT 1", (etype, eid, fld)).fetchone()
        return row[0] if row else current

    def _start(self) -> None:
        self._animals = self.animals
        for pid, loc, status in self.conn.execute("SELECT id, location_id, status FROM people ORDER BY id"):
            place = self._initial("person", pid, "location_id", loc) or ""
            st = self._initial("person", pid, "status", status)
            self.bodies[pid] = _Body()
            if place and st != "inactive":
                self._arrive(pid, place, 0.0, None, entering=False)
        for oid, owner, loc in self.conn.execute("SELECT id, owner_person_id, location_id FROM objects ORDER BY id"):
            holder = self._initial("object", oid, "owner_person_id", owner) or ""
            place = self._initial("object", oid, "location_id", loc) or ""
            t = _Thing(holder=holder, place="" if holder else place)
            if holder:
                t.part = self._part(holder)
            elif place:
                t.x, t.y = self._floor_spot(place, oid, 0)
            self.things[oid] = t
            self._thing_key(0.0, oid)

    def _part(self, who: str) -> str:
        return "mouth" if who in self._animals else "right"

    def _book(self, who: str, resources: tuple[str, ...], start: float, end: float, kind: str) -> None:
        """Reserve a body's (or a thing's) resources; overlapping an earlier booking is a bug and raises."""
        self.sched.book(who, resources, start, end, kind, self._eid)
        if "move" in resources and who in self.bodies:
            self.bodies[who].busy = max(self.bodies[who].busy, end)
        elif who in self.things:
            self.things[who].busy = max(self.things[who].busy, end)

    def _free(self, who: str, *resources: str) -> float:
        return self.sched.free(who, *resources)

    # -- positions --------------------------------------------------------------------------------------------------
    def _layout(self, place: str) -> dict:
        return LAYOUTS.get(template_for(place), LAYOUTS["cafe"])

    def _grid(self, place: str):
        return grid(template_for(place) if template_for(place) in LAYOUTS else "cafe")

    def _others(self, place: str, *exclude: str, at: float | None = None) -> tuple:
        """Where the other bodies in a place are: where they will stand, and (given a time) where they are then."""
        out = []
        for p, b in sorted(self.bodies.items()):
            if p in exclude:
                continue
            if b.place == place and b.pose != "offstage":
                out.append((round(b.x, 3), round(b.y, 3)))
            if at is not None:  # and where they are at that moment, even if they end up elsewhere
                now = self.position(p, at)
                if now and now[0] == place and now[4] != "offstage" and                         all(_dist((now[1], now[2]), o) > 0.05 for o in out):
                    out.append((round(now[1], 3), round(now[2], 3)))
        return tuple(out)

    def _spots(self, place: str) -> list[tuple[str, float, float, float, str]]:
        """Where one can be in a place: its seats and standing spots, never a table top, a perch or the street."""
        lay = self._layout(place)
        out = []
        for n, (x, y, yaw) in sorted(lay["anchors"].items()):
            seat = "seat" in n or "sofa" in n
            if seat or (n in lay.get("stand", []) and "door" not in n):
                out.append((n, x, y, self._facing(lay, n, x, y) if seat else yaw, "sit" if seat else "stand"))
        return out

    @staticmethod
    def _facing(lay: dict, name: str, x: float, y: float) -> float:
        """Which way one sits: at a table, towards it; on a bench or a sofa, away from its back."""
        base = name.rsplit(".seat", 1)[0] if ".seat" in name else name.rsplit("_", 1)[0]
        o = next((o for o in lay["objects"] if o.id == base), None)
        if o is None:
            return 0.0
        if o.kind in ("table", "desk"):
            return _yaw((x, y), (o.position[0], o.position[1]))
        return _yaw((o.position[0], o.position[1]), (x, y)) if abs(y - o.position[1]) < 1e-6 else             (90.0 if y > o.position[1] else 270.0)

    def _spot(self, place: str, who: str, event_id: int) -> tuple[float, float, float, str]:
        """A free place to be, chosen by the world's seed: a seat or a spot nobody is at, else open floor nobody is
        near. An animal does not take a seat."""
        taken = self._others(place, who)
        g = self._grid(place)
        pick = make_rng(self.seed, event_id, who, "runtime_spot")
        free = [s for s in self._spots(place) if all(_dist((s[1], s[2]), o) > CLEAR for o in taken)
                and not (who in self._animals and s[4] == "sit")]
        if free:
            n, x, y, yaw, pose = free[pick.randrange(len(free))]
            return round(x, 3), round(y, 3), yaw, pose if who not in self._animals else "stand"
        cells = [(i, j) for j in range(g.ny) for i in range(g.nx)]
        pick.shuffle(cells)  # a crowded place: somewhere on the open floor, as far from the walls as it can be
        for clear in (CLEAR, 0.55):
            for i, j in cells:
                x, y = g.centre(i, j)
                if g.free(x, y) and all(_dist((x, y), o) > clear for o in taken) and self._inside(place, x, y):
                    return round(x, 3), round(y, 3), float(pick.randrange(8) * 45), "stand"
        n, x, y, yaw, _pose = self._spots(place)[0]
        return round(x, 3), round(y, 3), yaw, "stand"

    def _residents(self, place: str) -> list[str]:
        """Who lives here (sorted), from the world's own notion of home."""
        if not hasattr(self, "_homes"):
            from world.content import home_of
            self._homes = {p: home_of(self.conn, p) for p, in self.conn.execute("SELECT id FROM people ORDER BY id")}
        return [p for p, h in sorted(self._homes.items()) if h == place]

    def _bed(self, place: str, who: str) -> tuple[float, float, float, str] | None:
        """Where someone sleeps at home: residents in order take a bed, then the sofa, then chairs; an animal its
        own spot. None if this is not their home, or their place is taken."""
        lay = self._layout(place)
        slots = lay.get("animal_sleep" if who in self._animals else "sleep")
        people = [p for p in self._residents(place) if (p in self._animals) == (who in self._animals)]
        if not slots or who not in people:
            return None
        name = slots[people.index(who) % len(slots)]
        x, y, yaw = lay["anchors"][name]
        spot = next(sp for sp in self._spots(place) + [(name, x, y, yaw, "stand")] if sp[0] == name)
        taken = self._others(place, who)
        if any(_dist((spot[1], spot[2]), o) < 0.3 for o in taken):
            return None
        return round(spot[1], 3), round(spot[2], 3), spot[3], spot[4] if who not in self._animals else "stand"

    @staticmethod
    def _night(ts: int) -> bool:
        m = ts % 1440
        return m >= 22 * 60 or m < 6 * 60

    def _inside(self, place: str, x: float, y: float) -> bool:
        """Within the walls of a room (an open place has no walls)."""
        walls = [o for o in self._layout(place)["objects"] if o.kind == "wall"]
        if not walls:
            return True
        return (min(o.position[0] for o in walls) < x < max(o.position[0] for o in walls)
                and min(o.position[1] for o in walls) < y < max(o.position[1] for o in walls))

    def _floor_spot(self, place: str, oid: str, event_id: int, near: tuple[float, float] | None = None,
                    yaw: float = 0.0) -> tuple[float, float]:
        """Where a thing lies: behind whoever let it go, or a seeded spot; never inside a bench, a table or a tree."""
        g = self._grid(place)
        if near is None:
            spots = self._spots(place)
            s = spots[make_rng(self.seed, event_id, oid, "runtime_floor").randrange(len(spots))]
            near, yaw = (s[1], s[2]), s[3]
        for off in (150, 210, 180, 120, 240, 90, 270, 60, 300, 0):
            a = math.radians(yaw + off)
            x, y = round(near[0] + 0.35 * math.cos(a), 3), round(near[1] + 0.35 * math.sin(a), 3)
            if not g.inside_solid(x, y, 0.08) and self._inside(place, x, y):
                return x, y
        return round(near[0], 3), round(near[1], 3)

    def _door(self, place: str) -> tuple[float, float]:
        lay = self._layout(place)
        door = next((a for n, a in sorted(lay["anchors"].items()) if "door" in n), None)
        return (door[0], door[1]) if door else (0.5, 0.5)

    # -- keys -------------------------------------------------------------------------------------------------------
    def _add(self, t: float, tr: RuntimeTransform) -> None:
        t = round(t, 3)
        self.keys.append((t, tr))
        ks, ts = self.by_entity.setdefault(tr.entity, []), self._times.setdefault(tr.entity, [])
        if ts and t < ts[-1]:  # never earlier than what this entity already does (every body has one clock)
            raise AssertionError(f"{tr.entity}: key at {t} before {ts[-1]}")
        ks.append((t, tr))
        ts.append(t)

    def _key(self, t: float, who: str, pose: str | None = None) -> None:
        b = self.bodies[who]
        self._add(t, RuntimeTransform(who, b.place, round(b.x, 3), round(b.y, 3), round(b.yaw % 360, 3),
                                      pose or b.pose))

    def _thing_key(self, t: float, oid: str, pose: str | None = None, at: tuple[float, float] | None = None) -> None:
        th = self.things[oid]
        if th.holder and pose is None:
            h = self.bodies[th.holder]
            tr = RuntimeTransform(oid, h.place, round(h.x, 3), round(h.y, 3), round(h.yaw % 360, 3), "carried",
                                  th.holder)
        elif pose is not None:
            x, y = at if at is not None else (th.x, th.y)
            place = th.place or (self.bodies[th.holder].place if th.holder else "")
            tr = RuntimeTransform(oid, place, round(x, 3), round(y, 3), 0.0, pose, th.holder if pose == "lift" else "")
        else:
            tr = RuntimeTransform(oid, th.place, round(th.x, 3), round(th.y, 3), 0.0,
                                  "on_floor" if th.place else "offstage")
        self._add(t, tr)

    # -- moving bodies ----------------------------------------------------------------------------------------------
    def _turn(self, who: str, yaw: float, t: float) -> float:
        """Turn the body to face `yaw`. Seated, one turns one's head, not the chair (the performance does that)."""
        b = self.bodies[who]
        if b.pose == "sit":
            return t
        d = yaw_diff(b.yaw, yaw)
        if abs(d) < 1.0:  # not worth turning for, and never snapped: the body keeps the yaw it has
            return t
        t = max(t, self._free(who, "move"))
        self._key(t, who, "turn")
        b.yaw = yaw % 360
        dur = turn_time(d)
        self._key(t + dur, who)
        self._book(who, ("move",), t, t + dur, "turn")
        return t + dur

    def _rise(self, who: str, t: float, toward: tuple[float, float] | None = None) -> float:
        """Up from a seat and one step out of it, onto open floor."""
        b = self.bodies[who]
        if b.pose != "sit":
            return t
        t = max(t, self._free(who, "move"))
        speed = TROT if who in self._animals else WALK
        for _wait in range(12):  # standing up into somebody's way: stay seated until they have passed
            out = self._grid(b.place).nearest_free((b.x, b.y), self._others(b.place, who, at=t), prefer=toward)
            if self._conflict(who, b.place, [out, out], t + RISE, speed, hold=1.0) is None:
                break
            t += 0.5
        self._key(t, who, "rise")
        b.yaw = _yaw((b.x, b.y), out) if _dist((b.x, b.y), out) > 0.05 else b.yaw
        b.x, b.y, b.pose = out[0], out[1], "stand"
        self._key(t + RISE, who)
        self._book(who, ("move",), t, t + RISE, "rise")
        return t + RISE

    def _walk(self, eid: int, who: str, to: tuple[float, float], t: float, why: str, end: str = "stand",
              end_yaw: float | None = None, avoid: tuple = (), hold: float | None = None) -> float:
        b = self.bodies[who]
        t = max(t, b.busy, self._free(who, "move"))
        frm = (round(b.x, 3), round(b.y, 3))
        to = (round(to[0], 3), round(to[1], 3))
        if _dist(frm, to) < 0.05:
            if end == "sit" and b.pose != "sit":
                self._key(t, who, "settle")
                b.yaw, b.pose = (end_yaw if end_yaw is not None else b.yaw) % 360, "sit"
                self._book(who, ("move",), t, t + SETTLE, "settle")
                t += SETTLE
                self._key(t, who)
            elif end_yaw is not None:
                t = self._turn(who, end_yaw, t)
            b.busy = t
            return t
        t = self._rise(who, t, toward=to)
        frm = (round(b.x, 3), round(b.y, 3))
        seat = to if end == "sit" else None
        if seat is not None:  # walk to the floor in front of the seat, then sit down into it
            fy = math.radians(end_yaw if end_yaw is not None else b.yaw)
            front = (seat[0] + 0.5 * math.cos(fy), seat[1] + 0.5 * math.sin(fy))
            to = self._grid(b.place).nearest_free(front, self._others(b.place, who, *avoid, at=t), prefer=frm)
        speed = TROT if who in self._animals else WALK
        pts, t = self._plan(eid, who, frm, to, t, speed, avoid, hold)
        if _dist(tuple(pts[-1]), to) > 0.05:  # stopped short of a crowd: stand there, sit nowhere
            to, end, seat = (round(pts[-1][0], 3), round(pts[-1][1], 3)), "stand", None
            if _dist(frm, to) < 0.05:
                if end_yaw is not None:
                    t = self._turn(who, end_yaw, t)
                b.busy = max(b.busy, t)
                return t
        t = self._turn(who, _yaw(pts[0], pts[1]), t)
        t0 = t
        pts = [q for k, q in enumerate(pts) if k in (0, len(pts) - 1) or _dist(q, pts[k - 1]) >= 0.05]
        pts = self._no_slivers(b.place, pts, speed, self._others(b.place, who, *avoid, at=t))
        if len(pts) > 2 and _dist(pts[-2], pts[-1]) < 0.25 and \
                abs(yaw_diff(_yaw(pts[-3], pts[-2]), _yaw(pts[-2], pts[-1]))) > 45:
            pts = pts[:-1]  # a last step of a few centimetres round a sharp corner: stop at the corner instead
            to = (round(pts[-1][0], 3), round(pts[-1][1], 3))
        for a, c in zip(pts, pts[1:]):
            if _dist(a, c) < 1e-3:
                continue
            b.x, b.y, b.yaw = a[0], a[1], _yaw(a, c)
            self._key(t, who, "walk")
            t += _dist(a, c) / speed
        b.x, b.y = to
        self._book(who, ("move",), t0, t, "walk")
        self.actions.append(RuntimeAction(eid, who, "walk_to", why, round(t0, 3), round(t, 3), b.place,
                                          list(frm), list(seat or to), [list(p) for p in pts]))
        if who not in self._animals and t > t0:
            self._footsteps(who, b.place, pts, t0, t)
        if end == "sit":
            self._key(t, who, "settle")
            settle = max(SETTLE, _dist((b.x, b.y), seat) / 0.8)  # a crowded room leaves one further off: shuffle in
            b.x, b.y = seat
            b.yaw, b.pose = (end_yaw if end_yaw is not None else b.yaw) % 360, "sit"
            self._book(who, ("move",), t, t + settle, "settle")
            t += settle
            self._key(t, who)
        else:
            b.pose = "stand"
            self._key(t, who)
            if end_yaw is not None:
                t = self._turn(who, end_yaw, t)
        b.busy = t
        return t

    def _plan(self, eid: int, who: str, frm, to, t: float, speed: float, avoid: tuple = (),
              hold: float | None = None) -> tuple[list, float]:
        """A path and a start time that pass nobody: the path round standing bodies first; if somebody already on
        their way would meet it, a detour round where they will be; if nothing clears, wait for them to pass.
        Earlier plans have right of way: a later walk never changes one already made."""
        b = self.bodies[who]
        g = self._grid(b.place)
        pts = g.path(frm, to, self._others(b.place, who, *avoid, at=t)) if _dist(frm, to) >= 0.05 else [frm, to]
        start = t
        through = g.through_people if _dist(frm, to) >= 0.05 else False
        for _try in range(TRIES):
            if _try:  # after waiting, the way is planned again for who is where now
                pts = g.path(frm, to, self._others(b.place, who, *avoid, at=t)) if _dist(frm, to) >= 0.05 else [frm, to]
                through = g.through_people if _dist(frm, to) >= 0.05 else False
            if through and _try < TRIES - 1:  # the only way is through somebody: wait for them to move
                t += 0.5
                continue
            if through:  # waited a minute and they are still in the way: go as far as the edge of them, no further
                pts = g.clear_prefix(pts, self._others(b.place, who, *avoid, at=t))
                if len(pts) < 2 or _dist(pts[0], pts[-1]) < 0.05:
                    pts = [frm, frm]
                self.actions.append(RuntimeAction(eid, who, "stop_short", "", round(t, 3), round(t, 3), b.place))
            lead = turn_time(yaw_diff(b.yaw, _yaw(pts[0], pts[1]))) if len(pts) > 1 and pts[0] != pts[1] else 0.0
            hit = self._conflict(who, b.place, pts, t + lead, speed, waiting_at=frm, since=start, hold=hold)
            if hit is None:
                if t > start:
                    self.actions.append(RuntimeAction(eid, who, "yield", hit or "", round(start, 3), round(t, 3), b.place))
                return pts, t
            if _try >= 3:  # a detour is tried at first; after that one waits for them to pass
                t += 0.5
                continue
            # a detour round everybody's positions while this walk would be under way
            moving = self._moving_points(who, b.place, t, t + lead + sum(_dist(a, c) for a, c in zip(pts, pts[1:])) / speed + 1.0)
            detour = g.path(frm, to, self._others(b.place, who, *avoid, at=t) + moving)
            if detour != pts and self._conflict(who, b.place, detour, t + lead, speed, waiting_at=frm, since=start,
                                                hold=hold) is None:
                self.actions.append(RuntimeAction(eid, who, "detour", hit, round(t, 3), round(t, 3), b.place))
                return detour, t
            t += 0.5  # let them pass
        return pts, t

    def _no_slivers(self, place: str, pts: list, speed: float, others: tuple = ()) -> list:
        """Drop a waypoint whose next leg is too short to finish turning onto (the heading would never catch up),
        where the straight line past it is clear."""
        g = self._grid(place)
        out = list(pts)
        k = 1
        while k < len(out) - 1:
            turn = abs(yaw_diff(_yaw(out[k - 1], out[k]), _yaw(out[k], out[k + 1])))
            need = max(0.25, turn / 450.0) * speed
            if _dist(out[k], out[k + 1]) < need and g.line(out[k - 1], out[k + 1]) and \
                    not g.crosses_solid(out[k - 1], out[k + 1]) and \
                    g.clear_of(out[:k] + out[k + 1:], others):  # never cut a corner through somebody
                del out[k]
                continue
            k += 1
        return out

    def _moving_points(self, who: str, place: str, t0: float, t1: float) -> tuple:
        """Where every other body in the place will be, every 0.2 s from t0 to t1, as keyed now."""
        out = []
        for p in sorted(self.bodies):
            if p == who or p not in self._times:
                continue
            k = t0
            while k <= t1:
                q = self.position(p, k)
                if q and q[0] == place and q[4] != "offstage":
                    out.append((round(q[1], 2), round(q[2], 2)))
                k += 0.2
        return tuple(dict.fromkeys(out))

    def _conflict(self, who: str, place: str, pts: list, t0: float, speed: float, waiting_at=None,
                  since: float | None = None, hold: float | None = None) -> str | None:
        """Who this walk would meet, as everybody else is already keyed to move: along the walk (every 0.05 s),
        while waiting at its start, and while standing at its end until the last move anybody has planned."""
        # everybody with keys: where they are *at each moment* decides, not where they will end up (a body that has
        # already left in a later key is still in the doorway now)
        others = [p for p in self.bodies if p != who and p in self._times]
        if not others:
            return None
        lengths = [_dist(a, c) for a, c in zip(pts, pts[1:])]
        total = sum(lengths)
        t1 = t0 + total / speed

        def at(s: float):
            for (a, c), L in zip(zip(pts, pts[1:]), lengths):
                if s <= L:
                    f = s / L if L else 0.0
                    return a[0] + (c[0] - a[0]) * f, a[1] + (c[1] - a[1]) * f
                s -= L
            return pts[-1]

        checks = []
        if waiting_at is not None and since is not None and t0 > since:  # standing where one waits
            k = since
            while k < t0:
                checks.append((k, waiting_at))
                k += 0.1
        n = max(2, int((t1 - t0) / 0.05) + 1)
        checks += [(t0 + (t1 - t0) * m / n, at(total * m / n)) for m in range(n + 1)]
        for tt, (x, y) in checks:
            for p in others:
                q = self.position(p, tt)
                if q and q[0] == place and q[4] != "offstage" and _dist((x, y), (q[1], q[2])) < 0.45:
                    return p
        gx, gy = pts[-1]
        until = t1 + hold if hold is not None else float("inf")  # an exit stands in the doorway only a moment
        for p in others:  # standing at the end while everybody's planned moves play out
            ts, ks = self._times[p], self.by_entity[p]
            i = max(0, bisect_right(ts, t1) - 1)
            for j in range(i, len(ks)):
                ta, a = ks[j]
                if ta > until:
                    break
                if a.place != place or a.pose == "offstage":
                    continue
                tb = ks[j + 1][0] if j + 1 < len(ks) else ta
                if a.pose in MOVING and tb > ta:
                    k = max(ta, t1)
                    while k <= min(tb, until):
                        q = self.position(p, k)
                        if q and q[0] == place and _dist((gx, gy), (q[1], q[2])) < 0.45:
                            return p
                        k += 0.1
                elif _dist((gx, gy), (a.x, a.y)) < 0.45 and tb >= t1:
                    return p
        return None

    def _footsteps(self, who: str, place: str, pts: list, t0: float, t1: float) -> None:
        """Footfalls along a walk. Even steps end exactly at the goal; a foot lands when the body is half a step
        short of its mark and lifts when the body is 0.7 of a step past it; the trailing foot joins the leading
        one where the body stops. Both feet stand where the walk starts until they first lift."""
        lengths = [_dist(a, c) for a, c in zip(pts, pts[1:])]
        total = sum(lengths)
        if total <= 0 or t1 <= t0:
            return

        def at(s: float) -> tuple[float, float, float]:
            s = max(0.0, min(total, s))
            for (a, c), L in zip(zip(pts, pts[1:]), lengths):
                if s <= L + 1e-9:
                    f = s / L if L else 0.0
                    return a[0] + (c[0] - a[0]) * f, a[1] + (c[1] - a[1]) * f, math.atan2(c[1] - a[1], c[0] - a[0])
                s -= L
            a, c = pts[-2], pts[-1]
            return c[0], c[1], math.atan2(c[1] - a[1], c[0] - a[0])

        def when(s: float) -> float:
            return round(t0 + (t1 - t0) * max(0.0, min(total, s)) / total, 3)

        def plant(foot: str, s: float, land: float, lift: float) -> None:
            x, y, h = at(s)
            side = 1 if foot == "R" else -1  # the body's right, seen from above with y into the room
            self.steps.append(RuntimeStep(who, foot, round(land, 3), round(max(land, lift), 3), place,
                                          round(x + side * FOOT * math.sin(h), 3), round(y - side * FOOT * math.cos(h), 3)))

        n = max(1, round(total / STEP))
        L = total / n
        plant("R", 0.0, t0, t0)
        plant("L", 0.0, t0, when(0.7 * L))
        last_lift = {"R": t0, "L": when(0.7 * L)}
        for k in range(n):
            foot = "R" if k % 2 == 0 else "L"
            s = (k + 1) * L
            land = max(when(s - 0.5 * L), last_lift[foot] + 0.05)
            lift = t1 if k == n - 1 else when(s + 0.7 * L)
            plant(foot, s, land, lift)
            last_lift[foot] = lift
        join = "L" if (n - 1) % 2 == 0 else "R"
        plant(join, total, max(t1 - 0.05, last_lift[join] + 0.05), t1)

    def _arrive(self, who: str, place: str, t: float, eid: int | None, entering: bool = True,
                night: bool = False) -> float:
        b = self.bodies[who]
        b.place = place
        x, y, yaw, pose = (night and self._bed(place, who)) or self._spot(place, who, eid or 0)
        if entering and eid is not None:
            t = max(t, self.doorway.get(place, 0.0))
            door = self._door(place)
            speed = TROT if who in self._animals else WALK
            g = self._grid(place)
            for _wait in range(TRIES):  # someone is in the doorway, or the way in: wait outside, offstage
                if self._conflict(who, place, [door, door], t, speed, hold=1.0) is None:
                    g.path(door, (x, y), self._others(place, who, at=t))
                    if not g.through_people:
                        break
                t += 0.5
            self.doorway[place] = t + 1.0
            b.x, b.y = door
            b.pose = "stand"
            self._key(t, who)
            self.actions.append(RuntimeAction(eid, who, "enter", place, round(t, 3), round(t + 0.2, 3), place,
                                              [b.x, b.y], [b.x, b.y]))
            b.busy = t
            return self._walk(eid, who, (x, y), t, "a place to be", end=pose, end_yaw=yaw)
        b.x, b.y, b.yaw, b.pose = x, y, yaw, pose
        self._key(t, who)
        return t

    def _leave(self, who: str, t: float, eid: int) -> float:
        b = self.bodies[who]
        if not b.place:
            return t
        t = self._walk(eid, who, self._door(b.place), t, "the way out", hold=0.2)
        self.actions.append(RuntimeAction(eid, who, "exit", b.place, round(t, 3), round(t + 0.1, 3), b.place,
                                          [b.x, b.y], [b.x, b.y]))
        self._book(who, ("move",), t, t + 0.1, "exit")
        b.place, b.pose = "", "offstage"
        self._key(t + 0.1, who)  # through the door, not standing in it
        b.busy = t + 0.1
        return t + 0.1

    def _approach(self, eid: int, who: str, other: str, t: float) -> float:
        a, o = self.bodies[who], self.bodies[other]
        if not a.place or a.place != o.place:
            return t
        t = max(t, a.busy, o.busy)
        d = _dist((a.x, a.y), (o.x, o.y))
        if d > TALK + 0.3:
            k = (d - TALK) / d
            goal = (a.x + (o.x - a.x) * k, a.y + (o.y - a.y) * k)
            g = self._grid(a.place)
            goal = g.nearest_free(goal, self._others(a.place, who, at=t), prefer=(a.x, a.y))
            t = self._walk(eid, who, goal, t, other)
        ta = self._turn(who, _yaw((a.x, a.y), (o.x, o.y)), t)
        to = self._turn(other, _yaw((o.x, o.y), (a.x, a.y)), max(t, o.busy))
        self.actions.append(RuntimeAction(eid, who, "face", other, round(t, 3), round(max(ta, to, t + 0.4), 3), a.place))
        t = max(ta, to)
        a.busy = max(a.busy, t)
        o.busy = max(o.busy, t)
        return t

    # -- events -----------------------------------------------------------------------------------------------------
    def advance(self) -> int:
        """Play every event recorded since the last call; returns how many."""
        rows = self.conn.execute("SELECT event_id, timestamp, type, location_id, truth FROM events WHERE event_id > ? "
                                 "ORDER BY event_id", (self.last_event,)).fetchall()
        if not rows:
            return 0
        self._animals = self.animals
        deltas: dict[int, list] = {}
        for eid, etype, ent, fld, new in self.conn.execute(
                "SELECT event_id, entity_type, entity_id, field, new_value FROM event_deltas WHERE event_id > ? AND "
                "((entity_type = 'person' AND field IN ('location_id', 'status')) OR "
                "(entity_type = 'object' AND field IN ('owner_person_id', 'location_id'))) ORDER BY delta_id",
                (self.last_event,)):
            deltas.setdefault(eid, []).append((etype, ent, fld, new))
        for oid, in self.conn.execute("SELECT id FROM objects ORDER BY id"):
            if oid not in self.things:  # an object that came into the world later
                self.things[oid] = _Thing()
        for pid, in self.conn.execute("SELECT id FROM people ORDER BY id"):
            self.bodies.setdefault(pid, _Body())
        for eid, ts, etype, here, truth in rows:
            self._play_event(eid, ts, etype, here, json.loads(truth), deltas.get(eid, []))
            self.last_event = eid
        return len(rows)

    def _play_event(self, eid: int, ts: int, etype: str, here: str | None, d: dict, ch: list) -> None:
        t = float(ts * 60)
        self._eid = eid
        for etype_, ent, fld, new in ch:  # people who come and go
            if etype_ == "person" and fld == "location_id" and ent in self.bodies:
                if self.bodies[ent].place != (new or ""):
                    t2 = self._leave(ent, t, eid)
                    if new:
                        self._arrive(ent, new, max(t2, self.bodies[ent].busy), eid,
                                     night=etype == "upkeep" or self._night(ts))
            elif etype_ == "person" and fld == "status" and ent in self.bodies:
                if new == "inactive" and self.bodies[ent].place:
                    self._leave(ent, t, eid)
                elif new != "inactive" and not self.bodies[ent].place:
                    loc = self.conn.execute("SELECT location_id FROM people WHERE id = ?", (ent,)).fetchone()[0]
                    after = next((n for e_, en, f_, n in ch if en == ent and f_ == "location_id"), None)
                    if after or loc:
                        self._arrive(ent, after or loc, max(t, self.bodies[ent].busy), eid)
        if etype == "upkeep" and d.get("actor") in self.bodies:  # already home: to bed
            who = d["actor"]
            b = self.bodies[who]
            if b.place and not any(e_ == "person" and en == who and f_ == "location_id" for e_, en, f_, _n in ch):
                bed = self._bed(b.place, who)
                if bed is not None and _dist((b.x, b.y), (bed[0], bed[1])) > 0.05:
                    self._walk(eid, who, (bed[0], bed[1]), t, "to bed", end=bed[3], end_yaw=bed[2])
        moves: dict[str, dict] = {}
        for etype_, ent, fld, new in ch:
            if etype_ == "object" and ent in self.things:
                moves.setdefault(ent, {})[fld] = new
        actor = d.get("actor")
        if etype in SOCIAL and actor in self.bodies:
            other = d.get("target") or d.get("victim")
            if other in self.bodies:
                t = self._approach(eid, actor, other, t)
                if etype == "duel":
                    t = max(t, self._free(actor, "move", "hands"), self._free(other, "move", "hands"))
                    for k in range(3):
                        self.interactions.append(RuntimeInteraction(eid, actor, "strike", other, t + k, t + k + 0.3,
                                                                    t + k + 0.6, "right"))
                    self._book(actor, ("move", "hands"), t, t + 3, "duel")
                    self._book(other, ("move", "hands"), t, t + 3, "duel")
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
            if "location_id" in m and not new:  # moved while nobody holds it (delivered, cleared away):
                t = max(t, th.busy)               # it leaves where it was and appears where it is now
                if th.place:
                    self._thing_key(t, oid, "offstage", at=(th.x, th.y))
                th.place = m["location_id"] or ""
                if th.place:
                    th.x, th.y = self._floor_spot(th.place, oid, eid)
                self._thing_key(t + 0.001, oid)
            return
        if old and not new:  # let go: it falls from the hand (or mouth) to the floor behind the body
            b = self.bodies[old]
            start = max(t, b.busy, th.busy, self._free(old, "hands")) + 0.4
            place = m.get("location_id") or b.place or (here or "")
            fx, fy = self._floor_spot(place, oid, eid, near=(b.x, b.y), yaw=b.yaw) if place else (b.x, b.y)
            self.interactions.append(RuntimeInteraction(eid, old, "drop", oid, start, start + 0.3, start + 0.3 + FALL,
                                                        self._part(old)))
            self.actions.append(RuntimeAction(eid, old, "detach", oid, start + 0.3, start + 0.3, b.place))
            self.tracks.append(RuntimeActionTrack(eid, old, "drop", oid, start, start, round(start + 0.3, 3),
                                                  round(start + 0.3 + FALL, 3), self._socket(old),
                                                  [fx, fy, 0.0], ""))
            th.holder, th.part, th.place = "", "", place
            self._thing_key(start + 0.3, oid, "fall", at=(b.x, b.y))
            th.x, th.y = fx, fy
            self._thing_key(start + 0.3 + FALL, oid)
            self._book(old, ("hands",), start, start + 0.3, "let go")
            self._book(oid, ("move",), start + 0.3, start + 0.3 + FALL, "fall")
            if etype == "misplace" and old in self.bodies and b.place:  # and they go on, unaware
                x, y, yaw, pose = self._spot(b.place, old, eid + 1)
                self._walk(eid, old, (x, y), start + 0.8, "going on", end=pose, end_yaw=yaw)
            return
        if not old:  # picked up from where it lies
            b = self.bodies.get(new)
            if b is None:
                return
            t = max(t, b.busy, th.busy, self._free(new, "hands"))
            approach = t
            if b.place == th.place:
                g = self._grid(b.place)
                v = (b.x - th.x, b.y - th.y)
                n = math.hypot(*v) or 1.0
                goal = (th.x + NEAR * v[0] / n, th.y + NEAR * v[1] / n)
                goal = g.nearest_free(goal, self._others(b.place, new, at=t), prefer=(b.x, b.y))
                t = self._walk(eid, new, goal, t, oid, end_yaw=_yaw(goal, (th.x, th.y)))
            else:
                t = self._rise(new, t)
            t = max(t, self._free(new, "move", "hands"))
            reach_from = t
            sniff = -1.0
            if new in self._animals:
                sniff = round(t, 3)
                self.actions.append(RuntimeAction(eid, new, "sniff", oid, round(t, 3), round(t + SNIFF, 3), b.place))
                t += SNIFF
            contact = round(t + REACH, 3)
            self.actions.append(RuntimeAction(eid, new, "reach", oid, round(t, 3), contact, b.place))
            self.interactions.append(RuntimeInteraction(eid, new, "pickup", oid, round(t, 3), contact,
                                                        round(contact + LIFT, 3), self._part(new)))
            self.actions.append(RuntimeAction(eid, new, "attach", oid, round(contact + LIFT, 3), round(contact + LIFT, 3),
                                              b.place))
            self.tracks.append(RuntimeActionTrack(eid, new, "pickup", oid, round(approach, 3), round(t, 3), contact,
                                                  round(contact + LIFT, 3), self._socket(new), [th.x, th.y, 0.0], new,
                                                  sniff))
            th.holder, th.part = new, self._part(new)
            self._thing_key(contact, oid, "lift", at=(th.x, th.y))
            th.place = ""
            self._thing_key(contact + LIFT, oid)
            self._book(new, ("move", "hands"), reach_from, contact + LIFT, "pick up")
            self._book(oid, ("move",), contact, contact + LIFT, "lift")
            return
        # from one body to another (given, stolen, won back)
        if old in self.bodies and new in self.bodies and self.bodies[old].place == self.bodies[new].place:
            t = self._approach(eid, new if etype == "steal" else old, old if etype == "steal" else new, t)
        kind = "grab" if etype == "steal" else "hand_over"
        t = max(t, th.busy, *(self._free(p, "move", "hands") for p in (old, new) if p in self.bodies))
        contact = round(t + 0.5, 3)
        self.interactions.append(RuntimeInteraction(eid, old, kind, oid, round(t, 3), contact, round(contact + 0.3, 3),
                                                    self._part(old)))
        self.interactions.append(RuntimeInteraction(eid, new, "receive", oid, round(t, 3), contact,
                                                    round(contact + 0.3, 3), self._part(new)))
        self.actions.append(RuntimeAction(eid, old, "detach", oid, contact, contact,
                                          self.bodies[old].place if old in self.bodies else ""))
        self.actions.append(RuntimeAction(eid, new, "attach", oid, contact, contact,
                                          self.bodies[new].place if new in self.bodies else ""))
        giver = self.bodies.get(old)
        at = (giver.x, giver.y) if giver else (0.0, 0.0)
        self.tracks.append(RuntimeActionTrack(eid, new, kind, oid, round(t, 3), round(t, 3), contact,
                                              round(contact + 0.3, 3), self._socket(new), [at[0], at[1], 1.0], new))
        th.holder, th.part, th.place = new, self._part(new), ""
        self._thing_key(contact, oid, "lift", at=at)
        self._thing_key(contact + 0.3, oid)
        for p in (old, new):
            if p in self.bodies:
                self._book(p, ("move", "hands"), t, contact + 0.3, kind if p == old else "receive")
        self._book(oid, ("move",), contact, contact + 0.3, "pass")

    def _socket(self, who: str) -> str:
        return "mouth" if who in self._animals else "hand.R"

    # -- reading it -------------------------------------------------------------------------------------------------
    def position(self, who: str, t: float) -> tuple[str, float, float, float, str] | None:
        """(place, x, y, yaw, pose) at world second t, by the rule every engine plays (runtime/export.py:sample)."""
        keys = self.by_entity.get(who)
        if not keys:
            return None
        i = bisect_right(self._times[who], t) - 1
        if i < 0:
            k = keys[0][1]
            return k.place, k.x, k.y, k.yaw, k.pose
        a = keys[i][1]
        if i + 1 < len(keys):
            tb, b = keys[i + 1]
            f = (t - keys[i][0]) / (tb - keys[i][0]) if tb > keys[i][0] else 0.0
            if a.pose == "walk":
                return a.place, a.x + (b.x - a.x) * f, a.y + (b.y - a.y) * f, a.yaw, "walk"
            if a.pose == "turn":
                return a.place, a.x, a.y, (a.yaw + yaw_diff(a.yaw, b.yaw) * f) % 360, "turn"
        return a.place, a.x, a.y, a.yaw, a.pose

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
                transforms.append(RuntimeTransform(o, hb[0], hb[1], hb[2], hb[3], "carried", holder))
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
        # each entity's last key before the window, at its own time: a walk under way is still under way
        lead = []
        for ent, ts in sorted(self._times.items()):
            i = bisect_right(ts, lo) - 1
            if i >= 0 and ts[i] < lo:
                lead.append(self.by_entity[ent][i])
        return stamp_trace(RuntimeTrace(
            self.VERSION, sorted(ids), [a for a in self.actions if a.event_id in ids],
            [i for i in self.interactions if i.event_id in ids],
            sorted(lead + [(t, k) for t, k in self.keys if lo <= t <= hi], key=lambda x: x[0]),
            before.transforms if before else [], dict(before.holders) if before else {},
            [k for k in self.tracks if k.event_id in ids],
            sorted((s for s in self.steps if lo <= s.land <= hi + 1), key=lambda s: (s.land, s.entity, s.foot))))

    def invariants(self) -> dict:
        """The runtime's own laws, checked over everything it has played (all must be empty):
        exclusive   no body's move / hands / voice booked twice at once (the scheduler refuses; counted here)
        teleport    a body or a thing never changes position between two keys without a moving pose between them
                    (walk, turn, rise, settle, lift, fall), and never changes place without going offstage
        speed       no walk faster than the body can walk (the cinema's clock never changes the runtime's)
        sockets     one thing at a time in a hand being lifted, one thing at a time in an animal's mouth
        walls       no walk's path crosses a wall or a piece of furniture
        """
        from contracts.runtime import RuntimeTransform  # noqa: F401  (the keys are RuntimeTransforms)
        out: dict[str, list] = {"exclusive": [], "teleport": [], "speed": [], "sockets": [], "walls": []}
        for a in self.actions:  # every walk's path is clear of walls and furniture (the seat's last step aside)
            if a.kind == "walk_to" and len(a.path) > 1 and a.place:
                g = self._grid(a.place)
                for p, q in zip(a.path, a.path[1:]):
                    hit = g.crosses_solid(tuple(p), tuple(q))
                    if hit:
                        out["walls"].append((a.actor, a.start, hit))
        for who, keys in self.by_entity.items():
            for (ta, a), (tb, b) in zip(keys, keys[1:]):
                if a.place and b.place and a.place != b.place and a.pose != "carried":  # a carried thing goes with its holder
                    out["teleport"].append((who, tb, f"{a.place} -> {b.place} without leaving"))
                    continue
                moved = math.hypot(b.x - a.x, b.y - a.y) > 1e-3
                if moved and a.place == b.place and a.place and a.pose not in MOVING and b.pose not in ("carried",) \
                        and a.pose not in ("carried",) and tb > ta:
                    out["teleport"].append((who, tb, f"{a.pose} at ({a.x}, {a.y}) -> ({b.x}, {b.y})"))
                if a.pose == "walk" and tb > ta:
                    v = math.hypot(b.x - a.x, b.y - a.y) / (tb - ta)
                    vmax = TROT if who in self._animals else WALK
                    if v > vmax + (0.0015 + vmax * 0.0011) / (tb - ta):  # beyond what mm and ms rounding explain
                        out["speed"].append((who, ta, round(v, 3)))
        for (who, r), rows in self.sched.books.items():
            for x, y in zip(rows, rows[1:]):
                if y.start < x.end - 1e-6:
                    out["exclusive"].append((who, r, x.kind, y.kind, y.start))
        for f in self.frames:
            for a in self._animals:
                held = [o for o, v in f.things.items() if v[0] == a]
                if len(held) > 1:
                    out["sockets"].append((a, f.revision, held))
        lifting: dict[str, list] = {}
        for k in self.tracks:
            if k.action != "drop":
                lifting.setdefault(k.actor, []).append((k.contact, k.complete, k.target))
        for who, rows in lifting.items():
            rows.sort()
            for x, y in zip(rows, rows[1:]):
                if y[0] < x[1] - 1e-6:
                    out["sockets"].append((who, y[0], f"{x[2]} and {y[2]} in one hand"))
        return out

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
