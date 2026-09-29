"""Floor plans for the five places: white-box geometry and named anchors. Metres; x right, y into the room, z up.

Deliberately plain (boxes only): the plan is for blocking, sight lines and camera control, not for looks.
"""
from __future__ import annotations

from contracts.base import content_hash
from contracts.spatial import LayoutRef, SpatialObject


def _o(id: str, kind: str, x: float, y: float, w: float, d: float, h: float, blocks: bool = True, label: str = "") -> SpatialObject:
    return SpatialObject(id, kind, [x, y, 0.0], [w, d, h], 0.0, blocks, label)


def _room(prefix: str, w: float, d: float, h: float = 3.0, window: tuple[float, float] | None = None,
          door: float | None = None) -> list[SpatialObject]:
    """Four walls; the front wall (y = 0) may have a window (x from..to, sill 0.9 m, top 2.4 m) and a door."""
    t = 0.2
    out = [_o(f"{prefix}.wall_back", "wall", w / 2, d, w, t, h), _o(f"{prefix}.wall_left", "wall", 0, d / 2, t, d, h),
           _o(f"{prefix}.wall_right", "wall", w, d / 2, t, d, h)]
    gaps = []
    if window:
        gaps.append(("window", window[0], window[1]))
    if door is not None:
        gaps.append(("door", door - 0.5, door + 0.5))
    gaps.sort(key=lambda g: g[1])
    x = 0.0
    for i, (kind, a, b) in enumerate(gaps):
        if a > x:
            out.append(_o(f"{prefix}.wall_front{i}", "wall", (x + a) / 2, 0, a - x, t, h))
        if kind == "window":
            out.append(_o(f"{prefix}.window_sill", "wall", (a + b) / 2, 0, b - a, t, 0.9))
            out.append(SpatialObject(f"{prefix}.window", "window", [(a + b) / 2, 0, 0.9], [b - a, t, 1.5], 0.0, False))
            out.append(SpatialObject(f"{prefix}.window_top", "wall", [(a + b) / 2, 0, 2.4], [b - a, t, h - 2.4], 0.0, True))
        else:
            out.append(SpatialObject(f"{prefix}.door", "door", [(a + b) / 2, 0, 0.0], [b - a, t, 2.1], 0.0, False))
            out.append(SpatialObject(f"{prefix}.door_top", "wall", [(a + b) / 2, 0, 2.1], [b - a, t, h - 2.1], 0.0, True))
        x = b
    if x < w:
        out.append(_o(f"{prefix}.wall_front_end", "wall", (x + w) / 2, 0, w - x, t, h))
    return out


def _table_with_seats(prefix: str, x: float, y: float, kind: str = "table") -> tuple[list[SpatialObject], dict]:
    objs = [_o(f"{prefix}", kind, x, y, 0.9, 0.9, 0.75)]
    anchors = {f"{prefix}.seat_a": (x - 0.8, y, 90.0), f"{prefix}.seat_b": (x + 0.8, y, 270.0),
               f"{prefix}.seat_c": (x, y + 0.8, 180.0), f"{prefix}.surface": (x, y, 0.0)}
    return objs, anchors


