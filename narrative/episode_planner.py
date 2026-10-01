"""Episode planner: from what happened to the shape of one episode (read only; it adds no event and decides nothing).

    material    what is worth an episode today: a release the audience waited for (a payoff, narrative/payoff.py), or else the
                story thread the director ranks first (narrative/director.py)
    classify    each event goes on a rung of the ladder (daily, anomaly, doubt, rising, conflict, choice, irreversible, change)
                and is given a shot intent (the closed vocabulary of contracts/episode_plan.py)
    checklist   what each scene changes, read from the world's own deltas: who wanted what, who stood against them, who knew,
                how a feeling or a relationship moved, what else changed. A scene in which nothing changed is *not filmed*
    shape       the one question, the tension curve and whether it breathes, a near miss, where the truth reaches the audience,
                and the question left open at the end
    grammar     for a payoff, the web-novel line (belittled, hidden growth, a gathering, the reversal, the bystanders, the next
                goal): which steps the world really produced, and which it did not (a missing step is reported, never invented)

The planner chooses and orders; the world made every event it points at.
"""
from __future__ import annotations

import json
import sqlite3

from contracts.episode_plan import (GRAMMAR_STEPS, STAGES, EpisodeBeat, EpisodePlan, GrammarStep, SceneChecklist, finalize)
from narrative.arcs import Arc, Ev, load_events

PLANNER_VERSION = "episode_planner_v0.1"
NOT_STORY = {"day_end", "upkeep", "circles", "role_ended", "sleep", "rest", "setup"}
KNOWLEDGE = {"tell", "accuse", "confront", "notice_missing", "backstory", "find"}
RELATION_FIELDS = ("trust", "affection", "respect", "resentment", "estimate", "attraction", "fear", "rivalry")
MIN_SHIFT = 0.05
BREATH_DROP = 0.08
QUIET_OPENING = 0.30
INNER_AT = 0.4             # the tension from which a choice against oneself is the episode (the dramaturgy extension's threshold)
PAYOFF_AT = 0.25            # an earned payoff this big comes before a feud (the audience has been waiting for it)
LOOKBACK = 14               # days behind a payoff in which its set-up is looked for
MAX_EVENTS = 8

BY_TYPE = {
    "eat": ("daily", "observe"), "move": ("daily", "orient"), "work": ("daily", "observe"), "praise": ("daily", "connect"),
    "overtime": ("daily", "isolate"), "give": ("rising", "connect"), "lend": ("rising", "connect"), "repay": ("rising", "connect"),
    "misplace": ("anomaly", "foreshadow"), "take": ("anomaly", "hide"), "steal": ("anomaly", "hide"), "find": ("anomaly", "reveal"),
    "backstory": ("anomaly", "foreshadow"), "intervention": ("anomaly", "setup"), "parrot_speaks": ("anomaly", "contrast"),
    "notice_missing": ("doubt", "misdirect"),
    "train": ("rising", "setup"), "recruit": ("rising", "rival_standoff"), "campaign": ("rising", "rival_standoff"),
    "flirt": ("rising", "longing_glance"), "date": ("rising", "connect"),
    "shove": ("conflict", "escalate"), "smash": ("conflict", "escalate"), "hit": ("conflict", "escalate"), "break_down": ("conflict", "reveal"),
    "break_up": ("irreversible", "aftermath"), "defect": ("irreversible", "choice"), "found_faction": ("choice", "rival_standoff"),
    "succession": ("irreversible", "payoff"), "breakthrough": ("change", "payoff"), "goal_change": ("change", "aftermath"),
    "regret": ("change", "aftermath"), "reflection": ("change", "aftermath"),
}
NEXT_GOAL_LEAD = "下一個"


def _names(conn: sqlite3.Connection) -> dict[str, str]:
    return {r[0]: r[1] for r in conn.execute("SELECT id, name FROM people")}


