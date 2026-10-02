"""Goals that live: they form, meet setbacks, get blocked, are abandoned or turn into other goals.

A goal is world state (table `goals`, fixed slots per person). It changes only by a `goal_change` event whose parent
is the event that caused it, so every goal can say where it came from:

    Mei notices her ring is gone                    -> forms  recover(ring)
    she accuses Yun, who denies it                  -> recover(ring) transformed into expose(Yun, ring)
    she accuses again and is denied again           -> expose blocked
    two more days and nothing                       -> expose transformed into revenge(Yun)   (if Mei's temper allows)
    five days later                                 -> revenge abandoned: her anger has cooled

The rules here only look at what happened and at the person's traits; they never make anyone act. Goals change
what people want, and what people want leans their own choices (agent/volition.py).
"""
from __future__ import annotations

import json
import sqlite3

from world.events import Change, EventSpec, MemorySpec

SLOTS = 6
OPEN = ("formed", "active", "blocked")
CLOSED = ("abandoned", "revised", "completed", "transformed")
TEXT = {
    "recover": "找回{o}", "expose": "讓{t}承認拿了{o}", "revenge": "報復{t}", "clear_name": "向{t}證明自己的清白",
    "make_amends": "彌補{t}", "repay": "還清欠{t}的錢", "save": "存到{o}元", "reconcile": "和{t}和好",
    "befriend": "和{t}成為朋友", "keep_secret": "守住秘密", "outshine": "壓過{t}",
}  # domain packs add their own kinds (world/domains): see text_of
# initial goals from the personas: person -> (kind, target, object, priority)
INITIAL = {
    "ming": ("outshine", "kai", "", 0.5), "mei": ("save", "", "500", 0.6), "jun": ("repay", "tao", "", 0.7),
    "lan": ("reconcile", "ning", "", 0.6), "hao": ("befriend", "yun", "", 0.5),
    "yun": ("keep_secret", "", "yun:take:ring_mei", 0.8), "kai": ("outshine", "ming", "", 0.5),
    "tao": ("save", "", "400", 0.5), "rui": ("reconcile", "lan", "", 0.5),
}
BLOCK_AFTER_SETBACKS = 2
BLOCKED_DAYS = 2
REVENGE_COOLS_DAYS = 5
SOFT_GOAL_DAYS = 4


def initial_rows(people: list[str], initial: dict | None = None) -> list[tuple]:
    initial = INITIAL if initial is None else initial
    rows = []
    for pid in people:
        for slot in range(SLOTS):
            if slot == 0 and pid in initial:
                kind, target, obj, prio = initial[pid]
                rows.append((pid, slot, kind, target, obj, "active", prio, 0, 0, ""))
            else:
                rows.append((pid, slot, "", "", "", "empty", 0.0, 0, 0, ""))
    return rows


def describe(conn: sqlite3.Connection, g: sqlite3.Row | dict) -> str:
    names = {r[0]: r[1] for r in conn.execute("SELECT id, name FROM people UNION ALL SELECT id, name FROM objects "
                                               "UNION ALL SELECT id, name FROM locations")}
    return text_of(g["kind"]).format(t=names.get(g["target"], g["target"]), o=names.get(g["object"], g["object"]))


def text_of(kind: str) -> str:
    from world.domains import goal_text
    return TEXT.get(kind) or goal_text().get(kind, kind)


