"""The shaper: what is lacking -> the least that can be done about it, in the world's own closed vocabulary.

An opportunity says what it lacks (narrative/opportunity.py). Each lack has a fixed, small answer here, and nothing else: it
cannot be made to say "so that they win". The answers are all things the town does with anyway (an occasion, a part, a parcel,
a vacancy), and what comes of them is the people's and the rules'.

  occasion    announce a tournament, a couple of days ahead, at the training ground
  challenger  cast the one who looks down on the hero as the doubter (a lean on choices they already have), or cast somebody who
              wants the same person as the hero in the suitor's part
  vacancy     the seat falls vacant, to be decided in a few days
  strength    deliver the manual (only when the hero is a little short: a parcel for somebody who would win anyway buys nothing)
  recovery    nothing: somebody is hurt, and waiting is the only answer
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from contracts.opportunity import Opportunity
from producer.intervention import COSTS

OCCASION_LEAD = 2      # days ahead a gathering is announced
ROLE_DAYS = 7          # how long a part runs
SEAT_LEAD = 5


@dataclass(frozen=True)
class Candidate:
    lack: str
    type: str
    target: str
    params: dict
    purpose: str

    @property
    def cost(self) -> int:
        return COSTS[self.type]


def _training_place(conn: sqlite3.Connection) -> str:
    return next((r[0] for r in conn.execute("SELECT id FROM locations WHERE tags LIKE '%\"training\"%' ORDER BY id")), "")


def candidates(conn: sqlite3.Connection, op: Opportunity, day: int, protected: set[str]) -> list[Candidate]:
    """The answers to what an opportunity lacks, cheapest and most basic first. Whether the world takes them is not decided here."""
    from world.domains.roles import role_of
    out: list[Candidate] = []
    held = {m.lack for m in op.missing}
    tourney = op.evidence.get("tournament_day")
    until = str((tourney + 1) if tourney is not None else day + ROLE_DAYS)
    if "recovery" in held:
        return []
    if op.kind == "reversal":
        if "occasion" in held:
            tourney = day + OCCASION_LEAD
            until = str(tourney + 1)
            out.append(Candidate("occasion", "announce_gathering", "", {"kind": "tournament", "place": _training_place(conn), "day": str(tourney)},
                                 f"somewhere {op.others[0]} could be seen against {op.protagonist}"))
        if "challenger" in held and op.others[0] not in protected and role_of(conn, op.others[0], day) is None:
            out.append(Candidate("challenger", "cast_role", op.others[0], {"role": "doubter", "toward": op.protagonist, "until": until},
                                 f"{op.others[0]} looks down on {op.protagonist}"))
        if "strength" in held:
            out.append(Candidate("strength", "deliver_parcel", op.protagonist, {"object": "manual_secret"},
                                 f"{op.protagonist} is a little short of what it takes"))
    elif op.kind == "triangle" and "challenger" in held:
        rival, wanted = op.others[0], op.evidence["object"]
        if rival not in protected - {op.protagonist} and role_of(conn, rival, day) is None:
            out.append(Candidate("challenger", "cast_role", rival, {"role": "suitor", "toward": wanted, "until": str(day + ROLE_DAYS)},
                                 f"{rival} has been slow to want {wanted}"))
    elif op.kind == "succession" and "vacancy" in held:
        out.append(Candidate("vacancy", "open_seat", op.evidence["seat"], {"day": str(day + SEAT_LEAD)}, f"{op.protagonist} could hold the seat"))
    return out
