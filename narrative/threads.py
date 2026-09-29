"""Story threads, derived read-only from world history.

A thread gathers the events around one open question:
item    what became of a thing: lost, taken, missed, suspected, accused, returned;
debt    money between two people: lent, repaid, owed;
rumor   a claim being passed on, twisted, repeated by a parrot, confronted;
feud    two people who keep clashing: cold or hostile words, a false accusation.

One event can belong to several threads (a lie about a stolen watch is in the watch's thread and in the rumour's),
which is how threads cross. Nothing here writes to the world.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from contracts.claim import TRUE, Claim
from contracts.thread import StoryThread
from world.claims import evaluate, labels

ITEM_EVENTS = ("misplace", "take", "find", "give", "steal", "notice_missing", "accuse", "seed", "cash_prize", "backstory")
DUEL_ITEM = "returned"  # a duel that settles who holds a thing joins that thing's thread
RUMOR_EVENTS = ("tell", "confront", "parrot_speaks")
PRINCIPAL_ROLES = ("actor", "target", "victim", "suspect", "receiver", "addressee")
DECISION = "decision"
EXPOSED = ("lie_exposed", "distortion_exposed", "concealment_exposed", "caught")
MIN_FEUD_EVENTS = 3
DORMANT_AFTER_DAYS = 3


@dataclass
class Row:
    id: int
    ts: int
    type: str
    trigger: str
    importance: float
    parent: int | None
    truth: dict
    principals: list[str]

    @property
    def day(self) -> int:
        return self.ts // 1440


def _rows(conn: sqlite3.Connection) -> dict[int, Row]:
    parts: dict[int, list[str]] = {}
    for r in conn.execute("SELECT event_id, person_id, role FROM event_participants ORDER BY rowid"):
        if r["role"] in PRINCIPAL_ROLES and r["person_id"] not in parts.setdefault(r["event_id"], []):
            parts[r["event_id"]].append(r["person_id"])
    return {r["event_id"]: Row(r["event_id"], r["timestamp"], r["type"], r["trigger_type"], r["importance"],
                               r["parent_event_id"], json.loads(r["truth"]), parts.get(r["event_id"], []))
            for r in conn.execute("SELECT * FROM events ORDER BY event_id")}


def _claim_object(e: Row) -> str | None:
    t = e.truth
    for key in ("asserted_claim", "claim"):
        if isinstance(t.get(key), dict):
            return t[key].get("object")
    return None


def _incident(e: Row, rows: dict[int, Row]) -> int | None:
    if e.type == "parrot_speaks":
        said = rows.get(int(e.truth["repeats"]))
        return _incident(said, rows) if said else None
    inc = e.truth.get("incident")
    return int(inc) if inc is not None else None


def thread_keys(e: Row, rows: dict[int, Row], items: set[str]) -> set[str]:
    keys = set()
    obj = e.truth.get("object") or (e.truth.get(DUEL_ITEM) if e.type == "duel" else None)
    if (e.type in ITEM_EVENTS or (e.type == "duel" and obj)) and obj in items:
        keys.add(f"item:{obj}")
    cobj = _claim_object(e)
    if cobj in items and e.type in RUMOR_EVENTS + ("accuse",):
        keys.add(f"item:{cobj}")
    elif e.type in RUMOR_EVENTS and _incident(e, rows) is not None:
        keys.add(f"rumor:{_incident(e, rows)}")
    if e.type in ("lend", "repay"):
        keys.add("debt:" + ":".join(sorted(e.principals[:2])))
    clash = (e.type == "talk" and e.truth.get("tone") in ("cold", "hostile")) or (
        e.type == "accuse" and e.truth.get("outcome") == "false") or e.type == "duel"
    if clash and len(e.principals) >= 2:
        keys.add("feud:" + ":".join(sorted(e.principals[:2])))
    return keys


def _question(kind: str, key: str, names: dict[str, str], rows: dict[int, Row], events: list[Row]) -> str:
    parts = key.split(":")
    if kind == "item":
        return f"{names.get(parts[1], parts[1])}最後會落到誰手上？"
    if kind == "debt":
        return f"{names.get(parts[1], parts[1])}和{names.get(parts[2], parts[2])}之間的錢，還得清嗎？"
    if kind == "feud":
        return f"{names.get(parts[1], parts[1])}和{names.get(parts[2], parts[2])}的衝突會怎麼收場？"
    said = next((e.truth.get("text") for e in events if e.type == "tell" and e.truth.get("text")), None)
    root = rows.get(int(parts[1]))
    text = said or (root.truth.get("text") if root else None)
    return f"「{text}」——大家最後會相信哪個版本？" if text else "這個傳言會傳到哪裡？"


def _false_beliefs(conn: sqlite3.Connection, kind: str, key: str, events: list[Row]) -> int:
    """Beliefs held about this thread that world truth does not support."""
    if kind == "item":
        obj = key.split(":", 1)[1]
        rows = conn.execute(
            "SELECT DISTINCT m.observer_id, c.subject, c.act, c.object, c.polarity FROM memories m JOIN claims c USING (claim_id) "
            "WHERE c.object = ? AND c.act IN ('take', 'steal')", (obj,)).fetchall()
    elif kind == "rumor":
        asserted = [e.truth["asserted_claim"] for e in events if isinstance(e.truth.get("asserted_claim"), dict)]
        if not asserted:
            return 0
        rows = []
        for a in asserted:
            rows += conn.execute(
                "SELECT DISTINCT m.observer_id, c.subject, c.act, c.object, c.polarity FROM memories m JOIN claims c USING (claim_id) "
                "WHERE c.subject = ? AND c.act = ? AND c.object = ? AND c.polarity = ?",
                (a["subject"], a["act"], a["object"], a["polarity"])).fetchall()
    else:
        return 0
    seen, n = set(), 0
    for r in rows:
        key2 = (r["observer_id"], r["subject"], r["act"], r["object"], r["polarity"])
        if key2 in seen:
            continue
        seen.add(key2)
        if evaluate(conn, Claim(r["subject"], r["act"], r["object"], r["polarity"])) != TRUE:
            n += 1
    return n


def _tension_and_status(conn: sqlite3.Connection, kind: str, key: str, events: list[Row], today: int,
                        asymmetry: int) -> tuple[float, str]:
    last = events[-1]
    if kind == "item":
        obj = conn.execute("SELECT * FROM objects WHERE id = ?", (key.split(":", 1)[1],)).fetchone()
        missing = conn.execute("SELECT value FROM world_vars WHERE key = ?", (f"missing.{obj['id']}",)).fetchone()
        home = obj["rightful_owner_id"] is not None and obj["owner_person_id"] == obj["rightful_owner_id"]
        settled = home or obj["status"] == "spent"
        tension = (0.1 + 0.1 * min(asymmetry, 3)) if settled else 0.6 + 0.4 * bool(missing and missing[0])
    elif kind == "debt":
        a, b = key.split(":")[1:]
        owed = conn.execute("SELECT COALESCE(SUM(debt_cents), 0) FROM relationships WHERE (actor_id = ? AND target_id = ?) "
                            "OR (actor_id = ? AND target_id = ?)", (a, b, b, a)).fetchone()[0]
        tension = 0.5 if owed else 0.05
    elif kind == "rumor":
        lied = any(e.type == "tell" and e.truth.get("mode") in ("lie", "distortion") and e.truth.get("verdict") in ("FALSE", "PARTIAL")
                   for e in events)
        exposed = any(e.truth.get("outcome") in EXPOSED for e in events)
        tension = 1.0 if lied and not exposed else 0.5 if asymmetry else 0.2
    else:
        tension = min(1.0, len(events) / 5)
    if all(e.type == "seed" for e in events):
        return tension, "seeded"
    if tension <= 0.2:
        return tension, "resolved"
    if last.day < today - DORMANT_AFTER_DAYS:
        return tension, "dormant"
    if last.truth.get("outcome") in EXPOSED or last.type == "cash_prize":
        return tension, "climax"
    recent = [e for e in events if e.day >= today - 1]
    if len(recent) >= 2 and recent[-1].importance >= recent[0].importance:
        return tension, "escalating"
    if len(events) < 3:
        return tension, "forming"
    return tension, "active"


def _stakes(conn: sqlite3.Connection, kind: str, key: str, events: list[Row]) -> float:
    if kind == "item":
        v = conn.execute("SELECT value_cents FROM objects WHERE id = ?", (key.split(":", 1)[1],)).fetchone()[0]
        return round(max(0.3, min(1.0, v / 20000)), 3)
    if kind == "debt":
        amount = sum(e.truth.get("amount_cents", 0) for e in events if e.type == "lend")
        return round(min(1.0, 0.3 + amount / 9000), 3)
    if kind == "rumor":
        return 0.7 if any((e.truth.get("asserted_claim") or {}).get("act") in ("steal", "take", "deceive") for e in events) else 0.4
    return 0.4


def derive_threads(conn: sqlite3.Connection, today: int | None = None) -> list[StoryThread]:
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'world_vars'").fetchone() is None:
        return []  # threads need a World C world (rightful owners, world variables)
    rows = _rows(conn)
    if not rows:
        return []
    today = max(r.day for r in rows.values()) if today is None else today
    items = {r[0] for r in conn.execute("SELECT id FROM objects")}
    members: dict[str, list[Row]] = {}
    for e in rows.values():
        for k in thread_keys(e, rows, items):
            members.setdefault(k, []).append(e)
    names = labels(conn)
    revision = max(rows)
    event_threads: dict[int, set[str]] = {}
    kept = {}
    for key, evs in members.items():
        kind = key.split(":", 1)[0]
        if kind == "feud" and len(evs) < MIN_FEUD_EVENTS:
            continue
        if len(evs) < 2:
            continue
        kept[key] = evs
        for e in evs:
            event_threads.setdefault(e.id, set()).add(key)
    # causal crossing: an event in one thread whose cause sits in another, directly or through a goal:
    # thread A's event changes someone's goal, and an act that goal drove belongs to thread B
    goal_cause = {e.truth["goal"]: e.truth.get("cause_event") for e in rows.values()
                  if e.type == "goal_change" and e.truth.get("to") in ("formed", "transformed")}
    crosses: dict[str, set[str]] = {k: set() for k in kept}
    for key, evs in kept.items():
        for e in evs:
            others = set(event_threads.get(e.id, ())) - {key}
            deps = [e.parent] + [int(d) for d in e.truth.get("depends_on", [])]
            reason = e.truth.get("reason") or ""
            if reason.startswith("goal:"):
                deps.append(goal_cause.get(reason[5:]))
            for dep in deps:
                others |= event_threads.get(dep, set()) - {key} if dep is not None else set()
            crosses[key] |= others
            for o in others:
                crosses.setdefault(o, set()).add(key)
    out = []
    for key in sorted(kept):
        evs = kept[key]
        kind = key.split(":", 1)[0]
        asym = _false_beliefs(conn, kind, key, evs)
        tension, status = _tension_and_status(conn, kind, key, evs, today, asym)
        people = []
        for e in evs:
            for p in e.principals:
                if p not in people:
                    people.append(p)
        recent = [e for e in evs if e.day >= today - 1]
        out.append(StoryThread(
            thread_id=key, kind=kind, central_question=_question(kind, key, names, rows, evs), participants=people,
            event_ids=[e.id for e in evs], decision_event_ids=[e.id for e in evs if e.trigger == DECISION],
            first_day=evs[0].day, last_day=evs[-1].day, status=status, stakes=_stakes(conn, kind, key, evs),
            momentum=round(min(1.0, sum(e.importance for e in recent) / 2), 3), tension=round(tension, 3),
            information_asymmetry=asym, cross_threads=sorted(crosses.get(key, set())),
            seed_origins=sorted({e.truth["external_event_id"] for e in evs if e.type == "seed"}),
            world_revision=revision))
    return out
