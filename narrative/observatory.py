"""The Observatory: read models over the world's history, for watching how stories grow and how people change.

    thread_views(conn)          every StoryThread as a story: status, origin, why it exists, a timeline of events and
                                their consequences (trust, feeling, goals, holdings) and what each person came to
                                believe, cross-thread links
    character_life(conn, pid)   a person's life: identity, now, psychology (traits, values, self-model, scars) and its
                                history, relationships and their history, knowledge (believed, and whether it is true),
                                life milestones, and a biography compiled from them

Nothing here is truth. The canonical record is world.db (events, deltas, state); these are projections of it, and
every milestone, paragraph and timeline node carries the event_id it comes from. Nothing here writes.
"""
from __future__ import annotations

import json
import sqlite3

from narrative.threads import derive_threads
from world.psyche import ADAPTIVE, SCAR, SELF_MODEL, VALUES, appraise

DAY = 1440
DORMANT = 3  # days without an event before a thread counts as having slept
TRAIT_NAMES = {"vigilance": "警戒", "cynicism": "憤世", "aggression": "攻擊性", "withdrawal": "退縮", "trust_default": "預設信任"}
VALUE_NAMES = {"security": "安全", "truth": "真相", "belonging": "歸屬", "revenge": "復仇"}
EXPERIENCE_NAMES = {"betrayal": "背叛", "wronged": "被冤枉", "shame": "羞恥", "kindness": "被善待", "hostility": "敵意",
                    "failure": "挫敗", "success": "成功"}
MILESTONE_BASE = {"betrayal": 0.8, "wronged": 0.8, "shame": 0.7, "kindness": 0.5, "hostility": 0.4, "failure": 0.4,
                  "success": 0.6, "loss": 0.5, "discovery": 0.6, "turning_point": 0.7, "identity_shift": 0.9,
                  "value_shift": 0.7, "goal_formed": 0.5, "goal_transformed": 0.7, "goal_abandoned": 0.7,
                  "goal_completed": 0.6, "first_time": 0.45}
KIND_NAMES = {"betrayal": "背叛", "wronged": "被冤枉", "shame": "羞愧", "kindness": "被善待", "hostility": "敵意",
              "failure": "挫敗", "success": "勝利", "loss": "失去", "discovery": "發現", "turning_point": "轉折",
              "identity_shift": "自我認知改變", "value_shift": "價值轉變", "goal_formed": "立下目標",
              "goal_transformed": "目標轉變", "goal_abandoned": "放棄目標", "goal_completed": "完成目標",
              "first_time": "第一次"}
FIRSTS = ("take", "find", "accuse", "confront", "tell", "lend", "give", "duel", "steal")


def _names(conn) -> dict:
    out = {r[0]: r[1] for r in conn.execute("SELECT id, name FROM people")}
    out.update({r[0]: r[1] for r in conn.execute("SELECT id, name FROM objects")})
    out.update({r[0]: r[1] for r in conn.execute("SELECT id, name FROM locations")})
    return out


def _caption(etype: str, truth: dict, place: str, names: dict) -> str:
    from runtime.godview import caption
    return caption(etype, truth, place, names)


def _event(conn, eid: int, names: dict) -> dict:
    ts, etype, place, truth, imp, parent = conn.execute(
        "SELECT timestamp, type, location_id, truth, importance, parent_event_id FROM events WHERE event_id = ?",
        (eid,)).fetchone()
    d = json.loads(truth)
    who = [r[0] for r in conn.execute("SELECT person_id FROM event_participants WHERE event_id = ? ORDER BY person_id",
                                      (eid,))]
    cause = parent or d.get("incident") or d.get("loss_event") or d.get("about_event")
    trust, feelings, goals, hands = [], [], [], []
    for ent_type, ent, fld, old, new in conn.execute(
            "SELECT entity_type, entity_id, field, old_value, new_value FROM event_deltas WHERE event_id = ? "
            "ORDER BY delta_id", (eid,)):
        if ent_type == "relationship" and fld == "trust" and old is not None and new is not None:
            a, b = ent.split(":", 1)
            trust.append({"from": a, "to": b, "before": round(float(old), 2), "after": round(float(new), 2)})
        elif ent_type == "person" and fld == "emotion":
            feelings.append({"who": ent, "before": old, "after": new})
        elif ent_type == "goal" and fld == "status":
            goals.append({"who": ent.split(":")[0], "slot": ent.split(":")[1], "before": old, "after": new})
        elif ent_type == "object" and fld == "owner_person_id":
            hands.append({"thing": ent, "from": old or "", "to": new or ""})
    knowledge = [{"who": o, "believes": b, "confidence": round(c, 2), "source": s, "source_id": sid or ""}
                 for o, b, c, s, sid in conn.execute(
                     "SELECT observer_id, belief, confidence, source_type, source_id FROM memories WHERE event_id = ? "
                     "ORDER BY memory_id", (eid,))]
    return {"id": eid, "t": ts * 60.0, "day": ts // DAY, "type": etype, "place": place or "",
            "caption": _caption(etype, d, place or "", names), "who": who, "importance": imp,
            "cause": cause, "why": d.get("reason") or "", "trust": trust, "feelings": feelings, "goals": goals,
            "hands": hands, "knowledge": knowledge}


