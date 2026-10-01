"""Causal audit: can a person's "now" be explained by their past? A read model: it never writes to the world.

Three kinds of memory, as the persona layer keeps them:

  facts            what happened, as the person believes it: their memories and the claims behind them (world/claims.py)
  experiences      what it did to them: each night's reflection lists which event gave how much of each experience
                   (hurt, wronged, shame, kindness, ...)                       -> reflection.truth.experienced
  interpretations  how they came to see themselves: the self-models a reflection formed, with the experiences that
                   piled up to it                                              -> reflection.truth.formed

`trace(event)` follows one choice back: the record of why it was made (truth.influences, agent/trace.py) names the
self-models and goals that were leaning it; a self-model leads to the reflection that formed it, that reflection to the
events that hurt (or warmed) them. `audit` does it for a sample and says how many chains are whole: a chain is whole when
every link exists, comes before what it explains, and involves the person.

Worlds made before the records existed (no social.exchange) have no chains: they are reported as having nothing to
audit, never as failures.
"""
from __future__ import annotations

import json
import sqlite3

from world.psyche import SELF_MODEL
from world.rng import rng as make_rng


def _truth(row) -> dict:
    return json.loads(row["truth"])


def _reflections(conn: sqlite3.Connection, pid: str, upto: int | None = None):
    q = ("SELECT event_id, timestamp, truth FROM events WHERE type = 'reflection' "
         "AND json_extract(truth, '$.actor') = ?" + (" AND event_id <= ?" if upto is not None else "") + " ORDER BY event_id")
    return conn.execute(q, (pid, upto) if upto is not None else (pid,)).fetchall()


def experiences(conn: sqlite3.Connection, pid: str) -> list[dict]:
    """What happened to someone, night by night: [{day, kind, weight, event, reflection}]."""
    out = []
    for r in _reflections(conn, pid):
        t = _truth(r)
        for kind, items in (t.get("experienced") or {}).items():
            for eid, w in items:
                out.append({"day": t["day"], "kind": kind, "weight": w, "event": eid, "reflection": r["event_id"]})
    return out


def interpretations(conn: sqlite3.Connection, pid: str) -> list[dict]:
    """How someone came to see themselves: [{key, text, day, reflection, because: [experience, ...]}], in order."""
    out = []
    for r in _reflections(conn, pid):
        t = _truth(r)
        for key in t.get("formed") or []:
            out.append({"key": key, "text": SELF_MODEL[key][0], "day": t["day"], "reflection": r["event_id"],
                        "because": _because(conn, pid, key, r["event_id"])})
    return out


def _because(conn: sqlite3.Connection, pid: str, key: str, upto: int) -> list[dict]:
    source = SELF_MODEL[key][1]
    out = []
    for r in _reflections(conn, pid, upto):
        t = _truth(r)
        for eid, w in (t.get("experienced") or {}).get(source, []):
            out.append({"event": eid, "kind": source, "weight": w, "day": t["day"], "reflection": r["event_id"]})
    return out


def facts(conn: sqlite3.Connection, pid: str, limit: int = 5) -> list[dict]:
    """The strongest things someone believes happened: [{belief, confidence}]."""
    return [{"belief": r["belief"], "confidence": r["confidence"]} for r in conn.execute(
        "SELECT belief, confidence FROM memories WHERE observer_id = ? AND belief NOT LIKE '我開始覺得：%' "
        "ORDER BY confidence DESC, memory_id DESC LIMIT ?", (pid, limit))]


def three_memories(conn: sqlite3.Connection, pid: str) -> dict:
    return {"facts": facts(conn, pid), "experiences": experiences(conn, pid), "interpretations": interpretations(conn, pid)}


def _event(conn: sqlite3.Connection, eid: int):
    return conn.execute("SELECT event_id, timestamp, truth FROM events WHERE event_id = ?", (eid,)).fetchone()


def _took_part(conn: sqlite3.Connection, eid: int, pid: str) -> bool:
    return conn.execute("SELECT 1 FROM event_participants WHERE event_id = ? AND person_id = ?", (eid, pid)).fetchone() is not None


def _self_model_link(conn: sqlite3.Connection, pid: str, factor: dict, at) -> dict:
    key = factor["key"]
    link = {"kind": "self_model", "key": key, "text": SELF_MODEL[key][0], "formed_by": None, "because": [], "problems": []}
    formed = None
    for r in _reflections(conn, pid, at["event_id"]):
        if key in (_truth(r).get("formed") or []):
            formed = r  # the latest time it formed before this choice
    if formed is None:
        link["problems"].append("no reflection formed this self-model before the choice")
        link["whole"] = False
        return link
    link["formed_by"] = formed["event_id"]
    link["because"] = _because(conn, pid, key, formed["event_id"])
    if not link["because"]:
        link["problems"].append("the reflection that formed it cites no experience")
    for b in link["because"]:
        e = _event(conn, b["event"])
        if e is None:
            link["problems"].append(f"experience event {b['event']} does not exist")
        elif e["timestamp"] >= formed["timestamp"]:
            link["problems"].append(f"experience event {b['event']} is not before the reflection")
        elif not _took_part(conn, b["event"], pid):
            link["problems"].append(f"{pid} did not take part in event {b['event']}")
    link["whole"] = not link["problems"]
    return link


def _goal_link(conn: sqlite3.Connection, pid: str, factor: dict) -> dict:
    link = {"kind": "goal", "slot": factor["slot"], "problems": []}
    person, _, slot = factor["slot"].partition(":")
    row = conn.execute("SELECT kind, status FROM goals WHERE person_id = ? AND slot = ?",
                       (person, int(slot) if slot.isdigit() else slot)).fetchone()
    if row is None:
        link["problems"].append("no such goal")
    link["whole"] = not link["problems"]
    return link


def trace(conn: sqlite3.Connection, event_id: int) -> dict | None:
    """Why this choice was made, followed back through the self-models and goals that leaned it to the events behind
    them. None when the event has no record of why."""
    row = _event(conn, event_id)
    if row is None:
        return None
    t = _truth(row)
    inf = t.get("influences")
    if not inf:
        return None
    pid = t.get("actor", "")
    links = []
    for f in inf.get("factors", []):
        if f["kind"] == "self_model":
            links.append(_self_model_link(conn, pid, f, row))
        elif f["kind"] == "goal":
            links.append(_goal_link(conn, pid, f))
    answer = (inf.get("situation") or {}).get("to")
    return {"event": event_id, "actor": pid, "p": inf["p"], "answering": answer, "links": links,
            "body": [f for f in inf.get("factors", []) if f["kind"] == "body"],
            "whole": all(link["whole"] for link in links)}


def audit(conn: sqlite3.Connection, n: int = 20, seed: int = 0) -> dict:
    """Trace a sample of the choices a self-model was leaning. {"candidates", "checked", "whole", "failures"}."""
    ids = [r[0] for r in conn.execute(
        "SELECT event_id FROM events WHERE json_extract(truth, '$.influences.factors') LIKE '%\"self_model\"%' ORDER BY event_id")]
    rng = make_rng(seed, 0, "causal_audit", "sample")
    picked = sorted(rng.sample(ids, min(n, len(ids))))
    failures, whole = [], 0
    for eid in picked:
        chain = trace(conn, eid)
        if chain is not None and chain["whole"] and chain["links"]:
            whole += 1
        else:
            failures.append({"event": eid, "chain": chain})
    return {"candidates": len(ids), "checked": len(picked), "whole": whole, "failures": failures}
