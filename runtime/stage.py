"""A whole scene for the Director Camera Sandbox: every place the story touches, laid side by side in one space, the
runtime's movements and hand-offs, and one cut list per DirectorPlan (per ProductionPacket).

Two clocks. The *world* clock (playback seconds of the runtime, idle gaps compressed) is where bodies are; it is
the same for every version. The *film* clock is the director's edit. Each shot is mapped to a slice of its event's
world time: the shots of one moment continue each other (coverage, not repetition), and where the world holds
still the slice is simply a held pose. Changing the DirectorPlan changes the cut list only, never the world clock or
anything on it: that is the sandbox's guarantee, and `fidelity.py` checks it.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from contracts.packet import ProductionPacket
from contracts.runtime import RuntimeTrace
from narrative.layouts import LAYOUTS
from narrative.spatial import template_for
from runtime.export import motion_spans, timeline, to_play

SPACING = 40.0  # metres between places laid side by side
ORDER_MOTION = ("walk_to", "reach", "attach", "detach", "enter", "exit", "face")
GOLDEN = 137.508
THING_ASSETS = ("wallet", "phone", "diary", "key", "watch", "ring", "ticket", "package", "sword", "cup", "letter")
CAPSULE = {"person": {"radius": 0.22, "height": 1.85}, "animal": {"radius": 0.2, "height": 0.6}}


def thing_asset(oid: str) -> str:
    """Which model stands for a thing: its own silhouette where there is one (a wallet is not a phone)."""
    return next((a for a in THING_ASSETS if oid == a or oid.startswith(a + "_") or oid.startswith(a)), "thing")


KELLY = ("#f3c300", "#875692", "#f38400", "#a1caf1", "#be0032", "#c2b280", "#008856", "#e68fac", "#0067a5", "#f99379",
         "#604e97", "#f6a600", "#b3446c", "#dcd300", "#882d17", "#8db600", "#654522", "#e25822")


def mask_color(k: int) -> str:
    """The k-th instance colour of the id mask: Kelly's colours of maximum contrast first (never black, the
    background, or grey, the set), then golden-angle hues."""
    if k < len(KELLY):
        return KELLY[k]
    import colorsys
    r, g, b = colorsys.hsv_to_rgb((k * 0.618034) % 1.0, 0.85, 0.95)
    return "#%02x%02x%02x" % (round(r * 255), round(g * 255), round(b * 255))


SET_MASK = {"floor": "#202020", "wall": "#404040", "furniture": "#606060", "tree": "#305030"}


def _perf(pb) -> dict:
    out = {"actor": pb.actor, "profile": pb.profile, "primary": pb.primary, "intent": pb.intent,
           "gaze": pb.gaze.mode, "gaze_target": pb.gaze.target, "tension": pb.posture.tension,
           "openness": pb.posture.openness, "lean": pb.posture.lean, "micro": [[m.name, m.at] for m in pb.micro]}
    if pb.hands is not None:
        out["hands"] = pb.hands.action
    if pb.face is not None:
        out["jaw"], out["brows"], out["mouth"] = pb.face.jaw, pb.face.brows, pb.face.mouth
    if pb.animal is not None:
        out.update(ears=pb.animal.ears, tail=pb.animal.tail, tilt=pb.animal.head_tilt)
    return out


def _coverage(shot, ph: dict, start: float) -> tuple[str, float]:
    """Which part of its event's action a shot shows (Event -> action phases -> coverage), and from when:
    a wide shot shows it from the start; an insert of the thing or the hands, the moment of contact; the face of the
    one who acts, the act and what they do with it; a payoff or a reaction, what follows."""
    d = shot.duration_seconds
    if not ph or "contact" not in ph:
        return "moment", start
    c = ph["contact"]
    if shot.scale == "INSERT" or shot.attention in ("hands", "object"):
        return "contact", max(start, c - 0.55 * d)
    if shot.function in ("payoff", "reaction") or shot.relation == "subjective" and "approach" not in ph:
        return "after", max(start, ph.get("complete", c) - 0.3)
    if shot.function in ("reveal", "observe", "hide") and shot.scale in ("CU", "MCU", "ECU"):
        return "act", max(start, c - 0.35 * d)
    if shot.relation == "subjective":
        return "approach", max(start, ph.get("reach", c) - 0.6 * d)
    return "whole", start


def _place_of(entities: dict, who: str, t: float, tl) -> str:
    e = entities.get(who)
    if not e:
        return ""
    p = to_play(t, tl)
    cur = e["keys"][0]
    for k in e["keys"]:
        if k[0] <= p + 1e-6:
            cur = k
    return cur[1]


def export_scene(conn: sqlite3.Connection, trace: RuntimeTrace, packets: dict[str, ProductionPacket], out: Path) -> dict:
    places = []
    for p in packets.values():
        for s in p.shots:
            if s.location.id not in places:
                places.append(s.location.id)
    offset = {pl: i * SPACING for i, pl in enumerate(places)}
    keys = [(t, k) for t, k in trace.keyframes if k.place in places or k.place == ""]
    times = [t for t, _ in keys] + [x for i in trace.interactions for x in (i.start, i.contact, i.complete)]
    starts = [a.start for a in trace.actions] + [i.start for i in trace.interactions]
    tl = timeline(times, motion_spans(keys), anchor=min(starts) if starts else None)  # runtime seconds, shifted only
    # the scene starts from each entity's last key before its window (trace.keyframes leads with them)
    people = {r[0] for r in conn.execute("SELECT id FROM people")}
    animals = {r[0] for r in conn.execute("SELECT person_id FROM personas WHERE json_extract(traits, '$.species') "
                                          "IS NOT NULL AND json_extract(traits, '$.species') <> 'human'")}
    entities: dict[str, dict] = {}
    for t, k in sorted(keys, key=lambda x: x[0]):
        e = entities.setdefault(k.entity, {"id": k.entity, "kind": "animal" if k.entity in animals else
                                           "person" if k.entity in people else "thing", "keys": []})
        dx = offset.get(k.place, 0.0)
        e["keys"].append([round(to_play(t, tl), 4), k.place, round(k.x + dx, 4), k.y, k.yaw, k.pose] +
                         ([k.holder] if k.pose in ("carried", "lift") else []))
    cast = [r[0] for r in conn.execute("SELECT id FROM people ORDER BY id")]
    for n, e in enumerate(sorted(entities.values(), key=lambda e: e["id"])):
        e["mask"] = mask_color(n)
        if e["kind"] == "thing":
            e["asset"] = thing_asset(e["id"])
            continue
        # every person in the world keeps one colour, as far from everybody else's as the golden angle puts it
        e["hue"] = round(cast.index(e["id"]) * GOLDEN % 360, 1) if e["id"] in cast else 210.0
        row = conn.execute("SELECT name FROM people WHERE id = ?", (e["id"],)).fetchone()
        e["name"] = row[0] if row else e["id"]
        e["capsule"] = CAPSULE[e["kind"]]
        e["sockets"] = ["mouth", "head"] if e["kind"] == "animal" else ["hand.R", "hand.L", "head", "look_at"]
    for st in trace.steps:  # footfalls: where each foot is planted, and when
        if st.entity in entities and st.place in offset:
            entities[st.entity].setdefault("steps", []).append(
                [round(to_play(st.land, tl), 4), round(to_play(st.lift, tl), 4), st.foot,
                 round(st.x + offset[st.place], 4), st.y])
    handoffs = sorted(({"t": round(to_play(i.contact, tl), 4), "start": round(to_play(i.start, tl), 4),
                        "complete": round(to_play(i.complete, tl), 4),
                        "actor": i.actor, "action": i.action, "thing": i.target, "hand": i.hand, "event": i.event_id}
                       for i in trace.interactions), key=lambda h: (h["t"], h["actor"]))
    tracks = [{"event": k.event_id, "actor": k.actor, "action": k.action, "thing": k.target, "socket": k.socket,
               "parent": k.parent, "approach": round(to_play(k.approach_start, tl), 4),
               "reach": round(to_play(k.reach_start, tl), 4), "contact": round(to_play(k.contact, tl), 4),
               "complete": round(to_play(k.complete, tl), 4),
               "sniff": round(to_play(k.sniff, tl), 4) if k.sniff >= 0 else None,
               "point": [round(k.point[0] + offset.get(_place_of(entities, k.actor, k.contact, tl), 0.0), 4),
                         k.point[1], k.point[2]]}
              for k in trace.tracks]
    # the runtime's own order of things, for the fidelity check (what an engine must trigger, in this order)
    motions = sorted(({"t": round(to_play(a.start, tl), 4), "end": round(to_play(a.end, tl), 4), "actor": a.actor,
                       "kind": a.kind, "target": a.target, "event": a.event_id}
                      for a in trace.actions if a.kind in ORDER_MOTION and (a.place in places or a.place == "")),
                     key=lambda m: (m["t"], m["actor"], m["kind"]))
    span = {}
    for m in motions:
        a, b = span.get(m["event"], (m["t"], m["end"]))
        span[m["event"]] = (min(a, m["t"]), max(b, m["end"]))
    for h in handoffs:
        a, b = span.get(h["event"], (h["start"], h["t"]))
        span[h["event"]] = (min(a, h["start"]), max(b, h["t"] + 0.4))
    # event times with no motion (a thought, a discovery alone): the moment itself
    ev_time = {eid: to_play(ts * 60.0, tl) for eid, ts in conn.execute(
        f"SELECT event_id, timestamp FROM events WHERE event_id IN ({','.join('?' * len(trace.event_ids))})",
        trace.event_ids)} if trace.event_ids else {}
    # each event's action phases on the playback clock: the walk towards, the reach, contact, and what comes after
    phases: dict[int, dict] = {}
    for k in trace.tracks:
        ph = phases.setdefault(k.event_id, {})
        if k.action == "drop":
            ph.setdefault("contact", to_play(k.contact, tl))
            continue
        ph["approach"] = to_play(k.approach_start, tl)
        ph["reach"] = to_play(k.reach_start, tl)
        ph["contact"] = to_play(k.contact, tl)
        ph["complete"] = to_play(k.complete, tl)
    for m in motions:
        ph = phases.setdefault(m["event"], {})
        if m["kind"] == "walk_to" and "complete" in ph and m["t"] >= ph["complete"] - 1e-6:
            ph.setdefault("after", m["t"])
    cuts = {}
    for name, packet in packets.items():
        by_event: dict[int, list] = {}
        for s in packet.shots:
            by_event.setdefault(s.event_id, []).append(s)
        last: dict[int, float] = {}
        rows = []
        for s in packet.shots:
            a, _b = span.get(s.event_id, (ev_time.get(s.event_id, 0.0), ev_time.get(s.event_id, 0.0)))
            a = max(0.0, a - 0.4)  # a breath before the moment
            phase, start = _coverage(s, phases.get(s.event_id, {}), a)
            start = max(start, last.get(s.event_id, -1e9))  # coverage runs forward: never back in time within a beat
            last[s.event_id] = start
            rows.append({
                "phase": phase,
                "film_start": s.start_seconds, "film_end": round(s.start_seconds + s.duration_seconds, 3),
                "t_start": round(start, 4), "t_end": round(start + s.duration_seconds, 4), "event": s.event_id,
                "place": s.location.id, "offset": offset.get(s.location.id, 0.0),
                "subject": s.subject_id, "scale": s.scale or "MS", "angle": s.angle or "eye_level",
                "relation": s.relation or "frontal", "motion": s.camera.movement, "focal": s.focalizer,
                "function": s.function, "info": s.information_function, "step": s.grammar_step,
                "performances": [_perf(pb) for pb in s.performances],
                "hidden": [c.id for c in s.characters if c.role == "actor"] if s.function == "hide" else [],
            })
        cuts[name] = {"shots": rows, "film_duration": round(packet.shots[-1].start_seconds +
                                                            packet.shots[-1].duration_seconds, 3) if packet.shots else 0}
    geometry = []
    from runtime.nav import blocks
    for pl in places:
        lay = LAYOUTS[template_for(pl)]
        for o in lay["objects"]:
            cls = "wall" if o.kind in ("wall", "window", "door") else "tree" if o.kind == "tree" else "furniture"
            # the visual (a box now; a model later) and the collision proxy are separate on purpose
            geometry.append({"id": o.id, "place": pl, "kind": o.kind, "x": o.position[0] + offset[pl], "y": o.position[1],
                             "z": o.position[2], "w": o.size[0], "d": o.size[1], "h": o.size[2], "yaw": o.yaw,
                             "visual": {"asset": "box"}, "mask": SET_MASK[cls],
                             "collision": {"shape": "box", "blocks": blocks(o), "blocks_sight": o.blocks_sight}})
    doc = {"version": trace.version, "trace_hash": trace.trace_hash, "places": [{"id": p, "offset": offset[p]} for p in places],
           "geometry": geometry, "entities": sorted(entities.values(), key=lambda e: e["id"]), "handoffs": handoffs,
           "tracks": tracks, "motions": motions, "cuts": cuts, "set_mask": SET_MASK,
           "duration": round(max([tl[-1][1] if tl else 0.0] + [r["t_end"] for c in cuts.values() for r in c["shots"]]) + 1, 3)}
    from runtime.camera import solve
    doc["camera_summary"] = solve(doc)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    return doc