def thread_views(conn: sqlite3.Connection, names: dict | None = None) -> list[dict]:
    names = names or _names(conn)
    out = []
    for t in derive_threads(conn):
        events = [_event(conn, e, names) for e in t.event_ids]
        days = sorted({e["day"] for e in events})
        revived = any(b - a >= DORMANT for a, b in zip(days, days[1:]))
        status = "revived" if revived and t.status in ("active", "escalating", "climax", "forming") else t.status
        counts: dict[str, int] = {}
        for e in events:
            for w in e["who"]:
                counts[w] = counts.get(w, 0) + 1
        primary = [p for p, _ in sorted(counts.items(), key=lambda x: (-x[1], x[0]))][:2]
        drivers: dict[str, int] = {}
        for e in events:
            if any(x["after"] < x["before"] for x in e["trust"]):
                drivers["關係惡化"] = drivers.get("關係惡化", 0) + 1
            if any(k["confidence"] < 1.0 for k in e["knowledge"]):
                drivers["不確定的信念"] = drivers.get("不確定的信念", 0) + 1
            if e["type"] in ("accuse", "confront"):
                drivers["指控與質問"] = drivers.get("指控與質問", 0) + 1
            if e["hands"]:
                drivers["東西換手"] = drivers.get("東西換手", 0) + 1
            if e["type"] == "tell":
                drivers["傳話"] = drivers.get("傳話", 0) + 1
        ranked = [k for k, _ in sorted(drivers.items(), key=lambda x: -x[1])]
        pressure = []
        for p in primary:
            for slot, kind, target, obj, status_ in conn.execute(
                    "SELECT slot, kind, target, object, status FROM goals WHERE person_id = ? AND status IN "
                    "('formed', 'active', 'blocked')", (p,)):
                if target in primary or obj in [x["thing"] for e in events for x in e["hands"]]:
                    from world.goals import TEXT
                    what = TEXT.get(kind, kind).format(t=names.get(target, target), o=names.get(obj, obj))
                    pressure.append(f"{names.get(p, p)}想{what}")
        out.append({
            "id": t.thread_id, "kind": t.kind, "question": t.central_question, "status": status,
            "first_day": t.first_day, "last_day": t.last_day, "participants": t.participants, "primary": primary,
            "tension": round(t.tension, 2), "stakes": round(t.stakes, 2), "asymmetry": t.information_asymmetry,
            "events": events, "cross": t.cross_threads,
            "why": {"origin": events[0]["id"] if events else None, "drivers": ranked[:3],
                    "affected": sorted(set(counts) - set(primary)), "last": events[-1]["id"] if events else None,
                    "pressure": pressure[:4]},
        })
    return sorted(out, key=lambda x: (-x["tension"], -(x["last_day"] - x["first_day"])))


def _series(conn, entity_type: str, entity_id: str, fld: str, start) -> list:
    rows = [[0, start]]
    for eid, ts, new in conn.execute(
            "SELECT d.event_id, e.timestamp, d.new_value FROM event_deltas d JOIN events e USING (event_id) WHERE "
            "d.entity_type = ? AND d.entity_id = ? AND d.field = ? ORDER BY d.delta_id", (entity_type, entity_id, fld)):
        rows.append([ts * 60.0, round(float(new), 3) if new is not None else None, eid])
    return rows


