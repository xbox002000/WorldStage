from __future__ import annotations

import json
import random
import sqlite3

from narrative.arcs import Ev
from narrative.selector import Candidate

SPEC_VERSION = 1
WEATHER = ("clear", "cloudy", "rain", "fog")

# (event type, tone) -> (actor action, target action, actor emotion, target emotion, shot, camera move, seconds)
BEATS = {
    ("talk", "warm"): ("chat_warmly", "listen_happily", "warm", "happy", "two_shot", "static", 4),
    ("talk", "neutral"): ("talk", "listen", "calm", "calm", "wide", "static", 3),
    ("talk", "cold"): ("speak_coldly", "flinch", "distant", "hurt", "medium", "slow_push_in", 4),
    ("talk", "hostile"): ("confront", "recoil", "angry", "angry", "close_up", "slow_push_in", 5),
    ("steal", None): ("take_object", "notice_loss", "tense", "shocked", "insert", "static", 4),
}


def asset_ids(person_id: str) -> str:
    """Stable per-person asset id: the same character always maps to the same face/costume/voice."""
    return f"char_{person_id}"


def _clock(ts: int) -> str:
    m = ts % 1440
    return f"{m // 60:02d}:{m % 60:02d}"


def _weather(world_seed: str, day: int) -> str:
    return random.Random(f"{world_seed}:{day}:weather").choice(WEATHER)


def _shot(conn: sqlite3.Connection, ev: Ev, names: dict[str, str], seed: str, index: int) -> dict:
    tone = ev.truth.get("tone") if ev.type == "talk" else None
    a_act, t_act, a_emo, t_emo, shot_type, move, seconds = BEATS.get((ev.type, tone), BEATS[("talk", "neutral")])
    if ev.flipped:
        seconds += 2
    loc = conn.execute("SELECT * FROM locations WHERE id = ?", (ev.location_id,)).fetchone()
    characters = []
    for pid, role in ev.participants:
        if role == "actor":
            action, emotion, pos = a_act, a_emo, "left"
        elif role in ("target", "victim"):
            action, emotion, pos = t_act, t_emo, "right"
        else:
            action, emotion, pos = "watch", "uneasy", "background"
        characters.append({"id": pid, "name": names[pid], "asset_id": asset_ids(pid), "role": role,
                           "position": pos, "action": action, "emotion": emotion})
    thoughts = [
        {"person": r["observer_id"], "belief": r["belief"], "confidence": r["confidence"]}
        for r in conn.execute(
            "SELECT observer_id, belief, confidence FROM memories WHERE event_id = ? AND confidence >= 0.9 "
            "ORDER BY memory_id", (ev.id,))
    ]
    prop = ev.truth.get("object")
    prop_name = None
    if prop:
        prop_name = conn.execute("SELECT name FROM objects WHERE id = ?", (prop,)).fetchone()[0]
    return {
        "shot_id": f"s{index:02d}",
        "event_id": ev.id,
        "event_type": ev.type,
        "location": {"id": loc["id"], "name": loc["name"], "asset_id": f"loc_{loc['id']}", "x": loc["x"], "y": loc["y"]},
        "time": {"day": ev.day + 1, "clock": _clock(ev.ts)},
        "weather": _weather(seed, ev.day),
        "characters": characters,
        "props": [{"id": prop, "name": prop_name, "asset_id": f"prop_{prop}"}] if prop else [],
        "camera": {"shot_type": shot_type, "movement": move},
        "duration_seconds": seconds,
        "motivation": ev.truth.get("reason") if ev.truth.get("source") else None,
        "inner_thoughts": thoughts,
        "trust_flipped": ev.flipped,
    }


def build_scene(conn: sqlite3.Connection, cand: Candidate, names: dict[str, str], seed: str, number: int) -> dict:
    events = cand.arc.events
    peak = cand.arc.peak
    shots = [_shot(conn, e, names, seed, i) for i, e in enumerate(events)]
    actor, target = peak.people[0], peak.people[1] if len(peak.people) > 1 else peak.people[0]
    people = list(dict.fromkeys(p for e in events for p in e.people))
    props = list(dict.fromkeys(pr["id"] for s in shots for pr in s["props"]))
    return {
        "scene_id": f"scene_{number:02d}",
        "title": f"{names[actor]} 與 {names[target]}",
        "score": cand.score,
        "score_breakdown": cand.breakdown,
        "peak_event_id": peak.id,
        "arc_event_ids": list(cand.arc.ids),
        "assets": {
            "characters": {p: {"asset_id": asset_ids(p), "name": names[p]} for p in people},
            "locations": {s["location"]["id"]: s["location"]["asset_id"] for s in shots},
            "props": {p: f"prop_{p}" for p in props},
        },
        "shots": shots,
        "total_seconds": sum(s["duration_seconds"] for s in shots),
    }


def build_spec(conn: sqlite3.Connection, chosen: list[Candidate]) -> dict:
    names = {r["id"]: r["name"] for r in conn.execute("SELECT id, name FROM people")}
    seed = conn.execute("SELECT value FROM meta WHERE key = 'world_seed'").fetchone()[0]
    spec = {
        "version": SPEC_VERSION,
        "world_seed": seed,
        "map": {
            "locations": [dict(r) for r in conn.execute("SELECT id, name, x, y FROM locations ORDER BY id")],
            "edges": [[r[0], r[1]] for r in conn.execute(
                "SELECT from_location_id, to_location_id FROM location_edges WHERE from_location_id < to_location_id "
                "ORDER BY 1, 2")],
        },
        "scenes": [build_scene(conn, c, names, seed, i + 1) for i, c in enumerate(chosen)],
    }
    validate_spec(conn, spec)
    return spec


def validate_spec(conn: sqlite3.Connection, spec: dict) -> None:
    """Every id must exist in the world and each person must map to exactly one asset id."""
    people = {r["id"] for r in conn.execute("SELECT id FROM people")}
    locations = {r["id"] for r in conn.execute("SELECT id FROM locations")}
    event_ids = {r["event_id"] for r in conn.execute("SELECT event_id FROM events")}
    seen_assets: dict[str, str] = {}
    for scene in spec["scenes"]:
        for shot in scene["shots"]:
            if shot["event_id"] not in event_ids:
                raise ValueError(f"unknown event {shot['event_id']}")
            if shot["location"]["id"] not in locations:
                raise ValueError(f"unknown location {shot['location']['id']}")
            for ch in shot["characters"]:
                if ch["id"] not in people:
                    raise ValueError(f"unknown person {ch['id']}")
                if seen_assets.setdefault(ch["id"], ch["asset_id"]) != ch["asset_id"]:
                    raise ValueError(f"{ch['id']} maps to two assets")
        declared = set(scene["assets"]["characters"])
        used = {ch["id"] for s in scene["shots"] for ch in s["characters"]}
        if used - declared:
            raise ValueError(f"characters missing from assets: {used - declared}")


def dumps(spec: dict) -> str:
    return json.dumps(spec, ensure_ascii=False, indent=2)
