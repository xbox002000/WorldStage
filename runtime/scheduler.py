"""ActionScheduler: every body's resources on the runtime clock, so no body is ever driven by two things at once.

    move    where the body is and which way it faces: walking, turning, rising, sitting down, reaching, handing over
    hands   the right hand (a person) or the mouth (an animal): taking hold, letting go, handing over, striking
    voice   speaking (compatible with walking and looking)

Two bookings of the same resource of the same body may never overlap: a walk and a turn, or a pick-up and a hand-over,
are exclusive, while walk + talk or walk + look are not (they use different resources). The runtime resolves a
conflict by starting the later action when the resource is free (it waits); a booking that would still overlap is
a bug, and raises instead of drawing a body in two places.
"""
from __future__ import annotations

from dataclasses import dataclass, field

EPS = 1e-6
RESOURCES = ("move", "hands", "voice")


class SchedulingConflict(AssertionError):
    pass


@dataclass
class Booking:
    start: float
    end: float
    kind: str
    event: int


@dataclass
class ActionScheduler:
    books: dict[tuple[str, str], list[Booking]] = field(default_factory=dict)

    def free(self, who: str, *resources: str) -> float:
        """When all of these resources of this body are next free (append-only: after its last booking)."""
        return max([self.books[(who, r)][-1].end for r in resources if self.books.get((who, r))] or [0.0])

    def book(self, who: str, resources: tuple[str, ...], start: float, end: float, kind: str, event: int) -> None:
        start, end = round(start, 3), round(end, 3)  # the runtime's clock resolution
        if end < start - EPS:
            raise SchedulingConflict(f"{who} {kind}: ends before it starts ({start} > {end})")
        for r in resources:
            if r not in RESOURCES:
                raise ValueError(r)
            rows = self.books.setdefault((who, r), [])
            if rows and start < rows[-1].end - EPS:
                last = rows[-1]
                raise SchedulingConflict(f"{who}.{r}: {kind} (event {event}) at {start:.3f} overlaps {last.kind} "
                                         f"(event {last.event}) until {last.end:.3f}")
            rows.append(Booking(round(start, 3), round(end, 3), kind, event))

    def summary(self) -> dict:
        out: dict[str, int] = {}
        for (_who, r), rows in self.books.items():
            out[r] = out.get(r, 0) + len(rows)
        return dict(sorted(out.items()))
