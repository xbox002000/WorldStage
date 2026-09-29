from __future__ import annotations

import sqlite3

from contracts.claim import AFFIRM, FALSE, PARTIAL, TRUE, UNKNOWN, Claim


def claim_id(conn: sqlite3.Connection, claim: Claim) -> int:
    """Get or create the row for this proposition. Must run inside a mutation()."""
    conn.execute(
        "INSERT OR IGNORE INTO claims(claim_hash, subject, act, object, polarity) VALUES (?,?,?,?,?)",
        (claim.hash(), claim.subject, claim.act, claim.object, claim.polarity),
    )
    return conn.execute("SELECT claim_id FROM claims WHERE claim_hash = ?", (claim.hash(),)).fetchone()[0]


def load_claim(conn: sqlite3.Connection, cid: int) -> Claim:
    r = conn.execute("SELECT subject, act, object, polarity FROM claims WHERE claim_id = ?", (cid,)).fetchone()
    return Claim(r["subject"], r["act"], r["object"], r["polarity"])


def truth_claims(conn: sqlite3.Connection, about_event_id: int | None = None) -> list[Claim]:
    sql = ("SELECT c.subject, c.act, c.object, c.polarity FROM event_claims ec JOIN claims c USING (claim_id) "
           "WHERE ec.role = 'truth'")
    args: tuple = ()
    if about_event_id is not None:
        sql += " AND ec.event_id = ?"
        args = (about_event_id,)
    return [Claim(*tuple(r)) for r in conn.execute(sql + " ORDER BY ec.event_id, c.claim_id", args)]


def evaluate(conn: sqlite3.Connection, claim: Claim, about_event_id: int | None = None) -> str:
    """Compare a proposition with world truth: TRUE / FALSE / PARTIAL / UNKNOWN.

    With about_event_id only that event's truth is consulted; otherwise all events. Precedence when several
    truths are comparable: an exact match beats a same-family or different-object near match.
    """
    same_polarity = opposite = near = False
    for t in truth_claims(conn, about_event_id):
        if t.proposition == claim.proposition:
            if t.polarity == claim.polarity:
                same_polarity = True
            else:
                opposite = True
        elif t.polarity == AFFIRM and claim.polarity == AFFIRM and t.subject == claim.subject and (
            (t.family == claim.family and t.act != claim.act and t.object == claim.object)
            or (t.act == claim.act and t.object != claim.object)
        ):
            near = True
    if same_polarity:
        return TRUE
    if opposite:
        return FALSE
    return PARTIAL if near else UNKNOWN


# act -> (affirmed phrase, denied phrase); {o} is the object's display name
PHRASE: dict[str, tuple[str, str]] = {
    "steal": ("偷了{o}", "沒有偷{o}"),
    "take": ("拿走了{o}", "沒有拿走{o}"),
    "borrow": ("借走了{o}", "沒有借{o}"),
    "speak_warm": ("親切地對{o}說話", "沒有親切地對{o}說話"),
    "speak_neutral": ("和{o}閒聊", "沒有和{o}閒聊"),
    "speak_cold": ("冷淡地對{o}說話", "沒有冷淡地對{o}說話"),
    "speak_hostile": ("敵意地質問{o}", "沒有敵意地質問{o}"),
    "tell": ("告訴了{o}一些事", "沒有告訴{o}任何事"),
    "deceive": ("欺騙了{o}", "沒有欺騙{o}"),
    "conceal": ("對{o}隱瞞了事情", "沒有對{o}隱瞞事情"),
    "confront": ("當面質問了{o}", "沒有當面質問{o}"),
}


def labels(conn: sqlite3.Connection) -> dict[str, str]:
    """Display names for every person and item id (the two id spaces never overlap)."""
    out = {r["id"]: r["name"] for r in conn.execute("SELECT id, name FROM objects ORDER BY id")}
    out.update({r["id"]: r["name"] for r in conn.execute("SELECT id, name FROM people ORDER BY id")})
    return out


def describe_claim(claim: Claim, names: dict[str, str]) -> str:
    """A claim in plain Traditional Chinese, e.g. 阿明偷了手機 / 阿明沒有偷手機."""
    affirm, deny = PHRASE[claim.act]
    phrase = affirm if claim.polarity == AFFIRM else deny
    return names.get(claim.subject, claim.subject) + phrase.format(o=names.get(claim.object, claim.object))


def claim_dict(claim: Claim) -> dict:
    return {"subject": claim.subject, "act": claim.act, "object": claim.object, "polarity": claim.polarity}
