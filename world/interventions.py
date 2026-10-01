"""How the world takes an intervention in: a closed vocabulary of opportunities, judged by the rules, written as one event.

The producer (producer/) proposes; this decides whether the world may hear it, and says it. It is the only door:

  announce_gathering  a tournament or an assessment will be held at a place on a day. Everybody hears of it. Who goes, what
                      they do there and how it ends is nobody's but their own
  deliver_parcel      a parcel for somebody arrives. What they do with it is theirs
  open_seat           a position falls vacant, to be decided on a day. Who wants it, and who gets it, is not decided here
  announce_visitor    somebody from outside is said to be coming. (They arrive by their own rules.)
  cast_role           somebody is cast, until a day, in a part towards somebody else (world/domains/roles.py). It leans their
                      choices and rewrites nothing; nobody is told, and the hero is never cast

Nothing here names an outcome, a feeling, a relationship or a verdict, and nothing can: the parameters are closed (a day, a
place, a kind, an id), the words said to the town are the world's own templates, and a `WorldIntervention` has no field in which
to say why. The event carries an opaque id and the producer's `source`, nothing of any season, arc or purpose.
"""
from __future__ import annotations

import json
import sqlite3

from contracts.intervention import WorldIntervention
from world.events import Change, EventSpec, MemorySpec, apply_event
from world.seeds import humans

KINDS = ("tournament", "assessment")
# type -> the parameters it takes (and only those)
PARAMS = {"announce_gathering": {"kind", "place", "day"}, "deliver_parcel": {"object"}, "open_seat": {"day"},
          "announce_visitor": {"place", "day"}, "cast_role": {"role", "toward", "until"}}
LEAD_DAYS = 1  # an announcement is for a day at least this far ahead