def character_life(conn: sqlite3.Connection, pid: str, names: dict | None = None) -> dict:
    names = names or _names(conn)
    p = conn.execute("SELECT * FROM people WHERE id = ?", (pid,)).fetchone()
    persona = conn.execute("SELECT traits FROM personas WHERE person_id = ?", (pid,)).fetchone()
    core = json.loads(persona[0]) if persona else {}
    from world.content import home_of
    identity = {"name": p["name"], "species": core.get("species", "human"), "life_goal": p["goal"],
                "home": names.get(home_of(conn, pid), home_of(conn, pid)),
                "temperament": {k: v for k, v in core.items() if isinstance(v, (int, float))},
                "backstory": [_event(conn, e, names) for e, in conn.execute(
                    "SELECT e.event_id FROM events e JOIN event_participants p USING (event_id) WHERE p.person_id = ? "
                    "AND e.type = 'backstory' ORDER BY e.event_id", (pid,))]}
    var = lambda k, d: (conn.execute("SELECT value FROM world_vars WHERE key = ?", (k,)).fetchone() or [d])[0]  # noqa: E731
    traits, scars = {}, []
    for k, rest in ADAPTIVE.items():
        cur, worst = var(f"psy.{pid}.{k}", rest), var(f"psy.{pid}.worst.{k}", rest)
        traits[k] = {"name": TRAIT_NAMES[k], "now": round(cur, 3), "rest": rest,
                     "history": _series(conn, "var", f"psy.{pid}.{k}", "value", rest)}
        harm = (worst - rest) if k != "trust_default" else (rest - worst)
        if harm > 0.05:  # a trait pushed well past its resting value: the scar is how far healing can get back
            hist = traits[k]["history"]
            origin = next((h[2] for h in hist[1:] if len(h) > 2 and abs(h[1] - rest) > 0.05), None)
            scars.append({"domain": TRAIT_NAMES[k], "trait": k, "intensity": round(harm, 3),
                          "floor": round(rest + SCAR * (worst - rest), 3), "origin_event": origin})
    values = {k: {"name": VALUE_NAMES[k], "now": round(var(f"psy.{pid}.value.{k}", v), 3), "start": v,
                  "history": _series(conn, "var", f"psy.{pid}.value.{k}", "value", v)} for k, v in VALUES.items()}
    self_model = [{"key": k, "text": text, "held": var(f"psy.{pid}.self.{k}", 0.0) >= 0.5}
                  for k, (text, _src, _th) in SELF_MODEL.items()]
    rels = []
    for other, trust, aff, fear in conn.execute(
            "SELECT target_id, trust, affection, fear FROM relationships WHERE actor_id = ? ORDER BY target_id", (pid,)):
        rels.append({"to": other, "name": names.get(other, other), "trust": round(trust, 2), "affection": round(aff, 2),
                     "fear": round(fear, 2), "history": _series(conn, "relationship", f"{pid}:{other}", "trust", None)})
    rels.sort(key=lambda r: -abs(r["trust"]))
    from world.claims import evaluate
    from contracts.claim import Claim
    knowledge = []
    for mid, eid, belief, conf, src, sid, subj, act, obj, pol in conn.execute(
            "SELECT m.memory_id, m.event_id, m.belief, m.confidence, m.source_type, m.source_id, c.subject, c.act, "
            "c.object, c.polarity FROM memories m LEFT JOIN claims c ON c.claim_id = m.claim_id WHERE m.observer_id = ? "
            "ORDER BY m.memory_id DESC LIMIT 40", (pid,)):
        truth = ""
        if subj is not None:
            try:
                truth = evaluate(conn, Claim(subj, act, obj, pol))
            except Exception:  # an act the evaluator does not know
                truth = ""
        knowledge.append({"memory": mid, "event": eid, "believes": belief, "confidence": round(conf, 2),
                          "source": src, "source_id": names.get(sid or "", sid or ""), "truth": truth,
                          "subject": subj or "", "object": obj or ""})
    return {"id": pid, "identity": identity, "traits": traits, "values": values, "self_model": self_model,
            "scars": scars, "relationships": rels[:8], "knowledge": knowledge,
            "milestones": milestones(conn, pid, names)}


