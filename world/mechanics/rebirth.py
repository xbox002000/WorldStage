"""Rebirth: the same world runs a second time, and only one person remembers the first.

world.db is never rolled back. Timeline B is rebuilt deterministically from the same seed, the same feed and the
same decisions up to the fork day; then an `awakening` event gives the protagonist what they knew in timeline A
that has not yet happened in B. From there B runs on its own: the protagonist's knowledge changes what they do, and
what they do changes what happens, so the remembered future may never come.

The prior life is carried in the world as ordinary claims (source `prior_life:<A's snapshot hash>`), so a warning
about the future is judged against B's truth like any other claim.
"""
from __future__ import annotations

import json
import sqlite3

from contracts.claim import Claim
from contracts.mechanic import MechanicSpec, NarrativeMechanicPack
from world.claims import describe_claim, labels
from world.events import EventSpec, MemorySpec, apply_event
from world.intent import Intent
from world.mechanics.base import Mechanic, record_pack
from world.content import home_of
from world.snapshot import snapshot_hash

AWAKEN_SLOT = 400  # before the dawn seeds (420) and the first schedule (480)
MAX_MEMORIES = 12
MIN_IMPORTANCE = 0.55
WRONGS = ("steal", "take", "deceive", "conceal", "accuse", "threaten", "speak_hostile")


