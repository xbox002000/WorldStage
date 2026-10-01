"""Scenes: what a viewer would call "a moment" — one person says something, the other answers, it heats up or calms
down, someone walks out or steps in. A read model over events, for the God View's list of what is worth watching.

A scene is an opening social event (talk, tell, confront, accuse) and the answers that follow it at once (events
whose reason is reply:* or intervene:*, see agent/reply.py). Everything in it is an event id; nothing is invented.
"""
from __future__ import annotations

import json
import sqlite3

CORE_OPENERS = ("talk", "tell", "confront", "accuse", "lend", "repay")
TONE_HEAT = {"warm": 0, "neutral": 1, "cold": 2, "hostile": 3}
KIND_HEAT = {"confront": 2, "accuse": 3}


def openers() -> tuple[str, ...]:
    from world.domains import styles
    return CORE_OPENERS + tuple(k for k, s in styles().items() if s.opens_scene)


OPENERS = CORE_OPENERS  # kept for callers; scenes() uses openers(), which adds the domains' (duel, ...)


def _heat(etype: str, t: dict) -> int:
    if etype == "talk":
        return TONE_HEAT.get(t.get("tone"), 1)
    from world.domains import style
    st = style(etype)
    return st.heat if st is not None else KIND_HEAT.get(etype, 1)


def _answer(etype: str, t: dict) -> bool:
    return (t.get("reason") or "").startswith(("reply:", "intervene:")) and etype in ("talk", "move")


def scenes(conn: sqlite3.Connection, first_day: int = 0, last_day: int | None = None, names: dict | None = None) -> list[dict]:
    names = names or {r[0]: r[1] for r in conn.execute("SELECT id, name FROM people")}
    hi = (last_day + 1) * 1440 if last_day is not None else 1 << 40
    out: list[dict] = []
    cur: dict | None = None
    for eid, ts, etype, place, truth, imp in conn.execute(
            "SELECT event_id, timestamp, type, location_id, truth, importance FROM events WHERE timestamp >= ? AND "
            "timestamp < ? ORDER BY event_id", (first_day * 1440, hi)):
        t = json.loads(truth)
        if cur is not None and _answer(etype, t) and ts - cur["last_ts"] <= 5:
            cur["events"].append(eid)
            cur["last_ts"] = ts
            stance = t["reason"].split(":", 1)[1]
            cur["stances"].append(stance)
            if etype == "talk":
                cur["heat"] = max(cur["heat"], _heat(etype, t))
                cur["hostile"] += t.get("tone") == "hostile"
            for p in (t.get("actor"), t.get("target")):
                if p and p not in cur["people"]:
                    cur["people"].append(p)
            cur["importance"] = max(cur["importance"], imp)
            cur["inner"] = max(cur["inner"], (t.get("dilemma") or {}).get("tension", 0.0))
            continue
        if etype in openers() and t.get("actor") and t.get("target"):
            cur = {"id": eid, "day": ts // 1440, "minute": ts % 1440, "place": place or "", "events": [eid],
                   "people": [t["actor"], t["target"]], "opener": etype, "stances": [], "last_ts": ts,
                   "heat": _heat(etype, t), "hostile": int(t.get("tone") == "hostile"), "importance": imp,
                   "outcome": t.get("outcome") or "", "inner": (t.get("dilemma") or {}).get("tension", 0.0)}
            out.append(cur)
        elif etype not in ("goal_change", "reflection"):  # after-effects do not break a scene; anything else does
            cur = None
    kept = []
    for s in out:
        turns = len(s["events"])
        if turns < 2 and s["heat"] < 2 and s["importance"] < 0.5:
            continue  # a passing word
        a, b = (names.get(p, p) for p in s["people"][:2])
        last = s["stances"][-1] if s["stances"] else ""
        if "storm_off" in s["stances"]:
            who = names.get(conn.execute("SELECT json_extract(truth, '$.actor') FROM events WHERE event_id = ?",
                                         (s["events"][-1],)).fetchone()[0], "")
            title = f"{a}和{b}鬧翻，{who}氣得走掉"
        elif s["opener"] == "accuse":
            title = f"{a}指控{b}" + ("，當場抓包" if s["outcome"] == "caught" else "，冤枉了人" if s["outcome"] == "false" else "")
        elif s["opener"] == "confront":
            title = f"{a}當面質問{b}"
        elif s["hostile"] >= 2:
            title = f"{a}和{b}吵起來了"
        elif last == "apologize":
            title = f"{b if len(s['stances']) % 2 else a}道歉了"
        elif "side" in s["stances"] or "comfort" in s["stances"]:
            title = f"{a}和{b}起衝突，有人出面"
        elif s["heat"] >= 2:
            title = f"{a}對{b}很冷淡"
        elif s["opener"] == "tell":
            title = f"{a}跟{b}說了一件事"
        else:
            title = f"{a}和{b}聊了起來"
        score = (2.0 * s["heat"] + 0.5 * turns + 3.0 * s["importance"] + 1.5 * ("storm_off" in s["stances"]) + 3.0 * s["inner"]
                 + 1.0 * any(x in s["stances"] for x in ("side", "comfort", "apologize")))
        kept.append({"id": s["id"], "day": s["day"], "minute": s["minute"], "place": s["place"], "people": s["people"],
                     "events": s["events"], "turns": turns, "heat": s["heat"], "stances": s["stances"], "inner": s["inner"],
                     "title": title, "score": round(score, 2)})
    return kept
