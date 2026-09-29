"""The system: a rule layer only the protagonist can see. It sets quests; the world decides whether they are met.

A quest is drawn from the protagonist's real situation (something of theirs is missing, someone owes them money,
someone distrusts them). It never makes anyone do anything: it only leans the protagonist's own motives towards
the goal. After every event the system checks the world. On success it pays in the one currency it has, a true
piece of information the protagonist could not otherwise know, marked as coming from the system. On failure the
quest simply lapses. Nobody else ever hears of it.
"""
from __future__ import annotations

import json
import sqlite3

from contracts.claim import Claim
from world.claims import describe_claim, labels
from world.events import EventSpec, MemorySpec, apply_event
from world.intent import Intent
from world.mechanics.base import Mechanic

QUEST_DAYS = 3
HINT_CONFIDENCE = 0.6  # a hint is a lead, not proof: an accusation on it alone may be denied


class QuestSystem(Mechanic):
    def _open(self, conn: sqlite3.Connection) -> dict | None:
        row = conn.execute(
            "SELECT event_id, truth FROM events WHERE type = 'system_quest' AND json_extract(truth, '$.actor') = ? "
            "AND NOT EXISTS (SELECT 1 FROM events r WHERE r.type IN ('system_reward', 'system_lapse') "
            "  AND json_extract(r.truth, '$.quest_event') = events.event_id) ORDER BY event_id DESC LIMIT 1",
            (self.target,)).fetchone()
        return {**json.loads(row["truth"]), "event_id": row["event_id"]} if row else None

    # -- issuing ------------------------------------------------------------------------------------------------------
    def _draw(self, conn: sqlite3.Connection, not_goal: str | None = None) -> dict | None:
        """The first goal that fits the protagonist's situation, skipping the one that just lapsed."""
        for goal in ("recover", "collect", "trust"):
            if goal != not_goal:
                q = self._draw_goal(conn, goal)
                if q:
                    return q
        return None

    def _draw_goal(self, conn: sqlite3.Connection, goal: str) -> dict | None:
        me = self.target
        names = labels(conn)
        missing = None if goal != "recover" else conn.execute(
            "SELECT o.id FROM objects o JOIN world_vars v ON v.key = 'missing.' || o.id WHERE o.rightful_owner_id = ? "
            "AND v.value = 1 AND COALESCE(o.owner_person_id, '') <> ? ORDER BY o.value_cents DESC, o.id LIMIT 1",
            (me, me)).fetchone()
        if missing:
            return {"goal": "recover", "object": missing[0], "text": f"找回你的{names[missing[0]]}"}
        debtor = None if goal != "collect" else conn.execute(
            "SELECT actor_id FROM relationships WHERE target_id = ? AND debt_cents > 0 "
            "ORDER BY debt_cents DESC, actor_id LIMIT 1", (me,)).fetchone()
        if debtor:
            return {"goal": "collect", "person": debtor[0], "text": f"讓{names[debtor[0]]}把欠你的錢還你"}
        cold = None if goal != "trust" else conn.execute(
            "SELECT actor_id, trust FROM relationships WHERE target_id = ? AND trust < 0 "
            "ORDER BY trust, actor_id LIMIT 1", (me,)).fetchone()
        if cold:
            return {"goal": "trust", "person": cold[0], "text": f"讓{names[cold[0]]}重新信任你"}
        return None

    def on_dawn(self, conn: sqlite3.Connection, day: int) -> None:
        last = conn.execute("SELECT COALESCE(MAX(timestamp), 0) FROM events").fetchone()[0]
        now = max(day * 1440 + 430, last)  # after the dawn seeds, before the first schedule
        quest = self._open(conn)
        if quest and quest["deadline_day"] < day:
            apply_event(conn, EventSpec(
                timestamp=now, type="system_lapse", trigger_type="mechanic", importance=0.2,
                truth={"actor": self.target, "quest_event": quest["event_id"], "goal": quest["goal"]},
                participants=[(self.target, "actor")],
                memories=[MemorySpec(self.target, f"［系統］任務失敗：{quest['text']}", 1.0,
                                     source_type="external_rumor", source_id="system")]))
            lapsed, quest = quest["goal"], None
        else:
            lapsed = None
        if quest is None:
            new = self._draw(conn, not_goal=lapsed)
            if new:
                memories = [MemorySpec(self.target, f"［系統］新任務：{new['text']}（{QUEST_DAYS}天內）", 1.0,
                                       source_type="external_rumor", source_id="system")]
                hint = self._hint(conn, new)
                if hint:
                    new["hint"] = describe_claim(hint, labels(conn))
                    memories.append(MemorySpec(self.target, f"［系統］提示：{new['hint']}", HINT_CONFIDENCE, claim=hint,
                                               source_type="external_rumor", source_id="system"))
                apply_event(conn, EventSpec(
                    timestamp=now + 1, type="system_quest", trigger_type="mechanic", importance=0.4,
                    truth={"actor": self.target, "deadline_day": day + QUEST_DAYS, **new},
                    participants=[(self.target, "actor")], memories=memories))

    def _hint(self, conn: sqlite3.Connection, q: dict) -> Claim | None:
        """The system knows part of the truth: for a missing thing, who holds it (never who is merely suspected)."""
        if q["goal"] != "recover":
            return None
        holder = conn.execute("SELECT owner_person_id FROM objects WHERE id = ?", (q["object"],)).fetchone()[0]
        return Claim(holder, "take", q["object"]) if holder and holder != self.target else None

    # -- checking and paying ------------------------------------------------------------------------------------------
    def _met(self, conn: sqlite3.Connection, q: dict) -> bool:
        me = self.target
        if q["goal"] == "recover":
            return conn.execute("SELECT owner_person_id FROM objects WHERE id = ?", (q["object"],)).fetchone()[0] == me
        if q["goal"] == "collect":
            return conn.execute("SELECT debt_cents FROM relationships WHERE actor_id = ? AND target_id = ?",
                                (q["person"], me)).fetchone()[0] == 0
        return conn.execute("SELECT trust FROM relationships WHERE actor_id = ? AND target_id = ?",
                            (q["person"], me)).fetchone()[0] > 0

    def _reward(self, conn: sqlite3.Connection) -> Claim | None:
        """A true claim about someone else's misdeed that the protagonist does not yet hold."""
        rows = conn.execute(
            "SELECT c.subject, c.act, c.object, c.polarity FROM event_claims ec JOIN claims c USING (claim_id) "
            "JOIN events e ON e.event_id = ec.event_id WHERE ec.role = 'truth' AND c.act IN ('steal', 'take', 'deceive', 'conceal') "
            "AND c.polarity = 'affirm' AND c.subject <> ? AND c.subject IN (SELECT id FROM people) "
            "AND NOT EXISTS (SELECT 1 FROM memories m WHERE m.observer_id = ? AND m.claim_id = c.claim_id) "
            "ORDER BY e.importance DESC, e.event_id DESC LIMIT 1", (self.target, self.target)).fetchone()
        return Claim(rows["subject"], rows["act"], rows["object"], rows["polarity"]) if rows else None

    def after_event(self, conn: sqlite3.Connection, event_id: int) -> None:
        etype = conn.execute("SELECT type FROM events WHERE event_id = ?", (event_id,)).fetchone()[0]
        if etype.startswith("system_") or etype in ("day_end", "move"):
            return
        q = self._open(conn)
        if q is None or not self._met(conn, q):
            return
        now = conn.execute("SELECT MAX(timestamp) FROM events").fetchone()[0]
        prize = self._reward(conn)
        names = labels(conn)
        memories = [MemorySpec(self.target, f"［系統］任務完成：{q['text']}", 1.0, source_type="external_rumor",
                               source_id="system")]
        if prize:
            memories.append(MemorySpec(self.target, f"［系統］獎勵情報：{describe_claim(prize, names)}", 0.95, claim=prize,
                                       source_type="external_rumor", source_id="system"))
        apply_event(conn, EventSpec(
            timestamp=now, type="system_reward", trigger_type="mechanic", importance=0.5, parent_event_id=event_id,
            truth={"actor": self.target, "quest_event": q["event_id"], "goal": q["goal"],
                   "reward": describe_claim(prize, names) if prize else None},
            participants=[(self.target, "actor")], memories=memories))

    # -- leaning the protagonist's own motives -------------------------------------------------------------------------
    def bias(self, conn, actor, now, scored):
        if actor != self.target:
            return scored
        q = self._open(conn)
        if q is None:
            return scored
        out = []
        for score, it in scored:
            if it is not None:
                if q["goal"] == "recover" and it.action in ("take", "accuse") and (
                        it.target == q.get("object") or it.action == "accuse"):
                    score += 0.8
                elif q["goal"] == "collect" and it.target == q.get("person") and it.action == "talk":
                    it = Intent(it.actor, "talk", it.target, "hostile" if it.tone in ("cold", "hostile") else "cold",
                                reason="system: collect the debt")
                    score += 0.6
                elif q["goal"] == "trust" and it.target == q.get("person") and it.action in ("talk", "lend", "give"):
                    if it.action == "talk":
                        it = Intent(it.actor, "talk", it.target, "warm", reason="system: win them back")
                    score += 0.7
            out.append((score, it))
        return out
