"""The director's camera, solved in space before anything is drawn: CameraShot -> a camera move (a small DSL) -> a
deterministic trajectory any engine plays (three.js, Blender, a video model's camera track).

For every cut the solver asks "can this shot physically exist?": the camera must be inside the room, not inside a
table, a wall, a tree or a person, and see its subject without a wall, a tree or somebody else in between, at the
start, the middle and the end of the shot. It tries the shot as written, then the same shot turned round the subject
(25, 50, ... 180 degrees), then closer, then the room's camera mounts. The chosen solution is kept for the whole shot,
so the camera never jumps inside a shot. A shot nothing can stage is marked `legal: false`, never silently faked.

Coordinates are the runtime's: x right, y into the room, z up, metres. Keys are in film seconds at KEY_RATE.
"""
from __future__ import annotations

import math

from runtime.export import _index, sample_full

KEY_RATE = 10  # camera keys per second of film
DIST = {"EWS": 9.0, "WS": 6.0, "MS": 2.8, "MCU": 1.7, "CU": 1.15, "ECU": 0.8, "INSERT": 0.7}
FOV = {"EWS": 60, "WS": 55, "MS": 45, "MCU": 38, "CU": 32, "ECU": 28, "INSERT": 30}  # vertical, degrees
EYE = {"person": 1.6, "animal": 0.47, "thing": 0.1}
TURNS = (0, 25, -25, 50, -50, 75, -75, 100, -100, 140, -140, 180)
BODY = {"person": (0.25, 1.85), "animal": (0.45, 0.62)}  # an animal is long: its radius covers the head


def move_of(cut: dict) -> dict:
    """The CameraShot's motion as a primitive with parameters (the DSL a trajectory is compiled from)."""
    m = cut.get("motion") or "static"
    if "push_in" in m:
        return {"primitive": "push_in", "amount": 0.28}
    if m == "pull_out":
        return {"primitive": "pull_out", "from": 0.7}
    if m == "handheld":
        return {"primitive": "handheld", "amplitude": [0.03, 0.025, 0.03], "rates": [17, 13, 11]}
    if m == "tracking":
        return {"primitive": "tracking", "lateral": 0.8}
    return {"primitive": "static"}


def _hits(a, b, lo, hi) -> bool:
    """Does the segment a-b pass through the box lo-hi (not counting its last 5%, where the subject is)?"""
    t0, t1 = 0.0, 1.0
    for i in range(3):
        d = b[i] - a[i]
        if abs(d) < 1e-9:
            if a[i] < lo[i] or a[i] > hi[i]:
                return False
            continue
        ta, tb = (lo[i] - a[i]) / d, (hi[i] - a[i]) / d
        if ta > tb:
            ta, tb = tb, ta
        t0, t1 = max(t0, ta), min(t1, tb)
        if t0 > t1:
            return False
    return t1 > 0.02 and t0 < 0.95


def _box(g: dict, pad: float = 0.0):
    w, d = g["w"], g["d"]
    if abs((g.get("yaw") or 0) % 180) == 90:
        w, d = d, w
    z = g.get("z", 0.0)
    return ((g["x"] - w / 2 - pad, g["y"] - d / 2 - pad, z), (g["x"] + w / 2 + pad, g["y"] + d / 2 + pad, z + g["h"] + pad))


