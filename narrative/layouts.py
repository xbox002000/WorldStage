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


def _wall_x(prefix: str, y: float, x0: float, x1: float, doors: tuple = (), h: float = 3.0,
            t: float = 0.15) -> list[SpatialObject]:
    """An inside wall along x at y, with a 1 m doorway centred on each x in `doors`."""
    out, x, cuts = [], x0, sorted(doors)
    for k, d in enumerate(cuts + [None]):
        end = d - 0.5 if d is not None else x1
        if end > x + 0.05:
            out.append(_o(f"{prefix}{k}", "wall", (x + end) / 2, y, end - x, t, h))
        if d is not None:
            out.append(SpatialObject(f"{prefix}.door{k}", "door", [d, y, 0.0], [1.0, t, 2.1], 0.0, False))
            out.append(SpatialObject(f"{prefix}.lintel{k}", "wall", [d, y, 2.1], [1.0, t, h - 2.1], 0.0, True))
            x = d + 0.5
    return out


def _wall_y(prefix: str, x: float, y0: float, y1: float, h: float = 3.0, t: float = 0.15) -> list[SpatialObject]:
    return [_o(prefix, "wall", x, (y0 + y1) / 2, t, y1 - y0, h)]


def _table_with_seats(prefix: str, x: float, y: float, kind: str = "table") -> tuple[list[SpatialObject], dict]:
    objs = [_o(f"{prefix}", kind, x, y, 0.9, 0.9, 0.75)]
    # a chair at each seat: nobody sits on air, and nobody walks through one (low: it does not block the view)
    objs += [_o(f"{prefix}.chair_{k}", "chair", cx, cy, 0.45, 0.45, 0.45, blocks=False)
             for k, (cx, cy) in (("a", (x - 0.8, y)), ("b", (x + 0.8, y)), ("c", (x, y + 0.8)))]
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
               "park.path": (9.0, 1.0, 0.0), "park.door_gate": (9.0, -0.3, 90.0), "park.bench1.surface": (5.0, 5.0, 0.0),
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
    # apartment: a corridor along the front, then a kitchen, a living room and three bedrooms (two beds each);
    # 0.1 was one room, so at night the whole building stood in it
    objs = _room("apartment", 16, 10, window=(1.0, 3.0), door=14.5)
    objs += _wall_x("apartment.corridor_wall", 2.8, 0.0, 16.0, doors=(2.0, 6.0, 9.35, 12.05, 14.7))
    for k, x in enumerate((4.0, 8.0, 10.7, 13.4)):
        objs += _wall_y(f"apartment.divider{k}", x, 2.8, 10.0)
    objs += [_o("apartment.sofa", "sofa", 6.0, 9.35, 2.4, 0.9, 0.8),
             _o("apartment.counter", "counter", 2.0, 9.55, 3.6, 0.6, 0.9)]
    anchors = {"apartment.sofa_a": (5.4, 8.6, 270.0), "apartment.sofa_b": (6.6, 8.6, 270.0),
               "apartment.door_in": (14.5, 1.0, 90.0), "apartment.hall": (10.0, 1.4, 180.0),
               "apartment.corner": (7.3, 3.6, 225.0), "apartment.kitchen_spot": (1.0, 3.8, 45.0),
               "apartment.living_spot": (4.9, 4.6, 45.0), "apartment.counter_front": (2.0, 8.7, 90.0),
               "apartment.dog_bed": (4.7, 6.5, 0.0),
               # enough room to stand in the kitchen and the living room, so a witness can be in the same room
               "apartment.kitchen_spot2": (3.3, 4.0, 135.0), "apartment.kitchen_spot3": (0.8, 7.9, 315.0),
               "apartment.kitchen_spot4": (3.3, 7.9, 225.0), "apartment.living_spot2": (7.3, 6.6, 180.0),
               "apartment.living_spot3": (5.2, 7.4, 315.0)}
    o, a = _table_with_seats("apartment.t1", 2.0, 6.0)
    objs += o
    anchors.update(a)
    sleep = []
    for room, (x0, x1) in (("room_a", (8.0, 10.7)), ("room_b", (10.7, 13.4)), ("room_c", (13.4, 16.0))):
        for k, bx in enumerate((x0 + 0.65, x1 - 0.65)):
            bed = f"apartment.{room}.bed{k + 1}"
            objs.append(_o(bed, "bed", bx, 8.95, 0.9, 1.9, 0.5))
            anchors[bed + ".seat"] = (bx, 8.1, 270.0)  # the bed's edge: one sits (and sleeps) there
            sleep.append(bed + ".seat")
    out["apartment"] = {"objects": objs, "anchors": anchors, "tables": ["apartment.t1"],
                        # the corridor is for passing through, not for standing in: it has no standing spot
                        "stand": ["apartment.corner", "apartment.kitchen_spot", "apartment.living_spot",
                                  "apartment.counter_front", "apartment.kitchen_spot2", "apartment.kitchen_spot3",
                                  "apartment.kitchen_spot4", "apartment.living_spot2", "apartment.living_spot3"],
                        "outside": [],
                        # who sleeps where: residents in order take a bed, then the sofa, then the kitchen chairs
                        "sleep": sleep + ["apartment.sofa_a", "apartment.sofa_b", "apartment.t1.seat_a",
                                          "apartment.t1.seat_b", "apartment.t1.seat_c"],
                        "animal_sleep": ["apartment.dog_bed"],
                        "rooms": {"corridor": (0.0, 0.0, 16.0, 2.8), "kitchen": (0.0, 2.8, 4.0, 10.0),
                                  "living": (4.0, 2.8, 8.0, 10.0), "room_a": (8.0, 2.8, 10.7, 10.0),
                                  "room_b": (10.7, 2.8, 13.4, 10.0), "room_c": (13.4, 2.8, 16.0, 10.0)}}
    # station: platform with a pillar
    objs = [_o("station.platform", "platform", 8, 4, 16, 4, 0.3, False), _o("station.pillar", "wall", 8, 4, 0.6, 0.6, 3.5),
            _o("station.bench", "bench", 4, 5, 2.0, 0.6, 0.5)]
    anchors = {"station.bench.seat_a": (3.5, 4.6, 0.0), "station.bench.seat_b": (4.5, 4.6, 0.0),
               "station.p1": (6.0, 3.0, 90.0), "station.p2": (7.2, 3.0, 270.0), "station.far": (12.0, 4.0, 270.0),
               "station.behind_pillar": (8.0, 5.0, 180.0), "station.door_stairs": (15.2, 3.0, 180.0), "station.bench.surface": (4.0, 5.0, 0.0)}
    out["station"] = {"objects": objs, "anchors": anchors, "tables": [],
                      "pairs": [("station.bench.seat_a", "station.bench.seat_b"), ("station.p1", "station.p2")],
                      "stand": ["station.far", "station.behind_pillar", "station.p1"], "outside": []}
    return out


LAYOUTS = _build()


def layout_ref(location: str) -> LayoutRef:
    lay = LAYOUTS[location]
    objs = lay["objects"]
    return LayoutRef(f"{location}.v1", location, objs, content_hash({"objects": objs, "anchors": lay["anchors"]}))
