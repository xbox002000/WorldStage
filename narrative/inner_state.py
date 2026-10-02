"""Inner state: what somebody shows and what is underneath it (a read model, never truth; $0, no model).

A person's emotion is one word in the world (angry, hurt, ashamed...). It was set by one event, and the same event meant something
different to each of them depending on what lay between them and on what they had come to believe about themselves. This reads
that back, as of just before an event:

    {surface: 生氣, underneath: 怕被阿浩丟下, because: {event_id, text}, evidence: [...], confidence}

How it is found, and nothing else:
  1. the event that set the emotion the person has now (`event_deltas`, person.emotion). A night in between (the nightly
     settling of anger or shame into unease, world/simulation.py OVERNIGHT) is followed back to the daytime event that
     put the feeling there; a feeling that came from nothing we can see has no inner state.
  2. what the event was to *this* person (their role in it, its recorded outcome, the tone), and what held between the two
     of them just before it: relationship fields, the self-model they had formed (psyche), the goal that the event itself
     gave rise to (a goal_change that cites it as its cause).
  3. a closed table of readings (`RULES` below). Each says what is underneath, how sure it is, and which records make it so.

Every reading carries its `evidence`: the cause event, each relationship field or self-model it leaned on with the event that last
set it (or None: it was so from the start of the world), and the recorded fields of the event itself. `verify()` re-reads every
one of them from the history and fails on a reading that is not what the records say. Nothing is guessed: with no rule that
holds, there is no inner state and nothing is said. The world's hidden truth is never read (not who really took a thing, not who
really lied): only what the person themselves was in a position to know.

Read only: no write path of the world is imported, no event is made, the world does not change. A reading is a pure function of
the history up to the event, so the same world always reads the same. Characters never act on it.

`inner_state_v0.1`: a draft. The readings are the first set, to be argued with and extended.
"""
from __future__ import annotations

import json
import sqlite3

INNER_VERSION = "inner_state_v0.1"
SAY_AT = 0.5                 # below this confidence a reading is kept for the read model but never put in anybody's mouth
FRESH = 2 * 1440             # minutes: a feeling whose cause is older than two days is not read (nobody is still that angry)
NIGHT = 0.85                 # a reading through a night is a little less sure

EMOTION_ZH = {"angry": "生氣", "hurt": "受傷", "ashamed": "羞愧", "embarrassed": "尷尬", "uneasy": "不安", "scared": "害怕",
              "happy": "開心", "relieved": "鬆了口氣"}
# the lines a reading hangs on (narrative/speech.py always gives these a line), for "has it already shown"
SPEECH_TYPES = ("talk", "duel", "accuse", "confront", "tell", "flirt", "confession", "date", "break_up", "campaign", "recruit", "defect")
ALONE = ("regret", "smash", "break_down", "notice_missing", "train")      # said to no one
ALONE_EVERY = {"train": 3}                           # ...and of these, said once in so many (speech.py SELF_RARE: or the day is all murmuring)
VOICED_ON = SPEECH_TYPES + ALONE


