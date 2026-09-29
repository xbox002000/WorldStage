"""Explain an event: what the actor knew, why they did it, what it changed, and what it grew out of.

Everything is read back from the world's own history; nothing here is invented after the fact.
"""
from __future__ import annotations

import json
import sqlite3

from world.claims import labels

DAY = 1440


def _day(ts: int) -> int:
    return ts // DAY + 1


def _clock(ts: int) -> str:
    return f"{ts % DAY // 60:02d}:{ts % DAY % 60:02d}"


def _event(conn: sqlite3.Connection, event_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM events WHERE event_id = ?", (event_id,)).fetchone()
    if row is None:
        raise KeyError(f"no event {event_id}")
    return row


def _summary(row: sqlite3.Row, truth: dict, names: dict[str, str]) -> str:
    who = names.get(truth.get("actor", ""), truth.get("actor", ""))
    other = names.get(truth.get("target") or truth.get("victim") or "", "")
    kind = row["type"]
    if kind in ("tell", "confront"):
        return f"{who}{'告訴' if kind == 'tell' else '質問'}{other}：{truth.get('text', '')}"
    if kind == "talk":
        return f"{who}對{other}說話（{truth.get('tone')}）"
    if kind == "steal":
        return f"{who}偷了{names.get(truth.get('object', ''), '東西')}"
    return f"{who}{kind}" if who else kind


def causes(conn: sqlite3.Connection, event_id: int, limit: int = 60) -> list[dict]:
    """Every earlier event this one depends on (parents and belief provenance), oldest first."""
    names = labels(conn)
    seen: dict[int, dict] = {}
    frontier = [event_id]
    while frontier and len(seen) < limit:
        nxt: list[int] = []
        for eid in frontier:
            row = _event(conn, eid)
            truth = json.loads(row["truth"])
            deps = {int(d) for d in truth.get("depends_on", ())}
            if row["parent_event_id"] is not None:
                deps.add(row["parent_event_id"])
            for d in sorted(deps):
                if d not in seen and d != event_id:
                    r = _event(conn, d)
                    seen[d] = {"event_id": d, "day": _day(r["timestamp"]), "clock": _clock(r["timestamp"]), "type": r["type"],
                               "text": _summary(r, json.loads(r["truth"]), names)}
                    nxt.append(d)
        frontier = nxt
    return sorted(seen.values(), key=lambda c: c["event_id"])


def earliest_cause(conn: sqlite3.Connection, event_id: int) -> dict | None:
    chain = causes(conn, event_id)
    return chain[0] if chain else None


def _knew(conn: sqlite3.Connection, row: sqlite3.Row, truth: dict, names: dict[str, str]) -> list[dict]:
    """The actor's memories, as they stood before this event, that bear on what they did."""
    actor, before = truth.get("actor"), row["event_id"]
    if not actor:
        return []
    wanted: list[sqlite3.Row] = []
    if row["type"] == "confront":
        ids = [truth.get("memory_id"), truth.get("grounds_memory_id")]
        wanted = [conn.execute("SELECT * FROM memories WHERE memory_id = ?", (i,)).fetchone() for i in ids if i]
    elif row["type"] == "tell":
        wanted = conn.execute(
            "SELECT * FROM memories WHERE observer_id = ? AND claim_id = ? AND event_id < ? ORDER BY confidence DESC, memory_id LIMIT 1",
            (actor, truth.get("source_claim"), before)).fetchall()
    else:
        target = truth.get("target") or truth.get("victim")
        wanted = list(reversed(conn.execute(
            "SELECT m.* FROM memories m JOIN claims c USING (claim_id) WHERE m.observer_id = ? AND m.event_id < ? "
            "AND (c.subject = ? OR c.object = ?) ORDER BY m.memory_id DESC LIMIT 3", (actor, before, target, target)).fetchall()))
    out = []
    for m in wanted:
        how = {"direct_observation": "親眼看到", "told_by": f"聽{names.get(m['source_id'], m['source_id'])}說",
               "inference": "自己推測", "external_rumor": "外面的傳聞"}[m["source_type"]]
        origin = _event(conn, m["event_id"])
        out.append({"memory_id": m["memory_id"], "text": m["belief"], "confidence": m["confidence"], "how": how,
                    "learned_in_event": m["event_id"], "day": _day(origin["timestamp"])})
    return out


def explain_event(conn: sqlite3.Connection, event_id: int) -> dict:
    row = _event(conn, event_id)
    truth = json.loads(row["truth"])
    names = labels(conn)
    claims = {}
    for r in conn.execute("SELECT ec.role, c.subject, c.act, c.object, c.polarity FROM event_claims ec JOIN claims c USING (claim_id) "
                          "WHERE ec.event_id = ? ORDER BY ec.role, c.claim_id", (event_id,)):
        from contracts.claim import Claim
        from world.claims import describe_claim
        claims.setdefault(r["role"], []).append(describe_claim(Claim(r["subject"], r["act"], r["object"], r["polarity"]), names))
    return {
        "event_id": event_id, "day": _day(row["timestamp"]), "clock": _clock(row["timestamp"]), "type": row["type"],
        "summary": _summary(row, truth, names), "reason": truth.get("reason") or None,
        "decided_by": truth.get("source") or ("rules / seeded choice" if truth.get("actor") else "rules"),
        "knew": _knew(conn, row, truth, names),
        "claims": claims,
        "changes": [{"entity": d["entity_id"], "field": d["field"], "old": d["old_value"], "new": d["new_value"]}
                    for d in conn.execute("SELECT entity_id, field, old_value, new_value FROM event_deltas WHERE event_id = ? ORDER BY delta_id", (event_id,))],
        "causes": causes(conn, event_id),
        "verdict": {k: truth[k] for k in ("mode", "verdict", "outcome", "listener_confidence") if k in truth},
    }


def format_explanation(x: dict) -> str:
    lines = [f"事件 #{x['event_id']}（第 {x['day']} 天 {x['clock']}）{x['summary']}"]
    if x["reason"]:
        lines.append(f"  理由：{x['reason']}（{x['decided_by']}）")
    if x["verdict"]:
        lines.append("  判定：" + "、".join(f"{k}={v}" for k, v in x["verdict"].items()))
    if x["knew"]:
        lines.append("  當時他知道：")
        lines += [f"    - [{k['how']}] {k['text']}（可信度 {k['confidence']:.2f}，第 {k['day']} 天，事件 #{k['learned_in_event']}）"
                  for k in x["knew"]]
    for role, texts in x["claims"].items():
        lines.append(f"  主張（{role}）：" + "；".join(texts))
    if x["changes"]:
        lines.append("  造成的變化：" + "；".join(f"{c['entity']}.{c['field']} {c['old']}→{c['new']}" for c in x["changes"][:6]))
    if x["causes"]:
        lines.append("  來龍去脈：")
        lines += [f"    #{c['event_id']}（第 {c['day']} 天）{c['text']}" for c in x["causes"]]
    return "\n".join(lines)
