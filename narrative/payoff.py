"""Payoff: when what had been building is released, and whether the person earned it. Metric payoff_metric_v0.1 (a draft).

dramaturgy_metric_v1 (narrative/dramaturgy.py) measures tension and stays frozen. This measures *release*: a payoff is a moment
in the world's history where somebody who had been held down, kept waiting or counted out is, in front of others, proved
right, chosen or put in the place they were after. It finds them in what happened; it never creates one, and it only counts what
was already set up.

A payoff event is one of:
  face_slap   a duel the underdog won, in front of witnesses      (the duel's `slap`, world/domains/progression.py)
  chosen      a confession that was accepted
  succession  a contested seat won, against the favourite

and it is scored in six parts, each 0..1:

  expectation_gap       how far the audience's expectation (narrative/audience.py, as of *before* the event) was from what
                        happened. An expectation that was not already there a day earlier counts for a third: irony cannot
                        be made at the moment of the payoff
  social_witness        how many saw it (the people there; the voters)
  pressure              what the protagonist had been through in the week before (shame, wrongs, failure, hostility)
  magnitude             how much was won (how big the surprise; how unlikely the yes; the seat)
  causal_investment     what they had themselves put in beforehand (practice, courtship, campaigning)
  agency_attribution    how much of the result is theirs (below)

    base          = 0.30 gap + 0.15 witness + 0.20 pressure + 0.20 magnitude + 0.15 investment
    earned_payoff = base x agency_attribution

Agency attribution is not guessed. It is the share of the causes on record that were the protagonist's own choices (their practice,
the challenge or the courtship they chose to make, the campaign they ran, the reflection that turned a defeat into tempering)
against those that were not: an opportunity the producer arranged (the stage: a gathering, a vacancy), a parcel it delivered
(each practice done with it counts half to it) and plain luck (how unlikely the result was: the lower the chance, the more of it
was luck). A payoff the producer handed over scores low here however dramatic it looks; one that the person made themselves scores
high. The weights are in this file and in docs/payoff.md, and they will move as the data says so (hence v0.1).
"""
from __future__ import annotations

import json
import sqlite3
from collections import Counter

from narrative import audience as A

METRIC_VERSION = "payoff_metric_v0.1"
WEIGHTS = {"gap": 0.30, "witness": 0.15, "pressure": 0.20, "magnitude": 0.20, "investment": 0.15}
WINDOW_DAYS = 14          # what counts as "beforehand" for practice, courtship and campaigning
PRESSURE_DAYS = 7
OWN = {"train": 1.0, "challenge": 1.0}     # units a choice of one's own is worth (capped below)
OWN_CAP = 10.0
DEFEAT_UNITS = 2.0        # a defeat that was turned into tempering
STAGE_UNITS = 1.0         # an opportunity the producer arranged
PARCEL_SHARE = 0.5        # of a practice done with a delivered manual, the producer's
LUCK_UNITS = 3.0          # times how unlikely the result was
EARNED_AT = 0.35          # an earned payoff counts as "earned" from this score
NEW_IRONY = 1 / 3         # an expectation less than a day old counts for this much of its gap


def _truth(row) -> dict:
    return json.loads(row["truth"])


def _clip(x: float) -> float:
    return max(0.0, min(1.0, x))


def _pressure(conn: sqlite3.Connection, pid: str, day: int) -> float:
    """What somebody had been through in the week before: the weight of shame, wrongs, failure and hostility in their nightly
    reflections (psyche), over 3."""
    total = 0.0
    for r in conn.execute("SELECT truth FROM events WHERE type = 'reflection' AND json_extract(truth, '$.actor') = ? AND "
                          "json_extract(truth, '$.day') >= ? AND json_extract(truth, '$.day') < ?", (pid, day - PRESSURE_DAYS, day)):
        exp = json.loads(r[0]).get("experiences", {})
        total += sum(exp.get(k, 0.0) for k in ("shame", "wronged", "failure", "hostility"))
    return _clip(total / 3.0)


def _own_events(conn: sqlite3.Connection, pid: str, kinds: tuple[str, ...], day: int, upto: int) -> list[sqlite3.Row]:
    marks = ",".join("?" * len(kinds))
    return conn.execute(
        f"SELECT event_id, timestamp, type, truth FROM events WHERE type IN ({marks}) AND event_id < ? AND timestamp >= ? "
        f"AND json_extract(truth, '$.actor') = ? AND trigger_type != 'external' ORDER BY event_id",
        (*kinds, upto, (day - WINDOW_DAYS) * 1440, pid)).fetchall()


