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
