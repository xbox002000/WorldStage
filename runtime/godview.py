"""The god view's world save: a stretch of the world's history, every place side by side, everyone in it, played on
the world's own clock, and what each of them feels, wants, believes and holds as it changes.

    python -m runtime.godview <world.db> <out.json> [first_day] [last_day]

Nothing is directed here: no cuts, no whose-eyes, no edit. The page (render/godview) plays the world at 1x-600x,
pauses, rewinds, follows anyone, looks through anyone's eyes (a dog's too) and says why someone did something. It
reads this file; it cannot change the world. Going on ("LIVE") is channel/live.py's job: it runs the simulation,
the only writer, and writes a new save.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

from narrative.layouts import LAYOUTS
from narrative.spatial import template_for
from runtime.stage import CAPSULE, GOLDEN, SET_MASK, SPACING, mask_color, thing_asset
from runtime.world_runtime import WorldRuntime

DAY = 1440
PEOPLE_FIELDS = ("emotion", "hunger", "energy", "money_cents", "location_id", "status")
VERBS = {"talk": "和{t}聊天", "tell": "告訴{t}一件事", "confront": "質問{t}", "accuse": "指控{t}", "lend": "借錢給{t}",
         "repay": "還錢給{t}", "take": "拿走了{o}", "find": "找回了{o}", "misplace": "弄丟了{o}", "give": "把{o}交給{t}",
         "notice_missing": "發現{o}不見了", "steal": "偷走{t}的{o}", "bark": "對{t}吠", "move": "走到{p}", "eat": "吃東西",
         "work": "工作", "sleep": "睡覺", "upkeep": "回家過夜", "goal_change": "改變了目標", "reflection": "想了想自己",
         "parrot_speaks": "鸚鵡學舌", "feed_pet": "餵了寵物"}  # domain packs caption their own events


def _names(conn) -> dict:
    out = {r[0]: r[1] for r in conn.execute("SELECT id, name FROM people")}
    out.update({r[0]: r[1] for r in conn.execute("SELECT id, name FROM objects")})
    out.update({r[0]: r[1] for r in conn.execute("SELECT id, name FROM locations")})
    return out


def caption(etype: str, truth: dict, place: str, names: dict) -> str:
    who = names.get(truth.get("actor", ""), truth.get("actor", ""))
    t = names.get(truth.get("target") or truth.get("victim") or truth.get("suspect") or "", "")
    o = names.get(truth.get("object", ""), truth.get("object", ""))
    from world.domains import style
    st = style(etype)
    verb = (st.caption if st is not None and st.caption else VERBS.get(etype, etype)).format(
        t=t or "某人", o=o or "東西", p=names.get(place, place), text=truth.get("text", ""))
    return f"{who}{verb}" if who else verb


def export_world(conn: sqlite3.Connection, out: Path, first_day: int | None = None, last_day: int | None = None,
                 rt: WorldRuntime | None = None) -> dict:
    rt = rt or WorldRuntime(conn)
    last = conn.execute("SELECT MAX(timestamp) FROM events").fetchone()[0] or 0
    last_day = last // DAY if last_day is None else last_day
    first_day = max(0, last_day) if first_day is None else first_day
    t0, t1 = first_day * DAY * 60.0, (last_day + 1) * DAY * 60.0
    names = _names(conn)
    places = [r[0] for r in conn.execute("SELECT id FROM locations ORDER BY id")]
    offset = {p: i * SPACING for i, p in enumerate(places)}
    animals = rt.animals
    cast = [r[0] for r in conn.execute("SELECT id FROM people ORDER BY id")]
    entities = []
    for n, (eid, keys) in enumerate(sorted(rt.by_entity.items())):
        before = [k for k in keys if k[0] < t0]
        window = ([before[-1]] if before else []) + [k for k in keys if t0 <= k[0] <= t1]
        if not window:
            continue
        kind = "animal" if eid in animals else "person" if eid in cast else "thing"
        e = {"id": eid, "kind": kind, "name": names.get(eid, eid), "mask": mask_color(n),
             "keys": [[round(max(t, t0 - 1.0), 3), k.place, round(k.x + offset.get(k.place, 0.0), 3), k.y, k.yaw, k.pose]
                      + ([k.holder] if k.pose in ("carried", "lift") else []) for t, k in window]}
        if kind == "thing":
            e["asset"] = thing_asset(eid)
        else:
            e["hue"] = round(cast.index(eid) * GOLDEN % 360, 1)
            e["capsule"] = CAPSULE[kind]
        entities.append(e)
    by = {e["id"]: e for e in entities}
    for st in rt.steps:
        if t0 <= st.land <= t1 and st.entity in by:
            by[st.entity].setdefault("steps", []).append([st.land, st.lift, st.foot, round(st.x + offset.get(st.place, 0.0), 3), st.y])
    tracks = [{"event": k.event_id, "actor": k.actor, "action": k.action, "thing": k.target, "socket": k.socket,
               "approach": k.approach_start, "reach": k.reach_start, "contact": k.contact, "complete": k.complete,
               "sniff": k.sniff if k.sniff >= 0 else None, "parent": k.parent,
               "point": [round(k.point[0] + offset.get(_place(rt, k.actor, k.contact), 0.0), 3), k.point[1], k.point[2]]}
              for k in rt.tracks if t0 <= k.contact <= t1]
    handoffs = [{"t": i.contact, "start": i.start, "complete": i.complete, "actor": i.actor, "action": i.action,
                 "thing": i.target, "hand": i.hand, "event": i.event_id} for i in rt.interactions if t0 <= i.contact <= t1]
    actions = [{"t": a.start, "end": a.end, "actor": a.actor, "kind": a.kind, "target": a.target, "event": a.event_id}
               for a in rt.actions if t0 <= a.start <= t1 and a.kind in ("walk_to", "reach", "sniff", "face", "enter", "exit", "say")]
    from narrative.lines import line
    said = {}  # event -> when it is said on the runtime's clock (the speaker's voice booking)
    for a in rt.actions:
        if a.kind == "say" and t0 <= a.start <= t1:
            said[a.event_id] = [a.start, a.end]
        elif a.kind == "exit" and t0 <= a.start <= t1:
            said.setdefault(a.event_id, [a.start, a.start + 2.5])
    events = []
    for eid, ts, etype, place, truth, imp in conn.execute(
            "SELECT event_id, timestamp, type, location_id, truth, importance FROM events WHERE timestamp >= ? AND "
            "timestamp < ? ORDER BY event_id", (first_day * DAY, (last_day + 1) * DAY)):
        d = json.loads(truth)
        if etype in ("day_end",):
            continue
        who = [r[0] for r in conn.execute("SELECT person_id FROM event_participants WHERE event_id = ? ORDER BY person_id", (eid,))]
        ev = {"id": eid, "t": ts * 60.0, "type": etype, "place": place or "", "who": who,
              "importance": imp, "caption": caption(etype, d, place or "", names), "why": d.get("reason") or ""}
        spoken = line(eid, etype, d, names)
        if spoken:  # a line to show over the speaker (a read model: narrative/lines.py), when the runtime says it
            ev.update(line=spoken, actor=d.get("actor"), target=d.get("target") or d.get("victim") or "",
                      say=said.get(eid, [ts * 60.0, ts * 60.0 + 2.5]))
        events.append(ev)
    from narrative.scenes import scenes as find_scenes
    by_event = {e["id"]: e for e in events}
    scenes = []
    for sc in find_scenes(conn, first_day, last_day, names):
        spans = [by_event[i]["say"] for i in sc["events"] if i in by_event and "say" in by_event[i]]
        if spans:
            sc.update(start=min(a for a, _ in spans), end=max(b for _, b in spans))
        scenes.append(sc)
    people = {}
    for pid in cast:
        row = conn.execute("SELECT p.name, p.goal, s.traits FROM people p LEFT JOIN personas s ON s.person_id = p.id "
                           "WHERE p.id = ?", (pid,)).fetchone()
        tl: dict[str, list] = {}
        for fld in PEOPLE_FIELDS:
            first = conn.execute("SELECT old_value FROM event_deltas WHERE entity_type = 'person' AND entity_id = ? AND "
                                 "field = ? ORDER BY delta_id LIMIT 1", (pid, fld)).fetchone()
            cur = conn.execute(f"SELECT {fld} FROM people WHERE id = ?", (pid,)).fetchone()[0]
            series = [[0.0, first[0] if first else cur]]
            for ts, new in conn.execute("SELECT e.timestamp, d.new_value FROM event_deltas d JOIN events e USING (event_id) "
                                        "WHERE d.entity_type = 'person' AND d.entity_id = ? AND d.field = ? AND "
                                        "e.timestamp < ? ORDER BY d.delta_id", (pid, fld, (last_day + 1) * DAY)):
                series.append([ts * 60.0, new])
            tl[fld] = _window(series, t0)
        trust = {}
        for ent, ts, new in conn.execute("SELECT d.entity_id, e.timestamp, d.new_value FROM event_deltas d JOIN events e "
                                         "USING (event_id) WHERE d.entity_type = 'relationship' AND d.field = 'trust' AND "
                                         "d.entity_id LIKE ? AND e.timestamp < ? ORDER BY d.delta_id",
                                         (f"{pid}:%", (last_day + 1) * DAY)):
            trust.setdefault(ent.split(":", 1)[1], []).append([ts * 60.0, round(float(new), 3)])
        for other, series in list(trust.items()):
            trust[other] = _window(series, t0)
        goals = []
        slots: dict[str, dict] = {}
        for ent, fld, new, ts in conn.execute(
                "SELECT d.entity_id, d.field, d.new_value, e.timestamp FROM event_deltas d JOIN events e USING (event_id) "
                "WHERE d.entity_type = 'goal' AND d.entity_id LIKE ? AND e.timestamp < ? ORDER BY d.delta_id",
                (f"{pid}:%", (last_day + 1) * DAY)):
            g = slots.setdefault(ent, {"kind": "", "target": "", "object": "", "status": "empty"})
            g[fld] = new
            goals.append([ts * 60.0, ent.split(":")[1], g["kind"], names.get(g["target"], g["target"]),
                          names.get(g["object"], g["object"]), g["status"]])
        memories = [[ts * 60.0, belief, round(conf, 2), src, names.get(sid or "", sid or "")]
                    for ts, belief, conf, src, sid in conn.execute(
                        "SELECT e.timestamp, m.belief, m.confidence, m.source_type, m.source_id FROM memories m JOIN events e "
                        "ON e.event_id = m.event_id WHERE m.observer_id = ? AND e.timestamp < ? ORDER BY m.memory_id",
                        (pid, (last_day + 1) * DAY))]
        traits = json.loads(row[2]) if row and row[2] else {}
        people[pid] = {"name": row[0] if row else pid, "life_goal": row[1] if row else "", "species": traits.get("species", "human"),
                       "timeline": tl, "trust": trust, "goals": goals, "memories": memories[-60:]}
    geometry = []
    from runtime.nav import blocks
    for pl in places:
        tpl = template_for(pl)
        if tpl not in LAYOUTS:
            continue
        for o in LAYOUTS[tpl]["objects"]:
            cls = "wall" if o.kind in ("wall", "window", "door") else "tree" if o.kind == "tree" else "furniture"
            geometry.append({"id": o.id, "place": pl, "kind": o.kind, "x": o.position[0] + offset[pl], "y": o.position[1],
                             "z": o.position[2], "w": o.size[0], "d": o.size[1], "h": o.size[2], "yaw": o.yaw,
                             "mask": SET_MASK[cls], "collision": {"shape": "box", "blocks": blocks(o),
                                                                  "blocks_sight": o.blocks_sight}})
    from narrative.observatory import observatory  # read models: stories and lives, each item traceable to events
    doc = {"kind": "world", "version": rt.VERSION, "observatory": observatory(conn), "first_day": first_day, "last_day": last_day, "t0": t0, "t1": t1,
           "places": [{"id": p, "name": names.get(p, p), "offset": offset[p]} for p in places], "geometry": geometry,
           "entities": entities, "tracks": tracks, "handoffs": handoffs, "actions": actions, "events": events, "scenes": scenes,
           "people": people, "set_mask": SET_MASK, "cuts": {}, "duration": t1}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return doc


def _place(rt: WorldRuntime, who: str, t: float) -> str:
    p = rt.position(who, t)
    return p[0] if p else ""


def _window(series: list, t0: float) -> list:
    """The value at the window's start, then every change inside it."""
    before = [s for s in series if s[0] < t0]
    return ([[t0, before[-1][1]]] if before else []) + [s for s in series if s[0] >= t0]


if __name__ == "__main__":
    from world.db import connect
    c = connect(sys.argv[1])
    a = int(sys.argv[3]) if len(sys.argv) > 3 else None
    b = int(sys.argv[4]) if len(sys.argv) > 4 else None
    d = export_world(c, Path(sys.argv[2]), a, b)
    print("world save", sys.argv[2], "days", d["first_day"], "-", d["last_day"], "entities", len(d["entities"]),
          "events", len(d["events"]))