def _day(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COALESCE(MAX(timestamp), 0) FROM events").fetchone()[0] // 1440


def problems(conn: sqlite3.Connection, wi: WorldIntervention) -> list[str]:
    """Why the world may not hear this (empty when it may)."""
    bad = []
    if wi.type not in PARAMS:
        return [f"{wi.type!r} is not in the closed vocabulary"]
    if wi.source != "producer":
        bad.append(f"source {wi.source!r} is not the producer")
    extra, missing = set(wi.params) - PARAMS[wi.type], PARAMS[wi.type] - set(wi.params)
    if extra:
        bad.append(f"parameters outside the vocabulary: {sorted(extra)}")
    if missing:
        bad.append(f"parameters missing: {sorted(missing)}")
    if bad:
        return bad
    if conn.execute("SELECT 1 FROM events WHERE type = 'intervention' AND json_extract(truth, '$.intervention_id') = ?",
                    (wi.intervention_id,)).fetchone():
        bad.append(f"{wi.intervention_id} was already made")
    p = wi.params
    today = _day(conn)
    if "day" in p and (not p["day"].isdigit() or int(p["day"]) < today + LEAD_DAYS):
        bad.append(f"day {p['day']!r} is not a day ahead")
    if "place" in p and conn.execute("SELECT 1 FROM locations WHERE id = ?", (p["place"],)).fetchone() is None:
        bad.append(f"no place {p['place']!r}")
    if wi.type == "announce_gathering" and p["kind"] not in KINDS:
        bad.append(f"no gathering of kind {p['kind']!r}")
    if wi.type == "deliver_parcel":
        o = conn.execute("SELECT status FROM objects WHERE id = ?", (p["object"],)).fetchone()
        if o is None or o[0] != "offstage":
            bad.append(f"{p['object']!r} is not waiting offstage")
        if wi.target not in humans(conn):
            bad.append(f"{wi.target!r} is nobody in the town")
    if wi.type == "open_seat":
        s = conn.execute("SELECT status FROM seats WHERE seat_id = ?", (wi.target,)).fetchone()
        if s is None:
            bad.append(f"no seat {wi.target!r}")
        elif s[0] != "held":
            bad.append(f"seat {wi.target!r} is already open")
    if wi.type == "cast_role":
        from world.domains.roles import ROLES
        from world.domains.roles import role_of
        if p["role"] not in ROLES:
            bad.append(f"no role {p['role']!r}")
        if wi.target not in humans(conn) or p["toward"] not in humans(conn) or wi.target == p["toward"]:
            bad.append("a role is played by one person towards another")
        elif role_of(conn, wi.target, today) is not None:
            bad.append(f"{wi.target!r} already has a part")
        elif role_of(conn, p["toward"], today) is not None:
            bad.append("the one it is played towards is an actor themselves")  # a hero is never cast
        elif any(role_of(conn, other, today) and role_of(conn, other, today)[1] == wi.target for other in humans(conn)):
            bad.append(f"{wi.target!r} is somebody's hero and cannot be cast")
        if conn.execute("SELECT 1 FROM world_vars WHERE key = ?", (f"role.{wi.target}",)).fetchone() is None:
            bad.append("this world has no actors")
        if not p["until"].isdigit() or int(p["until"]) < today + LEAD_DAYS:
            bad.append(f"until {p['until']!r} is not a day ahead")
    if wi.type == "announce_visitor":
        v = conn.execute("SELECT status FROM people WHERE id = ?", (wi.target,)).fetchone()
        if v is None or v[0] != "inactive":
            bad.append(f"{wi.target!r} is not somebody waiting outside")
    return bad


def _say(conn: sqlite3.Connection, wi: WorldIntervention) -> str:
    """What the town is told, in the world's own words (a template, never the producer's)."""
    names = {r[0]: r[1] for r in conn.execute("SELECT id, name FROM people UNION ALL SELECT id, name FROM objects UNION ALL "
                                              "SELECT id, name FROM locations")}
    p = wi.params
    if wi.type == "announce_gathering":
        what = "比武大會" if p["kind"] == "tournament" else "門派考核"
        return f"{names[p['place']]}將在第{p['day']}天舉行{what}"
    if wi.type == "deliver_parcel":
        return f"有人送來了一個給{names[wi.target]}的{names[p['object']]}"
    if wi.type == "open_seat":
        title = conn.execute("SELECT title FROM seats WHERE seat_id = ?", (wi.target,)).fetchone()[0]
        return f"「{title}」的位子空了出來，第{p['day']}天決定人選"
    if wi.type == "cast_role":
        return ""  # nobody is told
    return f"聽說{names[wi.target]}將在第{p['day']}天來到{names[p['place']]}"


def apply(conn: sqlite3.Connection, wi: WorldIntervention, now: int) -> int:
    """Write the intervention as one event, if the world may hear it. Raises ValueError otherwise."""
    bad = problems(conn, wi)
    if bad:
        raise ValueError("; ".join(bad))
    text = _say(conn, wi)
    changes: list[Change] = []
    participants: list[tuple[str, str]] = []
    told = humans(conn)
    if wi.type == "deliver_parcel":
        o = wi.params["object"]
        changes = [Change("object", o, "status", value="normal"), Change("object", o, "owner_person_id", value=wi.target),
                   Change("object", o, "rightful_owner_id", value=wi.target)]
        participants = [(wi.target, "receiver")]
        told = [wi.target]
    elif wi.type == "cast_role":
        from world.domains.roles import CODES
        people = sorted(r[0] for r in conn.execute("SELECT person_id FROM character_profiles"))
        changes = [Change("var", f"role.{wi.target}", "value", delta=float(CODES[wi.params["role"]])),
                   Change("var", f"role_for.{wi.target}", "value", delta=float(people.index(wi.params["toward"]) + 1)),
                   Change("var", f"role_until.{wi.target}", "value", delta=float(wi.params["until"]))]
        told = []
    elif wi.type == "open_seat":
        cur = conn.execute("SELECT decide_by FROM seats WHERE seat_id = ?", (wi.target,)).fetchone()[0]
        changes = [Change("seat", wi.target, "status", value="vacant"),
                   Change("seat", wi.target, "decide_by", delta=int(wi.params["day"]) - cur)]
    memories = [MemorySpec(p, text, 0.9, source_type="external_rumor", source_id=wi.intervention_id) for p in told]
    return apply_event(conn, EventSpec(
        timestamp=now, type="intervention", trigger_type="external", importance=0.4,
        truth={"intervention_id": wi.intervention_id, "kind": wi.type, "target": wi.target, "params": dict(wi.params),
               "text": text, "source": wi.source},
        participants=participants, changes=changes, memories=memories))


def made(conn: sqlite3.Connection) -> list[dict]:
    """Every intervention the world has heard, in order (what a reader of the world can see of the producer)."""
    return [{"event_id": r[0], "timestamp": r[1], **json.loads(r[2])} for r in conn.execute(
        "SELECT event_id, timestamp, truth FROM events WHERE type = 'intervention' ORDER BY event_id")]