def classify(e: Ev) -> tuple[str, str]:
    """(rung, shot intent) of one event."""
    t, tr = e.type, e.truth
    stage, intent = BY_TYPE.get(t, (None, None))
    if t == "talk":
        tone = tr.get("tone", "neutral")
        stage, intent = ("conflict", "escalate") if tone == "hostile" else ("rising", "escalate") if tone == "cold" else ("daily", "connect")
    elif t == "tell":
        stage, intent = ("doubt", "hide") if e.mode in ("lie", "distortion", "omission") else ("daily", "connect")
    elif t in ("accuse", "confront"):
        out = tr.get("outcome") or tr.get("variant") or ""
        stage, intent = ("doubt", "misdirect") if out in ("false", "unfounded", "misinformed") else ("conflict", "reveal")
    elif t == "duel":
        stage, intent = ("irreversible", "face_slap") if tr.get("slap") else ("conflict", "escalate")
    elif t == "confession":
        stage, intent = ("irreversible", "confession") if tr.get("outcome") == "accepted" else ("choice", "confession")
    if stage is None:
        from world.domains import style
        st = style(t)
        heat = st.heat if st is not None else 0
        stage, intent = (("daily", "observe"), ("rising", "observe"), ("conflict", "escalate"), ("irreversible", "payoff"))[min(3, heat)]
    if float((tr.get("dilemma") or {}).get("tension", 0.0)) >= INNER_AT and stage not in ("irreversible", "change"):
        stage, intent = "choice", "choice"
    return stage, intent


def _is_story(e: Ev) -> bool:
    if e.type in NOT_STORY:
        return False
    if e.type == "reflection":
        return bool(e.truth.get("shifted") or e.truth.get("self_model") or e.truth.get("formed"))
    return True


def _goal(conn: sqlite3.Connection, pid: str) -> str:
    r = conn.execute("SELECT kind, target, object FROM goals WHERE person_id = ? AND status = 'active' ORDER BY priority DESC LIMIT 1", (pid,)).fetchone()
    return "" if r is None else f"{r[0]}" + (f" {r[1]}" if r[1] else (f" {r[2]}" if r[2] else ""))


def checklist(conn: sqlite3.Connection, e: Ev, names: dict[str, str], situations: list[dict]) -> SceneChecklist:
    """What this scene changed, from the world's own deltas (the entity changes the event wrote)."""
    emo: dict[str, list[str]] = {}
    rel: list[tuple[float, str]] = []
    state: list[str] = []
    for r in conn.execute("SELECT entity_type, entity_id, field, old_value, new_value, delta_value FROM event_deltas WHERE event_id = ?", (e.id,)):
        et, eid, f = r["entity_type"], r["entity_id"], r["field"]
        if et == "person" and f == "emotion" and r["old_value"] != r["new_value"]:
            emo[names.get(eid, eid)] = [str(r["old_value"]), str(r["new_value"])]
        elif et == "relationship" and f in RELATION_FIELDS and r["delta_value"] is not None and abs(float(r["delta_value"])) >= MIN_SHIFT:
            a, _, b = eid.partition(":")
            rel.append((abs(float(r["delta_value"])), f"{names.get(a, a)}>{names.get(b, b)} {f} {float(r['delta_value']):+.2f}"))
        elif et in ("seat", "affiliation", "faction", "object") and f in ("holder_id", "status", "faction_id", "owner_person_id"):
            state.append(f"{et} {eid} {f}")
        elif et == "var" and eid.startswith(("skill.", "role.")) and f == "value" and r["delta_value"] is not None and abs(float(r["delta_value"])) >= 0.01:
            state.append(f"{eid.split('.')[0]} {names.get(eid.split('.', 1)[1], eid.split('.', 1)[1])}")
    if e.type == "goal_change":
        state.append(f"goal {e.truth.get('to', '')}: {e.truth.get('text', '')}")
    actor = e.truth.get("actor") or (e.people[0] if e.people else "")
    other = e.truth.get("target") or e.truth.get("loser") or next((p for p in e.people if p != actor), "")
    hostile = classify(e)[0] in ("conflict", "irreversible") and other and other != actor
    mine = [s for s in situations if e.id in s["events"]]
    audience_only = any(s["kind"] in ("misbelief", "secret", "live_lie") for s in mine)
    changed = bool(emo or rel or state) or e.type in KNOWLEDGE or classify(e)[0] in ("irreversible", "change")
    return SceneChecklist(
        wants={names.get(actor, actor): _goal(conn, actor)} if actor and _goal(conn, actor) else {},
        obstructs=names.get(other, other) if hostile else "", knows=[names.get(p, p) for p in e.people],
        audience_only=audience_only, emotion=emo, relationship=[s for _, s in sorted(rel, reverse=True)[:4]], state=state[:4],
        leaves_question=max(mine, key=lambda s: s["potential"])["question"] if mine else "", changed=changed)