def has_goals(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'goals'").fetchone() is not None


def goals_of(conn: sqlite3.Connection, pid: str, statuses: tuple[str, ...] = OPEN) -> list[sqlite3.Row]:
    return conn.execute(f"SELECT * FROM goals WHERE person_id = ? AND status IN ({','.join('?' * len(statuses))}) "
                        "ORDER BY priority DESC, slot", (pid, *statuses)).fetchall()


def find(conn: sqlite3.Connection, pid: str, kind: str, target: str = "", obj: str = "") -> sqlite3.Row | None:
    for g in goals_of(conn, pid):
        if g["kind"] == kind and (not target or g["target"] == target) and (not obj or g["object"] == obj):
            return g
    return None


def _traits(conn: sqlite3.Connection, pid: str) -> dict:
    row = conn.execute("SELECT traits FROM personas WHERE person_id = ?", (pid,)).fetchone()
    return json.loads(row[0]) if row else {}


class GoalWriter:
    """Builds goal_change events. One event per change, parented to its cause."""

    def __init__(self, conn: sqlite3.Connection, now: int, cause: int | None) -> None:
        self.conn, self.now, self.cause = conn, now, cause
        self.out: list[EventSpec] = []
        self.taken: set[tuple[str, int]] = set()

    def _event(self, g: sqlite3.Row | dict, changes: list[Change], to: str, why: str, fields: dict) -> None:
        pid = g["person_id"]
        new = {**{k: g[k] for k in ("person_id", "slot", "kind", "target", "object")}, **fields}
        text = describe(self.conn, new)
        changes = list(changes)
        top = self._top_text(pid, new, to)
        if top is not None and top != self.conn.execute("SELECT goal FROM people WHERE id = ?", (pid,)).fetchone()[0]:
            changes.append(Change("person", pid, "goal", value=top))
        self.out.append(EventSpec(
            timestamp=self.now, type="goal_change", trigger_type="rule", importance=0.35 if to in ("transformed", "formed") else 0.25,
            parent_event_id=self.cause,
            truth={"actor": pid, "goal": f"{pid}:{g['slot']}", "kind": new["kind"], "target": new["target"],
                   "object": new["object"], "from": g["status"] if "status" in g.keys() else "empty", "to": to,
                   "why": why, "cause_event": self.cause, "parent": fields.get("parent", g["parent"] if "parent" in g.keys() else ""),
                   "text": text},
            participants=[(pid, "actor")] + ([(new["target"], "target")] if new["target"] and new["target"] != pid and
                                              self.conn.execute("SELECT 1 FROM people WHERE id = ?", (new["target"],)).fetchone() else []),
            changes=changes,
            memories=[MemorySpec(pid, f"我的目標：{text}（{ {'formed': '開始', 'active': '進行中', 'blocked': '卡住了', 'abandoned': '放棄了', 'completed': '達成了', 'transformed': '變了'}.get(to, to)}）", 1.0)]))

    def _top_text(self, pid: str, changed: dict, to: str) -> str | None:
        """The person's headline goal after this change: the most important open one."""
        rows = [dict(r) for r in goals_of(self.conn, pid)]
        rows = [r for r in rows if r["slot"] != changed["slot"]]
        if to in OPEN:
            rows.append({**changed, "status": to, "priority": changed.get("priority", 0.5)})
        if not rows:
            return None
        best = max(rows, key=lambda r: (r["priority"], -r["slot"]))
        return describe(self.conn, best)

    def status(self, g: sqlite3.Row, to: str, why: str, day: int) -> None:
        if (g["person_id"], g["slot"]) in self.taken or g["status"] == to:
            return
        self.taken.add((g["person_id"], g["slot"]))
        changes = [Change("goal", f"{g['person_id']}:{g['slot']}", "status", value=to)]
        if day != g["since_day"]:
            changes.append(Change("goal", f"{g['person_id']}:{g['slot']}", "since_day", delta=day - g["since_day"]))
        self._event(g, changes, to, why, {})

    def setback(self, g: sqlite3.Row, why: str, day: int) -> None:
        if (g["person_id"], g["slot"]) in self.taken:
            return
        self.taken.add((g["person_id"], g["slot"]))
        n = g["setbacks"] + 1
        to = "blocked" if n >= BLOCK_AFTER_SETBACKS else g["status"]
        changes = [Change("goal", f"{g['person_id']}:{g['slot']}", "setbacks", delta=1)]
        if to != g["status"]:
            changes.append(Change("goal", f"{g['person_id']}:{g['slot']}", "status", value=to))
            if day != g["since_day"]:
                changes.append(Change("goal", f"{g['person_id']}:{g['slot']}", "since_day", delta=day - g["since_day"]))
        self._event(g, changes, to, why, {})

    def form(self, pid: str, kind: str, target: str, obj: str, priority: float, day: int, why: str,
             parent: sqlite3.Row | None = None) -> None:
        """A new goal in a free slot. If it grows out of an old goal, the old one is marked transformed."""
        if find(self.conn, pid, kind, target, obj) is not None:
            return
        slot = self._free_slot(pid, parent)
        if slot is None:
            return
        g = self.conn.execute("SELECT * FROM goals WHERE person_id = ? AND slot = ?", (pid, slot)).fetchone()
        self.taken.add((pid, slot))
        key = f"{pid}:{slot}"
        parent_id = f"{parent['person_id']}:{parent['slot']}" if parent is not None else ""
        changes = [Change("goal", key, "kind", value=kind), Change("goal", key, "target", value=target),
                   Change("goal", key, "object", value=obj), Change("goal", key, "status", value="active"),
                   Change("goal", key, "parent", value=parent_id)]
        if round(priority - g["priority"], 6):
            changes.append(Change("goal", key, "priority", delta=round(priority - g["priority"], 6)))
        if day != g["since_day"]:
            changes.append(Change("goal", key, "since_day", delta=day - g["since_day"]))
        if g["setbacks"]:
            changes.append(Change("goal", key, "setbacks", delta=-g["setbacks"]))
        if parent is not None and (pid, parent["slot"]) not in self.taken:
            self.taken.add((pid, parent["slot"]))
            pkey = f"{pid}:{parent['slot']}"
            changes.append(Change("goal", pkey, "status", value="transformed"))
        self._event({**dict(g), "kind": kind, "target": target, "object": obj}, changes,
                    "formed" if parent is None else "transformed", why,
                    {"priority": priority, "parent": parent_id})

    def _free_slot(self, pid: str, parent: sqlite3.Row | None) -> int | None:
        rows = self.conn.execute("SELECT slot, status, since_day FROM goals WHERE person_id = ? ORDER BY slot", (pid,)).fetchall()
        empty = [r["slot"] for r in rows if r["status"] == "empty" and (pid, r["slot"]) not in self.taken]
        if empty:
            return empty[0]
        closed = sorted((r for r in rows if r["status"] in CLOSED and (pid, r["slot"]) not in self.taken),
                        key=lambda r: (r["since_day"], r["slot"]))
        return closed[0]["slot"] if closed else None


# -- after an event -------------------------------------------------------------------------------------------------
def after_event(conn: sqlite3.Connection, event_id: int) -> list[EventSpec]:
    if not has_goals(conn):
        return []
    e = conn.execute("SELECT * FROM events WHERE event_id = ?", (event_id,)).fetchone()
    t = json.loads(e["truth"])
    day = e["timestamp"] // 1440
    w = GoalWriter(conn, e["timestamp"], event_id)
    kind, a, b, obj = e["type"], t.get("actor"), t.get("target"), t.get("object")

    if kind == "notice_missing":
        w.form(a, "recover", "", obj, 0.7, day, "發現東西不見了")
    elif kind == "steal" and t.get("owner_noticed"):
        w.form(t["victim"], "recover", t["actor"], obj, 0.8, day, "親眼看到東西被偷")
    elif kind in ("find", "give"):
        owner = a if kind == "find" else b
        for g in goals_of(conn, owner):
            if g["kind"] in ("recover", "expose") and g["object"] == obj:
                w.status(g, "completed", "東西回來了", day)
        if kind == "give":
            g = find(conn, a, "make_amends", b)
            if g is not None:
                w.status(g, "completed", "把東西還了", day)
    elif kind == "accuse":
        outcome, trait_b = t.get("outcome"), _traits(conn, b)
        mine = [g for g in goals_of(conn, a) if g["kind"] in ("recover", "expose") and (not obj or g["object"] == obj)]
        if outcome == "caught":
            for g in mine:
                w.status(g, "completed", "人贓俱獲", day)
            secret = find(conn, b, "keep_secret")
            if secret is not None and secret["object"].split(":")[-1] == (obj or ""):
                w.status(secret, "abandoned", "秘密被揭穿了", day)
            if trait_b.get("honesty", 0.5) >= 0.45:
                w.form(b, "make_amends", a, obj or "", 0.6, day, "被當場抓到，想彌補")
            else:
                w.form(b, "revenge", a, "", 0.6, day, "被當眾揭穿，懷恨在心")
        elif outcome == "denied":
            for g in mine:
                if g["kind"] == "recover":
                    w.form(a, "expose", b, obj or "", 0.75, day, "對方不承認，我要讓他承認", parent=g)
                else:
                    w.setback(g, "又被否認了", day)
        elif outcome == "false":
            for g in mine:
                w.setback(g, "冤枉了人，東西還是沒找到", day)
            from world.psyche import trait
            if trait_b.get("temper", 0.5) + trait(conn, b, "value.revenge") - 0.1 >= 0.55:
                w.form(b, "revenge", a, "", 0.65, day, "被冤枉，嚥不下這口氣")
            else:
                w.form(b, "clear_name", a, "", 0.6, day, "被冤枉，想證明清白")
    elif kind == "confront":
        outcome = t.get("outcome")
        if outcome in ("lie_exposed", "distortion_exposed"):
            if _traits(conn, a).get("temper", 0.5) >= 0.6:
                w.form(a, "revenge", b, "", 0.6, day, "被騙了")
            w.form(b, "clear_name", a, "", 0.5, day, "謊話被拆穿，想挽回")
    elif kind == "lend":
        w.form(b, "repay", a, "", 0.5, day, "借了錢，要還")
    elif kind == "duel":
        winner, loser = t["winner"], t["loser"]
        g = find(conn, winner, "surpass", loser)
        if g is not None:
            w.status(g, "completed", "終於贏了", day)
        g = find(conn, loser, "surpass", winner)
        if g is not None:
            w.setback(g, "又輸了", day)
        elif _traits(conn, loser).get("temper", 0.5) >= 0.7:
            w.form(loser, "revenge", winner, "", 0.6, day, "當眾輸了，嚥不下這口氣")
        else:
            w.form(loser, "surpass", winner, "", 0.6, day, "輸了，要練到打贏他")
        if t.get("returned"):
            for g in goals_of(conn, winner):
                if g["kind"] in ("recover", "expose") and g["object"] == t["returned"]:
                    w.status(g, "completed", "以武論理，東西回來了", day)
    elif kind == "repay":
        left = conn.execute("SELECT debt_cents FROM relationships WHERE actor_id = ? AND target_id = ?", (a, b)).fetchone()[0]
        g = find(conn, a, "repay", b)
        if g is not None and left == 0:
            w.status(g, "completed", "錢還清了", day)
    elif kind in ("tell", "parrot_speaks"):
        claim = t.get("asserted_claim") or t.get("claim") or {}
        subject = claim.get("subject")
        if subject and claim.get("act") in ("steal", "take", "deceive", "conceal"):
            g = find(conn, subject, "keep_secret")
            present = {r[0] for r in conn.execute("SELECT person_id FROM event_participants WHERE event_id = ?", (event_id,))}
            if g is not None and subject in present and g["object"] == f"{subject}:{claim.get('act')}:{claim.get('object')}":
                w.setback(g, "秘密被說出來了", day)
    return w.out


# -- overnight ------------------------------------------------------------------------------------------------------
def overnight(conn: sqlite3.Connection, day: int, now: int) -> list[EventSpec]:
    if not has_goals(conn):
        return []
    w = GoalWriter(conn, now, None)
    from world.recipes import enabled
    earned = enabled(conn, "goals.earned")   # what reaches a goal comes after it was set, and the completion names it
    for g in conn.execute(f"SELECT * FROM goals WHERE status IN ({','.join('?' * len(OPEN))}) ORDER BY person_id, slot", OPEN).fetchall():
        pid, kind, age = g["person_id"], g["kind"], day - g["since_day"]
        traits = _traits(conn, pid)
        if kind == "recover":
            holder = conn.execute("SELECT owner_person_id FROM objects WHERE id = ?", (g["object"],)).fetchone()
            if holder and holder[0] == pid:
                w.status(g, "completed", "東西回來了", day)
                continue
        if kind == "repay" and conn.execute("SELECT debt_cents FROM relationships WHERE actor_id = ? AND target_id = ?",
                                            (pid, g["target"])).fetchone()[0] == 0:
            w.status(g, "completed", "錢還清了", day)
            continue
        if kind in ("reconcile", "befriend", "clear_name", "make_amends") and g["target"]:
            r = conn.execute("SELECT trust, affection FROM relationships WHERE actor_id = ? AND target_id = ?",
                             (g["target"], pid)).fetchone()
            if (kind in ("reconcile", "befriend") and r["affection"] >= 0.6 and age >= 1) or (kind != "reconcile" and kind != "befriend"
                                                                                 and r["trust"] > 0.1 and age >= 1):
                w.status(g, "completed", "對方的態度變了", day)
                continue
            if kind in ("clear_name", "make_amends") and age >= SOFT_GOAL_DAYS:
                w.status(g, "abandoned", "算了", day)
                continue
        verdict = None
        from world.domains import active
        for dom in active(conn):  # a domain's own goal kinds are judged by the domain
            verdict = dom.review_goal(conn, g, day)
            if verdict:
                break
        if verdict:
            w.status(g, verdict[0], verdict[1], day)
            continue
        if kind == "revenge":
            if age >= REVENGE_COOLS_DAYS:
                w.status(g, "abandoned", "氣消了", day)
                continue
            if earned:
                set_at = conn.execute("SELECT MAX(event_id) FROM events WHERE type = 'goal_change' AND json_extract(truth, '$.goal') = ? "
                                      "AND json_extract(truth, '$.to') IN ('formed', 'transformed')",
                                      (f"{pid}:{g['slot']}",)).fetchone()[0] or 0
                hit = conn.execute("SELECT event_id FROM events WHERE event_id > ? AND json_extract(truth, '$.target') = ? "
                                   "AND json_extract(truth, '$.outcome') IN ('caught', 'lie_exposed', 'distortion_exposed') "
                                   "ORDER BY event_id LIMIT 1", (set_at, g["target"])).fetchone()
                if hit:
                    w.cause = hit[0]           # the completion names what did it
                    w.status(g, "completed", "對方出糗了", day)
                    w.cause = None
                    continue
            elif conn.execute("SELECT 1 FROM events WHERE timestamp >= ? AND json_extract(truth, '$.target') = ? "
                            "AND json_extract(truth, '$.outcome') IN ('caught', 'lie_exposed', 'distortion_exposed') LIMIT 1",
                            (g["since_day"] * 1440, g["target"])).fetchone():
                w.status(g, "completed", "對方出糗了", day)
                continue
        if g["status"] == "blocked" and age >= BLOCKED_DAYS:
            if kind == "recover":
                suspect = conn.execute(
                    "SELECT c.subject, MAX(m.confidence) c FROM memories m JOIN claims c USING (claim_id) WHERE m.observer_id = ? "
                    "AND c.object = ? AND c.act IN ('take', 'steal') AND c.polarity = 'affirm' AND c.subject <> ? "
                    "GROUP BY c.subject ORDER BY c DESC, c.subject LIMIT 1", (pid, g["object"], pid)).fetchone()
                if suspect and suspect[1] >= 0.5:
                    w.form(pid, "expose", suspect[0], g["object"], 0.75, day, "我知道是誰拿的", parent=g)
                else:
                    w.status(g, "abandoned", "找不回來了", day)
            elif kind == "expose" and traits.get("temper", 0.5) >= 0.5:
                w.form(pid, "revenge", g["target"], "", 0.7, day, "他怎麼都不承認", parent=g)
            else:
                w.status(g, "abandoned", "放棄了", day)
    return w.out