def _prior_knowledge(a: sqlite3.Connection, who: str, fork_day: int) -> tuple[list[dict], list[dict]]:
    """From timeline A: the weighty events from the fork day on that `who` knew about, and the valuable things they
    saw others pick up (opportunities)."""
    since = fork_day * 1440
    rows = a.execute(
        "SELECT DISTINCT e.event_id, e.timestamp, e.importance, e.location_id, e.type, e.truth FROM events e "
        "JOIN memories m ON COALESCE(m.about_event_id, m.event_id) = e.event_id AND m.observer_id = ? "
        "WHERE e.timestamp >= ? AND e.importance >= ? AND e.type NOT IN ('seed', 'upkeep', 'day_end') "
        "ORDER BY e.importance DESC, e.event_id LIMIT ?", (who, since, MIN_IMPORTANCE, MAX_MEMORIES)).fetchall()
    known = []
    for r in sorted(rows, key=lambda r: r["event_id"]):
        for c in a.execute("SELECT c.subject, c.act, c.object, c.polarity FROM event_claims ec JOIN claims c USING (claim_id) "
                           "WHERE ec.event_id = ? AND ec.role = 'truth' ORDER BY c.claim_id", (r["event_id"],)):
            known.append({"day": r["timestamp"] // 1440, "location": r["location_id"], "type": r["type"],
                          "claim": [c["subject"], c["act"], c["object"], c["polarity"]]})
    chances = []
    for r in a.execute("SELECT e.timestamp, e.location_id, json_extract(e.truth, '$.object') AS obj, "
                       "json_extract(e.truth, '$.actor') AS actor FROM events e WHERE e.type = 'take' AND e.timestamp >= ? "
                       "ORDER BY e.event_id", (since,)):
        value = a.execute("SELECT MAX(value_cents) FROM objects WHERE id = ?", (r["obj"],)).fetchone()[0] or 0
        won = a.execute("SELECT 1 FROM events WHERE type = 'cash_prize' AND json_extract(truth, '$.object') = ?",
                        (r["obj"],)).fetchone()
        if r["actor"] != who and (value >= 10000 or won):
            chances.append({"day": r["timestamp"] // 1440, "location": r["location_id"], "object": r["obj"]})
    return known, chances


def awaken(b: sqlite3.Connection, a: sqlite3.Connection, who: str, fork_day: int) -> int:
    """Give the protagonist of timeline B their memories of timeline A."""
    parent = snapshot_hash(a)
    known, chances = _prior_knowledge(a, who, fork_day)
    names = labels(b)
    tag = f"prior_life:{parent.split(':')[1][:16]}"
    memories = [MemorySpec(who, "我死過一次。醒來時，回到了第%d天的早上" % (fork_day + 1), 1.0,
                           source_type="external_rumor", source_id=tag)]
    for k in known:
        claim = Claim(*k["claim"])
        memories.append(MemorySpec(who, f"（上一世）第{k['day'] + 1}天：{describe_claim(claim, names)}", 0.9, claim=claim,
                                   source_type="external_rumor", source_id=tag))
    return apply_event(b, EventSpec(
        timestamp=fork_day * 1440 + AWAKEN_SLOT, type="awakening", trigger_type="mechanic", importance=0.9,
        location_id=home_of(b, who),
        truth={"mechanic": "rebirth", "actor": who, "fork_day": fork_day, "parent_timeline": parent,
               "known": known, "opportunities": chances},
        participants=[(who, "actor")], memories=memories))


class Rebirth(Mechanic):
    """In timeline B the protagonist goes after remembered chances and is cold to those who wronged them."""

    def _awakening(self, conn: sqlite3.Connection) -> dict | None:
        row = conn.execute("SELECT truth FROM events WHERE type = 'awakening' AND json_extract(truth, '$.actor') = ? "
                           "ORDER BY event_id DESC LIMIT 1", (self.target,)).fetchone()
        return json.loads(row[0]) if row else None

    def options(self, conn: sqlite3.Connection, actor: str, now: int) -> list[tuple[float, Intent]]:
        if actor != self.target:
            return []
        state = self._awakening(conn)
        if not state:
            return []
        here = conn.execute("SELECT location_id FROM people WHERE id = ?", (actor,)).fetchone()[0]
        out = []
        for ch in state["opportunities"]:
            obj = conn.execute("SELECT status, location_id, owner_person_id FROM objects WHERE id = ?", (ch["object"],)).fetchone()
            if obj is None or obj["status"] != "normal" or obj["owner_person_id"] is not None:
                continue  # not lying around (yet), or someone already has it
            if obj["location_id"] and obj["location_id"] != here and conn.execute(
                    "SELECT 1 FROM location_edges WHERE from_location_id = ? AND to_location_id = ?",
                    (here, obj["location_id"])).fetchone():
                out.append((1.6, Intent(actor, "move", obj["location_id"], reason="rebirth: I know what lies there")))
        return out

    def bias(self, conn, actor, now, scored):
        if actor != self.target:
            return scored
        state = self._awakening(conn)
        if not state:
            return scored
        wrongers = {k["claim"][0] for k in state["known"] if k["claim"][1] in WRONGS and k["claim"][2] == actor}
        chances = {c["object"] for c in state["opportunities"]}
        out = []
        for score, it in scored:
            if it is not None and it.action == "talk" and it.target in wrongers and it.tone in ("warm", "neutral"):
                it = Intent(it.actor, "talk", it.target, "cold", reason="rebirth: I remember what you did")
                score += 0.2
            elif it is not None and it.action == "take" and it.target in chances:
                score += 2.0
            elif it is not None and it.action == "tell" and it.mode == "truth":
                score += 0.2  # someone who knows the future tends to say so
            out.append((score, it))
        return out


def fork(a: sqlite3.Connection, b: sqlite3.Connection, seed: int, feed: str | None, fork_day: int, who: str,
         decider_factory) -> None:
    """Rebuild timeline B up to `fork_day` exactly as A went, then wake the protagonist up."""
    from world.seed import build_world
    from world.db import init_db
    from world.simulation import Simulation
    init_db(b, seed)
    build_world(b, seed)
    d = decider_factory([])
    if fork_day:
        Simulation(b, d, d, set(), feed=feed).run(fork_day)
    pack = NarrativeMechanicPack("rebirth", [MechanicSpec("rebirth", "character", who)])
    record_pack(b, pack, fork_day * 1440 + AWAKEN_SLOT - 1, {"fork_day": fork_day})
    awaken(b, a, who, fork_day)
