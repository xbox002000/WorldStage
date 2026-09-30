"""A RuntimeTrace -> a playback file for an engine (runtime/godot/). The engine only plays it: every position, every
hand-off and every camera target is in this file, and `sample()` is the reference an engine's playback is checked
against (same interpolation rule: a key with pose "walk" moves linearly to the next key, any other pose holds).

World time runs in minutes and hours between events; playback compresses the idle gaps (GAP) so a day's scene plays
in seconds, without changing the order or the duration of anything that moves.
"""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

from contracts.runtime import RuntimeTrace
from narrative.layouts import LAYOUTS
from narrative.spatial import template_for

GAP = 1.2  # seconds of playback for any idle stretch longer than that
LEAD = 0.8  # playback seconds before the first movement


def timeline(times: list[float]) -> list[tuple[float, float]]:
    """(world seconds, playback seconds) breakpoints: motion keeps its duration, idle gaps shrink to GAP."""
    pts = sorted(set(times))
    out, play = [], LEAD
    for k, t in enumerate(pts):
        if k:
            play += min(GAP, t - pts[k - 1])
        out.append((t, round(play, 4)))
    return out


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
    tl = timeline(times)
    t0 = min(times) - 0.5 if times else 0.0  # the scene as it stood before the first event
    keys = [(t0, k) for k in trace.initial if k.place == place] + keys
    animals = {r[0] for r in conn.execute("SELECT person_id FROM personas WHERE json_extract(traits, '$.species') "
                                          "IS NOT NULL AND json_extract(traits, '$.species') <> 'human'")}
    people = {r[0] for r in conn.execute("SELECT id FROM people")}
    entities: dict[str, dict] = {}
    for t, k in keys:
        e = entities.setdefault(k.entity, {"id": k.entity, "kind": "animal" if k.entity in animals else
                                           "person" if k.entity in people else "thing", "keys": []})
        e["keys"].append([to_play(t, tl), k.place, k.x, k.y, k.yaw, k.pose])
    for e in entities.values():
        if e["kind"] != "thing":
            e["hue"] = _hue(conn, e["id"])
            name = conn.execute("SELECT name FROM people WHERE id = ?", (e["id"],)).fetchone()
            e["name"] = name[0] if name else e["id"]
    handoffs = [{"t": round(to_play(i.contact, tl), 4), "actor": i.actor, "action": i.action, "thing": i.target,
                 "hand": i.hand} for i in trace.interactions if i.action in ("pickup", "receive", "grab", "drop", "hand_over")]
    gains = sorted((h["t"], h["thing"], h["actor"], h["hand"]) for h in handoffs if h["action"] in ("pickup", "receive", "grab"))
    for e in entities.values():  # a carried thing follows whoever last took hold of it
        if e["kind"] != "thing":
            continue
        for key in e["keys"]:
            if key[5] == "carried":
                got = [g for g in gains if g[1] == e["id"] and g[0] <= key[0] + 1e-6]
                holder = got[-1][2] if got else trace.initial_holders.get(e["id"], "")
                key.append(holder or "")
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


def sample(doc: dict, entity: str, t: float) -> tuple[float, float] | None:
    """Where an entity is at playback time t, by the rule every engine must follow. A carried thing is wherever
    its holder is (a hand or a mouth offset is the engine's business, not a position)."""
    e = next((x for x in doc["entities"] if x["id"] == entity), None)
    if e is None or not e["keys"]:
        return None
    keys = e["keys"]
    current = next((k for k in reversed(keys) if k[0] <= t), keys[0])
    if current[5] == "carried" and len(current) > 6 and current[6]:
        return sample(doc, current[6], t)
    if t <= keys[0][0]:
        return keys[0][2], keys[0][3]
    for a, b in zip(keys, keys[1:]):
        if a[0] <= t < b[0]:
            if a[5] == "walk" and b[0] > a[0]:
                f = (t - a[0]) / (b[0] - a[0])
                return a[2] + (b[2] - a[2]) * f, a[3] + (b[3] - a[3]) * f
            return a[2], a[3]
    return keys[-1][2], keys[-1][3]