class Stage:
    def __init__(self, doc: dict) -> None:
        self.doc = doc
        self.by = {e["id"]: e for e in doc["entities"]}
        self.sight: dict[str, list] = {}
        self.solid: dict[str, list] = {}
        self.rooms: dict[str, tuple] = {}
        for g in doc["geometry"]:
            col = g.get("collision", {})
            if g["kind"] in ("window", "door") or g["h"] < 0.05:
                continue
            if col.get("blocks_sight", True) and g["h"] > 1.2:  # tables and benches do not hide a standing body
                self.sight.setdefault(g["place"], []).append(_box(g))
            self.solid.setdefault(g["place"], []).append(_box(g, 0.12))
            if g["kind"] == "wall":
                r = self.rooms.get(g["place"], (math.inf, -math.inf, math.inf, -math.inf))
                self.rooms[g["place"]] = (min(r[0], g["x"]), max(r[1], g["x"]), min(r[2], g["y"]), max(r[3], g["y"]))

    # -- where things are ---------------------------------------------------------------------------------------------
    def body(self, eid: str, t: float):
        """(x, y, yaw, kind, place, visible) of an entity at world time t."""
        e = self.by.get(eid)
        if e is None or not e["keys"]:
            return None
        k = e["keys"][max(0, _index(e["keys"], t))]
        s = sample_full(self.doc, eid, t)
        if e["kind"] == "thing" and k[5] in ("carried", "lift") and len(k) > 6 and k[6] in self.by:
            h = self.body(k[6], t)
            if h is None:
                return None
            a = math.radians(h[2])
            up = 0.85 if h[3] == "person" else 0.42
            return h[0] + 0.3 * math.cos(a), h[1] + 0.3 * math.sin(a), h[2], "thing", h[4], True, up
        return s[0], s[1], s[2], e["kind"], k[1], k[5] != "offstage", 0.03 if e["kind"] == "thing" else 0.0

    def mounts(self, place: str) -> list[tuple[float, float, float]]:
        r = self.rooms.get(place)
        if r is None:
            off = next((p["offset"] for p in self.doc["places"] if p["id"] == place), 0.0)
            return [(off - 2, -2, 3.5), (off + 16, -2, 3.5), (off - 2, 14, 3.5), (off + 16, 14, 3.5)]
        return [(r[0] + 0.5, r[2] + 0.5, 2.4), (r[1] - 0.5, r[2] + 0.5, 2.4), (r[0] + 0.5, r[3] - 0.5, 2.4),
                (r[1] - 0.5, r[3] - 0.5, 2.4)]

    def clamp(self, p, place):
        r = self.rooms.get(place)
        if r is None:
            return p
        return (min(max(p[0], r[0] + 0.4), r[1] - 0.4), min(max(p[1], r[2] + 0.4), r[3] - 0.4), p[2])

    def legal(self, pos, look, place, t, keep) -> tuple[bool, str]:
        """Can a camera stand here and see that? (why not, if not)"""
        for lo, hi in self.solid.get(place, []):
            if lo[0] < pos[0] < hi[0] and lo[1] < pos[1] < hi[1] and pos[2] < hi[2]:
                return False, "inside a solid"
        for lo, hi in self.sight.get(place, []):
            if _hits(pos, look, lo, hi):
                return False, "a wall or a tree in the way"
        for eid, e in self.by.items():
            if e["kind"] == "thing":
                continue
            b = self.body(eid, t)
            if b is None or not b[5] or b[4] != place:
                continue
            r, top = BODY[b[3]]
            if eid in keep:  # the subject may fill the frame, but the camera is never inside it
                if math.hypot(pos[0] - b[0], pos[1] - b[1]) < r + 0.2 and pos[2] < top + 0.1:
                    return False, f"inside {eid}"
                continue
            if math.hypot(pos[0] - b[0], pos[1] - b[1]) < r + 0.1 and pos[2] < top + 0.1:
                return False, f"inside {eid}"
            if _hits(pos, look, (b[0] - r, b[1] - r, 0.0), (b[0] + r, b[1] + r, top)):
                return False, f"{eid} in the way"
        return True, ""


