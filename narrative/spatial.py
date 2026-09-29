"""SceneSpec -> SpatialPlan: deterministic blocking, cameras and sight-line QA. No model, no randomness.

Rules, in order:
1. Principals (actor and target) sit at a table (or a bench pair) facing each other for quiet acts, and stand for
   loud ones (confront, accuse, a hostile word, a theft).
2. Witnesses take the next free seats or standing spots and face the actor. In the world they noticed the act, so
   the plan must give each of them a clear line of sight to the actor.
3. A lone act (taking, finding, losing, missing, cashing) puts the actor by the prop.
4. Cameras: a wide shot, a two-shot across the pair's axis, a single over the other's shoulder, and an insert on the
   prop. Each camera must see its subjects. If a position is blocked, the mirrored side is tried, then the corners.
A plan whose required sight lines cannot all be met is marked invalid and must not be sent to a video backend.
"""
from __future__ import annotations

import math

from contracts.scene_spec import Beat, SceneSpec
from contracts.spatial import BeatStaging, CameraShot, Placement, SightCheck, SpatialObject, SpatialPlan, finalize
from narrative.layouts import LAYOUTS, layout_ref

COMPILER_VERSION = "spatial-0.1"
BOUNDS = {"cafe": (10.0, 8.0), "office": (12.0, 8.0), "apartment": (9.0, 7.0), "park": (18.0, 14.0), "station": (16.0, 8.0)}
PRINCIPAL_ROLES = ("actor", "target", "victim", "suspect", "receiver", "addressee")
LOUD = ("confront", "accuse", "steal")
LONE = ("take", "find", "misplace", "notice_missing", "cash_prize", "give", "seed", "feed_pet")
EYE = 0.93  # eye height as a share of body height
SEATED_HEIGHT = 1.25


def _yaw(frm: list[float], to: list[float]) -> float:
    return round(math.degrees(math.atan2(to[1] - frm[1], to[0] - frm[0])) % 360, 2)


def _head(p: Placement) -> list[float]:
    return [p.position[0], p.position[1], round(p.height * EYE, 3)]


def _chest(p: Placement) -> list[float]:
    return [p.position[0], p.position[1], round(p.height * 0.7, 3)]


def segment_hits(a: list[float], b: list[float], obj: SpatialObject) -> bool:
    """Does the segment a->b pass through the object's box (slab test)? Endpoints inside the box do not count."""
    lo = [obj.position[0] - obj.size[0] / 2, obj.position[1] - obj.size[1] / 2, obj.position[2]]
    hi = [obj.position[0] + obj.size[0] / 2, obj.position[1] + obj.size[1] / 2, obj.position[2] + obj.size[2]]
    t0, t1 = 0.0, 1.0
    for i in range(3):
        d = b[i] - a[i]
        if abs(d) < 1e-9:
            if a[i] < lo[i] or a[i] > hi[i]:
                return False
            continue
        u0, u1 = (lo[i] - a[i]) / d, (hi[i] - a[i]) / d
        if u0 > u1:
            u0, u1 = u1, u0
        t0, t1 = max(t0, u0), min(t1, u1)
        if t0 > t1:
            return False
    return 0.02 < t1 and t0 < 0.98


def blocker(a: list[float], b: list[float], objects: list[SpatialObject]) -> str:
    for o in objects:
        if o.blocks_sight and segment_hits(a, b, o):
            return o.id
    return ""


def _anchor(loc: str, name: str) -> tuple[float, float, float]:
    return LAYOUTS[loc]["anchors"][name]


def _pair_anchors(loc: str, event_id: int) -> tuple[str, str, str | None]:
    lay = LAYOUTS[loc]
    if lay["tables"]:
        t = lay["tables"][event_id % len(lay["tables"])]
        return f"{t}.seat_a", f"{t}.seat_b", f"{t}.surface"
    a, b = lay["pairs"][event_id % len(lay["pairs"])]
    surface = next((k for k in lay["anchors"] if k.endswith(".surface")), None)
    return a, b, surface


def _free_spots(loc: str, used: set[str]) -> list[str]:
    lay = LAYOUTS[loc]
    seats = [k for k in lay["anchors"] if ".seat_" in k]
    return [k for k in seats + lay["stand"] if k not in used]


