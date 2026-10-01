"""Navigation for the World Runtime: where a body can stand and how it gets there without walking through a wall, a
table, a tree or somebody else.

The white-box layouts (narrative/layouts.py) are also the collision proxies: every blocking box, grown by a body's
radius, is closed floor. Other bodies standing in the place are closed discs. A walk goes straight when the line is
clear, and otherwise along an A* path on a grid, pulled tight (any corner that can be skipped is skipped). Everything
is deterministic: fixed cell size, fixed neighbour order, ties broken by cell index.
"""
from __future__ import annotations

import heapq
import math
from collections import Counter
from functools import lru_cache

from narrative.layouts import LAYOUTS

CELL = 0.15  # metres
RADIUS = 0.25  # a body's collision radius (the dog's is smaller; one grid serves both)
BODY_GAP = 0.5  # centre to centre, the room a body keeps round another when it can
SQUEEZE = 0.42  # when there is no other way: shoulders touch, bodies never pass through each other
STATS: Counter = Counter()  # path queries, searches, fallbacks: measured, never used to decide anything
PASSABLE = ("window", "door", "platform", "perch")  # geometry that does not block the floor
# the cells a standing body closes, as offsets from the cell it stands in (a disc of BODY_GAP, cell centres to centre)
def _disc(gap: float) -> tuple:
    return tuple((di, dj) for dj in range(-4, 5) for di in range(-4, 5) if math.hypot(di * CELL, dj * CELL) < gap)


_DISCS = {BODY_GAP: _disc(BODY_GAP), SQUEEZE: _disc(SQUEEZE)}


def blocks(o) -> bool:
    # benches and tables block the floor, not only the view; a lintel over a door or a window does not
    return o.kind not in PASSABLE and o.size[2] > 0.3 and o.position[2] < 1.0


def _box(o, pad: float) -> tuple[float, float, float, float]:
    w, d = o.size[0], o.size[1]
    if abs((o.yaw or 0) % 180) == 90:
        w, d = d, w
    return o.position[0] - w / 2 - pad, o.position[0] + w / 2 + pad, o.position[1] - d / 2 - pad, o.position[1] + d / 2 + pad