def _frame(st: Stage, cut: dict, t: float, local: float, turn: float, closer: float):
    """(camera position, look-at point) for a cut at world time t and 0..1 through it, turned and moved closer."""
    subj = st.body(cut["subject"], t)
    if subj is None:
        off = cut.get("offset", 0.0)
        return (off + 6, -4, 3), (off + 6, 4, 1)
    x, y, yaw, kind, place, _vis, lift = subj
    setup = st.body(cut["subject"], cut["t_start"])  # the set-up is fixed when the shot starts: if the subject turns
    yaw = setup[2] if setup else yaw                  # away, it turns away from the camera, the camera does not orbit
    eye = EYE[kind] if kind != "thing" else 0.1
    # framing is relative to the subject's size: a close-up of a dog is closer than one of a person
    dist = DIST.get(cut["scale"], 2.8) * closer * (0.7 if kind == "animal" and cut["scale"] != "INSERT" else 1.0)
    height = eye
    if cut["angle"] == "high":
        height = eye + 1.6
    elif cut["angle"] == "low":
        height = 0.6
    elif cut["angle"] == "ground":
        height = 0.35
    mv = move_of(cut)
    if mv["primitive"] == "push_in":
        dist *= 1 - mv["amount"] * local
    elif mv["primitive"] == "pull_out":
        dist *= mv["from"] + (1 - mv["from"]) * local
    a = math.radians(yaw + turn)
    fwd, side = (math.cos(a), math.sin(a)), (math.sin(a), -math.cos(a))  # side: the subject's right
    # where the lens aims: the eyes in a close shot, the chest in a medium one, the middle of the body in a wide one
    aim = {"ECU": 1.02, "CU": 1.02, "MCU": 0.97, "MS": 0.85, "WS": 0.6, "EWS": 0.55}.get(cut["scale"], 0.85)
    look = (x, y, lift + (0.05 if cut["scale"] == "INSERT" else eye * aim))
    rel = cut.get("relation") or "frontal"
    if rel == "subjective" and cut.get("focal") in st.by:
        f = st.body(cut["focal"], t)
        fa = math.radians(f[2])
        pos = (f[0] + 0.15 * math.cos(fa), f[1] + 0.15 * math.sin(fa), EYE[f[3]])
        if math.dist(pos, look) < 0.3:  # the thing is in its own mouth (or hands): look down at it and ahead
            look = (pos[0] + 0.8 * math.cos(fa), pos[1] + 0.8 * math.sin(fa), 0.0)
        return pos, look
    if rel == "profile":
        pos = (x + side[0] * dist, y + side[1] * dist, height)
    elif rel == "rear":
        pos = (x - fwd[0] * dist, y - fwd[1] * dist, height)
    elif rel == "over_shoulder" and cut.get("focal") in st.by and cut["focal"] != cut["subject"]:
        f = st.body(cut["focal"], t)
        v = (f[0] - x, f[1] - y)
        n = math.hypot(*v) or 1.0
        pos = (f[0] + 0.6 * v[0] / n + 0.35 * side[0], f[1] + 0.6 * v[1] / n + 0.35 * side[1], EYE[f[3]] + 0.15)
    elif rel == "two_shot":
        pos = (x + fwd[0] * dist * 1.3 + side[0] * 0.6, y + fwd[1] * dist * 1.3 + side[1] * 0.6, height)
    else:
        pos = (x + fwd[0] * dist + side[0] * dist * 0.25, y + fwd[1] * dist + side[1] * dist * 0.25, height)
    if mv["primitive"] == "handheld":
        am, rt = mv["amplitude"], mv["rates"]
        pos = (pos[0] + math.sin(local * rt[0]) * am[0], pos[1] + math.sin(local * rt[2]) * am[2],
               pos[2] + math.cos(local * rt[1]) * am[1])
    elif mv["primitive"] == "tracking":
        pos = (pos[0] + side[0] * (-mv["lateral"] / 2 + mv["lateral"] * local),
               pos[1] + side[1] * (-mv["lateral"] / 2 + mv["lateral"] * local), pos[2])
    return st.clamp(pos, place), look


