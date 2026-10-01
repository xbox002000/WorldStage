"""Work, as a domain pack (primitive life.work): a job wears on people or rewards them, and what they do about it
grows into stories nobody wrote: stress, a demand to stay late, praise that stings a rival, a quiet search for
something else, an offer to take or turn down.

Genre-free. A person has a job when their CharacterProfile has an occupation run by this domain: its workplace, its
superior (someone in the world, or an offstage name), its duty (the routine action that is the job: work in a town,
train in a sect) and its words (上班/加班/辭職 in a town, 練功/加練/離開師門 in a sect).

Life state (world_vars, per worker): work.stress, work.satisfaction (0..1), work.looked (searches so far),
work.offer (day an offer came, -1 none), work.employed (1/0), work.overtime (the day one was kept late, -1).

After the duty each day: the job wears (stress), and the superior may keep them late or praise them in front of the
others. A fight at the workplace is stress for both. At night stress eases and satisfaction settles towards what the
stress allows. When stress is high and satisfaction low, a goal forms: leave the job. Then looking elsewhere (quiet,
but one can be seen), an offer, and a choice with a cost either way.
"""
from __future__ import annotations

import json
import sqlite3

from contracts.claim import Claim
from contracts.recipe import MechanicPrimitive as P
from world.attention import QUIET, noticers, var, world_seed
from world.domains.base import ActionSpec, ClaimAct, Domain, EventStyle, add_changes
from world.events import Change, ClaimSpec, EventSpec, MemorySpec
from world.helpers import RelDeltas, person
from world.intent import Intent
from world.rng import rng as make_rng
from world.state import WorldError

WORDS = {"work": "上班", "superior": "主管", "overtime": "加班", "praise": "被誇獎", "quit": "辭職", "look": "找別的工作",
         "offer": "接到別家的邀請", "accept": "接受了邀請", "decline": "拒絕了邀請", "lapse": "邀請過期了"}
WEAR = 0.03             # stress a day of work adds
OVERTIME = 0.14         # chance a day ends with being kept late (more when jobs are insecure)
PRAISE = 0.12           # chance of being praised in front of the others
OVERTIME_STRESS = 0.12
PRAISE_SATISFACTION = 0.12
CLASH_STRESS = 0.04
REST = 0.05             # stress a night's sleep takes away
SETTLE = 0.15           # how fast satisfaction settles towards what stress allows
LEAVE_STRESS, LEAVE_SATISFACTION = 0.6, 0.42   # a goal to leave forms past both
STAY_SATISFACTION = 0.62                       # ... and is given up above this
OFFER_AFTER, OFFER_CHANCE, OFFER_DAYS = 3, 0.25, 3   # an offer is rare: a 30-day trial had 7 of 15 workers quit
INERTIA = 0.3           # leaving is a leap: it has to beat staying by this much
# Goals are sticky: a wish to leave is pursued in bouts, not every day, and it changes only when something happens.
#   leave_job --offer--> weigh_offer --decline--> stay_on --(stress back at the limit after a while)--> leave_job
#                                    --accept---> (resigned: completed)
#   leave_job --four searches, nothing--> earn_recognition (the ambitious: prove oneself here) | stay_on
#   earn_recognition --praised--> completed;  stay_on --satisfied again--> completed
SEARCH_GAP = 2          # days between two searches
SEARCHES_BEFORE_SETBACK = 4
CALM_DAYS = 7           # after deciding to stay, it takes this long before leaving is thought of again
RELAPSE_STRESS = 0.75
RECOGNITION_DAYS = 10
WORK_GOALS = ("leave_job", "weigh_offer", "stay_on", "earn_recognition")
EVENING = (900, 1200)   # routine moves in this window are dropped on a day one is kept late
KEYS = ("stress", "satisfaction", "looked", "offer", "employed", "overtime")


def occupation(conn: sqlite3.Connection, pid: str):
    """The job this domain runs for someone (their profile's occupation), or None."""
    from world.profiles import profile
    p = profile(conn, pid)
    return p.occupation if p is not None and p.occupation is not None and p.occupation.domain == "work" else None


def employed(conn: sqlite3.Connection, pid: str) -> bool:
    return occupation(conn, pid) is not None and var(conn, f"work.employed.{pid}", 0.0) >= 1.0


