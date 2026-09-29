"""Who knows what, per story thread: the measurable form of information asymmetry (read-only).

For a thread's central question the town splits into:
knows       holds the true answer with confidence >= 0.7 (or is the one who did it)
suspects    holds the true answer, unsure
wrong       holds an answer the world does not support (and has not dropped it)
unaware     holds nothing about it, although it concerns them (the owner of a missing thing)
And the audience: `audience_knows` if an event carrying the truth has been shown in an episode.

`gap` combines them into one number the director can read. A thread where the owner is unaware, one person wrongly
suspects another, and the audience saw the truth has dramatic irony; that is found in the world, never added.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from contracts.claim import FALSE, PARTIAL, TRUE, Claim
from contracts.thread import StoryThread
from world.claims import evaluate

KNOW = 0.7
ACQUIRE = ("take", "steal", "find")


@dataclass(frozen=True)
class Knowledge:
    thread_id: str
    question: str
    truth: list[str]  # the true answer(s), as claim triples subject:act:object
    knows: list[str]
    suspects: list[str]
    wrong: list[str]
    unaware: list[str]
    audience_knows: bool
    irony: bool  # the audience knows while someone it concerns does not
    gap: float  # 0..1
    wrong_beliefs: list[str] = field(default_factory=list)  # who believes what (for explaining)


def _dropped(conn: sqlite3.Connection, observer: str, memory_id: int) -> bool:
    from agent.perception import belief_dropped
    return belief_dropped(conn, observer, memory_id)


def _item_truth(conn: sqlite3.Connection, obj: str) -> list[Claim]:
    rows = conn.execute(
        "SELECT DISTINCT c.subject, c.act, c.object, c.polarity FROM event_claims ec JOIN claims c USING (claim_id) "
        f"WHERE ec.role = 'truth' AND c.object = ? AND c.act IN ('take', 'steal') AND c.polarity = 'affirm' "
        "ORDER BY c.subject, c.act", (obj,)).fetchall()
    return [Claim(*tuple(r)) for r in rows]


def _concerned(conn: sqlite3.Connection, t: StoryThread) -> set[str]:
    if t.kind == "item":
        owner = conn.execute("SELECT rightful_owner_id FROM objects WHERE id = ?", (t.thread_id.split(":", 1)[1],)).fetchone()
        return {owner[0]} if owner and owner[0] else set()
    return set(t.participants[:2])


def knowledge_of(conn: sqlite3.Connection, t: StoryThread, shown_events: set[int] | frozenset[int] = frozenset()) -> Knowledge | None:
    if t.kind == "item":
        obj = t.thread_id.split(":", 1)[1]
        truths = _item_truth(conn, obj)
        if not truths:
            return None
        doers = {c.subject for c in truths}
        rows = conn.execute(
            "SELECT m.memory_id, m.observer_id, m.confidence, c.subject, c.act, c.object, c.polarity FROM memories m "
            "JOIN claims c USING (claim_id) WHERE c.object = ? AND c.act IN ('take', 'steal', 'find') ORDER BY m.memory_id",
            (obj,)).fetchall()
        question = f"誰拿了{obj}？"
    elif t.kind == "rumor":
        root = int(t.thread_id.split(":", 1)[1])
        truths = [Claim(*tuple(r)) for r in conn.execute(
            "SELECT c.subject, c.act, c.object, c.polarity FROM event_claims ec JOIN claims c USING (claim_id) "
            "WHERE ec.event_id = ? AND ec.role = 'truth' ORDER BY c.claim_id", (root,))]
        if not truths:
            return None
        doers = {c.subject for c in truths}
        props = {(c.subject, c.object) for c in truths}
        rows = [r for r in conn.execute(
            "SELECT m.memory_id, m.observer_id, m.confidence, c.subject, c.act, c.object, c.polarity FROM memories m "
            "JOIN claims c USING (claim_id) ORDER BY m.memory_id") if (r["subject"], r["object"]) in props]
        question = "真正發生了什麼？"
    else:
        return None

    best: dict[str, tuple[str, float]] = {}  # person -> (verdict, confidence) of their latest live belief
    wrong_text = []
    for r in rows:
        if _dropped(conn, r["observer_id"], r["memory_id"]):
            continue
        claim = Claim(r["subject"], r["act"], r["object"], r["polarity"])
        verdict = evaluate(conn, claim)
        best[r["observer_id"]] = (verdict, r["confidence"])
        if verdict in (FALSE, PARTIAL) or (verdict != TRUE and claim.act in ACQUIRE):
            wrong_text.append(f"{r['observer_id']}:{claim.subject}:{claim.act}:{claim.polarity}")
    knows, suspects, wrong = [], [], []
    for pid, (verdict, conf) in sorted(best.items()):
        if pid in doers or (verdict == TRUE and conf >= KNOW):
            knows.append(pid)
        elif verdict == TRUE:
            suspects.append(pid)
        else:
            wrong.append(pid)
    for d in sorted(doers):
        if d not in knows and conn.execute("SELECT 1 FROM people WHERE id = ?", (d,)).fetchone():
            knows.append(d)
    concerned = _concerned(conn, t)
    unaware = sorted(p for p in concerned if p not in best and p not in doers)
    truth_events = {r[0] for r in conn.execute(
        f"SELECT DISTINCT ec.event_id FROM event_claims ec JOIN claims c USING (claim_id) WHERE ec.role = 'truth' AND "
        f"({' OR '.join(['(c.subject = ? AND c.act = ? AND c.object = ?)'] * len(truths))})",
        [x for c in truths for x in (c.subject, c.act, c.object)])}
    audience = bool(truth_events & set(shown_events))
    in_dark = [p for p in concerned if p in wrong or p in unaware]
    irony = audience and bool(in_dark)
    # hearing a true rumour at low confidence is not a gap; being unsure who took your thing is
    unsure = len(suspects) if t.kind == "item" else 0
    gap = min(1.0, 0.35 * len(wrong) + 0.25 * len(unaware) + 0.1 * unsure) * (1.0 if knows else 0.7)
    return Knowledge(t.thread_id, question, [f"{c.subject}:{c.act}:{c.object}" for c in truths], sorted(set(knows)),
                     suspects, wrong, unaware, audience, irony, round(gap + (0.2 if irony else 0.0), 3) if gap else 0.0,
                     wrong_text[-6:])