def _tension(e: Ev, stage: str) -> float:
    from world.domains import style
    st = style(e.type)
    heat = st.heat if st is not None else 1
    dil = float((e.truth.get("dilemma") or {}).get("tension", 0.0))
    return round(max(0.0, min(1.0, 0.08 + 0.10 * STAGES.index(stage) + 0.05 * heat + 0.25 * dil + 0.15 * e.importance)), 3)


def _witnesses(e: Ev) -> list[str]:
    return [p for p, role in e.participants if role == "witness"]


# -- the web-novel grammar ---------------------------------------------------------------------------------------------
def payoff_material(conn: sqlite3.Connection, events: dict[int, Ev], p: dict) -> tuple[Arc, list[GrammarStep]]:
    """A payoff and the steps behind it, drawn from what the world produced in the weeks before (nothing is added)."""
    hero, day = p["protagonist"], p["day"]
    peak = events[p["event_id"]]
    lo = (day - LOOKBACK) * 1440
    window = [e for e in events.values() if lo <= e.ts <= peak.ts and e.id != peak.id]

    belittled = [e for e in window if (e.type == "talk" and e.truth.get("tone") in ("cold", "hostile") and e.truth.get("target") == hero)
                 or (e.type == "duel" and e.truth.get("loser") == hero)][-2:]
    growth = [e for e in window if e.type in ("train", "breakthrough") and e.truth.get("actor") == hero][-2:]
    gathering = [e for e in window if e.type == "intervention" and e.truth.get("kind") in ("announce_gathering", "open_seat")][-1:]
    after = [e for e in events.values() if peak.ts < e.ts <= peak.ts + 2 * 1440 and e.truth.get("actor") == hero and (e.type in ("goal_change", "regret", "breakthrough")
             or (e.type == "reflection" and e.truth.get("shifted")))][:1]
    witnessed = _witnesses(peak)
    steps = [GrammarStep("belittled", [e.id for e in belittled], bool(belittled), "those who held them down"),
             GrammarStep("hidden_growth", [e.id for e in growth], bool(growth), "what they did where nobody looked"),
             GrammarStep("gathering", [e.id for e in gathering], bool(gathering) or len(witnessed) >= 3, "the place where it could be seen"),
             GrammarStep("reversal", [peak.id], True, p["kind"]),
             GrammarStep("bystanders", [peak.id] if witnessed else [], bool(witnessed), f"{len(witnessed)} saw it"),
             GrammarStep("next_goal", [e.id for e in after], bool(after), "what they want now")]
    chosen = sorted({i for s in steps for i in s.event_ids if i != peak.id} | {peak.id})
    arc = Arc(tuple(events[i] for i in chosen[-MAX_EVENTS:]), peak, "payoff")
    return arc, steps


def inner_material(conn: sqlite3.Connection, events: dict[int, Ev], day: int, shown) -> Arc | None:
    """The strongest choice somebody made against themselves in the last day, with what led to it and what it did to them."""
    rows = [(float(json.loads(r["truth"])["dilemma"]["tension"]), r["event_id"]) for r in conn.execute(
        "SELECT event_id, truth FROM events WHERE timestamp >= ? AND json_extract(truth, '$.dilemma.tension') >= ?", ((day - 1) * 1440, INNER_AT))
        if r["event_id"] not in shown]
    if not rows:
        return None
    _, eid = max(rows)
    peak = events[eid]
    chain, cur = [], peak
    while cur.parent is not None and cur.parent in events and len(chain) < 3:
        cur = events[cur.parent]
        chain.append(cur)
    after = [e for e in events.values() if e.type == "reflection" and eid in (e.truth.get("cites") or []) and e.truth.get("actor") == peak.truth.get("actor")][:1]
    return Arc(tuple(sorted({e.id: e for e in [*chain, peak, *after]}.values(), key=lambda e: e.id)), peak, "inner")