def _stage(conn: sqlite3.Connection, kinds: tuple[str, ...], day: int, upto: int, match: dict | None = None) -> list[int]:
    """The producer's interventions that made the stage (a gathering, a vacancy) in the weeks before."""
    out = []
    for r in conn.execute("SELECT event_id, truth FROM events WHERE type = 'intervention' AND event_id < ? AND timestamp >= ? ORDER BY event_id",
                          (upto, (day - WINDOW_DAYS) * 1440)):
        t = json.loads(r[1])
        if t["kind"] in kinds and all(str(t.get("params", {}).get(k, t.get(k))) == str(v) for k, v in (match or {}).items()):
            out.append(r[0])
    return out


def _parcels(conn: sqlite3.Connection, pid: str, upto: int) -> bool:
    """Was a parcel delivered to this person by the producer (so that practice with a manual is partly its)?"""
    return conn.execute("SELECT 1 FROM events WHERE type = 'intervention' AND event_id < ? AND json_extract(truth, '$.kind') = 'deliver_parcel' "
                        "AND json_extract(truth, '$.target') = ? LIMIT 1", (upto, pid)).fetchone() is not None


def _agency(own: float, producer: float, luck: float) -> float:
    total = own + producer + luck
    return round(own / total, 4) if total > 0 else 0.0


def _score(parts: dict[str, float], agency: float) -> dict:
    base = sum(WEIGHTS[k] * parts[k] for k in WEIGHTS)
    return {"parts": {k: round(v, 3) for k, v in parts.items()}, "base": round(base, 4), "agency": agency,
            "earned": round(base * agency, 4)}


# -- the three kinds of payoff ---------------------------------------------------------------------------------------
def _slap(conn: sqlite3.Connection, row: sqlite3.Row) -> dict | None:
    t = _truth(row)
    slap = t.get("slap")
    if not slap:
        return None
    eid, day = row["event_id"], row["timestamp"] // 1440
    hero, rival = t["winner"], t["loser"]
    exp = A.expectation_of(conn, hero, eid - 1)  # what the audience expected, as of just before
    gap = _clip((exp.knows - exp.expected) / 0.4) if exp is not None else 0.0
    waited = (day - exp.since_day) if exp is not None and exp.since_day else 0   # days the audience had been waiting
    if waited < 1:
        gap *= NEW_IRONY  # the irony was not there a day earlier: it cannot be made at the moment of the payoff
    parts = {"gap": gap, "witness": _clip((slap["witnesses"] + 2) / 5), "pressure": _pressure(conn, hero, day),
             "magnitude": _clip(2.0 * slap["surprise"] + 0.2 * len(slap["sneered"])), "investment": 0.0}
    trains = _own_events(conn, hero, ("train",), day, eid)
    defeats = [r for r in conn.execute("SELECT event_id FROM events WHERE type = 'duel' AND event_id < ? AND timestamp >= ? AND "
                                       "json_extract(truth, '$.loser') = ? ORDER BY event_id", (eid, (day - WINDOW_DAYS) * 1440, hero))]
    breakthroughs = _own_events(conn, hero, ("breakthrough",), day, eid)
    parts["investment"] = _clip((len(trains) + 2 * len(breakthroughs)) / 8.0)
    manual = _parcels(conn, hero, eid)
    own = min(OWN_CAP, sum(OWN["train"] * (1 - (PARCEL_SHARE if (manual and json.loads(r["truth"]).get("with_manual")) else 0.0)) for r in trains))
    own += DEFEAT_UNITS * len(defeats) + (1.0 if t["actor"] == hero else 0.0)  # (the challenge itself, if it was theirs)
    producer = STAGE_UNITS * len(_stage(conn, ("announce_gathering",), day, eid)) + PARCEL_SHARE * sum(
        1 for r in trains if manual and json.loads(r["truth"]).get("with_manual"))
    p_win = t["p_challenger"] if t["actor"] == hero else 1.0 - t["p_challenger"]
    luck = LUCK_UNITS * _clip(2.0 * (1.0 - p_win)) if p_win < 0.5 else 0.0
    return {"kind": "face_slap", "event_id": eid, "day": day, "protagonist": hero, "against": rival,
            "causes": {"practice": [r["event_id"] for r in trains], "defeats": [r[0] for r in defeats], "breakthroughs": [r["event_id"] for r in breakthroughs],
                       "stage": _stage(conn, ("announce_gathering",), day, eid), "p_win": round(p_win, 3)},
            **_score(parts, _agency(own, producer, luck))}


