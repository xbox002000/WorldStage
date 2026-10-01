"""Roles: a person cast, for a season, in a part that leans their choices without rewriting them (primitive production.roles).

The Truman Show has actors, and the world it keeps real is the hero's. Here an actor is somebody the producer has cast: for a
while they are the doubter, the rival, the mentor, the troublemaker, the other suitor. A *role policy* is an external bias on the
options they already have, never a new option and never a script:

  - it can only raise or lower the score of choices the rules already offer (a cold word to the hero, a challenge, a flirt),
    and the rules still judge whatever is chosen, so an actor can lose, can be made a fool of, can be hurt, like anyone;
  - it is bounded (MAX_PUSH), and a person's own nature pushes back: the more of a policy's `resists` traits they have (an honest
    person is slower to sneer, a generous one slower to wound), the less of it they follow. The same part, cast on two different
    people, is played two different ways, and not always;
  - it ends (`until`), and the person carries everything that happened back into their own life.

Casting itself is world truth, so it can be audited: the producer's `cast_role` intervention (world/interventions.py) sets the
person's `role.<id>`, `role_for.<id>` (the hero it is played towards) and `role_until.<id>` (a day), and the decision record names
the role whenever it leaned a choice. The hero is never an actor: their reactions are always their own.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from contracts.recipe import MechanicPrimitive as P
from world.attention import var
from world.domains.base import Change, Domain, EventSpec, Scored

MAX_PUSH = 0.9      # the most a role can add to one option
FLOOR = 0.25        # the least of a push that survives the person's own nature


@dataclass(frozen=True)
class Policy:
    """What a role leans, towards the hero: {action or action:tone: push}. `crowd` is how many others must be there for the
    push to apply to the ones marked so (a public sneer), `resists` the traits that hold a person back."""

    leans: dict[str, float]
    crowd: dict[str, int]
    resists: tuple[str, ...]


ROLES: dict[str, Policy] = {
    "doubter": Policy({"talk:cold": 0.6, "talk:hostile": 0.3, "challenge": 0.5, "talk:warm": -0.4},
                      {"talk:cold": 2, "challenge": 3}, ("generosity", "honesty")),
    "rival": Policy({"challenge": 0.8, "talk:cold": 0.3}, {}, ("generosity",)),
    "mentor": Policy({"talk:warm": 0.5, "talk:neutral": 0.3, "tell": 0.2}, {}, ()),
    "troublemaker": Policy({"accuse": 0.4, "tell": 0.5, "talk:hostile": 0.2}, {}, ("honesty", "generosity")),
    "suitor": Policy({"flirt": 0.6, "confess": 0.4, "talk:warm": 0.3}, {}, ("honesty",)),
}
CODES = {name: i + 1 for i, name in enumerate(ROLES)}
NAMES = {v: k for k, v in CODES.items()}


def role_of(conn: sqlite3.Connection, pid: str, day: int | None = None) -> tuple[str, str] | None:
    """(role, the hero it is played towards) while it lasts, else None."""
    code = int(var(conn, f"role.{pid}", 0.0))
    if code not in NAMES:
        return None
    if day is None:
        day = conn.execute("SELECT COALESCE(MAX(timestamp), 0) FROM events").fetchone()[0] // 1440
    if day > var(conn, f"role_until.{pid}", 0.0):
        return None
    people = sorted(r[0] for r in conn.execute("SELECT person_id FROM character_profiles"))
    idx = int(var(conn, f"role_for.{pid}", 0.0))
    return NAMES[code], (people[idx - 1] if 1 <= idx <= len(people) else "")


def _traits(conn: sqlite3.Connection, pid: str) -> dict:
    import json
    row = conn.execute("SELECT traits FROM personas WHERE person_id = ?", (pid,)).fetchone()
    return json.loads(row[0]) if row else {}


def resistance(conn: sqlite3.Connection, pid: str, policy: Policy) -> float:
    """How much of a push survives who they are: 1 for somebody with none of the traits that hold back, down to FLOOR."""
    if not policy.resists:
        return 1.0
    t = _traits(conn, pid)
    held = sum(t.get(k, 0.5) for k in policy.resists) / len(policy.resists)
    return max(FLOOR, 1.0 - 0.9 * held)


def push(conn: sqlite3.Connection, pid: str, hero: str, it, role: str, here: int) -> float:
    """What the role adds to one option: only options towards the hero, only those the policy names."""
    if it is None or it.target != hero:
        return 0.0
    pol = ROLES[role]
    key = f"{it.action}:{it.tone}" if it.action == "talk" and it.tone else it.action
    delta = pol.leans.get(key, 0.0)
    if delta and here < pol.crowd.get(key, 0):
        return 0.0  # a public sneer wants an audience
    return max(-MAX_PUSH, min(MAX_PUSH, delta * resistance(conn, pid, pol)))


class Roles(Domain):
    id = "roles"
    title = "角色"
    primitives = (P("production.roles", "social", "a person cast for a season in a part that leans their choices without rewriting "
                    "them; the rules still judge what they do", ["volition"], cost=0),)

    def initial_vars(self, pid: str, profile: dict | None) -> dict[str, float]:
        return {f"role.{pid}": 0.0, f"role_for.{pid}": 0.0, f"role_until.{pid}": 0.0}

    def shape(self, conn: sqlite3.Connection, actor: str, now: int, scored: Scored) -> Scored:
        cast = role_of(conn, actor, now // 1440)
        if cast is None or not cast[1]:
            return scored
        role, hero = cast
        here = conn.execute("SELECT COUNT(*) FROM people WHERE location_id = (SELECT location_id FROM people WHERE id = ?) AND id != ? "
                            "AND status = 'active'", (actor, actor)).fetchone()[0]
        return [(score + push(conn, actor, hero, it, role, here), it) for score, it in scored]

    def influences(self, conn: sqlite3.Connection, pid: str, now: int) -> list[dict]:
        cast = role_of(conn, pid, now // 1440)
        return [{"kind": "role", "role": cast[0], "toward": cast[1]}] if cast and cast[1] else []

    def nightly(self, conn: sqlite3.Connection, day: int, now: int) -> list[EventSpec]:
        """A part that has run its course ends: the person goes back to being only themselves."""
        change = []
        for (pid,) in conn.execute("SELECT person_id FROM character_profiles ORDER BY person_id"):
            code = var(conn, f"role.{pid}", 0.0)
            if code and day > var(conn, f"role_until.{pid}", 0.0):
                change += [Change("var", f"{k}.{pid}", "value", delta=-var(conn, f"{k}.{pid}", 0.0)) for k in ("role", "role_for", "role_until")]
        if not change:
            return []
        return [EventSpec(timestamp=now, type="role_ended", trigger_type="rule", importance=0.05, truth={"text": ""}, changes=change)]