def words(conn: sqlite3.Connection, pid: str) -> dict[str, str]:
    occ = occupation(conn, pid)
    out = dict(WORDS)
    if occ is not None:
        out.update(occ.words)
        if occ.superior and "superior" not in occ.words:
            out["superior"] = _name(conn, occ.superior)
    return out


def _name(conn: sqlite3.Connection, pid: str) -> str:
    row = conn.execute("SELECT name FROM people WHERE id = ?", (pid,)).fetchone()
    return row[0] if row else pid


def superior_person(conn: sqlite3.Connection, pid: str) -> str | None:
    """The superior, if they are someone in the world (a master, a landlady), else None (an offstage boss)."""
    occ = occupation(conn, pid)
    if occ is None or not occ.superior:
        return None
    return occ.superior if conn.execute("SELECT 1 FROM people WHERE id = ?", (occ.superior,)).fetchone() else None


def colleagues(conn: sqlite3.Connection, pid: str) -> list[str]:
    occ = occupation(conn, pid)
    if occ is None:
        return []
    out = []
    for (other,) in conn.execute("SELECT person_id FROM character_profiles WHERE person_id <> ? ORDER BY person_id", (pid,)):
        o = occupation(conn, other)
        if o is not None and o.place == occ.place and employed(conn, other):
            out.append(other)
    sup = superior_person(conn, pid)
    return out + ([sup] if sup and sup not in out else [])


def _v(conn: sqlite3.Connection, key: str, pid: str, default: float = 0.0) -> float:
    return var(conn, f"work.{key}.{pid}", default)


def _set(conn: sqlite3.Connection, key: str, pid: str, target: float, lo: float = -1.0, hi: float = 1.0) -> Change | None:
    cur = var(conn, f"work.{key}.{pid}", None)
    if cur is None:
        return None
    d = round(min(hi, max(lo, target)) - cur, 6)
    return Change("var", f"work.{key}.{pid}", "value", delta=d) if d else None


def _add(conn: sqlite3.Connection, key: str, pid: str, delta: float) -> Change | None:
    return _set(conn, key, pid, _v(conn, key, pid) + delta, 0.0, 1.0 if key in ("stress", "satisfaction") else 1e9)


def _value(conn: sqlite3.Connection, pid: str, key: str, default: float = 0.5) -> float:
    from world.profiles import profile
    p = profile(conn, pid)
    return p.values.get(key, default) if p is not None else default


def _bond(conn: sqlite3.Connection, pid: str) -> float:
    """How attached someone is to the people they work with (mean affection)."""
    cs = colleagues(conn, pid)
    if not cs:
        return 0.0
    rows = [conn.execute("SELECT affection FROM relationships WHERE actor_id = ? AND target_id = ?", (pid, c)).fetchone()
            for c in cs]
    vals = [r[0] for r in rows if r]
    return sum(vals) / len(vals) if vals else 0.0


def _days_since_search(conn: sqlite3.Connection, pid: str, now: int) -> int:
    row = conn.execute("SELECT MAX(timestamp) FROM events WHERE type = 'job_search' AND json_extract(truth, '$.actor') = ?",
                       (pid,)).fetchone()
    return 10 ** 6 if row[0] is None else (now - row[0]) // 1440


def _searches_since(conn: sqlite3.Connection, pid: str, day: int) -> int:
    return conn.execute("SELECT COUNT(*) FROM events WHERE type = 'job_search' AND json_extract(truth, '$.actor') = ? "
                        "AND timestamp >= ?", (pid, day * 1440)).fetchone()[0]


def _open_work_goal(conn: sqlite3.Connection, pid: str):
    from world.goals import goals_of
    return next((g for g in goals_of(conn, pid) if g["kind"] in WORK_GOALS), None)


def _free_schedule(conn: sqlite3.Connection, pid: str) -> dict:
    """Someone's day once the job is gone: the duty and the trips to the workplace give way to a social place."""
    occ = occupation(conn, pid)
    sched = json.loads(conn.execute("SELECT schedule FROM people WHERE id = ?", (pid,)).fetchone()[0])
    social = conn.execute("SELECT id FROM locations WHERE tags LIKE '%\"social\"%' AND id <> ? ORDER BY id LIMIT 1",
                          (occ.place if occ else "",)).fetchone()
    out = {}
    for k, v in sched.items():
        if occ is not None and v == occ.duty:
            continue
        if occ is not None and v == f"move:{occ.place}":
            if social:
                out[k] = f"move:{social[0]}"
            continue
        out[k] = v
    return out