def solve_cut(st: Stage, cut: dict) -> dict:
    from runtime.export import holder_at
    samples = [(cut["t_start"], 0.0), ((cut["t_start"] + cut["t_end"]) / 2, 0.5), (max(cut["t_start"], cut["t_end"] - 1e-3), 1.0)]
    # the subject, whose eyes these are, and whoever holds the subject (the hands or mouth are part of an insert)
    keep = [cut["subject"], cut.get("focal") or ""] + [holder_at(st.doc, cut["subject"], t) for t, _ in samples]
    subj = st.body(cut["subject"], cut["t_start"])
    place = subj[4] if subj else cut["place"]
    best = None
    if (cut.get("relation") or "") == "subjective":
        return {"turn": 0, "closer": 1.0, "mount": None, "legal": True, "why": "through their eyes", "seen": 1.0}
    for closer in (1.0, 0.7, 0.5):
        for turn in TURNS:
            ok = [st.legal(*_frame(st, cut, t, loc, turn, closer), place, t, keep) for t, loc in samples]
            seen = sum(o for o, _ in ok) / len(ok)
            if best is None or seen > best["seen"]:
                best = {"turn": turn, "closer": closer, "mount": None, "legal": seen == 1.0, "seen": seen,
                        "why": "as written" if turn == 0 and closer == 1.0 else
                        f"turned {turn} degrees round the subject" + (f", {closer:.1f} of the distance" if closer < 1 else ""),
                        "blocked": [w for o, w in ok if not o][:1]}
            if seen == 1.0:
                return best
    if place not in st.rooms:  # open ground: step back rather than jump to a far corner
        for closer in (1.4, 2.0, 3.0):
            for turn in TURNS:
                ok = [st.legal(*_frame(st, cut, t, loc, turn, closer), place, t, keep) for t, loc in samples]
                if all(o for o, _ in ok):
                    return {"turn": turn, "closer": closer, "mount": None, "legal": True, "seen": 1.0,
                            "why": f"stepped back to {closer:.1f} of the distance, turned {turn} degrees"}
    for m in st.mounts(place):  # the room's camera mounts, high in its corners
        ok = [st.legal(m, _frame(st, cut, t, loc, 0, 1.0)[1], place, t, keep) for t, loc in samples]
        if all(o for o, _ in ok):
            return {"turn": 0, "closer": 1.0, "mount": list(m), "legal": True, "seen": 1.0,
                    "why": "no clear angle close in: from the room's camera mount"}
    best["legal"] = False
    return best


def solve(doc: dict) -> dict:
    """Adds a `camera` to every cut of every version: the move (DSL), the solution and the keys
    [[film_t, px, py, pz, lx, ly, lz]], and returns a summary."""
    st = Stage(doc)
    illegal, turned, mounted = 0, 0, 0
    for cuts in doc["cuts"].values():
        for cut in cuts["shots"]:
            sol = solve_cut(st, cut)
            keys = []
            n = max(2, int(round((cut["film_end"] - cut["film_start"]) * KEY_RATE)) + 1)
            for k in range(n):
                local = k / (n - 1)
                t = cut["t_start"] + (cut["t_end"] - cut["t_start"]) * local
                pos, look = _frame(st, cut, t, local, sol["turn"], sol["closer"])
                if sol["mount"]:
                    pos = tuple(sol["mount"])
                keys.append([round(cut["film_start"] + (cut["film_end"] - cut["film_start"]) * local, 4),
                             *[round(v, 4) for v in pos], *[round(v, 4) for v in look]])
            eyes = cut.get("relation") == "subjective"  # through somebody's eyes: wide, as eyes see
            fov = (70 if st.by.get(cut.get("focal") or "", {}).get("kind") == "animal" else 60) if eyes \
                else FOV.get(cut["scale"], 45)
            cut["camera"] = {"move": move_of(cut), "fov": fov, "solution": sol, "keys": keys}
            illegal += not sol["legal"]
            turned += sol["turn"] != 0 or sol["closer"] != 1.0
            mounted += bool(sol["mount"])
    return {"shots": sum(len(c["shots"]) for c in doc["cuts"].values()), "illegal": illegal, "re_angled": turned,
            "from_mount": mounted}