def choose_material(conn: sqlite3.Connection, day: int, shown: set[int] | frozenset[int] = frozenset(), recent: tuple = ()):
    """(arc, thread, kind, payoff, steps) for today: an unshown payoff of the last day first, then a choice against oneself, else the
    director's best thread (not the pair of the last episodes, when there is another)."""
    from narrative import payoff as P
    from narrative.director import select_thread
    events = load_events(conn)
    fresh = [p for p in P.payoffs(conn) if p["day"] >= day - 1 and p["event_id"] not in shown and p["earned"] >= PAYOFF_AT]
    if fresh:
        p = max(fresh, key=lambda x: (x["earned"], x["event_id"]))
        arc, steps = payoff_material(conn, events, p)
        return arc, None, "payoff", p, steps
    inner = inner_material(conn, events, day, shown)
    if inner is not None:
        return inner, None, "inner", None, []
    from narrative.director import rank_threads, thread_arc
    ranked = rank_threads(conn, day, shown)
    if not ranked:
        return None, None, "", None, []
    pick = next(((s, t) for s, t in ranked if frozenset(p for i in t.event_ids if i in events for p in events[i].people[:2]) not in recent), ranked[0])
    return thread_arc(pick[1], events, set(shown)), pick[1], "thread", None, []


# -- the plan ----------------------------------------------------------------------------------------------------------
def _core_question(conn, names, arc, thread, shown, situations, kind, payoff, inner) -> str:
    n = lambda pid: names.get(pid, pid or "")  # noqa: E731
    if kind == "payoff":
        if payoff["kind"] == "face_slap":
            return f"{n(payoff['protagonist'])}被看輕了，能在眾人面前證明自己嗎？"
        if payoff["kind"] == "chosen":
            return f"{n(payoff['protagonist'])}的心意，會被{n(payoff.get('against'))}接受嗎？"
        return f"誰會成為「{conn.execute('SELECT title FROM seats WHERE seat_id = ?', (payoff.get('seat'),)).fetchone()[0] if payoff.get('seat') else '那個位子'}」？"
    ids = set(arc.ids)
    mine = [s for s in situations if ids & set(s["events"]) and s["question"]]
    if inner:
        dil = [s for s in mine if s["kind"] == "dilemma"]
        if dil:
            return max(dil, key=lambda s: s["potential"])["question"]
    if thread is not None:
        from narrative.knowledge import knowledge_of
        k = knowledge_of(conn, thread, set(shown))
        if k is not None and k.question:
            return k.question
    if mine:
        return max(mine, key=lambda s: (s["potential"], s["day"]))["question"]
    peak = arc.peak
    who = [n(p) for p in peak.people[:2]]
    return f"{'和'.join(who)}會怎麼收場？" if len(who) == 2 else f"{who[0] if who else ''}接下來會怎麼做？"