# -- actions --------------------------------------------------------------------------------------------------------
def _validate_look(conn: sqlite3.Connection, it: Intent, actor: sqlite3.Row) -> None:
    occ = occupation(conn, it.actor)
    if occ is None or not employed(conn, it.actor):
        raise WorldError("no job to leave")
    if actor["location_id"] == occ.place:
        raise WorldError("nobody looks for another job at their desk")
    today = (conn.execute("SELECT COALESCE(MAX(timestamp), 0) FROM events").fetchone()[0]) // 1440
    if conn.execute("SELECT 1 FROM events WHERE type = 'job_search' AND json_extract(truth, '$.actor') = ? AND timestamp >= ?",
                    (it.actor, today * 1440)).fetchone():
        raise WorldError("already looked today")


def _resolve_look(conn: sqlite3.Connection, it: Intent, now: int, trigger: str) -> EventSpec:
    a = it.actor
    occ = occupation(conn, a)
    here = person(conn, a)["location_id"]
    w = words(conn, a)
    seen = noticers(conn, here, now, f"job_search:{a}", QUIET, a)
    from world.claims import describe_claim, labels
    c = Claim(a, "seek_job", occ.place)
    text = describe_claim(c, labels(conn))
    changes = [x for x in (_add(conn, "looked", a, 1.0),) if x]
    return EventSpec(
        timestamp=now, type="job_search", trigger_type=trigger, location_id=here, importance=0.45,
        truth={"actor": a, "object": occ.place, "text": f"偷偷{w['look']}", "reason": it.reason, "source": it.source},
        participants=[(a, "actor")] + [(p, "witness") for p in seen], changes=changes,
        memories=[MemorySpec(a, text, 1.0, claim=c)] + [MemorySpec(p, text, 0.7, claim=c) for p in seen],
        claims=[ClaimSpec(c)])


def _stakes_look(conn: sqlite3.Connection, it: Intent) -> dict[str, float]:
    return {"freedom": 0.5, "loyalty": -0.4}


def _stakes_answer(accept: bool):
    def stakes(conn: sqlite3.Connection, it: Intent) -> dict[str, float]:
        bond = max(0.0, _bond(conn, it.actor))
        leave = {"freedom": 0.7, "ambition": 0.5, "security": -0.6, "belonging": -0.4 - 0.6 * bond, "loyalty": -0.5}
        return leave if accept else {k: round(-0.8 * v, 3) for k, v in leave.items()}
    return stakes


def _validate_offer(conn: sqlite3.Connection, it: Intent, actor: sqlite3.Row) -> None:
    if not employed(conn, it.actor) or _v(conn, "offer", it.actor, -1.0) < 0:
        raise WorldError("no offer to answer")


def _resolve_answer(accept: bool):
    def resolve(conn: sqlite3.Connection, it: Intent, now: int, trigger: str) -> EventSpec:
        a = it.actor
        occ = occupation(conn, a)
        w = words(conn, a)
        here = person(conn, a)["location_id"]
        changes = [x for x in (_set(conn, "offer", a, -1.0),) if x]
        claims, memories = [], []
        from world.claims import describe_claim, labels
        if accept:
            c = Claim(a, "resign", occ.place)
            changes += [x for x in (_set(conn, "employed", a, 0.0), _set(conn, "stress", a, 0.1, 0.0, 1.0)) if x]
            changes.append(Change("person", a, "schedule", value=json.dumps(_free_schedule(conn, a), sort_keys=True)))
            d = RelDeltas()
            sup = superior_person(conn, a)
            if sup:  # a master left behind takes it hard
                d.add(sup, a, "trust", -0.2)
                d.add(sup, a, "affection", -0.1)
            changes += d.changes(conn)
            names = labels(conn)
            claims.append(ClaimSpec(c))
            memories += [MemorySpec(p, describe_claim(c, names), 0.9, claim=c) for p in [a] + colleagues(conn, a)]
            text, imp, etype = f"{w['accept']}，{w['quit']}了", 0.9, "resign"
        else:
            changes += [x for x in (_add(conn, "satisfaction", a, 0.08), _set(conn, "looked", a, 0.0, 0.0, 1e9)) if x]
            text, imp, etype = f"{w['decline']}，決定留下", 0.6, "decline_offer"
        return EventSpec(timestamp=now, type=etype, trigger_type=trigger, location_id=here, importance=imp,
                         truth={"actor": a, "object": occ.place, "text": text, "reason": it.reason, "source": it.source},
                         participants=[(a, "actor")], changes=changes, memories=memories, claims=claims)
    return resolve