def _chosen(conn: sqlite3.Connection, row: sqlite3.Row) -> dict | None:
    t = _truth(row)
    if t.get("outcome") != "accepted":
        return None
    eid, day = row["event_id"], row["timestamp"] // 1440
    hero, other = t["actor"], t["target"]
    before = A.before_event(conn, eid)
    pair = sorted([hero, other])
    waited = [c for c in before.claims if c.kind in ("unspoken_crush", "unrequited_love") and sorted(c.people) == pair]
    rivals = bool(t.get("left")) or any(c.kind == "unrequited_love" and c.people[1] == other and c.people[0] != hero for c in before.claims)
    gap = _clip(0.45 * bool(waited) + 0.35 * (waited[0].gap if waited else 0.0) + 0.3 * rivals)
    flirts = _own_events(conn, hero, ("flirt", "date"), day, eid)
    witnesses = conn.execute("SELECT COUNT(*) FROM event_participants WHERE event_id = ? AND role = 'witness'", (eid,)).fetchone()[0]
    parts = {"gap": gap, "witness": _clip(witnesses / 3.0), "pressure": _pressure(conn, hero, day), "magnitude": _clip(1.2 - t["p"]),
             "investment": _clip(len(flirts) / 4.0)}
    own = min(OWN_CAP, float(len(flirts))) + 1.0
    luck = LUCK_UNITS * _clip(2.0 * (0.5 - t["p"])) if t["p"] < 0.5 else 0.0
    return {"kind": "chosen", "event_id": eid, "day": day, "protagonist": hero, "against": other,
            "causes": {"courtship": [r["event_id"] for r in flirts], "p_yes": t["p"], "rivals": rivals},
            **_score(parts, _agency(own, 0.0, luck))}


def _succession(conn: sqlite3.Connection, row: sqlite3.Row) -> dict | None:
    t = _truth(row)
    cands = t["candidates"]
    if len(cands) < 2:
        return None
    eid, day = row["event_id"], row["timestamp"] // 1440
    hero, voters = t["winner"], list(t["votes"])

    def standing(c: str) -> float:  # what the voters thought of each candidate just before: the favourite is who they most respected
        views = [float(A.value_at(conn, "relationship", f"{v}:{c}", "respect", eid - 1)) for v in voters if v != c]
        return sum(views) / len(views) if views else 0.0
    ranks = {c: standing(c) for c in cands}
    favourite = max(cands, key=lambda c: (ranks[c], c))
    gap = 0.0 if hero == favourite else _clip(0.3 + (ranks[favourite] - ranks[hero]) / 0.3)
    camp = _own_events(conn, hero, ("campaign",), day, eid)
    parts = {"gap": gap, "witness": _clip(len(voters) / 5.0), "pressure": _pressure(conn, hero, day), "magnitude": 0.8,
             "investment": _clip(len(camp) / 4.0)}
    own = min(OWN_CAP, float(len(camp))) + 1.0
    stage = _stage(conn, ("open_seat",), day, eid, {"target": t["seat"]})
    return {"kind": "succession", "event_id": eid, "day": day, "protagonist": hero, "against": favourite if favourite != hero else None,
            "causes": {"campaign": [r["event_id"] for r in camp], "stage": stage, "favourite": favourite},
            **_score(parts, _agency(own, STAGE_UNITS * len(stage), 0.0))}


FINDERS = (("duel", _slap), ("confession", _chosen), ("succession", _succession))


def payoffs(conn: sqlite3.Connection) -> list[dict]:
    """Every payoff in the world's history, in order, each scored."""
    out = []
    for etype, find in FINDERS:
        for row in conn.execute("SELECT event_id, timestamp, truth FROM events WHERE type = ? ORDER BY event_id", (etype,)).fetchall():
            p = find(conn, row)
            if p is not None:
                out.append(p)
    return sorted(out, key=lambda p: p["event_id"])


def summary(conn: sqlite3.Connection, found: list[dict] | None = None) -> dict:
    """The numbers a world is judged by: how many payoffs, how many earned, how fairly shared, how long the audience waited."""
    found = payoffs(conn) if found is None else found
    people = [r[0] for r in conn.execute("SELECT person_id FROM character_profiles ORDER BY person_id")]
    per = Counter(p["protagonist"] for p in found)
    shares = sorted(per.get(p, 0) for p in people)
    n = len(shares)
    gini = (sum((2 * (i + 1) - n - 1) * x for i, x in enumerate(shares)) / (n * sum(shares))) if n and sum(shares) else 0.0
    base = sum(p["base"] for p in found)
    return {"metric": METRIC_VERSION, "count": len(found), "by_kind": dict(Counter(p["kind"] for p in found)),
            "protagonists": len(per), "per_person": dict(per), "fairness_gini": round(gini, 3),
            "base": round(base, 3), "earned": round(sum(p["earned"] for p in found), 3),
            "earned_share": round(sum(p["earned"] for p in found) / base, 3) if base else 0.0,
            "earned_payoffs": sum(1 for p in found if p["earned"] >= EARNED_AT),
            "mean_agency": round(sum(p["agency"] for p in found) / len(found), 3) if found else 0.0}
