"""Physical plausibility of a scene (runtime/stage.py), measured by the rule every engine plays (runtime_rule.js and
runtime/export.py:sample): does anyone walk through a wall, a bench or somebody else, jump, snap round, or take hold
of a thing out of reach? The same numbers are reported for the whole world clock and for what is on screen.

    python -m runtime.physics out/sandbox/wallet.json
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

FPS = 30
RADIUS = {"person": 0.22, "animal": 0.2}  # the body's collision capsule, seen from above
MAX_SPEED = 2.6  # m/s: faster than this within a place is a jump
MAX_TURN = 720.0  # degrees per second (two full turns): faster is a snap
REACH = 0.75  # how far from the body's centre a hand or mouth can take hold of something on the floor
MOVING = ("walk", "turn", "rise", "settle", "lift", "fall")


def _at(e: dict, t: float, by_id: dict, doc: dict) -> tuple[float, float, float, str, str] | None:
    """(x, y, yaw, pose, place) at world time t, by the shared rule (runtime/export.py:sample_full)."""
    from runtime.export import _index, sample_full
    keys = e["keys"]
    if not keys:
        return None
    k = keys[max(0, _index(keys, t))]
    s = sample_full(doc, e["id"], t)
    place = k[1]
    if k[5] in ("carried", "lift") and len(k) > 6 and k[6] in by_id:
        hk = by_id[k[6]]["keys"]
        place = hk[max(0, _index(hk, t))][1]
    return s[0], s[1], s[2], k[5], place


def _sample_times(doc: dict) -> list[float]:
    """Where to look: every frame while something moves, and both sides of every key (so a jump at a key, over one
    millisecond, is seen). Nothing changes in between. The playback clock is runtime time and a scene can span days,
    so sampling the whole of it at 30 fps would look at millions of frames where nobody moves."""
    out = set()
    for e in doc["entities"]:
        keys = e["keys"]
        for a, b in zip(keys, keys[1:]):
            out.update((round(a[0] - 1e-3, 4), a[0]))
            if a[5] in MOVING and b[0] > a[0]:
                n = int((b[0] - a[0]) * FPS)
                out.update(round(a[0] + k / FPS, 4) for k in range(1, n + 1))
        if keys:
            out.update((round(keys[-1][0] - 1e-3, 4), keys[-1][0]))
    return sorted(out)


def _inside(x: float, y: float, box: dict, pad: float) -> bool:
    w, d = box["w"], box["d"]
    if abs((box.get("yaw") or 0) % 180) == 90:
        w, d = d, w
    return abs(x - box["x"]) < w / 2 + pad and abs(y - box["y"]) < d / 2 + pad


def _on_screen(doc: dict, t: float, place: str) -> bool:
    return any(s["t_start"] <= t < s["t_end"] and s["place"] == place for c in doc["cuts"].values() for s in c["shots"])


def audit(doc: dict) -> dict:
    by_id = {e["id"]: e for e in doc["entities"]}
    solid = [g for g in doc["geometry"] if (g.get("collision", {"blocks": g["h"] > 0.4 and g["kind"] not in
                                                                   ("window", "door", "platform", "perch")})["blocks"])]
    bodies = [e for e in doc["entities"] if e["kind"] != "thing"]
    things = [e for e in doc["entities"] if e["kind"] == "thing"]
    found: dict[str, list] = {k: [] for k in ("jump", "snap_turn", "in_obstacle", "body_overlap", "thing_in_obstacle",
                                             "reach_gap")}
    prev: dict[str, tuple] = {}
    for t in _sample_times(doc):
        now = {}
        for e in bodies:
            s = _at(e, t, by_id, doc)
            if s is None or s[3] == "offstage":
                prev.pop(e["id"], None)
                continue
            now[e["id"]] = s + (t,)
            p = prev.get(e["id"])
            if p is not None and p[4] == s[4] and t > p[5]:
                dt = t - p[5]
                v = math.hypot(s[0] - p[0], s[1] - p[1]) / dt
                if v > MAX_SPEED:
                    found["jump"].append((round(t, 3), e["id"], round(v * dt, 3), s[4]))
                dyaw = abs((s[2] - p[2] + 540) % 360 - 180) / dt
                if dyaw > MAX_TURN:
                    found["snap_turn"].append((round(t, 3), e["id"], round(dyaw * dt, 1), s[4]))
            r = RADIUS[e["kind"]]
            for g in solid:
                if g["place"] == s[4] and s[3] not in ("sit", "rise", "settle") and _inside(s[0], s[1], g, r * 0.6):
                    found["in_obstacle"].append((round(t, 3), e["id"], g["id"], s[4]))
        ids = sorted(now)
        for a in range(len(ids)):
            for b in range(a + 1, len(ids)):
                sa, sb = now[ids[a]], now[ids[b]]
                if sa[4] != sb[4]:
                    continue
                d = math.hypot(sa[0] - sb[0], sa[1] - sb[1])
                lim = (RADIUS[by_id[ids[a]]["kind"]] + RADIUS[by_id[ids[b]]["kind"]]) * 0.9
                if d < lim:
                    found["body_overlap"].append((round(t, 3), ids[a], ids[b], round(d, 3), sa[4]))
        for e in things:
            s = _at(e, t, by_id, doc)
            if s is None or s[3] != "on_floor":
                continue
            for g in solid:
                if g["place"] == s[4] and _inside(s[0], s[1], g, 0.02):
                    found["thing_in_obstacle"].append((round(t, 3), e["id"], g["id"], s[4]))
        prev.update(now)
    for h in doc["handoffs"]:
        if h["action"] != "pickup":
            continue
        thing, body = by_id.get(h["thing"]), by_id.get(h["actor"])
        if thing is None or body is None:
            continue
        before = _at(thing, h["t"] - 1e-3, by_id, doc)
        who = _at(body, h["t"], by_id, doc)
        if before and who:
            gap = math.hypot(before[0] - who[0], before[1] - who[1])
            if gap > REACH:
                found["reach_gap"].append((h["t"], h["actor"], h["thing"], round(gap, 3), who[4]))
    report = {}
    for k, rows in found.items():
        # count distinct incidents (a run of frames with the same entities is one)
        incidents, last = [], {}
        for r in rows:
            key = (k,) + tuple(x for x in r[1:] if isinstance(x, str))
            if key in last and r[0] - last[key] <= 2.0 / FPS:
                last[key] = r[0]
                continue
            last[key] = r[0]
            incidents.append(r)
        report[k] = {"incidents": len(incidents), "frames": len(rows),
                     "on_screen": sum(1 for r in incidents if _on_screen(doc, r[0], r[-1])),
                     "examples": incidents[:60]}
    report["ok"] = all(v["incidents"] == 0 for v in report.values() if isinstance(v, dict))
    return report


if __name__ == "__main__":
    r = audit(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")))
    for k, v in r.items():
        print(k, v if not isinstance(v, dict) else f"{v['incidents']} incidents ({v['on_screen']} on screen), "
              f"{v['frames']} frames  e.g. {v['examples'][:3]}")