def _build() -> dict[str, dict]:
    out = {}
    # cafe: 10 x 8, big street window, three tables, a counter and a perch
    objs = _room("cafe", 10, 8, window=(3.0, 7.0), door=8.5)
    anchors = {"cafe.door_in": (8.5, 1.0, 0.0), "cafe.counter_front": (2.0, 5.8, 180.0),
               "cafe.street": (5.0, -1.5, 0.0), "cafe.perch": (1.0, 6.5, 90.0), "cafe.corner": (9.0, 7.0, 225.0)}
    for name, (x, y) in {"cafe.t1": (3.0, 3.0), "cafe.t2": (7.0, 3.0), "cafe.t3": (5.0, 5.5)}.items():
        o, a = _table_with_seats(name, x, y)
        objs += o
        anchors.update(a)
    objs += [_o("cafe.counter", "counter", 2.0, 7.0, 3.0, 0.8, 1.1), _o("cafe.perch_stand", "perch", 1.0, 6.5, 0.3, 0.3, 1.6, False)]
    out["cafe"] = {"objects": objs, "anchors": anchors, "tables": ["cafe.t1", "cafe.t2", "cafe.t3"],
                   "stand": ["cafe.counter_front", "cafe.door_in", "cafe.corner"], "outside": ["cafe.street"]}
    # park: open lawn with two benches and three trees (trees block the view)
    objs = [_o("park.bench1", "bench", 5, 5, 2.0, 0.6, 0.5), _o("park.bench2", "bench", 13, 9, 2.0, 0.6, 0.5),
            _o("park.tree1", "tree", 8, 7, 1.0, 1.0, 5.0), _o("park.tree2", "tree", 10, 3.5, 1.0, 1.0, 5.0),
            _o("park.tree3", "tree", 4, 11, 1.0, 1.0, 5.0)]
    anchors = {"park.bench1.seat_a": (4.5, 5.4, 180.0), "park.bench1.seat_b": (5.5, 5.4, 180.0),
               "park.bench2.seat_a": (12.5, 9.4, 180.0), "park.bench2.seat_b": (13.5, 9.4, 180.0),
               "park.lawn1": (6.0, 7.0, 90.0), "park.lawn2": (11.0, 6.0, 270.0), "park.behind_tree": (8.0, 8.2, 180.0),
               "park.path": (9.0, 1.0, 0.0), "park.bench1.surface": (5.0, 5.0, 0.0),
               "park.lawn3": (3.0, 3.0, 45.0), "park.lawn4": (7.0, 2.5, 90.0), "park.lawn5": (12.0, 4.5, 135.0),
               "park.lawn6": (14.5, 6.5, 180.0), "park.lawn7": (6.5, 9.5, 270.0), "park.lawn8": (10.5, 10.5, 225.0)}
    out["park"] = {"objects": objs, "anchors": anchors, "tables": [], "pairs": [("park.bench1.seat_a", "park.bench1.seat_b"),
                   ("park.lawn1", "park.lawn2")], "stand": ["park.lawn1", "park.lawn2", "park.lawn3", "park.lawn4", "park.lawn5", "park.lawn6",
                             "park.lawn7", "park.lawn8", "park.path", "park.behind_tree"],
                   "outside": []}
    # office: 12 x 8, four desks, a window
    objs = _room("office", 12, 8, window=(2.0, 6.0), door=10.5)
    anchors = {"office.door_in": (10.5, 1.0, 0.0), "office.window_spot": (4.0, 1.0, 180.0), "office.corner": (11.0, 7.0, 225.0)}
    for name, (x, y) in {"office.d1": (3.0, 4.0), "office.d2": (6.0, 4.0), "office.d3": (9.0, 4.0), "office.d4": (6.0, 6.5)}.items():
        o, a = _table_with_seats(name, x, y, "desk")
        objs += o
        anchors.update(a)
    out["office"] = {"objects": objs, "anchors": anchors, "tables": ["office.d1", "office.d2", "office.d3", "office.d4"],
                     "stand": ["office.window_spot", "office.door_in", "office.corner"], "outside": []}
    # apartment: shared living room with a sofa and a table
    objs = _room("apartment", 9, 7, window=(1.5, 4.0), door=7.5)
    objs += [_o("apartment.sofa", "sofa", 3.0, 5.5, 2.4, 0.9, 0.8)]
    anchors = {"apartment.sofa_a": (2.4, 5.0, 180.0), "apartment.sofa_b": (3.6, 5.0, 180.0),
               "apartment.door_in": (7.5, 1.0, 0.0), "apartment.hall": (7.0, 4.0, 270.0), "apartment.corner": (8.0, 6.0, 225.0)}
    o, a = _table_with_seats("apartment.t1", 5.5, 3.0)
    objs += o
    anchors.update(a)
    out["apartment"] = {"objects": objs, "anchors": anchors, "tables": ["apartment.t1"],
                        "stand": ["apartment.hall", "apartment.door_in", "apartment.corner"], "outside": []}
    # station: platform with a pillar
    objs = [_o("station.platform", "platform", 8, 4, 16, 4, 0.3, False), _o("station.pillar", "wall", 8, 4, 0.6, 0.6, 3.5),
            _o("station.bench", "bench", 4, 5, 2.0, 0.6, 0.5)]
    anchors = {"station.bench.seat_a": (3.5, 4.6, 0.0), "station.bench.seat_b": (4.5, 4.6, 0.0),
               "station.p1": (6.0, 3.0, 90.0), "station.p2": (7.2, 3.0, 270.0), "station.far": (12.0, 4.0, 270.0),
               "station.behind_pillar": (8.0, 5.0, 180.0), "station.bench.surface": (4.0, 5.0, 0.0)}
    out["station"] = {"objects": objs, "anchors": anchors, "tables": [],
                      "pairs": [("station.bench.seat_a", "station.bench.seat_b"), ("station.p1", "station.p2")],
                      "stand": ["station.far", "station.behind_pillar", "station.p1"], "outside": []}
    return out


LAYOUTS = _build()


def layout_ref(location: str) -> LayoutRef:
    lay = LAYOUTS[location]
    objs = lay["objects"]
    return LayoutRef(f"{location}.v1", location, objs, content_hash({"objects": objs, "anchors": lay["anchors"]}))
