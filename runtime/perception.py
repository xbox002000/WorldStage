"""Perception in space, for a world simulated inside it (world/space.py asks, this answers).

    RuntimeSpace(conn)          keeps a WorldRuntime playing along with the simulation (advance() before each question)
    .weight(observer, key, t)   0 if the observer could not have perceived the act; more when close and facing it
    .perceives_thing(p, o, t)   whether p can see (or, an animal, smell) the thing lying where it lies

Senses, all in the runtime's space at world second t = minute * 60:
- sight: the same place, within range (a person 14 m, a dog 8 m), inside the field of view (220 and 250 degrees:
  noticing includes turning one's head) and no wall, tree or pillar between the eyes and the act;
- hearing: a quiet word carries 4 m and a normal one 8 m, round furniture (not through walls: another place is
  another room);
- smell: a dog smells a thing within 6 m whatever is in the way.
"""
from __future__ import annotations

import json
import math
import sqlite3

from narrative.layouts import LAYOUTS
from narrative.spatial import template_for
from runtime.world_runtime import WorldRuntime

RANGE = {"human": 14.0, "dog": 8.0}
FOV = {"human": 220.0, "dog": 250.0}
SMELL = 6.0
HEAR = {"quiet": 4.0, "normal": 8.0}
SPEECH = ("tell", "talk", "lend", "repay")  # acts perceived by ear
NEAR = 3.0  # close enough, and facing it, that it is hard to miss


def _seg_box(a, b, box) -> bool:
    """Does the 2D segment a-b cross the box (x0, x1, y0, y1)?"""
    t0, t1 = 0.0, 1.0
    for i, (lo, hi) in enumerate(((box[0], box[1]), (box[2], box[3]))):
        d = b[i] - a[i]
        if abs(d) < 1e-9:
            if a[i] < lo or a[i] > hi:
                return False
            continue
        ta, tb = (lo - a[i]) / d, (hi - a[i]) / d
        if ta > tb:
            ta, tb = tb, ta
        t0, t1 = max(t0, ta), min(t1, tb)
        if t0 > t1:
            return False
    return t1 > 0.02 and t0 < 0.98


class RuntimeSpace:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.rt = WorldRuntime(conn)
        self._walls: dict[str, list] = {}
        self.queries = 0  # how many questions the world asked space (measured, never used to decide)

    def _species(self, pid: str) -> str:
        row = self.conn.execute("SELECT json_extract(traits, '$.species') FROM personas WHERE person_id = ?", (pid,)).fetchone()
        return (row[0] if row else None) or "human"

    def _blockers(self, place: str) -> list:
        tpl = template_for(place)
        if tpl not in self._walls:
            out = []
            for o in LAYOUTS.get(tpl, LAYOUTS["cafe"])["objects"]:
                if o.blocks_sight and o.size[2] >= 1.2 and o.position[2] < 1.0:
                    w, d = (o.size[1], o.size[0]) if abs((o.yaw or 0) % 180) == 90 else (o.size[0], o.size[1])
                    out.append((o.position[0] - w / 2, o.position[0] + w / 2, o.position[1] - d / 2, o.position[1] + d / 2))
            self._walls[tpl] = out
        return self._walls[tpl]

    def _where(self, who: str, t: float):
        self.rt.advance()
        p = self.rt.position(who, t)
        return None if p is None or p[4] == "offstage" or not p[0] else p

    def _thing(self, oid: str, t: float):
        self.rt.advance()
        th = self.rt.things.get(oid)
        if th is None:
            return None
        if th.holder:
            h = self._where(th.holder, t)
            return (h[0], h[1], h[2]) if h else None
        return (th.place, th.x, th.y) if th.place else None

    def sees(self, observer: str, place: str, x: float, y: float, t: float) -> float:
        """0 if not; 1 if seen; 1.6 if close and in front."""
        me = self._where(observer, t)
        if me is None or me[0] != place:
            return 0.0
        sp = self._species(observer)
        d = math.hypot(x - me[1], y - me[2])
        if d > RANGE.get(sp, 14.0):
            return 0.0
        if d > 0.3:
            off = abs((math.degrees(math.atan2(y - me[2], x - me[1])) - me[3] + 540) % 360 - 180)
            if off > FOV.get(sp, 220.0) / 2:
                return 0.0
        else:
            off = 0.0
        if any(_seg_box((me[1], me[2]), (x, y), b) for b in self._blockers(place)):
            return 0.0
        return 1.6 if d < NEAR and off < 60 else 1.0

    def weight(self, observer: str, key: str, now: int) -> float:
        self.queries += 1
        kind, _, rest = key.partition(":")
        actor, _, target = rest.partition(":")
        target = target.split(":")[0]
        t = now * 60.0
        a = self._where(actor, t) if actor else None
        if a is None:  # an act by nobody placed (a prop): being there is enough
            return 1.0
        if kind in SPEECH:
            me = self._where(observer, t)
            if me is None or me[0] != a[0]:
                return 0.0
            reach = HEAR["quiet"] if kind in ("tell", "lend") else HEAR["normal"]
            return 1.0 if math.hypot(me[1] - a[1], me[2] - a[2]) <= reach else 0.0
        w = self.sees(observer, a[0], a[1], a[2], t)
        th = self._thing(target, t) if target else None
        if th is not None:  # the act happens at the thing as much as at the one who does it
            w = max(w, self.sees(observer, th[0], th[1], th[2], t))
        return w

    def perceives_thing(self, observer: str, oid: str, now: int) -> bool:
        self.queries += 1
        t = now * 60.0
        th = self._thing(oid, t)
        if th is None:
            return False
        if self._species(observer) == "dog":
            me = self._where(observer, t)
            if me is not None and me[0] == th[0] and math.hypot(me[1] - th[1], me[2] - th[2]) <= SMELL:
                return True
        return self.sees(observer, th[0], th[1], th[2], t) > 0

    # -- the god view's questions -----------------------------------------------------------------------------------
    def perceived(self, observer: str, now: int) -> dict:
        """Everyone and everything the observer can perceive now (for the god view's inspector)."""
        me = self._where(observer, now * 60.0)
        if me is None:
            return {"people": [], "things": []}
        people = [p for p in sorted(self.rt.bodies) if p != observer and (lambda q: q is not None and q[0] == me[0] and
                  self.sees(observer, q[0], q[1], q[2], now * 60.0) > 0)(self._where(p, now * 60.0))]
        things = [o for o, th in sorted(self.rt.things.items()) if th.place == me[0] and not th.holder
                  and self.perceives_thing(observer, o, now)]
        return {"people": people, "things": things}


def load(conn: sqlite3.Connection) -> RuntimeSpace:
    return RuntimeSpace(conn)


def traits(conn: sqlite3.Connection, pid: str) -> dict:
    row = conn.execute("SELECT traits FROM personas WHERE person_id = ?", (pid,)).fetchone()
    return json.loads(row[0]) if row else {}