def stage_beat(index: int, beat: Beat) -> BeatStaging:
    loc = beat.location.id if beat.location.id in LAYOUTS else "cafe"
    principals = [p.id for p in beat.participants if p.role in PRINCIPAL_ROLES][:2]
    witnesses = [p.id for p in beat.participants if p.role == "witness" and p.id not in principals]
    loud = beat.event_type in LOUD or beat.variant == "hostile"
    placements: list[Placement] = []
    used: set[str] = set()

    def place(pid: str, anchor: str, face: list[float] | None, pose: str) -> Placement:
        x, y, yaw = _anchor(loc, anchor)
        pos = [x, y, 0.0]
        p = Placement(pid, anchor, pos, _yaw(pos, face) if face else yaw, pose, SEATED_HEIGHT if pose == "sit" else 1.7)
        placements.append(p)
        used.add(anchor)
        return p

    a_anchor, b_anchor, surface = _pair_anchors(loc, beat.event_id)
    focus: list[float]
    if beat.event_type == "parrot_speaks" and "cafe.perch" in LAYOUTS[loc]["anchors"]:
        focus = list(_anchor(loc, "cafe.perch")[:2]) + [1.8]
        placements.append(Placement("parrot", "cafe.perch", [focus[0], focus[1], 1.6], 0.0, "stand", 0.3))
        used.add("cafe.perch")
    elif len(principals) >= 2 and beat.event_type not in LONE[:4]:
        pa, pb = _anchor(loc, a_anchor), _anchor(loc, b_anchor)
        pose = "stand" if loud else ("sit" if ".seat_" in a_anchor else "stand")
        place(principals[0], a_anchor, [pb[0], pb[1]], pose)
        place(principals[1], b_anchor, [pa[0], pa[1]], pose)
        focus = [(pa[0] + pb[0]) / 2, (pa[1] + pb[1]) / 2, 1.2]
    elif principals:
        place(principals[0], a_anchor, None, "stand")
        focus = placements[-1].position[:2] + [1.2]
    else:  # nobody acts (a price change, a power cut): an establishing view of the place
        w, d = BOUNDS[loc]
        focus = [w / 2, d / 2, 1.2]
    if beat.prop is not None and surface:
        x, y, _ = _anchor(loc, surface)
        placements.append(Placement(beat.prop.id, surface, [x, y, 0.75], 0.0, "stand", 0.15))
        used.add(surface)
    actor = next((p for p in placements if principals and p.id == principals[0]), None)
    objects = layout_ref(loc).objects
    for w in witnesses:
        spots = _free_spots(loc, used)
        if not spots:
            break
        # a witness noticed the act, so they get the first free spot with a clear view of the actor
        clear = [s for s in spots if actor is None or not blocker(
            [_anchor(loc, s)[0], _anchor(loc, s)[1], (SEATED_HEIGHT if ".seat_" in s else 1.7) * EYE], _chest(actor), objects)]
        spot = (clear or spots)[0]
        place(w, spot, actor.position if actor else focus, "stand" if ".seat_" not in spot else "sit")

    checks = [SightCheck(w.id, actor.id, True, not blocker(_head(w), _chest(actor), objects),
                         blocker(_head(w), _chest(actor), objects))
              for w in placements if actor and w.id in witnesses]
    cameras = _cameras(loc, placements, principals, beat, focus, objects)
    for i, cam in enumerate(cameras):
        for s in cam.subjects:
            p = next(pl for pl in placements if pl.id == s)
            b = blocker(cam.position, _chest(p) if p.height > 0.5 else p.position, objects)
            checks.append(SightCheck(f"camera:{i}", s, True, not b, b))
    return BeatStaging(index, beat.event_id, loc, f"{loc}.v1", placements, cameras, checks)


def _inside(loc: str, p: list[float], margin: float = 0.4) -> bool:
    w, d = BOUNDS[loc]
    return margin <= p[0] <= w - margin and margin <= p[1] <= d - margin


def _visible_all(pos: list[float], subjects: list[Placement], objects: list[SpatialObject]) -> bool:
    return all(not blocker(pos, _chest(s) if s.height > 0.5 else s.position, objects) for s in subjects)