class Grid:
    def __init__(self, template: str) -> None:
        lay = LAYOUTS[template]
        self.template = template
        self.solid = [o for o in lay["objects"] if blocks(o)]
        xs = [o.position[0] for o in lay["objects"]] + [a[0] for a in lay["anchors"].values()]
        ys = [o.position[1] for o in lay["objects"]] + [a[1] for a in lay["anchors"].values()]
        self.x0, self.y0 = min(xs) - 1.5, min(ys) - 1.5
        self.nx = int((max(xs) + 1.5 - self.x0) / CELL) + 1
        self.ny = int((max(ys) + 1.5 - self.y0) / CELL) + 1
        grown = [_box(o, RADIUS) for o in self.solid]
        self._memo: dict = {}
        self._static: dict = {}
        self._boxes: dict[float, list] = {}  # the solids' boxes by padding: asked millions of times, computed once
        self.through_people = False  # did the last path have to go through somebody (the caller then waits)
        self.closed = bytearray(self.nx * self.ny)
        for j in range(self.ny):
            for i in range(self.nx):
                x, y = self.centre(i, j)
                if any(a <= x <= b and c <= y <= d for a, b, c, d in grown):
                    self.closed[j * self.nx + i] = 1

    def cell(self, x: float, y: float) -> tuple[int, int]:
        return (min(self.nx - 1, max(0, int((x - self.x0) / CELL))), min(self.ny - 1, max(0, int((y - self.y0) / CELL))))

    def centre(self, i: int, j: int) -> tuple[float, float]:
        return self.x0 + (i + 0.5) * CELL, self.y0 + (j + 0.5) * CELL

    def inside_solid(self, x: float, y: float, pad: float = 0.0) -> str:
        """The id of the blocking box this point is in (grown by pad), or ""."""
        for oid, a, b, c, d in self._solid_boxes(pad):
            if a <= x <= b and c <= y <= d:
                return oid
        return ""

    def _solid_boxes(self, pad: float) -> list:
        boxes = self._boxes.get(pad)
        if boxes is None:
            boxes = self._boxes[pad] = [(o.id, *_box(o, pad)) for o in self.solid]
        return boxes

    def clear_of(self, pts: list, others: tuple, gap: float = 0.0) -> bool:
        """Does the path keep `gap` (default SQUEEZE) from everybody? Its first and last 25 cm are exempt: one may
        start or end beside somebody, but not pass through them."""
        gap = gap or SQUEEZE - 0.005
        total = sum(math.hypot(q[0] - p[0], q[1] - p[1]) for p, q in zip(pts, pts[1:]))
        if total <= 0.5:
            return True
        s, n = 0.0, max(2, int(total / 0.05))
        for k in range(n + 1):
            d = total * k / n
            if d < 0.25 or d > total - 0.25:
                continue
            x, y = self._along(pts, d)
            for ox, oy in others:  # hypot is only asked of bodies that are not plainly out of reach
                if -gap < x - ox < gap and -gap < y - oy < gap and math.hypot(x - ox, y - oy) < gap:
                    return False
        return True

    def clear_prefix(self, pts: list, others: tuple, gap: float = 0.0) -> list:
        """The path as far as it keeps its distance from everybody (stopping 0.3 m short of the first one it would
        brush): where one stops to talk across a crowd rather than push through it."""
        gap = gap or SQUEEZE - 0.005
        total = sum(math.hypot(q[0] - p[0], q[1] - p[1]) for p, q in zip(pts, pts[1:]))
        n = max(2, int(total / 0.05))
        stop = total
        for k in range(n + 1):
            d = total * k / n
            if d < 0.25:
                continue
            x, y = self._along(pts, d)
            if any(-gap < x - ox < gap and -gap < y - oy < gap and math.hypot(x - ox, y - oy) < gap for ox, oy in others):
                stop = max(0.0, d - 0.3)
                break
        if stop >= total:
            return pts
        out, acc = [pts[0]], 0.0
        for p, q in zip(pts, pts[1:]):
            L = math.hypot(q[0] - p[0], q[1] - p[1])
            if acc + L >= stop:
                f = (stop - acc) / L if L else 0.0
                out.append((round(p[0] + (q[0] - p[0]) * f, 3), round(p[1] + (q[1] - p[1]) * f, 3)))
                return out
            out.append(q)
            acc += L
        return out

    @staticmethod
    def _along(pts: list, d: float) -> tuple[float, float]:
        for p, q in zip(pts, pts[1:]):
            L = math.hypot(q[0] - p[0], q[1] - p[1])
            if d <= L:
                f = d / L if L else 0.0
                return p[0] + (q[0] - p[0]) * f, p[1] + (q[1] - p[1]) * f
            d -= L
        return pts[-1]

    def crosses_solid(self, a: tuple[float, float], b: tuple[float, float]) -> str:
        """The wall or piece of furniture the straight line a-b passes through (its own box, not grown), or ""."""
        n = max(1, int(math.hypot(b[0] - a[0], b[1] - a[1]) / 0.05))
        boxes = self._solid_boxes(0.0)
        ax, ay, dx, dy = a[0], a[1], b[0] - a[0], b[1] - a[1]
        for k in range(1, n):
            f = k / n
            x, y = ax + dx * f, ay + dy * f
            for oid, x0, x1, y0, y1 in boxes:
                if x0 <= x <= x1 and y0 <= y <= y1:
                    return oid
        return ""

    def free(self, x: float, y: float, others: tuple = ()) -> bool:
        i, j = self.cell(x, y)
        if self.closed[j * self.nx + i]:
            return False
        return all(math.hypot(x - ox, y - oy) >= BODY_GAP for ox, oy in others)

    def line(self, a: tuple[float, float], b: tuple[float, float], others: tuple = (), gap: float = BODY_GAP) -> bool:
        """Whether a body can walk the straight line from a to b (the end points themselves are not checked)."""
        dx, dy = b[0] - a[0], b[1] - a[1]
        d = math.hypot(dx, dy)
        n = max(1, int(d / (CELL / 2)))
        inv, x0, y0, nx, ny, closed = 1.0 / CELL, self.x0, self.y0, self.nx, self.ny, self.closed
        for k in range(1, n):
            f = k / n
            i = int((a[0] + dx * f - x0) * inv)
            j = int((a[1] + dy * f - y0) * inv)
            i = 0 if i < 0 else nx - 1 if i >= nx else i
            j = 0 if j < 0 else ny - 1 if j >= ny else j
            if closed[j * nx + i]:
                return False
        L = dx * dx + dy * dy
        g2 = gap * gap
        for ox, oy in others:  # distance from each standing body to the segment
            f = 0.0 if L == 0 else max(0.0, min(1.0, ((ox - a[0]) * dx + (oy - a[1]) * dy) / L))
            ex, ey = a[0] + dx * f - ox, a[1] + dy * f - oy
            if ex * ex + ey * ey < g2:
                return False
        return True

    def nearest_free(self, p: tuple[float, float], others: tuple = (), prefer: tuple[float, float] | None = None,
                     max_r: float = 4.0) -> tuple[float, float]:
        """The free floor nearest to p (rings of cells outwards); among equals, the one nearest `prefer`."""
        if self.free(p[0], p[1], others):
            return p
        ci, cj = self.cell(*p)
        for r in range(1, int(max_r / CELL) + 1):
            ring = []
            for j in range(cj - r, cj + r + 1):
                for i in range(ci - r, ci + r + 1):
                    if max(abs(i - ci), abs(j - cj)) != r or not (0 <= i < self.nx and 0 <= j < self.ny):
                        continue
                    x, y = self.centre(i, j)
                    if self.free(x, y, others):
                        ref = prefer or p
                        ring.append((round(math.hypot(x - p[0], y - p[1]), 6), round(math.hypot(x - ref[0], y - ref[1]), 6),
                                     j * self.nx + i, (round(x, 3), round(y, 3))))
            if ring:
                return min(ring)[3]
        return p

    def path(self, a: tuple[float, float], b: tuple[float, float], others: tuple = ()) -> list[tuple[float, float]]:
        """Waypoints from a to b (both included) that keep clear of everything solid and every standing body.
        Memoised on the cells everybody stands in: a replan after waiting, with nobody moved, is free."""
        STATS["path_queries"] += 1
        key = (a, b, tuple(sorted(self.cell(x, y) for x, y in others)))
        hit = self._memo.get(key)
        if hit is not None:
            self.through_people = hit[1]
            return hit[0]
        self.through_people = False
        out = self._path(a, b, others)
        # whatever the fallbacks did, a path never crosses a wall or a piece of furniture: checked here, once
        if any(self.crosses_solid(p, q) for p, q in zip(out, out[1:])):
            STATS["repaired"] += 1
            core = self._astar(self.nearest_free(a, (), prefer=b), self.nearest_free(b, (), prefer=a), (), budget=None)
            out = self._pull([a] + (core or [a, b])[1:-1] + [b], ())
        if others and not self.through_people and not self.clear_of(out, others):
            self.through_people = True  # the grid's cells let it pass closer than a body may: not a way
        if len(self._memo) > 20000:
            self._memo.clear()
        self._memo[key] = (out, self.through_people)
        return out

    def _path(self, a: tuple[float, float], b: tuple[float, float], others: tuple = ()) -> list[tuple[float, float]]:
        if self.line(a, b, others):
            return [a, b]
        # a seat or a spot tucked against furniture may be inside the grown boxes: step out to open floor first
        a2, b2 = self.nearest_free(a, others, prefer=b), self.nearest_free(b, others, prefer=a)
        gap = BODY_GAP
        core = static = None
        if self.line(a2, b2, others):
            core = [a2, b2]
        else:  # the way round the furniture (memoised); if nobody stands on it, that is the way
            static = self._astar(a2, b2, ())
            if static is not None:
                pulled = self._pull(static, ())
                if all(self.line(p, q, others) for p, q in zip(pulled, pulled[1:])):
                    core = pulled
        if core is None and static is not None:  # somebody stands on it: a way round them near that route first
            xs, ys = [q[0] for q in static], [q[1] for q in static]
            window = (*self.cell(min(xs) - 1.5, min(ys) - 1.5), *self.cell(max(xs) + 1.5, max(ys) + 1.5))
            core = self._search(a2, b2, others, BODY_GAP, 6000, window)
        if core is None:
            core = self._astar(a2, b2, others)
        if core is None and others:  # no way round with room to spare: squeeze past, shoulders touching
            STATS["squeeze"] += 1
            gap = SQUEEZE
            core = self._astar(a2, b2, others, SQUEEZE)
        if core is None:  # people block every way: past them, never through furniture or a wall (no budget)
            STATS["past_people"] += 1
            self.through_people = bool(others)
            core = self._astar(a2, b2, (), budget=None)
            others = ()
        if core is None:
            STATS["unreachable"] += 1
        core = core or [a2, b2]  # unreachable: a layout without a way in (a bug in the layout, not a walk)
        pts = [a] + ([a2] if a2 != a else []) + core[1:-1] + ([b2] if b2 != b else []) + [b]
        return self._pull(pts, others, gap)

    def _astar(self, a, b, others, gap: float = BODY_GAP, budget: int | None = 6000) -> list[tuple[float, float]] | None:
        if not others:  # round the furniture only: the same for every walk between the same two cells
            key = (self.cell(*a), self.cell(*b))
            if key not in self._static:
                self._static[key] = self._search(a, b, (), gap, None)
            hit = self._static[key]
            return None if hit is None else [a] + hit[1:-1] + [b]
        return self._search(a, b, others, gap, budget)

    def _search(self, a, b, others, gap: float, budget: int | None, window=None) -> list[tuple[float, float]] | None:
        nx, ny = self.nx, self.ny
        closed = bytearray(self.closed)
        for ox, oy in others:  # standing bodies close their discs of floor
            oi, oj = self.cell(ox, oy)
            for di, dj in _DISCS[gap]:
                i, j = oi + di, oj + dj
                if 0 <= i < nx and 0 <= j < ny:
                    closed[j * nx + i] = 1
        si, sj = self.cell(*a)
        gi, gj = self.cell(*b)
        start, goal = sj * nx + si, gj * nx + gi
        closed[start] = closed[goal] = 0
        for c in (start, goal):  # boxed in (a goal surrounded by people): no search can get there
            ci, cj = c % nx, c // nx
            if all(not (0 <= ci + di < nx and 0 <= cj + dj < ny) or closed[(cj + dj) * nx + ci + di]
                   for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1))):
                return None
        # budget: expansions allowed round people (a way round them this long is not worth walking); None = until found
        r2 = math.sqrt(2)
        moves = ((1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0), (1, 1, r2), (1, -1, r2), (-1, 1, r2), (-1, -1, r2))
        W = 1.5  # greedy: the path is pulled tight afterwards anyway
        i0, j0, i1, j1 = window if window is not None else (0, 0, nx - 1, ny - 1)  # a local search stays near its route
        g = [1e18] * (nx * ny)
        g[start] = 0.0
        came: dict[int, int] = {}
        heap = [(0.0, start)]
        flat = tuple((di, dj, w, dj * nx + di) for di, dj, w in moves)  # the same neighbour order, as flat index steps
        push, pop = heapq.heappush, heapq.heappop
        while heap:
            _f, cur = pop(heap)
            if budget is not None:
                budget -= 1
                if budget < 0:
                    return None
            if cur == goal:
                out = [cur]
                while cur in came:
                    cur = came[cur]
                    out.append(cur)
                out.reverse()
                keep = [c for k, c in enumerate(out[1:-1], 1)  # only where the grid path changes direction
                        if (c - out[k - 1]) != (out[k + 1] - c)]
                return [a] + [self.centre(c % nx, c // nx) for c in keep] + [b]
            ci, cj = cur % nx, cur // nx
            gc = g[cur]
            inside = i0 < ci < i1 and j0 < cj < j1  # not on the window's edge: no neighbour can fall outside it
            for di, dj, w, step in flat:
                if inside:
                    n = cur + step
                    i, j = ci + di, cj + dj
                else:
                    i, j = ci + di, cj + dj
                    if not (i0 <= i <= i1 and j0 <= j <= j1):
                        continue
                    n = cur + step
                if closed[n]:
                    continue
                if di and dj and (closed[cur + di] or closed[cur + dj * nx]):
                    continue  # no cutting corners
                ng = gc + w
                if ng < g[n] - 1e-9:
                    g[n] = ng
                    came[n] = cur
                    dx, dy = abs(i - gi), abs(j - gj)
                    push(heap, (ng + W * (dx + dy + (r2 - 2) * min(dx, dy)), n))
        return None

    def _pull(self, pts: list, others: tuple, gap: float = BODY_GAP) -> list[tuple[float, float]]:
        """Line-of-sight smoothing in one pass: keep a corner only where the straight line from the last kept
        point to the next one is blocked."""
        if len(pts) <= 2:
            return [(round(x, 3), round(y, 3)) for x, y in pts]
        out = [pts[0]]
        for k in range(1, len(pts) - 1):
            if not self.line(out[-1], pts[k + 1], others, gap):
                out.append(pts[k])
        out.append(pts[-1])
        return [(round(x, 3), round(y, 3)) for x, y in out]


@lru_cache(maxsize=None)
def grid(template: str) -> Grid:
    return Grid(template)