def milestones(conn: sqlite3.Connection, pid: str, names: dict) -> list[dict]:
    """The events that mattered to this person, and how: from the psyche's own appraisal (what the day meant to
    them), reflections (a self-model formed, a value shifted), trust reversals, goals, losses and discoveries, and
    first times. Significance = the kind's weight + the event's importance; below 0.6 an event stays out of the life."""
    last = conn.execute("SELECT MAX(timestamp) FROM events").fetchone()[0] or 0
    found: dict[int, dict] = {}

    def add(eid: int, kind: str, note: str = "") -> None:
        row = conn.execute("SELECT importance FROM events WHERE event_id = ?", (eid,)).fetchone()
        sig = round(MILESTONE_BASE.get(kind, 0.3) + (row[0] if row else 0.0) * 0.5, 3)
        cur = found.get(eid)
        if cur is None or sig > cur["significance"]:
            found[eid] = {"event": eid, "kind": kind, "label": KIND_NAMES.get(kind, kind), "significance": sig,
                          "note": note}

    for day in range(0, last // DAY + 1):
        exp, _cited = appraise(conn, pid, day)
        rows = conn.execute(
            "SELECT e.event_id, e.type, e.truth FROM events e JOIN event_participants p ON p.event_id = e.event_id "
            "WHERE p.person_id = ? AND e.timestamp >= ? AND e.timestamp < ? ORDER BY e.event_id",
            (pid, day * DAY, (day + 1) * DAY)).fetchall()
        for eid, etype, truth in rows:
            t = json.loads(truth)
            mine = t.get("actor") == pid
            target = t.get("target") == pid or t.get("victim") == pid
            outcome = t.get("outcome")
            if etype == "confront" and mine and outcome and outcome.endswith("_exposed"):
                add(eid, "betrayal", "發現自己被騙了")
            elif etype == "accuse" and target and outcome == "false":
                add(eid, "wronged", f"被{names.get(t.get('actor'), '')}冤枉")
            elif etype == "accuse" and target and outcome == "caught":
                add(eid, "shame", "被當場揭穿")
            elif etype in ("lend", "give") and target:
                add(eid, "kindness", f"{names.get(t.get('actor'), '')}幫了他")
            elif etype == "talk" and target and t.get("tone") == "hostile":
                add(eid, "hostility", f"{names.get(t.get('actor'), '')}對他充滿敵意")
            elif etype in ("misplace",) and mine or etype in ("take", "steal") and target:
                add(eid, "loss", f"失去了{names.get(t.get('object'), '')}")
            elif etype == "find" and mine:
                add(eid, "discovery", f"找回了{names.get(t.get('object'), '')}")
            elif etype == "goal_change" and mine and t.get("to") in ("formed", "transformed", "abandoned", "completed"):
                add(eid, f"goal_{t['to']}", t.get("text", ""))
            elif etype == "reflection" and mine and t.get("self_model"):
                add(eid, "identity_shift", "；".join(SELF_MODEL[k][0] for k in t["self_model"] if k in SELF_MODEL))
            elif etype == "reflection" and mine and any(k.startswith("value.") for k in t.get("shifted", {})):
                add(eid, "value_shift", "、".join(VALUE_NAMES.get(k.split(".", 1)[1], k) for k in t["shifted"]
                                                  if k.startswith("value.")))
    firsts: set = set()
    for eid, etype in conn.execute(
            "SELECT e.event_id, e.type FROM events e WHERE json_extract(e.truth, '$.actor') = ? ORDER BY e.event_id",
            (pid,)):
        if etype in FIRSTS and etype not in firsts:
            firsts.add(etype)
            add(eid, "first_time", "")
    for eid, ent, old, new in conn.execute(
            "SELECT d.event_id, d.entity_id, d.old_value, d.new_value FROM event_deltas d WHERE d.entity_type = "
            "'relationship' AND d.field = 'trust' AND d.entity_id LIKE ? ORDER BY d.delta_id", (f"{pid}:%",)):
        if old is not None and new is not None and (float(old) > 0) != (float(new) > 0) and abs(float(old) - float(new)) > 0.1:
            add(eid, "turning_point", f"對{names.get(ent.split(':', 1)[1], '')}的信任{'轉為負' if float(new) < 0 else '回到正'}")
    out = []
    for m in sorted(found.values(), key=lambda m: m["event"]):
        if m["significance"] < 0.6:
            continue
        e = _event(conn, m["event"], names)
        m.update(t=e["t"], day=e["day"], caption=e["caption"], place=e["place"])
        out.append(m)
    return out


def biography(life: dict, names: dict) -> list[dict]:
    """A life told from its milestones. Each paragraph cites the events it comes from; the text is a projection."""
    ident = life["identity"]
    paras = [{"text": f"{ident['name']}住在{ident['home']}。{('人生目標：' + ident['life_goal'] + '。') if ident['life_goal'] else ''}",
              "events": [e["id"] for e in ident["backstory"]]}]
    for e in ident["backstory"]:
        paras.append({"text": f"更早以前：{e['caption']}。", "events": [e["id"]]})
    by_day: dict[int, list] = {}
    for m in life["milestones"]:
        by_day.setdefault(m["day"], []).append(m)
    for day, ms in sorted(by_day.items()):
        bits = []
        for m in ms[:4]:
            bits.append(f"{m['label']}：{m['caption']}" + (f"（{m['note']}）" if m["note"] and m["note"] not in m["caption"] else ""))
        paras.append({"text": f"第 {day} 天，" + "；".join(bits) + "。", "events": [m["event"] for m in ms[:4]]})
    held = [s["text"] for s in life["self_model"] if s["held"]]
    if held or life["scars"]:
        tail = ("如今他覺得「" + "」「".join(held) + "」。") if held else ""
        if life["scars"]:
            tail += "留下的傷：" + "、".join(f"{s['domain']}（{s['intensity']}）" for s in life["scars"]) + "。"
        paras.append({"text": tail, "events": [s["origin_event"] for s in life["scars"] if s["origin_event"]]})
    return paras


def observatory(conn: sqlite3.Connection) -> dict:
    names = _names(conn)
    people = [r[0] for r in conn.execute("SELECT id FROM people ORDER BY id")]
    lives = {}
    for pid in people:
        life = character_life(conn, pid, names)
        life["biography"] = biography(life, names)
        lives[pid] = life
    return {"threads": thread_views(conn, names), "characters": lives}