def _first_clear(loc: str, options: list[list[float]], subjects: list[Placement], objects: list[SpatialObject]) -> list[float]:
    for pos in options:
        if _inside(loc, pos) and _visible_all(pos, subjects, objects):
            return pos
    return next((p for p in options if _inside(loc, p)), options[0])


def _cameras(loc: str, placements: list[Placement], principals: list[str], beat: Beat, focus: list[float],
             objects: list[SpatialObject]) -> list[CameraShot]:
    w, d = BOUNDS[loc]
    people = [p for p in placements if p.height > 0.5]
    corners = [[0.6, 0.6, 2.2], [w - 0.6, 0.6, 2.2], [w - 0.6, d - 0.6, 2.2], [0.6, d - 0.6, 2.2]]
    corners.sort(key=lambda c: -math.dist(c[:2], focus[:2]))
    ring = [[round(focus[0] + r * math.cos(math.radians(a)), 3), round(focus[1] + r * math.sin(math.radians(a)), 3), z]
            for r, z in ((5.0, 2.2), (7.0, 3.0)) for a in range(0, 360, 30)]
    crane = [[round(focus[0] + 3.0 * math.cos(math.radians(a)), 3), round(focus[1] + 3.0 * math.sin(math.radians(a)), 3), 7.0]
             for a in range(0, 360, 45)]  # last resort: a high angle over trees and pillars
    shots = [CameraShot("wide", _first_clear(loc, corners + ring + crane, people, objects), focus, 24.0, "static", None,
                        [p.id for p in people])]
    pair = [p for p in placements if p.id in principals]
    if len(pair) == 2:
        a, b = pair
        mx, my = (a.position[0] + b.position[0]) / 2, (a.position[1] + b.position[1]) / 2
        ax, ay = b.position[0] - a.position[0], b.position[1] - a.position[1]
        n = math.hypot(ax, ay) or 1.0
        px, py = -ay / n, ax / n
        sides = [[round(mx + s * 3.0 * px, 3), round(my + s * 3.0 * py, 3), 1.4] for s in (1, -1)]
        shots.append(CameraShot("two_shot", _first_clear(loc, sides, pair, objects), [mx, my, 1.1], 35.0, "push_in",
                                None, [a.id, b.id]))
        behind = [round(b.position[0] + 0.7 * ax / n + 0.35 * px, 3), round(b.position[1] + 0.7 * ay / n + 0.35 * py, 3), 1.5]
        mirror = [round(b.position[0] + 0.7 * ax / n - 0.35 * px, 3), round(b.position[1] + 0.7 * ay / n - 0.35 * py, 3), 1.5]
        shots.append(CameraShot("over_shoulder", _first_clear(loc, [behind, mirror] + corners, [a], objects), _head(a),
                                50.0, "static", None, [a.id]))
    # a point of view: through the first witness's eyes (at their own eye height: a dog sees from the floor)
    watchers = [p for p in placements if p.id in {q.id for q in beat.participants if q.role in ("witness", "sensed")}]
    actor = next((p for p in placements if principals and p.id == principals[0]), None)
    if watchers and actor is not None:
        w = watchers[0]
        shots.append(CameraShot("pov", _head(w), _chest(actor), 28.0, "static", None, [actor.id]))
    prop = next((p for p in placements if beat.prop is not None and p.id == beat.prop.id), None)
    if prop is not None:
        shots.append(CameraShot("insert", [prop.position[0] + 0.4, prop.position[1] - 0.6, 1.3], prop.position, 85.0,
                                "static", None, [prop.id]))
    return shots


def compile_spatial(spec: SceneSpec) -> SpatialPlan:
    beats = [stage_beat(i, b) for i, b in enumerate(spec.beats)]
    problems = [f"beat {s.beat_index}: {c.observer} cannot see {c.subject} (blocked by {c.blocked_by})"
                for s in beats for c in s.checks if c.required and not c.visible]
    locations = sorted({s.location for s in beats})
    return finalize(SpatialPlan(1, spec.scene_id, spec.scene_hash, COMPILER_VERSION, [layout_ref(l) for l in locations],
                                beats, not problems, problems))