def plan_episode(conn: sqlite3.Connection, arc: Arc, thread=None, shown: set[int] | frozenset[int] = frozenset(), day: int | None = None,
                 kind: str = "thread", payoff: dict | None = None, steps: list[GrammarStep] | None = None,
                 situations: list[dict] | None = None) -> EpisodePlan:
    if situations is None:
        from narrative.dramaturgy import analyse
        situations = analyse(conn)["situations"]
    names = _names(conn)
    day = arc.peak.day if day is None else day
    grammar_ids = {i for s in (steps or []) for i in s.event_ids}
    beats: list[EpisodeBeat] = []
    for e in sorted(arc.events, key=lambda x: x.id):
        if not _is_story(e):
            continue
        stage, intent = classify(e)
        cl = checklist(conn, e, names, situations)
        if e.type in ("train", "breakthrough") and payoff is not None and e.truth.get("actor") == payoff["protagonist"]:
            cl = SceneChecklist(**{**cl.__dict__, "audience_only": True})   # the growth only the audience saw
        on_stage = bool(e.people)
        setup = e.id in grammar_ids and e.id != arc.peak.id     # a step of the web-novel line: it is the set-up, kept even if it changed nothing yet
        shoot = on_stage and (cl.changed or setup)
        reason = ("" if shoot and cl.changed else "set-up of the line (changes nothing yet)" if shoot else "no one on stage" if not on_stage else "nothing changed")
        beats.append(EpisodeBeat(len(beats), [e.id], stage, _tension(e, stage), intent, [names.get(p, p) for p in e.people], cl, shoot, reason))
        wit = _witnesses(e)
        if shoot and intent in ("face_slap", "payoff", "confession") and len(wit) >= 2:
            react = SceneChecklist(knows=[names.get(p, p) for p in wit], changed=True, leaves_question="",
                                   relationship=[s for s in cl.relationship if "estimate" in s or "respect" in s][:3])
            beats.append(EpisodeBeat(len(beats), [e.id], stage, round(min(1.0, _tension(e, stage) * 0.9), 3), "bystander_shock",
                                     [names.get(p, p) for p in wit], react, True, "the room reacts to what it just saw", derived=True))
    filmed = [b for b in beats if b.shoot]
    curve = [b.tension for b in filmed]
    peak_i = max(range(len(curve)), key=lambda i: (curve[i], i)) if curve else 0
    drops = any(curve[i] - curve[i + 1] >= BREATH_DROP for i in range(min(peak_i, len(curve) - 1)))
    has_breath = bool(curve) and (drops or curve[0] <= QUIET_OPENING) and peak_i > 0
    inner = any(float((e.truth.get("dilemma") or {}).get("tension", 0.0)) >= INNER_AT for e in arc.events)
    ids = set(arc.ids)
    near = sorted({i for s in situations if s["kind"] == "near_miss" for i in s["events"] if i in ids})
    strategy, reveal_beat = "plain", None
    if thread is not None:
        from narrative.knowledge import knowledge_of
        k = knowledge_of(conn, thread, set(shown))
        if k is not None:
            strategy = "irony" if k.irony else "mystery" if (k.truth and not k.audience_knows) else "plain"
    if strategy == "irony" and filmed:
        reveal_beat = filmed[0].index
    elif strategy == "mystery":
        reveal_beat = next((b.index for b in filmed if b.intent == "reveal"), None)
    core = _core_question(conn, names, arc, thread, shown, situations, kind, payoff, inner)
    # what is left open: the next goal after a payoff, else a live situation of these people that goes on beyond the episode
    last = max((e.day for e in arc.events), default=day)
    people = {p for e in arc.events for p in e.people[:2]}     # the principals
    if kind == "payoff":
        nxt = next((s for s in (steps or []) if s.step == "next_goal" and s.present), None)
        ending = (f"{names.get(payoff['protagonist'], payoff['protagonist'])}接下來想要什麼？" if nxt is not None else
                  f"{NEXT_GOAL_LEAD}看輕{names.get(payoff['protagonist'], payoff['protagonist'])}的人是誰？")
    else:
        more = [s for s in situations if set(s["people"]) & people and (s["until"] or s["day"] + s.get("lasts", 1)) > last and s["question"] and s["question"] != core
                and not (set(s["events"]) <= ids)]
        ending = max(more, key=lambda s: (s["potential"], s["day"]))["question"] if more else ""
    plan = EpisodePlan(1, day, kind, thread.thread_id if thread is not None else "", core, beats, curve, has_breath, inner, near,
                       {"strategy": strategy, "beat": reveal_beat}, ending, steps or [], bool(steps) and all(s.present for s in steps),
                       [b.index for b in beats if not b.shoot], bool(filmed), sorted(people))
    return finalize(plan)


def plan_day(conn: sqlite3.Connection, day: int, shown: set[int] | frozenset[int] = frozenset(), situations: list[dict] | None = None,
             recent: tuple = ()) -> EpisodePlan | None:
    """The episode for `day`, or None on a quiet day (nothing worth telling). `recent`: the people of the last episodes (frozensets)."""
    arc, thread, kind, payoff, steps = choose_material(conn, day, shown, recent)
    if arc is None:
        return None
    return plan_episode(conn, arc, thread, shown, day, kind, payoff, steps, situations)
