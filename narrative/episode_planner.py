"""Episode planner: from what happened to the shape of one episode (read only; it adds no event and decides nothing).

    material    what is worth an episode today: a release the audience waited for (a payoff, narrative/payoff.py), a choice somebody
                made against themselves, or else a story thread that has really moved (narrative/director.py ranks, this checks)
    classify    each event goes on a rung of the ladder (daily, anomaly, doubt, rising, conflict, choice, irreversible, change)
                and is given a shot intent (the closed vocabulary of contracts/episode_plan.py)
    scene delta what each scene changes, in six kinds: state, relationship, emotion, goal (what the world's entities did), knowledge
                (somebody learns) and expectation (the audience is ahead: it has seen a growth the others have not, or a feeling
                nobody has said). A scene in which none of them changed is *not filmed*
    stagnation  a thread in which nothing real has happened (its fresh scenes only pass words along) is not the day's story
    question    one, of one of three kinds: a goal ("can they get X"), a choice ("A or B") or a revelation ("who will find out")
    grammar     for a payoff, the web-novel line (belittled, hidden growth, a gathering, the reversal, the bystanders, the new state):
                which steps the world really produced, and which it did not (a missing step is reported, never invented); the new
                state is a *consequence* read from the reversal, not an event the world has to log

The planner chooses and orders; the world made every event it points at. `Options` says which of these are on, so that two plans of the
same world can be compared (episode_lab.py).
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass

from contracts.episode_plan import (GRAMMAR_STEPS, STAGES, EpisodeBeat, EpisodePlan, GrammarStep, SceneChecklist, finalize)
from narrative.arcs import Arc, Ev, load_events

PLANNER_VERSION = "episode_planner_v0.2"
NOT_STORY = {"day_end", "upkeep", "circles", "role_ended", "sleep", "rest", "setup"}
KNOWLEDGE = {"tell", "accuse", "confront", "notice_missing", "backstory", "find"}
GROWTH = {"train", "breakthrough"}                         # what builds a gap between what somebody is and what they are taken for
RELATION_FIELDS = ("trust", "affection", "respect", "resentment", "estimate", "attraction", "fear", "rivalry")
MIN_SHIFT = 0.05
PROGRESS_SHIFT = 0.10      # a relationship that moves this much is a real change (a quarrel that moves it by a hair repeats, it does not progress)
BREATH_DROP = 0.08
QUIET_OPENING = 0.30
INNER_AT = 0.4             # the tension from which a choice against oneself is the episode (the dramaturgy extension's threshold)
PAYOFF_AT = 0.25           # an earned payoff this big comes before a feud (the audience has been waiting for it)
LOOKBACK = 14              # days behind a payoff in which its set-up is looked for
MAX_EVENTS = 8
VALUE_WORDS = {"truth": "真相", "loyalty": "忠誠", "security": "安穩", "belonging": "歸屬", "ambition": "野心",
               "fairness": "公道", "kindness": "善意", "freedom": "自由", "honor": "名譽"}


@dataclass(frozen=True)
class Options:
    delta: str = "narrative"       # "world": a scene changed what the world's entities did; "narrative": also what the audience gains
    keep_setup: bool = False       # (the first version's special case) keep the web-novel set-up scenes even if they changed nothing
    stagnation: bool = True        # a thread in which nothing real has happened is not the day's story
    grammar: str = "v2"            # "v1": next goal is an event; "v2": the new state is a consequence, bystanders include the voters
    questions: str = "typed"       # "typed": goal / choice / revelation; "free": whatever the analysis says
    ab_story: bool = False         # an episode is an A story, a B story that moves in the same days, and an ordinary moment to measure the peak from


V1 = Options("world", True, False, "v1", "free")        # the planner as first built (episode_planner_v0.1)
DEFAULT = Options()
AB = Options(ab_story=True)                              # + a B story and an ordinary moment (the control room shows these; production films one story)

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
    names = {r[0]: r[1] for r in conn.execute("SELECT id, name FROM people")}
    names.update({r[0]: r[1] for r in conn.execute("SELECT seat_id, title FROM seats")})
    return names


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


def _deltas(conn: sqlite3.Connection, e: Ev, names: dict[str, str]) -> tuple[dict, list[tuple[float, str]], list[str]]:
    """What the event changed in the world: feelings, relationships (and by how much), and the rest (a seat, a thing, a skill)."""
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
    return emo, rel, state


def real_progress(conn: sqlite3.Connection, e: Ev, names: dict[str, str]) -> bool:
    """Did the world itself move: a feeling changed, a relationship moved by a real amount, a seat, a thing or a goal changed."""
    emo, rel, state = _deltas(conn, e, names)
    return bool(emo or state or any(v >= PROGRESS_SHIFT for v, _ in rel))


def _advantage(conn: sqlite3.Connection, e: Ev, names: dict[str, str]) -> tuple[float, str]:
    """How far the audience is ahead at this scene: a growth the crowd has not seen (somebody is more than they are taken for), or a
    feeling nobody has said between the two on stage. (Narrative/audience.py: what the audience knows and expects, as of just before.)"""
    from narrative import audience as A
    actor = e.truth.get("actor") or (e.people[0] if e.people else "")
    if e.type in GROWTH and actor:
        exp = A.expectation_of(conn, actor, e.id - 1)
        if exp is not None and exp.knows - exp.expected >= A.GAP:
            return round(exp.knows - exp.expected, 3), f"觀眾知道{names.get(actor, actor)}比大家以為的強（{exp.knows:.2f} 對 {exp.expected:.2f}）"
    if e.type in ("flirt", "date") and len(e.people) >= 2:
        pair = sorted(e.people[:2])
        for c in A.before_event(conn, e.id).claims:
            if c.kind in ("unspoken_crush", "unrequited_love") and sorted(c.people) == pair:
                return round(c.gap, 3), "觀眾知道這份心意，當事人還不知道"
    return 0.0, ""


def checklist(conn: sqlite3.Connection, e: Ev, names: dict[str, str], situations: list[dict], options: Options = DEFAULT) -> SceneChecklist:
    """What this scene changed (see the module's note on the six kinds), read from the world's own deltas and the audience's view."""
    emo, rel, state = _deltas(conn, e, names)
    actor = e.truth.get("actor") or (e.people[0] if e.people else "")
    other = e.truth.get("target") or e.truth.get("loser") or next((p for p in e.people if p != actor), "")
    stage = classify(e)[0]
    hostile = stage in ("conflict", "irreversible") and other and other != actor
    mine = [s for s in situations if e.id in s["events"]]
    audience_only = any(s["kind"] in ("misbelief", "secret", "live_lie") for s in mine)
    kinds = []
    if state:
        kinds.append("state")
    if rel:
        kinds.append("relationship")
    if emo:
        kinds.append("emotion")
    if e.type == "goal_change":
        kinds.append("goal")
    if e.type in KNOWLEDGE:
        kinds.append("knowledge")
    if stage in ("irreversible", "change"):
        kinds.append("turn")
    adv, expectation = (0.0, "")
    if options.delta == "narrative":
        adv, expectation = _advantage(conn, e, names)
        if adv:
            kinds.append("expectation")
            audience_only = True
    progress = bool(emo or state or any(v >= PROGRESS_SHIFT for v, _ in rel) or e.type == "goal_change")
    return SceneChecklist(
        wants={names.get(actor, actor): _goal(conn, actor)} if actor and _goal(conn, actor) else {},
        obstructs=names.get(other, other) if hostile else "", knows=[names.get(p, p) for p in e.people],
        audience_only=audience_only, emotion=emo, relationship=[s for _, s in sorted(rel, reverse=True)[:4]], state=state[:4],
        leaves_question=max(mine, key=lambda s: s["potential"])["question"] if mine else "", changed=bool(kinds), delta_kinds=kinds,
        expectation=expectation, audience_advantage=adv, progress=progress)


def _tension(e: Ev, stage: str) -> float:
    from world.domains import style
    st = style(e.type)
    heat = st.heat if st is not None else 1
    dil = float((e.truth.get("dilemma") or {}).get("tension", 0.0))
    return round(max(0.0, min(1.0, 0.08 + 0.10 * STAGES.index(stage) + 0.05 * heat + 0.25 * dil + 0.15 * e.importance)), 3)


def _audience(e: Ev, options: Options = DEFAULT) -> list[str]:
    """Who saw it happen. The first version counted only those the event lists as witnesses; a vote is seen by those who vote, and a
    duel by those whose view of the two it moved."""
    seen = [p for p, role in e.participants if role == "witness"]
    if options.grammar == "v2":
        extra = list((e.truth.get("votes") or {}).keys()) + list((e.truth.get("gaps") or {}).keys())
        principals = {e.truth.get(k) for k in ("actor", "target", "winner", "loser")}
        seen += [p for p in extra if p not in seen and p not in principals]
    return seen


# -- the web-novel grammar ---------------------------------------------------------------------------------------------
def _new_state(conn: sqlite3.Connection, events: dict[int, Ev], p: dict, peak: Ev, after: list[Ev], names: dict[str, str]) -> GrammarStep:
    """What the reversal leaves behind: a new standing with others, a new want, a new opening. Read from the reversal and the days after;
    present only when there is evidence of at least one."""
    hero = p["protagonist"]
    _, rel, state = _deltas(conn, peak, names)
    standing = [s for _, s in sorted(rel, reverse=True) if f">{names.get(hero, hero)} " in s][:3]
    derived: dict = {}
    if standing:
        derived["standing"] = standing
    if any(s.startswith(("seat", "role", "skill")) for s in state):
        derived["state"] = [s for s in state if s.startswith(("seat", "role", "skill"))][:2]
    if after:
        derived["want"] = after[0].truth.get("text") or after[0].type
    try:
        from narrative.opportunity import detect
        nxt = next((o for o in detect(conn, p["day"] + 1) if o.protagonist == hero and not any(m.lack == "recovery" for m in o.missing)), None)
        if nxt is not None:
            derived["opening"] = {"kind": nxt.kind, "against": [names.get(x, x) for x in nxt.others[:1]], "lacks": [m.lack for m in nxt.missing]}
    except Exception:   # an opening is a bonus: its absence must not break a plan
        pass
    return GrammarStep("new_state", [e.id for e in after], bool(derived), "what the reversal leaves behind", derived)


def payoff_material(conn: sqlite3.Connection, events: dict[int, Ev], p: dict, options: Options = DEFAULT) -> tuple[Arc, list[GrammarStep]]:
    """A payoff and the steps behind it, drawn from what the world produced in the weeks before (nothing is added)."""
    hero, day = p["protagonist"], p["day"]
    peak = events[p["event_id"]]
    names = _names(conn)
    lo = (day - LOOKBACK) * 1440
    window = [e for e in events.values() if lo <= e.ts <= peak.ts and e.id != peak.id]

    belittled = [e for e in window if (e.type == "talk" and e.truth.get("tone") in ("cold", "hostile") and e.truth.get("target") == hero)
                 or (e.type == "duel" and e.truth.get("loser") == hero)][-2:]
    growth = [e for e in window if e.type in GROWTH and e.truth.get("actor") == hero][-2:]
    gathering = [e for e in window if e.type == "intervention" and e.truth.get("kind") in ("announce_gathering", "open_seat")][-1:]
    after = [e for e in events.values() if peak.ts < e.ts <= peak.ts + 2 * 1440 and e.truth.get("actor") == hero and (e.type in ("goal_change", "regret", "breakthrough")
             or (e.type == "reflection" and e.truth.get("shifted")))][:1]
    seen = _audience(peak, options)
    steps = [GrammarStep("belittled", [e.id for e in belittled], bool(belittled), "those who held them down"),
             GrammarStep("hidden_growth", [e.id for e in growth], bool(growth), "what they did where nobody looked"),
             GrammarStep("gathering", [e.id for e in gathering], bool(gathering) or len(seen) >= 3, "the place where it could be seen"),
             GrammarStep("reversal", [peak.id], True, p["kind"]),
             GrammarStep("bystanders", [peak.id] if seen else [], bool(seen), f"{len(seen)} saw it")]
    if options.grammar == "v2":
        steps.append(_new_state(conn, events, p, peak, after, names))
    else:
        steps.append(GrammarStep("new_state", [e.id for e in after], bool(after), "what they want now"))
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


@dataclass(frozen=True)
class Material:
    arc: Arc | None
    thread: object
    kind: str
    payoff: dict | None
    steps: list
    stagnant_skipped: int = 0       # threads the director ranked higher, in which nothing real had happened
    secondary: Arc | None = None    # the B story (ab_story)
    texture: Ev | None = None       # an ordinary moment of the A story's people, before its peak (ab_story)


def _threads(conn: sqlite3.Connection, day: int, shown, events: dict[int, Ev], names: dict[str, str], options: Options) -> tuple[list, int]:
    """The director's ranked threads, each with its arc, without the ones in which nothing real has happened."""
    from narrative.director import rank_threads, thread_arc
    skipped, out = 0, []
    for s, t in rank_threads(conn, day, shown):
        arc = thread_arc(t, events, set(shown))
        if options.stagnation and not any(_is_story(e) and real_progress(conn, e, names) for e in arc.events):
            skipped += 1
            continue
        out.append((s, t, arc))
    return out, skipped


def _principals(arc: Arc) -> set[str]:
    return {p for e in arc.events for p in e.people[:2]}


def _secondary(conn, candidates, a_arc: Arc, a_thread, events, names) -> Arc | None:
    """A second story that moves in the same days: the best thread of other people, with at most two of its scenes in which something happened."""
    mine = _principals(a_arc)
    for s, t, arc in candidates:
        if (a_thread is not None and t.thread_id == a_thread.thread_id) or _principals(arc) & mine:
            continue
        scenes = [e for e in arc.events if _is_story(e) and real_progress(conn, e, names)][-2:]
        if scenes:
            return Arc(tuple(scenes), scenes[-1], "thread")
    return None


def _texture(a_arc: Arc, shown, events: dict[int, Ev]) -> Ev | None:
    """An ordinary moment of the A story's people on its day, before its peak: warm words, a meal. Something the peak can be measured from."""
    mine = _principals(a_arc)
    used = {e.id for e in a_arc.events} | set(shown)
    pool = [e for e in events.values() if e.day == a_arc.peak.day and e.ts < a_arc.peak.ts and e.id not in used and _is_story(e)
            and classify(e)[0] == "daily" and len(e.people) >= 2 and set(e.people[:2]) & mine]
    return min(pool, key=lambda e: e.id) if pool else None


def material(conn: sqlite3.Connection, day: int, shown: set[int] | frozenset[int] = frozenset(), recent: tuple = (),
             options: Options = DEFAULT) -> Material:
    """Today's material: an unshown payoff of the last day first, then a choice against oneself, else the director's best thread that has
    really moved (and is not the pair of the last episodes, when there is another)."""
    from narrative import payoff as P
    events = load_events(conn)
    names = _names(conn)
    fresh = [p for p in P.payoffs(conn) if p["day"] >= day - 1 and p["event_id"] not in shown and p["earned"] >= PAYOFF_AT]
    candidates = None
    skipped = 0
    if fresh:
        p = max(fresh, key=lambda x: (x["earned"], x["event_id"]))
        arc, steps = payoff_material(conn, events, p, options)
        kind, thread, payoff = "payoff", None, p
    else:
        inner = inner_material(conn, events, day, shown)
        if inner is not None:
            arc, steps, kind, thread, payoff = inner, [], "inner", None, None
        else:
            candidates, skipped = _threads(conn, day, shown, events, names, options)
            if not candidates:
                return Material(None, None, "", None, [], skipped)
            pick = next(((s, t, a) for s, t, a in candidates if frozenset(p for i in t.event_ids if i in events for p in events[i].people[:2]) not in recent), candidates[0])
            arc, thread, kind, payoff, steps = pick[2], pick[1], "thread", None, []
    if not options.ab_story:
        return Material(arc, thread, kind, payoff, steps, skipped)
    if candidates is None:
        candidates, _ = _threads(conn, day, shown, events, names, options)
    return Material(arc, thread, kind, payoff, steps, skipped, _secondary(conn, candidates, arc, thread, events, names), _texture(arc, shown, events))


def choose_material(conn: sqlite3.Connection, day: int, shown: set[int] | frozenset[int] = frozenset(), recent: tuple = (),
                    options: Options = DEFAULT):
    """(arc, thread, kind, payoff, steps) for today (see `material`)."""
    m = material(conn, day, shown, recent, options)
    return m.arc, m.thread, m.kind, m.payoff, m.steps


# -- the plan ----------------------------------------------------------------------------------------------------------
def _question_type(q: str) -> str:
    """goal ("can they get X"), choice ("A or B"), revelation ("who will find out"), or open (a question that is none of these)."""
    if not q:
        return "open"
    if "還是" in q or "選" in q or "放棄" in q or "代價" in q:
        return "choice"
    if "誰" in q or "發現" in q or "真正" in q or "拿了" in q or "拆穿" in q or "揭" in q:
        return "revelation"
    if "能" in q or "接受" in q or "回得去" in q or "證明" in q or "成為" in q:
        return "goal"
    return "open"


def _regret(q: str) -> bool:
    return q.endswith("會後悔嗎？")      # a feeling to be predicted, not something anybody is after


def _core_question(conn, names, arc, thread, shown, situations, kind, payoff, inner, options: Options) -> str:
    n = lambda pid: names.get(pid, pid or "")  # noqa: E731
    if kind == "payoff":
        if payoff["kind"] == "face_slap":
            return f"{n(payoff['protagonist'])}被看輕了，能在眾人面前證明自己嗎？"
        if payoff["kind"] == "chosen":
            return f"{n(payoff['protagonist'])}的心意，會被{n(payoff.get('against'))}接受嗎？"
        return f"誰會成為「{n(payoff.get('seat')) if payoff.get('seat') else '那個位子'}」？"
    ids = set(arc.ids)
    mine = [s for s in situations if ids & set(s["events"]) and s["question"]]
    if inner:
        peak = max((e for e in arc.events if float((e.truth.get("dilemma") or {}).get("tension", 0.0)) >= INNER_AT),
                   key=lambda e: float(e.truth["dilemma"]["tension"]))
        d = peak.truth["dilemma"]
        if options.questions == "typed" and d.get("serves") and d.get("costs"):
            gave = "、".join(VALUE_WORDS.get(k, k) for k, _ in sorted(d["serves"].items(), key=lambda x: -x[1])[:2])
            lost = "、".join(VALUE_WORDS.get(k, k) for k, _ in sorted(d["costs"].items(), key=lambda x: -x[1])[:2])
            return f"{n(peak.truth.get('actor'))}要為了{gave}，付出{lost}的代價嗎？"
        dil = [s for s in mine if s["kind"] == "dilemma"]
        if dil:
            return max(dil, key=lambda s: s["potential"])["question"]
    if thread is not None:
        from narrative.knowledge import knowledge_of
        k = knowledge_of(conn, thread, set(shown))
        if k is not None and k.question and not (options.questions == "typed" and _regret(k.question)):
            return k.question
    pool = [s for s in mine if not (options.questions == "typed" and _regret(s["question"]))]
    if pool:
        return max(pool, key=lambda s: (s["potential"], s["day"]))["question"]
    peak = arc.peak
    who = [n(p) for p in peak.people[:2]]
    if len(who) == 2 and options.questions == "typed":
        a, b = peak.people[:2]
        r = conn.execute("SELECT trust, resentment FROM relationships WHERE actor_id = ? AND target_id = ?", (a, b)).fetchone()
        sour = r is not None and (r["trust"] < 0 or r["resentment"] > 0.2)
        return f"{who[0]}和{who[1]}會{'和好，還是徹底決裂' if sour else '更靠近，還是漸行漸遠'}？"      # a choice, from where the two stand now
    return f"{'和'.join(who)}會怎麼收場？" if len(who) == 2 else f"{who[0] if who else ''}接下來會怎麼做？"


def plan_episode(conn: sqlite3.Connection, arc: Arc, thread=None, shown: set[int] | frozenset[int] = frozenset(), day: int | None = None,
                 kind: str = "thread", payoff: dict | None = None, steps: list[GrammarStep] | None = None,
                 situations: list[dict] | None = None, options: Options = DEFAULT, secondary: Arc | None = None, texture: Ev | None = None) -> EpisodePlan:
    if situations is None:
        from narrative.dramaturgy import analyse
        situations = analyse(conn)["situations"]
    names = _names(conn)
    day = arc.peak.day if day is None else day
    grammar_ids = {i for s in (steps or []) for i in s.event_ids}
    beats: list[EpisodeBeat] = []
    extra = [(e, "B") for e in (secondary.events if secondary is not None else ())] + ([(texture, "texture")] if texture is not None else [])
    in_a = {x.id for x in arc.events}
    ordered = sorted([(e, "A") for e in arc.events] + [(e, w) for e, w in extra if e.id not in in_a], key=lambda x: x[0].id)
    for e, story in ordered:
        if not _is_story(e):
            continue
        stage, intent = classify(e)
        cl = checklist(conn, e, names, situations, options)
        if e.type in GROWTH and payoff is not None and e.truth.get("actor") == payoff["protagonist"]:
            cl = SceneChecklist(**{**cl.__dict__, "audience_only": True})   # the growth only the audience saw
        on_stage = bool(e.people)
        setup = options.keep_setup and e.id in grammar_ids and e.id != arc.peak.id    # (v1) a step of the web-novel line, kept though it changed nothing
        ordinary = story == "texture"                                                  # an ordinary moment is not meant to change anything
        shoot = on_stage and (cl.changed or setup or ordinary)
        reason = ("" if shoot and cl.changed else "texture: the ordinary, to measure the peak from" if shoot and ordinary else
                  "set-up of the line (changes nothing yet)" if shoot else "no one on stage" if not on_stage else "nothing changed")
        beats.append(EpisodeBeat(len(beats), [e.id], stage, _tension(e, stage), intent, [names.get(p, p) for p in e.people], cl, shoot, reason, story=story))
        wit = _audience(e, options)
        if shoot and story == "A" and intent in ("face_slap", "payoff", "confession") and len(wit) >= 2:
            react = SceneChecklist(knows=[names.get(p, p) for p in wit], changed=True, leaves_question="", delta_kinds=["relationship"],
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
    core = _core_question(conn, names, arc, thread, shown, situations, kind, payoff, inner, options)
    # what is left open: the new state after a payoff, else a live situation of these people that goes on beyond the episode
    last = max((e.day for e in arc.events), default=day)
    people = {p for e in arc.events for p in e.people[:2]}     # the principals
    hero = names.get(payoff["protagonist"], payoff["protagonist"]) if payoff else ""
    if kind == "payoff":
        ns = next((s for s in (steps or []) if s.step == "new_state" and s.present), None)
        opening = (ns.derived or {}).get("opening") if ns is not None else None
        if opening:
            ending = f"{hero}接下來要面對{'、'.join(opening['against']) or '下一個對手'}嗎？"
        elif ns is not None and (ns.derived or {}).get("want"):
            ending = f"{hero}接下來想要什麼？"
        else:
            ending = f"{NEXT_GOAL_LEAD}看輕{hero}的人是誰？"
    else:
        more = [s for s in situations if set(s["people"]) & people and (s["until"] or s["day"] + s.get("lasts", 1)) > last and s["question"] and s["question"] != core
                and not (set(s["events"]) <= ids) and not (options.questions == "typed" and _regret(s["question"]))]
        ending = max(more, key=lambda s: (s["potential"], s["day"]))["question"] if more else ""
    plan = EpisodePlan(1, day, kind, thread.thread_id if thread is not None else "", core, beats, curve, has_breath, inner, near,
                       {"strategy": strategy, "beat": reveal_beat}, ending, steps or [], bool(steps) and all(s.present for s in steps),
                       [b.index for b in beats if not b.shoot], bool(filmed), sorted(people),
                       _question_type(core) if options.questions == "typed" else "", asdict(options))
    return finalize(plan)


def plan_day(conn: sqlite3.Connection, day: int, shown: set[int] | frozenset[int] = frozenset(), situations: list[dict] | None = None,
             recent: tuple = (), options: Options = DEFAULT) -> EpisodePlan | None:
    """The episode for `day`, or None on a quiet day (nothing worth telling). `recent`: the people of the last episodes (frozensets)."""
    m = material(conn, day, shown, recent, options)
    if m.arc is None:
        return None
    return plan_episode(conn, m.arc, m.thread, shown, day, m.kind, m.payoff, m.steps, situations, options, m.secondary, m.texture)
