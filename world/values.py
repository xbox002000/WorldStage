"""What an act costs the one who does it: the values it serves and the values it betrays, for this person.

Every act has stakes in the values people hold (contracts/character.py VALUE_KEYS): a lie costs truth, accusing a
friend costs belonging, taking an offer serves freedom and ambition and costs security, belonging and loyalty. Who
feels it depends on the person: the same lie is nothing to someone who cares little for truth and a wound to
someone who lives by it.

An internal conflict is an act that serves one value someone holds dear while it betrays another they hold dear:
doing what one does not want to do. Its tension is the smaller of the two (both have to be large) and it is
recorded on the event (truth["dilemma"]) when it is high enough: a fact about this person and this act, computed
from their own profile and situation, never a reading after the fact. It changes nobody's choice; directors and the
Dramaturgy analysis look for it ("highest internal conflict", not just the loudest fight).

Domain packs give their own actions' stakes (ActionSpec.stakes): a function (conn, intent) -> {value: +serves/-costs}.
"""
from __future__ import annotations

import json
import sqlite3

from world.intent import Intent

RECORD = 0.3   # tension from which an act's dilemma is recorded on its event


def _aff(conn: sqlite3.Connection, a: str, b: str | None) -> float:
    if not b:
        return 0.0
    row = conn.execute("SELECT affection FROM relationships WHERE actor_id = ? AND target_id = ?", (a, b)).fetchone()
    return row[0] if row else 0.0


def stakes(conn: sqlite3.Connection, it: Intent) -> dict[str, float]:
    """value -> how much this act serves it (+) or betrays it (-), before weighing by the person's values (0..1)."""
    a, act, target = it.actor, it.action, it.target
    fond = max(0.0, _aff(conn, a, target))
    out: dict[str, float] = {}

    def add(v: str, x: float) -> None:
        out[v] = round(out.get(v, 0.0) + x, 3)

    if act == "tell" and it.claim_id is not None:
        c = conn.execute("SELECT subject, act FROM claims WHERE claim_id = ?", (it.claim_id,)).fetchone()
        subject = c[0] if c else ""
        about = max(0.0, _aff(conn, a, subject))
        if it.mode in ("lie", "distortion"):
            add("truth", -0.8 if it.mode == "lie" else -0.5)
            if about > 0.2:
                add("loyalty", 0.6 * about)       # covering for someone one cares about
            elif _aff(conn, a, subject) < -0.1:
                add("revenge", 0.6)               # bending it to hurt someone
        elif it.mode == "omission":
            add("truth", -0.3)
            add("loyalty", 0.4 * about)
        elif about > 0.3:                          # the truth, about a friend
            add("truth", 0.5)
            add("loyalty", -0.6 * about)
    elif act in ("confront", "accuse"):
        add("truth", 0.5)
        add("fairness", 0.5)
        add("belonging", -0.8 * fond)
    elif act == "steal":
        add("security", 0.6)
        add("fairness", -0.8)
        add("truth", -0.3)
    elif act == "give":
        add("fairness", 0.6)
        add("truth", 0.4)
        add("security", -0.3)
    elif act == "talk" and it.tone == "hostile":
        add("belonging", -0.7 * fond)
        add("revenge", 0.3)
    elif act == "talk" and it.tone == "warm" and _aff(conn, a, target) < -0.2:
        add("truth", -0.3)                        # smiling at someone one resents
        add("belonging", 0.3)
    elif act == "move" and (it.reason or "") == "reply:storm_off":
        add("belonging", -0.5 * fond)
        add("security", 0.3)
    else:
        from world.domains import action_spec
        spec = action_spec(act)
        fn = getattr(spec[1], "stakes", None) if spec else None
        if fn is not None:
            for v, x in fn(conn, it).items():
                add(v, x)
    return out


def held(conn: sqlite3.Connection, pid: str) -> dict[str, float]:
    """The values someone holds (their profile; the psyche's adaptive values where it keeps one)."""
    from world.profiles import profile
    p = profile(conn, pid)
    out = dict(p.values) if p is not None else {}
    for key in ("truth", "security", "belonging", "revenge"):  # the psyche moves these with experience
        row = conn.execute("SELECT value FROM world_vars WHERE key = ?", (f"psy.{pid}.value.{key}",)).fetchone()
        if row is not None and key in out:
            out[key] = round((out[key] + row[0]) / 2, 3)
    return out


def dilemma(conn: sqlite3.Connection, it: Intent) -> dict | None:
    """The act's internal conflict for its actor: what it serves and betrays among what they hold, and how much."""
    s = stakes(conn, it)
    if not s:
        return None
    v = held(conn, it.actor)
    if not v:
        return None
    serves = {k: round(x * v.get(k, 0.0), 3) for k, x in s.items() if x > 0 and v.get(k, 0.0) > 0}
    costs = {k: round(-x * v.get(k, 0.0), 3) for k, x in s.items() if x < 0 and v.get(k, 0.0) > 0}
    gain, loss = sum(serves.values()), sum(costs.values())
    tension = round(min(1.0, min(gain, loss) * 1.6), 3)
    return {"serves": serves, "costs": costs, "tension": tension} if serves and costs else None


def with_dilemma(conn: sqlite3.Connection, it: Intent, spec):
    """Record an act's internal conflict on its event when it is high enough."""
    from dataclasses import replace
    d = dilemma(conn, it)
    if d is None or d["tension"] < RECORD:
        return spec
    return replace(spec, truth={**spec.truth, "dilemma": d})


def recorded(conn: sqlite3.Connection, event_id: int) -> dict | None:
    row = conn.execute("SELECT json_extract(truth, '$.dilemma') FROM events WHERE event_id = ?", (event_id,)).fetchone()
    return json.loads(row[0]) if row and row[0] else None