class Work(Domain):
    id = "work"
    title = "工作"
    primitives = (P("life.work", "economy", "a job: stress and satisfaction, a superior's demands and praise, looking "
                    "elsewhere, an offer to take or turn down", ["schedule", "goals"], cost=0),)
    actions = {
        "look_for_work": ActionSpec("look_for_work", _validate_look, _resolve_look, label="偷偷找別的工作",
                                    stakes=_stakes_look),
        "accept_offer": ActionSpec("accept_offer", _validate_offer, _resolve_answer(True), label="接受邀請，離開現在的工作",
                                   stakes=_stakes_answer(True)),
        "decline_offer": ActionSpec("decline_offer", _validate_offer, _resolve_answer(False), label="拒絕邀請，留下來",
                                    stakes=_stakes_answer(False)),
    }
    acts = {"seek_job": ClaimAct("work", "place", "在找{o}以外的工作", "沒有在找別的工作", belief_effect=-0.05),
            "resign": ClaimAct("work", "place", "離開了{o}", "沒有離開{o}")}
    styles = {
        "overtime": EventStyle(caption="{text}", lines=("今天留下來{overtime}。", "事情還沒做完，別走。"), social=True, say=2.5,
                               heat=2, opens_scene=True, functions=("escalate",)),
        "praise": EventStyle(caption="{text}", lines=("做得好。", "大家都該學學。"), social=True, say=2.5, heat=0,
                             functions=("connect",)),
        "job_search": EventStyle(caption="{text}", functions=("setup",)),
        "job_offer": EventStyle(caption="{text}", first_time=True, functions=("complicate",)),
        "resign": EventStyle(caption="{text}", first_time=True, heat=2, functions=("payoff",)),
        "decline_offer": EventStyle(caption="{text}", functions=("reversal",)),
        "offer_lapsed": EventStyle(caption="{text}"),
    }
    goal_text = {"leave_job": "離開{o}", "weigh_offer": "考慮要不要離開{o}", "stay_on": "留在{o}撐下去",
                 "earn_recognition": "在{o}做出成績"}
    situation_kinds = {"choice": "兩難的選擇"}

    def initial_vars(self, pid: str, profile) -> dict[str, float]:
        if profile is None or profile.occupation is None or profile.occupation.domain != "work":
            return {}
        ambition = profile.values.get("ambition", 0.5)
        return {f"work.stress.{pid}": round(0.25 + 0.1 * ambition, 3), f"work.satisfaction.{pid}": 0.6,
                f"work.looked.{pid}": 0.0, f"work.offer.{pid}": -1.0, f"work.employed.{pid}": 1.0,
                f"work.overtime.{pid}": -1.0}

    # -- the rule agent --------------------------------------------------------------------------------------------
    def options(self, conn: sqlite3.Connection, actor: str, now: int, ctx: dict) -> list:
        if not employed(conn, actor):
            return []
        occ = occupation(conn, actor)
        stress, sat = _v(conn, "stress", actor), _v(conn, "satisfaction", actor, 0.6)
        out = []
        from world.goals import find
        leaving = find(conn, actor, "leave_job", "", occ.place)
        if ctx["location"] != occ.place and leaving is not None and _days_since_search(conn, actor, now) >= SEARCH_GAP:
            out.append((-0.3 + 0.7 * stress + 0.6 * (1 - sat) - 0.2 * _value(conn, actor, "security"),
                        Intent(actor, "look_for_work", reason="volition")))
        if _v(conn, "offer", actor, -1.0) >= 0:
            bond = _bond(conn, actor)
            v = lambda k: _value(conn, actor, k)  # noqa: E731
            out.append((0.2 + 0.9 * (1 - sat) + 0.5 * stress + 0.3 * v("freedom") + 0.3 * v("ambition") - 0.6 * bond
                        - 0.3 * v("security") - 0.3 * v("loyalty") - INERTIA, Intent(actor, "accept_offer", reason="volition")))
            out.append((0.3 + 0.7 * sat + 0.6 * bond + 0.3 * v("loyalty") + 0.3 * v("security"),
                        Intent(actor, "decline_offer", reason="volition")))
        return out

    def lean(self, conn: sqlite3.Connection, goal: sqlite3.Row, it: Intent) -> float | None:
        if goal["kind"] == "leave_job":
            return {"look_for_work": 0.9, "accept_offer": 0.6}.get(it.action)
        return None

    # -- the world -------------------------------------------------------------------------------------------------
    def effects(self, conn: sqlite3.Connection, spec: EventSpec, primitives: set[str]) -> EventSpec:
        """A day of the job wears on one; a fight at the workplace is stress for both."""
        t = spec.truth
        pid = t.get("actor")
        occ = occupation(conn, pid) if pid else None
        if occ is not None and spec.type == occ.duty and spec.location_id == occ.place and employed(conn, pid):
            c = _add(conn, "stress", pid, WEAR)
            return add_changes(conn, spec, [c]) if c else spec
        if spec.type != "talk" or t.get("tone") != "hostile":
            return spec
        extra = []
        for pid in (t.get("actor"), t.get("target")):
            occ = occupation(conn, pid) if pid else None
            if occ is not None and occ.place == spec.location_id and employed(conn, pid):
                c = _add(conn, "stress", pid, CLASH_STRESS)
                if c:
                    extra.append(c)
        return add_changes(conn, spec, extra) if extra else spec

    def after_event(self, conn: sqlite3.Connection, event_id: int) -> list[EventSpec]:
        row = conn.execute("SELECT * FROM events WHERE event_id = ?", (event_id,)).fetchone()
        t = json.loads(row["truth"])
        pid = t.get("actor")
        if row["type"] == "job_search" and pid:
            # an offer moves the goal on (job_offer is revised in turn); only a search that comes to nothing counts
            # against it. Never both: two goal events built at once would each read the slot before the other wrote it
            return self._maybe_offer(conn, row, pid) or self._revise_goals(conn, row, t)
        if row["type"] in ("job_offer", "decline_offer", "praise") and pid:
            return self._revise_goals(conn, row, t)
        if not pid or not employed(conn, pid):
            return []
        occ = occupation(conn, pid)
        if row["type"] != occ.duty or row["location_id"] != occ.place:
            return []
        return self._after_duty(conn, row, pid, occ)

    def _revise_goals(self, conn: sqlite3.Connection, row: sqlite3.Row, t: dict) -> list[EventSpec]:
        """A goal changes only when something happens: an offer, a refusal, being praised, searching in vain."""
        from world.goals import GoalWriter, find
        day = row["timestamp"] // 1440
        w = GoalWriter(conn, row["timestamp"], row["event_id"])
        if row["type"] == "praise":
            pid = t.get("worker") or t.get("actor")
            g = find(conn, pid, "earn_recognition")
            if g is not None:
                w.status(g, "completed", "被看見了", day)
            return w.out
        pid = t["actor"]
        occ = occupation(conn, pid)
        if occ is None:
            return []
        leaving = find(conn, pid, "leave_job", "", occ.place)
        if row["type"] == "job_offer":
            w.form(pid, "weigh_offer", "", occ.place, 0.9, day, "有一份邀請擺在眼前", parent=leaving)
        elif row["type"] == "decline_offer":
            weighing = find(conn, pid, "weigh_offer", "", occ.place)
            bond, sec, loy = _bond(conn, pid), _value(conn, pid, "security"), _value(conn, pid, "loyalty")
            why = max((bond, "捨不得這裡的人"), (sec, "怕失去安穩"), (loy, "不想背棄"))[1]
            w.form(pid, "stay_on", "", occ.place, 0.6, day, f"決定留下：{why}", parent=weighing)
        elif row["type"] == "job_search" and leaving is not None and _v(conn, "offer", pid, -1.0) < 0:
            if _searches_since(conn, pid, leaving["since_day"]) >= SEARCHES_BEFORE_SETBACK:
                if _value(conn, pid, "ambition") >= 0.5:
                    w.form(pid, "earn_recognition", "", occ.place, 0.6, day, "找不到出路，那就在這裡證明自己", parent=leaving)
                else:
                    w.form(pid, "stay_on", "", occ.place, 0.5, day, "找不到出路，只好留下", parent=leaving)
        return w.out

    def _after_duty(self, conn: sqlite3.Connection, row: sqlite3.Row, pid: str, occ) -> list[EventSpec]:
        now, day, place = row["timestamp"], row["timestamp"] // 1440, row["location_id"]
        w = words(conn, pid)
        sup = superior_person(conn, pid)
        present = {r[0] for r in conn.execute("SELECT id FROM people WHERE location_id = ? AND status = 'active'", (place,))}
        r = make_rng(world_seed(conn), now, pid, "work_day").random()
        insecure = 1.0 - var(conn, "job_security", 1.0)
        if (not occ.superior) or (sup and sup not in present):
            kind = None  # no one to keep them late or praise them
        elif r < OVERTIME + 0.2 * insecure:
            kind = "overtime"
        elif r < OVERTIME + 0.2 * insecure + PRAISE + 0.1 * self._striving(conn, pid) and not conn.execute(
                "SELECT 1 FROM events WHERE type = 'praise' AND location_id = ? AND timestamp >= ?", (place, day * 1440)).fetchone():
            kind = "praise"
        else:
            kind = None
        if kind is None:
            return []
        actor, target = (sup, pid) if sup else (pid, "")
        others = sorted(present - {pid, sup or ""})
        if kind == "overtime":
            changes = [x for x in (_add(conn, "stress", pid, OVERTIME_STRESS), _add(conn, "satisfaction", pid, -0.06),
                                           _set(conn, "overtime", pid, float(day), -1.0, 1e9)) if x]
            text = f"被{w['superior']}要求{w['overtime']}"
            imp, emo = 0.35, "uneasy"
        else:
            changes = [x for x in (_add(conn, "satisfaction", pid, PRAISE_SATISFACTION), _add(conn, "stress", pid, -0.05)) if x]
            d = RelDeltas()
            for o in others:  # praise in front of a rival stings the rival
                rv = conn.execute("SELECT rivalry FROM relationships WHERE actor_id = ? AND target_id = ?", (o, pid)).fetchone()
                has_goal = conn.execute("SELECT 1 FROM goals WHERE person_id = ? AND target = ? AND kind IN ('outshine', 'surpass') "
                                        "AND status IN ('active', 'formed', 'blocked')", (o, pid)).fetchone()
                if has_goal or (rv and rv[0] > 0.2):
                    d.add(o, pid, "rivalry", 0.06)
            changes += d.changes(conn)
            text = f"被{w['superior']}當眾誇獎"
            imp, emo = 0.4, "happy"
        if person(conn, pid)["emotion"] != emo:
            changes.append(Change("person", pid, "emotion", value=emo))
        return [EventSpec(timestamp=now, type=kind, trigger_type="rule", location_id=place, importance=imp,
                          truth={"actor": actor, "target": target, "worker": pid, "text": text, "overtime": w["overtime"]},
                          participants=[(actor, "actor")] + ([(target, "target")] if target else []) + [(o, "witness") for o in others],
                          changes=changes, memories=[MemorySpec(p, f"{_name(conn, pid)}{text}", 0.9) for p in [pid] + others])]

    @staticmethod
    def _striving(conn: sqlite3.Connection, pid: str) -> bool:
        from world.goals import find
        return find(conn, pid, "earn_recognition") is not None

    def _maybe_offer(self, conn: sqlite3.Connection, row: sqlite3.Row, pid: str) -> list[EventSpec]:
        if _v(conn, "looked", pid) < OFFER_AFTER or _v(conn, "offer", pid, -1.0) >= 0:
            return []
        if make_rng(world_seed(conn), row["timestamp"], pid, "job_offer").random() >= OFFER_CHANCE:
            return []
        w = words(conn, pid)
        changes = [x for x in (_set(conn, "offer", pid, float(row["timestamp"] // 1440), -1.0, 1e9),) if x]
        return [EventSpec(timestamp=row["timestamp"], type="job_offer", trigger_type="rule", location_id=row["location_id"],
                          importance=0.6, parent_event_id=row["event_id"], truth={"actor": pid, "text": w["offer"]},
                          participants=[(pid, "actor")], changes=changes,
                          memories=[MemorySpec(pid, f"我{w['offer']}", 1.0)])]

    def scripted(self, conn: sqlite3.Connection, it: Intent, now: int) -> Intent | None:
        """Kept late: the evening's routine trips wait (going home at night does not)."""
        if it.action != "move" or not employed(conn, it.actor):
            return it
        if _v(conn, "overtime", it.actor, -1.0) == now // 1440 and EVENING[0] <= now % 1440 < EVENING[1]:
            return None
        return it

    def overnight(self, conn: sqlite3.Connection, pid: str, now: int) -> list[Change]:
        if not employed(conn, pid):
            return []
        stress = max(0.0, _v(conn, "stress", pid) - REST)
        sat = _v(conn, "satisfaction", pid, 0.6)
        settled = sat + SETTLE * ((0.75 - 0.6 * stress) - sat)
        return [x for x in (_set(conn, "stress", pid, stress, 0.0, 1.0), _set(conn, "satisfaction", pid, settled, 0.0, 1.0)) if x]

    def nightly(self, conn: sqlite3.Connection, day: int, now: int) -> list[EventSpec]:
        """Goals born of how the job is going, and offers left unanswered."""
        from world.goals import GoalWriter, find
        w = GoalWriter(conn, now, None)
        out = []
        for (pid,) in conn.execute("SELECT person_id FROM character_profiles ORDER BY person_id").fetchall():
            if not employed(conn, pid):
                continue
            occ = occupation(conn, pid)
            stress, sat = _v(conn, "stress", pid), _v(conn, "satisfaction", pid, 0.6)
            open_goal = _open_work_goal(conn, pid)
            settled = conn.execute(  # a work goal that just ended (praised, resolved to stay) gives a week's peace
                "SELECT 1 FROM events WHERE type = 'goal_change' AND json_extract(truth, '$.actor') = ? AND "
                f"json_extract(truth, '$.kind') IN ({','.join('?' * len(WORK_GOALS))}) AND "
                "json_extract(truth, '$.to') IN ('completed', 'abandoned') AND timestamp >= ? LIMIT 1",
                (pid, *WORK_GOALS, (day - CALM_DAYS) * 1440)).fetchone()
            if open_goal is None and not settled and stress >= LEAVE_STRESS and sat <= LEAVE_SATISFACTION:
                again = conn.execute("SELECT 1 FROM events WHERE type = 'goal_change' AND json_extract(truth, '$.actor') = ? "
                                     "AND json_extract(truth, '$.kind') = 'leave_job' LIMIT 1", (pid,)).fetchone()
                w.form(pid, "leave_job", "", occ.place, round(0.4 + 0.5 * stress, 3), day,
                       ("又" if again else "") + f"想走了：壓力{stress:.2f}，滿意度{sat:.2f}")
            elif open_goal is not None and open_goal["kind"] == "stay_on" and day - open_goal["since_day"] >= CALM_DAYS \
                    and stress >= RELAPSE_STRESS:
                w.form(pid, "leave_job", "", occ.place, round(0.4 + 0.5 * stress, 3), day, "撐不下去了", parent=open_goal)
            offer = _v(conn, "offer", pid, -1.0)
            if offer >= 0 and day - offer >= OFFER_DAYS:
                weighing = find(conn, pid, "weigh_offer")
                if weighing is not None:
                    w.status(weighing, "abandoned", "拖到邀請過期了", day)
                ch = _set(conn, "offer", pid, -1.0, -1.0, 1e9)
                out.append(EventSpec(timestamp=now, type="offer_lapsed", trigger_type="rule", importance=0.3,
                                     truth={"actor": pid, "text": words(conn, pid)["lapse"]}, participants=[(pid, "actor")],
                                     changes=[ch] if ch else []))
        return w.out + out

    def review_goal(self, conn: sqlite3.Connection, goal: sqlite3.Row, day: int) -> tuple[str, str] | None:
        if goal["kind"] not in WORK_GOALS:
            return None
        pid, kind, age = goal["person_id"], goal["kind"], day - goal["since_day"]
        if occupation(conn, pid) is not None and not employed(conn, pid):
            return ("completed", "離開了") if kind in ("leave_job", "weigh_offer") else ("abandoned", "已經離開了")
        sat = _v(conn, "satisfaction", pid, 0.6)
        if kind == "leave_job" and sat >= STAY_SATISFACTION:
            return "abandoned", "好像也沒那麼糟"
        if kind == "stay_on" and sat >= STAY_SATISFACTION:
            return "completed", "日子過得去了"
        if kind == "earn_recognition" and age >= RECOGNITION_DAYS:
            return "abandoned", "沒人看見"
        return None

    def situations(self, conn: sqlite3.Connection, names: dict) -> list[dict]:
        """The drama of work: a search kept from the people one works with, an offer that costs either way, the day
        one leaves or stays, and a wish to leave that crosses someone else's wish about them."""
        from world.domains.base import situation
        end = (conn.execute("SELECT MAX(timestamp) FROM events").fetchone()[0] or 0) // 1440
        out = []
        n = lambda p: names.get(p, p)  # noqa: E731
        closed = {}  # person -> (day, event) they left or stayed
        for eid, ts, etype, truth in conn.execute("SELECT event_id, timestamp, type, truth FROM events WHERE type IN "
                                                   "('resign', 'decline_offer', 'offer_lapsed') ORDER BY event_id"):
            t = json.loads(truth)
            closed.setdefault(t["actor"], []).append((ts // 1440, eid, etype, t.get("text", "")))
        # a quiet search, and who is in the dark
        for pid, first, eid, count in conn.execute(
                "SELECT json_extract(truth, '$.actor'), MIN(timestamp), MIN(event_id), COUNT(*) FROM events "
                "WHERE type = 'job_search' GROUP BY json_extract(truth, '$.actor') ORDER BY 1").fetchall():
            occ = occupation(conn, pid)
            if occ is None:
                continue
            knowers = {r[0] for r in conn.execute("SELECT m.observer_id FROM memories m JOIN claims c USING (claim_id) "
                                                  "WHERE c.act = 'seek_job' AND c.subject = ?", (pid,))}
            dark = [c for c in colleagues(conn, pid) if c not in knowers]
            until = closed.get(pid, [(None,)])[0][0]
            if dark:
                out.append(situation("secret", 0.55, first // 1440, [pid] + dark,
                                     f"{n(pid)}{words(conn, pid)['look']}（{count} 次）；{'、'.join(n(d) for d in dark)}不知道",
                                     f"{n(dark[0])}會發現{n(pid)}想走嗎？", [eid], build=count / 4,
                                     stakes=0.5 + 0.3 * max(0.0, _bond(conn, pid)), until=until, lasts=end - first // 1440))
        # an offer: a choice with a cost either way
        for eid, ts, truth in conn.execute("SELECT event_id, timestamp, truth FROM events WHERE type = 'job_offer' ORDER BY event_id"):
            pid = json.loads(truth)["actor"]
            day = ts // 1440
            after = [c for c in closed.get(pid, []) if c[0] >= day]
            cs = colleagues(conn, pid)
            out.append(situation("choice", 0.6, day, [pid] + cs[:3],
                                 f"{n(pid)}{words(conn, pid)['offer']}：接受就要離開{'、'.join(n(c) for c in cs[:3]) or '這裡'}，"
                                 f"拒絕就得繼續撐下去",
                                 f"{n(pid)}會走嗎？", [eid] + ([after[0][1]] if after else []), stakes=0.8,
                                 until=after[0][0] if after else None, lasts=end - day))
        # the day one leaves, or stays
        for pid, items in closed.items():
            for day, eid, etype, text in items:
                if etype == "offer_lapsed":
                    continue
                sup = superior_person(conn, pid)
                other = sup or (colleagues(conn, pid) or [""])[0]
                q = f"{n(other)}怎麼面對{n(pid)}的離開？" if etype == "resign" else f"{n(pid)}為什麼留下來？"
                out.append(situation("turning_point", 0.45, day, [pid] + ([other] if other else []), f"{n(pid)}{text}", q,
                                     [eid], stakes=0.8 if etype == "resign" else 0.6))
        # wanting to leave, while someone wants something of them
        for g in conn.execute("SELECT person_id, object FROM goals WHERE kind = 'leave_job' AND status IN ('active', 'formed', 'blocked')").fetchall():
            for o in conn.execute("SELECT person_id, kind FROM goals WHERE target = ? AND kind IN ('befriend', 'reconcile', 'outshine', "
                                  "'surpass', 'repay') AND status IN ('active', 'formed', 'blocked')", (g[0],)).fetchall():
                what = {"befriend": "和他做朋友", "reconcile": "和他和好", "outshine": "贏過他", "surpass": "贏過他", "repay": "向他討債"}[o[1]]
                out.append(situation("goal_clash", 0.5, end, [g[0], o[0]], f"{n(g[0])}想離開{n(g[1])}，而{n(o[0])}想{what}",
                                     f"{n(o[0])}來得及嗎？", [], stakes=0.7))
        return out

    def describe(self, conn: sqlite3.Connection, pid: str) -> dict:
        occ = occupation(conn, pid)
        if occ is None:
            return {}
        return {"工作": occ.role + ("" if employed(conn, pid) else "（已離開）"), "壓力": round(_v(conn, "stress", pid), 2),
                "滿意度": round(_v(conn, "satisfaction", pid, 0.6), 2),
                "邀請": "有，還沒回覆" if _v(conn, "offer", pid, -1.0) >= 0 else "—"}