def _num(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


class _Cause:
    """The event that set the feeling, from the point of view of one person, with the history wound back to just before it."""

    def __init__(self, conn: sqlite3.Connection, pid: str, eid: int, etype: str, truth: dict, felt: str, names: dict, role: str, ts: int,
                 now: int) -> None:
        self.conn, self.pid, self.eid, self.etype, self.truth, self.felt, self.names, self.role, self.ts = \
            conn, pid, eid, etype, truth, felt, names, role, ts
        self.rev = eid - 1          # the relationships and the self-model are read as of just before the cause
        self.now = now              # what came of it (a goal it gave rise to) is read as of the line being spoken
        self.witnesses = conn.execute("SELECT COUNT(*) FROM event_participants WHERE event_id = ? AND role = 'witness'", (eid,)).fetchone()[0]

    def name(self, pid: str) -> str:
        return self.names.get(pid, "對方") if pid else "對方"

    @property
    def other(self) -> str:
        t = self.truth
        if self.role == "actor":
            return t.get("target") or t.get("victim") or t.get("suspect") or ""
        return t.get("actor") or ""

    # -- the records a reading may lean on; each returns (value, evidence) -------------------------------------------------
    def event(self) -> dict:
        return {"kind": "event", "event_id": self.eid, "type": self.etype}

    def field(self, a: str, b: str, field: str) -> tuple[float, dict]:
        from narrative.audience import value_at
        v = _num(value_at(self.conn, "relationship", f"{a}:{b}", field, self.rev)) or 0.0
        return v, {"kind": "relationship", "entity": f"{a}:{b}", "field": field, "value": v, "as_of": self.rev,
                   "set_by": self._set_by("relationship", f"{a}:{b}", field)}

    def holds(self, model: str) -> dict | None:
        """The evidence that this person had come to see themselves this way before the event, or None."""
        from narrative.audience import value_at
        key = f"psy.{self.pid}.self.{model}"
        v = _num(value_at(self.conn, "var", key, "value", self.rev))
        if v is None or v < 0.5:
            return None
        return {"kind": "self_model", "entity": key, "field": "value", "value": v, "as_of": self.rev, "set_by": self._set_by("var", key, "value")}

    def vigilance_raised(self) -> dict | None:
        from narrative.audience import value_at
        from world.psyche import ADAPTIVE
        key = f"psy.{self.pid}.vigilance"
        v = _num(value_at(self.conn, "var", key, "value", self.rev))
        if v is None or v < ADAPTIVE["vigilance"] + 0.05:
            return None
        return {"kind": "var", "entity": key, "field": "value", "value": v, "as_of": self.rev, "set_by": self._set_by("var", key, "value")}

    def piled_up(self, experience: str) -> dict | None:
        """The evidence that the same kind of thing had been happening to this person again and again (the psyche's accumulated
        experience, which the nightly reflections build and fade), or None."""
        from narrative.audience import value_at
        from world.psyche import REPEAT
        key = f"psy.{self.pid}.exp.{experience}"
        v = _num(value_at(self.conn, "var", key, "value", self.rev))
        if v is None or v < REPEAT:
            return None
        return {"kind": "var", "entity": key, "field": "value", "value": v, "as_of": self.rev, "set_by": self._set_by("var", key, "value")}

    def said(self, key: str) -> dict:
        """A recorded field of the cause event itself."""
        return {"kind": "truth", "event_id": self.eid, "key": key, "value": self.truth.get(key)}

    def motive(self, kinds: tuple[str, ...] = ()) -> tuple[dict, dict] | None:
        """A goal this person formed *because of* the event (a goal_change that names it as its cause): (the goal_change, evidence)."""
        row = self.conn.execute(
            "SELECT event_id, truth FROM events WHERE type = 'goal_change' AND event_id > ? AND event_id <= ? "
            "AND json_extract(truth, '$.cause_event') = ? AND json_extract(truth, '$.actor') = ? AND json_extract(truth, '$.to') = 'formed' "
            "ORDER BY event_id LIMIT 1", (self.eid, self.now, self.eid, self.pid)).fetchone()
        if row is None:
            return None
        t = json.loads(row[1])
        if kinds and t.get("kind") not in kinds:
            return None
        return t, {"kind": "event", "event_id": row[0], "type": "goal_change", "caused_by": self.eid}

    def earlier_goal(self, kind: str) -> tuple[dict, dict] | None:
        row = self.conn.execute(
            "SELECT event_id, truth FROM events WHERE type = 'goal_change' AND event_id <= ? AND json_extract(truth, '$.kind') = ? "
            "AND json_extract(truth, '$.actor') = ? AND json_extract(truth, '$.to') = 'formed' ORDER BY event_id DESC LIMIT 1",
            (self.rev, kind, self.pid)).fetchone()
        if row is None:
            return None
        return json.loads(row[1]), {"kind": "event", "event_id": row[0], "type": "goal_change"}

    def _set_by(self, etype: str, eid: str, field: str) -> int | None:
        row = self.conn.execute("SELECT event_id FROM event_deltas WHERE entity_type = ? AND entity_id = ? AND field = ? AND event_id <= ? "
                                "ORDER BY delta_id DESC LIMIT 1", (etype, eid, field, self.rev)).fetchone()
        return row[0] if row else None


def _r(underneath: str, rule: str, confidence: float, because: str, *evidence: dict | None) -> dict:
    return {"underneath": underneath, "rule": rule, "confidence": confidence, "because": because, "evidence": [e for e in evidence if e]}


# -- the readings -----------------------------------------------------------------------------------------------------------------
def _talk_received(k: _Cause) -> dict | None:
    """Somebody spoke coldly or hostilely to this person."""
    tone, x = k.truth.get("tone"), k.other
    if tone not in ("cold", "hostile") or not x:
        return None
    X = k.name(x)
    heard = f"{X}對他說了{'兇話' if tone == 'hostile' else '冷話'}"
    if k.felt == "scared":
        owed, ev = k.field(k.pid, x, "debt_cents")
        if owed > 0:
            return _r(f"欠了{X}的錢，怕被追討", "owes_money", 0.7, heard, k.event(), ev)
        return None
    if k.felt not in ("angry", "hurt"):
        return None
    aff, ev_aff = k.field(k.pid, x, "affection")
    att, ev_att = k.field(k.pid, x, "attraction")
    if aff >= 0.5:
        return _r(f"怕被{X}丟下", "fond_turned_cold", 0.7, heard, k.event(), ev_aff)
    if att >= 0.3:
        return _r(f"怕被{X}丟下", "fond_turned_cold", 0.7, heard, k.event(), ev_att)
    alone = k.holds("on_my_own")
    fam, ev_fam = k.field(k.pid, x, "familiarity")
    if alone and fam >= 0.4:
        return _r("怕被所有人丟下，只能靠自己", "on_my_own", 0.65, heard, k.event(), alone, ev_fam)
    trust, ev_tr = k.field(k.pid, x, "trust")
    if trust >= 0.3:
        return _r(f"本來信得過{X}，沒想到他會這樣", "trusted", 0.6, heard, k.event(), ev_tr)
    grudge, ev_g = k.field(k.pid, x, "resentment")
    if grudge >= 0.3:
        return _r(f"對{X}的舊怨還沒消，這句只是引子", "old_grudge", 0.55, heard, k.event(), ev_g)
    hostile = k.holds("world_is_hostile")
    if hostile and tone == "hostile":
        return _r(f"覺得大家都對自己有敵意，連{X}也一樣", "world_is_hostile", 0.6, heard, k.event(), hostile)
    worn = k.piled_up("hostility")
    if worn:
        return _r("已經被這樣對待很多次，累了", "worn_down", 0.55, heard, k.event(), worn)
    return None


def _talk_spoken(k: _Cause) -> dict | None:
    """This person's own hostile word left them angry; what is behind a hard word."""
    x = k.other
    if k.truth.get("tone") != "hostile" or not x or k.felt != "angry":
        return None
    X = k.name(x)
    said = f"對{X}說了兇話"
    aff, ev_aff = k.field(k.pid, x, "affection")
    att, ev_att = k.field(k.pid, x, "attraction")
    if aff >= 0.5 or att >= 0.3:
        return _r(f"其實在乎{X}，不想鬧成這樣", "hard_to_the_loved", 0.6, said, k.event(), ev_aff if aff >= 0.5 else ev_att)
    fear, ev_f = k.field(k.pid, x, "fear")
    if fear >= 0.3:
        return _r(f"怕{X}，所以先兇", "hard_from_fear", 0.6, said, k.event(), ev_f)
    grudge, ev_g = k.field(k.pid, x, "resentment")
    if grudge >= 0.3:
        return _r(f"對{X}的舊怨還沒消", "hard_from_grudge", 0.6, said, k.event(), ev_g)
    hostile = k.holds("world_is_hostile")
    if hostile:
        return _r("怕被欺負，所以先兇", "hard_from_hostile_world", 0.55, said, k.event(), hostile)
    worn = k.piled_up("hostility")
    if worn:
        return _r("近來被針對太多次，說話才帶刺", "hard_from_worn_down", 0.55, said, k.event(), worn)
    return None


def _talk_kind(k: _Cause) -> dict | None:
    """A kind word, to somebody who was not expecting one (the psyche's own test of an unexpected kindness)."""
    x = k.other
    if k.truth.get("tone") != "warm" or k.felt != "happy" or not x:
        return None
    X = k.name(x)
    trust, ev_tr = k.field(k.pid, x, "trust")
    if trust <= -0.2:
        return _r(f"對{X}的戒心還沒放下", "kind_but_wary", 0.55, f"{X}對他說了暖話", k.event(), ev_tr)
    vig = k.vigilance_raised()
    if vig:
        return _r("最近被傷過，還不敢全信", "kind_after_hurt", 0.55, f"{X}對他說了暖話", k.event(), vig)
    return None


def _talk(k: _Cause) -> dict | None:
    if k.role == "target":
        return _talk_kind(k) if k.truth.get("tone") == "warm" else _talk_received(k)
    if k.role == "actor":
        return _talk_spoken(k)
    return None


def _exposed(k: _Cause) -> dict | None:
    """confront / accuse: the recorded outcome says what it was to each side."""
    outcome, x = k.truth.get("outcome"), k.other
    if not outcome or not x:
        return None
    X = k.name(x)
    what = "當面質疑" if k.etype == "confront" else "被指控"
    if k.role == "target":
        if outcome in ("unfounded", "false"):
            text = "說的明明是實話，卻被當面質疑" if k.etype == "confront" else "明明沒做過，卻被冤枉"
            return _r(text, "wronged", 0.75, f"被{X}{what}，而那是冤枉", k.event(), k.said("outcome"))
        if outcome in ("lie_exposed", "caught"):
            return _r(f"怕{X}從此不再信自己", "exposed", 0.75, f"被{X}當面拆穿", k.event(), k.said("outcome"))
        return None
    if k.role == "actor":
        if outcome in ("unfounded", "false"):
            return _r(f"冤枉了{X}，不知道怎麼面對他", "wrongly_doubted", 0.7, f"{what}了{X}，卻是誤會", k.event(), k.said("outcome"))
        if outcome in ("lie_exposed", "caught"):
            trust, ev = k.field(k.pid, x, "trust")
            if trust >= 0.2:
                return _r(f"本來信得過{X}，卻被他騙了", "betrayed_by_trusted", 0.7, f"發現{X}說了謊", k.event(), k.said("outcome"), ev)
            return _r(f"被{X}騙了，不知道還能信誰", "betrayed", 0.65, f"發現{X}說了謊", k.event(), k.said("outcome"))
        if outcome in ("distortion_exposed", "concealment_exposed"):
            return _r(f"{X}沒有對自己說實話", "not_told", 0.6, f"發現{X}有所隱瞞", k.event(), k.said("outcome"))
    return None


def _duel(k: _Cause) -> dict | None:
    t = k.truth
    if t.get("loser") == k.pid and k.felt == "ashamed":
        goal = k.motive(("surpass", "revenge"))
        if goal:
            g, ev = goal
            return _r(f"不甘心，想著「{g.get('text') or '贏回來'}」", "lost_wants_back", 0.8, "比武輸了", k.event(), ev)
        if k.witnesses >= 2:
            return _r("怕被人看輕", "lost_in_front_of_others", 0.6, f"在{k.witnesses}個人面前比武輸了", k.event(),
                      {"kind": "witnesses", "event_id": k.eid, "value": k.witnesses})
        return None
    if t.get("winner") == k.pid and k.felt == "happy":
        slap = t.get("slap") or {}
        if slap.get("underdog") == k.pid:
            return _r("一直被人看輕，今天總算讓人看見", "proved_them_wrong", 0.7, "比武贏了，也讓看輕自己的人改觀", k.event(), k.said("slap"))
        if t.get("bully"):
            return _r("贏了比自己弱的人，贏得不光彩", "bully_win", 0.55, "贏了比自己弱得多的人", k.event(), k.said("bully"))
    return None


def _break_up(k: _Cause) -> dict | None:
    if k.role == "target" and k.felt == "hurt":
        return _r("怕被丟下，又只剩自己一個", "left", 0.75, f"{k.name(k.other)}提了分手", k.event())
    return None


def _confession(k: _Cause) -> dict | None:
    if k.role == "actor" and k.felt == "ashamed" and k.truth.get("outcome") == "declined":
        return _r("怕被笑，也怕連朋友都做不成", "declined", 0.6, f"向{k.name(k.other)}告白，被婉拒", k.event(), k.said("outcome"))
    return None


def _missing(k: _Cause) -> dict | None:
    """What is missing and who is suspected: the owner's own belief (never whether the suspect did it)."""
    s, c = k.truth.get("suspect"), _num(k.truth.get("confidence"))
    if k.role != "actor" or k.felt != "uneasy" or not s or c is None:
        return None
    S = k.name(s)
    text = f"幾乎認定是{S}拿的" if c >= 0.7 else f"懷疑{S}，可是不確定"
    return _r(text, "suspects", 0.7, "發現東西不見了", k.event(), k.said("suspect"), k.said("confidence"))


def _praised(k: _Cause) -> dict | None:
    if k.truth.get("worker") != k.pid or k.felt != "happy":
        return None
    goal = k.earlier_goal("earn_recognition")
    if goal:
        g, ev = goal
        return _r("一直想被看見，今天終於有人看見了", "recognised", 0.7, "被當眾誇獎", k.event(), ev)
    return None


RULES = {"talk": _talk, "confront": _exposed, "accuse": _exposed, "duel": _duel, "break_up": _break_up, "confession": _confession,
         "notice_missing": _missing, "praise": _praised}


# -- finding the cause --------------------------------------------------------------------------------------------------------------
def _cause_of_feeling(conn: sqlite3.Connection, pid: str, rev: int) -> tuple[str, int, str, int, list[int]] | None:
    """(the feeling now, the daytime event that set it, the feeling it set then, its timestamp, the nights between), as of `rev`."""
    rows = conn.execute(
        "SELECT d.event_id, e.type, d.new_value, e.timestamp FROM event_deltas d JOIN events e ON e.event_id = d.event_id "
        "WHERE d.entity_type = 'person' AND d.entity_id = ? AND d.field = 'emotion' AND d.event_id <= ? ORDER BY d.delta_id DESC LIMIT 4",
        (pid, rev)).fetchall()
    if not rows:
        return None
    nights = []
    for r in rows:
        if r[1] == "upkeep":
            nights.append(r[0])
            continue
        return str(rows[0][2]), r[0], str(r[2]), r[3], nights
    return None


def inner_state(conn: sqlite3.Connection, pid: str, event_id: int, names: dict | None = None) -> dict | None:
    """What `pid` shows and what is underneath, as of just before event `event_id`; None where nothing can be said with grounds."""
    rev = event_id - 1
    found = _cause_of_feeling(conn, pid, rev)
    if found is None:
        return None
    surface, root, felt, ts, nights = found
    if surface not in EMOTION_ZH:
        return None
    now = conn.execute("SELECT timestamp FROM events WHERE event_id <= ? ORDER BY event_id DESC LIMIT 1", (max(rev, 1),)).fetchone()
    if now is not None and now[0] - ts > FRESH:
        return None
    row = conn.execute("SELECT type, truth FROM events WHERE event_id = ?", (root,)).fetchone()
    if row is None or row[0] not in RULES:
        return None
    truth = json.loads(row[1])
    part = conn.execute("SELECT role FROM event_participants WHERE event_id = ? AND person_id = ?", (root, pid)).fetchone()
    role = part[0] if part else ""
    if truth.get("worker") == pid:
        role = "worker"
    names = names or {}
    k = _Cause(conn, pid, root, row[0], truth, felt, names, role, ts, rev)
    got = RULES[row[0]](k)
    if got is None:
        return None
    conf = round(got["confidence"] * (NIGHT if nights else 1.0), 3)
    return {"version": INNER_VERSION, "person": pid, "as_of": rev, "surface": surface, "surface_zh": EMOTION_ZH[surface],
            "other": k.other, "felt_then": felt, "nights": len(nights), "underneath": got["underneath"], "rule": got["rule"],
            "because": {"event_id": root, "type": row[0], "text": got["because"]}, "evidence": got["evidence"], "confidence": conf}


def phrase(state: dict) -> str:
    return f"表面{state['surface_zh']}，底下是{state['underneath']}"


def voiced(conn: sqlite3.Connection, pid: str, state: dict, event_id: int, addressee: str = "") -> bool:
    """Has this feeling already shown in what `pid` said? It shows on the first thing they say after its cause, and again on
    the first thing they say to the person it is about; after that the same sentence would hang on every word of a bad day."""
    marks = ",".join("?" * len(VOICED_ON))
    alone = ",".join("?" * len(ALONE))
    gate = "".join(f" AND (e.type != '{t}' OR e.event_id % {n} = 0)" for t, n in ALONE_EVERY.items())    # (the lines speech.py leaves silent)
    rows = conn.execute(
        f"SELECT CASE WHEN e.type IN ({alone}) THEN '' ELSE COALESCE(json_extract(e.truth, '$.target'), json_extract(e.truth, '$.victim'), '') END "
        f"FROM events e JOIN event_participants p ON p.event_id = e.event_id AND p.person_id = ? AND p.role = 'actor' "
        f"WHERE e.event_id > ? AND e.event_id < ? AND e.type IN ({marks}) {gate}",
        (*ALONE, pid, state["because"]["event_id"], event_id, *VOICED_ON)).fetchall()
    if not rows:
        return False                                   # nothing said since: this is the first
    return not (addressee and addressee == state["other"] and addressee not in {r[0] for r in rows})


def inner_subtext(conn: sqlite3.Connection, pid: str, event_id: int, addressee: str = "", names: dict | None = None) -> dict | None:
    """The reading to hang on a line `pid` speaks at `event_id`: it must be sure enough, and not yet voiced."""
    state = inner_state(conn, pid, event_id, names)
    if state is None or state["confidence"] < SAY_AT or voiced(conn, pid, state, event_id, addressee):
        return None
    return state


# -- checking a reading against the records ------------------------------------------------------------------------------------------
def verify(conn: sqlite3.Connection, state: dict) -> list[str]:
    """Every claim of a reading, re-read from the history. Returns what does not hold (empty: it is all in the records)."""
    from narrative.audience import value_at
    bad = []
    pid, rev = state["person"], state["as_of"]
    root = state["because"]["event_id"]
    ev = conn.execute("SELECT type, truth FROM events WHERE event_id = ?", (root,)).fetchone()
    if ev is None or root > rev:
        return [f"the cause event {root} is not in the history before the line"]
    if ev[0] != state["because"]["type"]:
        bad.append(f"event {root} is a {ev[0]}, not a {state['because']['type']}")
    if not conn.execute("SELECT 1 FROM event_participants WHERE event_id = ? AND person_id = ?", (root, pid)).fetchone():
        bad.append(f"{pid} had no part in event {root}")
    if not conn.execute("SELECT 1 FROM event_deltas WHERE event_id = ? AND entity_type = 'person' AND entity_id = ? AND field = 'emotion' "
                        "AND new_value = ?", (root, pid, state["felt_then"])).fetchone():
        bad.append(f"event {root} did not set {pid}'s emotion to {state['felt_then']}")
    if not any(e.get("kind") == "event" and e.get("event_id") == root for e in state["evidence"]):
        bad.append("the cause event is not among the evidence")
    truth = json.loads(ev[1])
    for e in state["evidence"]:
        kind = e.get("kind")
        if kind == "event":
            row = conn.execute("SELECT type FROM events WHERE event_id = ?", (e["event_id"],)).fetchone()
            if row is None or e["event_id"] > rev or row[0] != e["type"]:
                bad.append(f"event {e.get('event_id')} is not a {e.get('type')} before the line")
        elif kind in ("relationship", "self_model", "var"):
            entity_type = "relationship" if kind == "relationship" else "var"
            got = _num(value_at(conn, entity_type, e["entity"], e["field"], e["as_of"]))
            if got is None or abs(got - e["value"]) > 1e-9:
                bad.append(f"{e['entity']}.{e['field']} was {got}, not {e['value']}")
            if e["set_by"] is not None and not conn.execute(
                    "SELECT 1 FROM event_deltas WHERE event_id = ? AND entity_type = ? AND entity_id = ? AND field = ?",
                    (e["set_by"], entity_type, e["entity"], e["field"])).fetchone():
                bad.append(f"event {e['set_by']} did not set {e['entity']}.{e['field']}")
        elif kind == "truth":
            if e["event_id"] != root or truth.get(e["key"]) != e["value"]:
                bad.append(f"event {e.get('event_id')} has no {e.get('key')} = {e.get('value')}")
        elif kind == "witnesses":
            n = conn.execute("SELECT COUNT(*) FROM event_participants WHERE event_id = ? AND role = 'witness'", (e["event_id"],)).fetchone()[0]
            if n != e["value"]:
                bad.append(f"event {e['event_id']} had {n} witnesses, not {e['value']}")
        else:
            bad.append(f"unknown evidence {kind}")
    return bad
