"""A RuntimeTrace -> a playback file for an engine (runtime/godot/). The engine only plays it: every position, every
hand-off and every camera target is in this file, and `sample()` is the reference an engine's playback is checked
against (same interpolation rule: a key with pose "walk" moves linearly to the next key, any other pose holds).

Three clocks, kept apart:
- world time: the events' minutes (world.db);
- runtime time: seconds of continuous motion the runtime derives from them (where everyone is, how fast they walk);
- cinema time: a version's edit, which plays slices of runtime time at 1:1, and a viewer's playback rate (0.25x to
  600x), which is only how fast one watches.
A scene's playback clock is runtime time shifted so its first action starts at LEAD: nothing is ever compressed.
Runtime 0.1 compressed idle gaps into the same clock; a walk with no other key inside counted as idle, and walked at
3.6 m/s. Speed belongs to the runtime; the cinema only chooses which slices to show and how fast to watch.
"""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

from contracts.runtime import RuntimeTrace
from narrative.layouts import LAYOUTS
from narrative.spatial import template_for

LEAD = 0.8  # playback seconds before the first movement


MOVING = ("walk", "turn", "rise", "settle", "lift", "fall")


def motion_spans(keyframes) -> list[tuple[float, float]]:
    """World-time intervals in which something moves: from a key with a moving pose to the entity's next key."""
    by: dict[str, list] = {}
    for t, k in keyframes:
        by.setdefault(k.entity, []).append((t, k.pose))
    out = []
    for ks in by.values():
        ks.sort(key=lambda x: x[0])
        for (ta, pa), (tb, _pb) in zip(ks, ks[1:]):
            if pa in MOVING and tb > ta:
                out.append((ta, tb))
    return out


def timeline(times: list[float], moving: list[tuple[float, float]] = (),
             anchor: float | None = None) -> list[tuple[float, float]]:
    """The scene's playback clock: runtime seconds, shifted so `anchor` (default: the earliest time) falls at LEAD.
    One breakpoint, slope 1: playback never compresses, so nothing moves faster on screen than in the runtime."""
    del moving  # kept for callers; motion is never compressed, so the spans do not matter any more
    first = anchor if anchor is not None else (min(times) if times else 0.0)
    return [(first, LEAD)]


def to_play(t: float, tl: list[tuple[float, float]]) -> float:
    if t <= tl[0][0]:
        return tl[0][1] - (tl[0][0] - t)
    for (a, pa), (b, pb) in zip(tl, tl[1:]):
        if a <= t <= b:
            return pa + (pb - pa) * ((t - a) / (b - a) if b > a else 0.0)
    return tl[-1][1] + (t - tl[-1][0])


def _hue(conn: sqlite3.Connection, pid: str) -> float:
    from narrative.color import avatar_color
    row = conn.execute("SELECT id FROM people WHERE id = ?", (pid,)).fetchone()
    color = avatar_color(pid, None) if row else "hsl(210"
    m = re.search(r"hsl\((\d+(?:\.\d+)?)", color)
    return float(m.group(1)) if m else 210.0


def export(conn: sqlite3.Connection, trace: RuntimeTrace, place: str, out: Path, focus: list[str] | None = None) -> dict:
    """One place's part of a trace, ready for an engine: geometry, bodies, things, keys, hand-offs and camera."""
    lay = LAYOUTS[template_for(place)]
    keys = [(t, k) for t, k in trace.keyframes if k.place in (place, "")]
    times = [t for t, _ in keys] + [x for i in trace.interactions for x in (i.start, i.contact, i.complete)]
    tl = timeline(times, motion_spans(keys))
    # the scene as it stood before the first event: trace.keyframes leads with each entity's last earlier key
    animals = {r[0] for r in conn.execute("SELECT person_id FROM personas WHERE json_extract(traits, '$.species') "
                                          "IS NOT NULL AND json_extract(traits, '$.species') <> 'human'")}
    people = {r[0] for r in conn.execute("SELECT id FROM people")}
    entities: dict[str, dict] = {}
    for t, k in keys:
        e = entities.setdefault(k.entity, {"id": k.entity, "kind": "animal" if k.entity in animals else
                                           "person" if k.entity in people else "thing", "keys": []})
        e["keys"].append([to_play(t, tl), k.place, k.x, k.y, k.yaw, k.pose] +
                         ([k.holder] if k.pose in ("carried", "lift") else []))
    for e in entities.values():
        if e["kind"] != "thing":
            e["hue"] = _hue(conn, e["id"])
            name = conn.execute("SELECT name FROM people WHERE id = ?", (e["id"],)).fetchone()
            e["name"] = name[0] if name else e["id"]
    handoffs = [{"t": round(to_play(i.contact, tl), 4), "actor": i.actor, "action": i.action, "thing": i.target,
                 "hand": i.hand} for i in trace.interactions if i.action in ("pickup", "receive", "grab", "drop", "hand_over")]
    # the camera follows whoever is doing something, from a little before they start until they are done
    shots = []
    for a in sorted(trace.actions, key=lambda a: a.start):
        if a.place != place or a.kind not in ("walk_to", "reach", "enter", "face"):
            continue
        if focus and a.actor not in focus and a.target not in focus:
            continue
        s, e_ = to_play(a.start, tl) - 0.3, to_play(a.end, tl) + 0.5
        if shots and shots[-1]["target"] == a.actor and s <= shots[-1]["end"] + 0.2:
            shots[-1]["end"] = max(shots[-1]["end"], e_)
        else:
            shots.append({"start": round(s, 4), "end": round(e_, 4), "target": a.actor, "why": f"{a.kind} {a.target}"})
    geometry = [{"id": o.id, "kind": o.kind, "x": o.position[0], "y": o.position[1], "w": o.size[0], "d": o.size[1],
                 "h": o.size[2], "yaw": o.yaw} for o in lay["objects"]]
    doc = {"version": trace.version, "trace_hash": trace.trace_hash, "place": place, "geometry": geometry,
           "focus": (focus or [""])[0],
           "entities": sorted(entities.values(), key=lambda e: e["id"]), "handoffs": handoffs, "camera": shots,
           "duration": round(max([tl[-1][1]] + [s["end"] for s in shots]) + 1.0, 3)}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    return doc


