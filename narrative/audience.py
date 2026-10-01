"""The audience's view of the world, read from its history (contracts/audience.py). Read only.

The audience knows what the story has shown it: the training nobody saw, the feeling nobody has said, the couple nobody
knows about. The people in the world know what they have seen and heard (their memories, their estimates of each other).
The distance between the two is dramatic irony, and the distance between what the audience expected and what then happens
is a payoff. Neither may be decided afterwards, so everything here is computed *as of a revision*: the world's history
(event_deltas) is wound back to that moment, and an expectation is only worth something if it was already there before
the event it is compared with (`before_event`).

What the audience knows is taken to be the world's truth on stage (it sees everything the God View shows); what it
expects is the crowd's view (the people's own estimates of each other), which is exactly what lags behind a hidden
growth.
"""
from __future__ import annotations

import sqlite3

from contracts.audience import AudienceClaim, AudienceExpectation, AudienceKnowledge
from world.state import read_entity

GAP = 0.15          # how far the truth must be ahead of the crowd's view to be an irony
CRUSH = 0.45        # attraction at which a feeling is worth watching
UNREQUITED = 0.15   # the other's attraction at or below which a love is not returned


def value_at(conn: sqlite3.Connection, entity_type: str, entity_id: str, field: str, revision: int):
    """The value of one field of one entity right after event `revision` (the world's history wound back)."""
    row = conn.execute("SELECT new_value FROM event_deltas WHERE entity_type = ? AND entity_id = ? AND field = ? AND event_id <= ? "
                       "ORDER BY delta_id DESC LIMIT 1", (entity_type, entity_id, field, revision)).fetchone()
    if row is not None:
        return row[0]
    first = conn.execute("SELECT old_value FROM event_deltas WHERE entity_type = ? AND entity_id = ? AND field = ? "
                         "ORDER BY delta_id LIMIT 1", (entity_type, entity_id, field)).fetchone()
    if first is not None:
        return first[0]  # it has changed since, and this is how it began
    cur = read_entity(conn, entity_type, entity_id)
    return cur[field] if cur is not None else None


def _people(conn: sqlite3.Connection) -> list[str]:
    return [r[0] for r in conn.execute("SELECT person_id FROM character_profiles ORDER BY person_id")]


def _ability(conn: sqlite3.Connection, pid: str, revision: int):
    v = value_at(conn, "var", f"skill.{pid}", "value", revision)
    return None if v is None else float(v)


def crowd_view(conn: sqlite3.Connection, subject: str, revision: int, people: list[str] | None = None) -> float | None:
    """What everyone else (on average) believes of somebody's ability, as of a revision."""
    views = [float(value_at(conn, "relationship", f"{o}:{subject}", "estimate", revision)) for o in (people or _people(conn)) if o != subject]
    return sum(views) / len(views) if views else None


def expectation_of(conn: sqlite3.Connection, subject: str, revision: int, scan_days: bool = True) -> AudienceExpectation | None:
    """The audience's expectation of somebody as of a revision: how the crowd sees them, against what the audience has seen
    them become, and for how long the two have been apart."""
    people = _people(conn)
    knows, expected = _ability(conn, subject, revision), crowd_view(conn, subject, revision, people)
    if knows is None or expected is None:
        return None
    since_rev = since_day = 0
    if knows - expected >= GAP and scan_days:
        day = (conn.execute("SELECT COALESCE(MAX(timestamp), 0) FROM events WHERE event_id <= ?", (revision,)).fetchone()[0]) // 1440
        since_day, since_rev = day, revision
        for d in range(day, -1, -1):
            r = conn.execute("SELECT COALESCE(MAX(event_id), 0) FROM events WHERE timestamp < ? AND event_id <= ?", (d * 1440, revision)).fetchone()[0]
            k, e = _ability(conn, subject, r), crowd_view(conn, subject, r, people)
            if k is None or e is None or k - e < GAP:
                break
            since_day, since_rev = d, r
    return AudienceExpectation(subject, round(expected, 4), round(knows, 4), revision, since_rev, since_day)


def knowledge(conn: sqlite3.Connection, revision: int) -> AudienceKnowledge:
    """What the audience knows that the people in the world do not, as of a revision."""
    people = _people(conn)
    claims: list[AudienceClaim] = []
    expectations: list[AudienceExpectation] = []
    for pid in people:
        exp = expectation_of(conn, pid, revision, scan_days=False)
        if exp is None:
            continue
        expectations.append(exp)
        if exp.knows - exp.expected >= GAP:
            shown = [r[0] for r in conn.execute(
                "SELECT event_id FROM events WHERE event_id <= ? AND type IN ('train', 'breakthrough') AND "
                "json_extract(truth, '$.actor') = ? ORDER BY event_id DESC LIMIT 5", (revision, pid))]
            claims.append(AudienceClaim("hidden_strength", [pid], exp.knows, exp.expected, round(exp.knows - exp.expected, 4), revision, shown[::-1]))
    for i, a in enumerate(people):
        for b in people[i + 1:]:
            ab, ba = (float(value_at(conn, "relationship", f"{x}:{y}", "attraction", revision)) for x, y in ((a, b), (b, a)))
            bonded = value_at(conn, "relationship", f"{a}:{b}", "bond", revision) == "dating"
            if bonded:
                knew = conn.execute(
                    "SELECT COUNT(DISTINCT m.observer_id) FROM memories m JOIN claims c USING (claim_id) WHERE m.event_id <= ? AND "
                    "c.act = 'dating' AND ((c.subject = ? AND c.object = ?) OR (c.subject = ? AND c.object = ?))", (revision, a, b, b, a)).fetchone()[0]
                if knew <= 2:
                    claims.append(AudienceClaim("secret_couple", [a, b], 1.0, 0.0, 1.0, revision))
            elif ab >= CRUSH and ba >= CRUSH and value_at(conn, "relationship", f"{a}:{b}", "bond", revision) in ("", None):
                claims.append(AudienceClaim("unspoken_crush", [a, b], round(min(ab, ba), 4), 0.0, round(min(ab, ba), 4), revision))
    for a in people:
        for b in people:
            if a == b:
                continue
            ab, ba = (float(value_at(conn, "relationship", f"{x}:{y}", "attraction", revision)) for x, y in ((a, b), (b, a)))
            if ab >= 0.5 and ba <= UNREQUITED:
                claims.append(AudienceClaim("unrequited_love", [a, b], round(ab, 4), round(ba, 4), round(ab - ba, 4), revision))
    return AudienceKnowledge(revision, claims, expectations)


def before_event(conn: sqlite3.Connection, event_id: int) -> AudienceKnowledge:
    """What the audience knew and expected just before an event: the only expectation that event may be measured against."""
    return knowledge(conn, event_id - 1)