def _holder_at_start(conn: sqlite3.Connection, trace: RuntimeTrace, oid: str) -> str:
    first = min(trace.event_ids) if trace.event_ids else 0
    row = conn.execute("SELECT new_value FROM event_deltas WHERE entity_type = 'object' AND entity_id = ? AND "
                       "field = 'owner_person_id' AND event_id < ? ORDER BY delta_id DESC LIMIT 1", (oid, first)).fetchone()
    return row[0] if row and row[0] else ""


def _lerp_yaw(a: float, b: float, f: float) -> float:
    return (a + ((b - a + 540.0) % 360.0 - 180.0) * f) % 360.0


def sample_full(doc: dict, entity: str, t: float) -> tuple[float, float, float] | None:
    """(x, y, yaw) of an entity at playback time t, by the rule every engine must follow (runtime_rule.js is the
    same rule in JavaScript):
    - walk: moves linearly to the next key, heading this key's yaw (eased in from the previous walk key at a corner);
    - turn: holds its place, its yaw turns to the next key's;
    - rise, settle: moves to the next key and turns to its yaw (out of a seat, into one);
    - lift: travels from here to its holder by the next key (a thing going from the floor or a hand to a socket);
    - fall: travels from here to the next key (let go, to the floor);
    - carried: wherever its holder is (the hand or mouth offset is the engine's business, not a position);
    - anything else holds."""
    e = _entity(doc, entity)
    if e is None or not e["keys"]:
        return None
    keys = e["keys"]
    i = _index(keys, t)
    cur = keys[max(0, i)]
    if cur[5] == "carried" and len(cur) > 6 and cur[6]:
        return sample_full(doc, cur[6], t)
    if i < 0:
        return keys[0][2], keys[0][3], keys[0][4]
    if i + 1 < len(keys):
        a, b = keys[i], keys[i + 1]
        f = (t - a[0]) / (b[0] - a[0]) if b[0] > a[0] else 0.0
        if a[5] == "walk":
            yaw = a[4]
            # the heading eases in from the yaw the body had: after a corner, or a small turn not worth a turn key
            # (after a turn, rise or settle the body already faces this way); sharper turns take longer
            if i > 0 and keys[i - 1][5] not in ("turn", "rise", "settle"):
                turn = abs((a[4] - keys[i - 1][4] + 540.0) % 360.0 - 180.0)
                ease = min(max(0.25, turn / 450.0), b[0] - a[0])
                if turn > 1e-6 and ease > 0 and t - a[0] < ease:
                    yaw = _lerp_yaw(keys[i - 1][4], a[4], (t - a[0]) / ease)
            return a[2] + (b[2] - a[2]) * f, a[3] + (b[3] - a[3]) * f, yaw
        if a[5] == "turn":
            return a[2], a[3], _lerp_yaw(a[4], b[4], f)
        if a[5] in ("rise", "settle"):
            return a[2] + (b[2] - a[2]) * f, a[3] + (b[3] - a[3]) * f, _lerp_yaw(a[4], b[4], f)
        if a[5] == "lift" and len(a) > 6 and a[6]:
            h = sample_full(doc, a[6], t)
            if h is not None:
                return a[2] + (h[0] - a[2]) * f, a[3] + (h[1] - a[3]) * f, h[2]
        if a[5] == "fall":
            return a[2] + (b[2] - a[2]) * f, a[3] + (b[3] - a[3]) * f, a[4]
    return cur[2], cur[3], cur[4]


_BY_ID: dict[int, tuple[dict, dict]] = {}


def _entity(doc: dict, entity: str) -> dict | None:
    hit = _BY_ID.get(id(doc))
    if hit is None or hit[0] is not doc:
        hit = _BY_ID[id(doc)] = (doc, {x["id"]: x for x in doc["entities"]})
    return hit[1].get(entity)


def _index(keys: list, t: float) -> int:
    """The last key at or before t (-1 before the first)."""
    lo, hi = 0, len(keys)
    while lo < hi:
        mid = (lo + hi) // 2
        if keys[mid][0] <= t:
            lo = mid + 1
        else:
            hi = mid
    return lo - 1


def sample(doc: dict, entity: str, t: float) -> tuple[float, float] | None:
    s = sample_full(doc, entity, t)
    return (s[0], s[1]) if s else None


def pose_at(doc: dict, entity: str, t: float) -> str:
    e = _entity(doc, entity)
    if e is None or not e["keys"]:
        return "offstage"
    return e["keys"][max(0, _index(e["keys"], t))][5]


def holder_at(doc: dict, entity: str, t: float) -> str:
    e = _entity(doc, entity)
    if e is None or not e["keys"]:
        return ""
    k = e["keys"][max(0, _index(e["keys"], t))]
    return k[6] if k[5] in ("carried", "lift") and len(k) > 6 else ""
