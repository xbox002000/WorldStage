"""Dramaturgy v0: where is the drama in what really happened? An offline, read-only analysis of a world.

It never writes the world and never invents: every situation it finds is built from events, claims, memories,
relationships and goals, and names the event ids it stands on. What it finds are dramatic *resources* — the things a
writer would build a scene or an episode on:

  secret          someone did something to someone else, and the one it concerns does not know
  misbelief       someone believes something about a person that world truth contradicts (irony: we know, they do not)
  live_lie        a lie, distortion or omission that nobody has exposed yet
  near_miss       it almost came out: a confrontation that proved nothing, a denial that held, the secret's keeper and
                  the one it is kept from talking in the same room
  contradiction   what someone does against what they are or feel: warm words to someone they distrust (subtext:
                  hiding hostility), cold words to someone they are fond of (subtext: "I care"), an honest person lying
  goal_clash      two people whose open goals cannot both come true
  turning_point   a relationship crossing from trust to distrust, or back

    python -m narrative.dramaturgy out/life60.db [--out report.json]

Each situation gets a potential (0..1) from its kind, how long it has been building, how close the people are, and
what is at stake, and a dramatic question ("will Mei find out Yun has her ring?").
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

from contracts.claim import AFFIRM, FALSE, PARTIAL, TRUE, Claim
from world.claims import describe_claim, evaluate
from world.social import belief_effect

# The metric is versioned and frozen. dramaturgy_metric_v1 is the seven core detectors below exactly as they were
# when it was frozen (2026-10-01); tests/test_dramaturgy_metric.py holds it to a golden record on a stored world.
# Never change what v1 finds or weighs to suit a new genre or a new rule: a changed detector is v2, side by side.
# Domain packs' situations (world/domains: Domain.situations) are reported apart, as extensions, never inside v1.
METRIC_VERSION = "dramaturgy_metric_v1"
KIND_WEIGHT = {"secret": 0.55, "misbelief": 0.5, "live_lie": 0.6, "near_miss": 0.5, "contradiction": 0.35,
               "goal_clash": 0.5, "turning_point": 0.45}
KIND_NAME = {"secret": "秘密", "misbelief": "誤會（觀眾知道、角色不知道）", "live_lie": "還沒被拆穿的謊", "near_miss": "差一點揭開",
             "contradiction": "言行矛盾（潛台詞）", "goal_clash": "目標衝突", "turning_point": "關係轉折"}
HARMFUL = ("steal", "take", "deceive", "conceal", "speak_hostile", "threaten")


def _names(conn: sqlite3.Connection) -> dict:
    out = {r[0]: r[1] for r in conn.execute("SELECT id, name FROM people")}
    out.update({r[0]: r[1] for r in conn.execute("SELECT id, name FROM objects")})
    out.update({r[0]: r[1] for r in conn.execute("SELECT id, name FROM locations")})
    return out


def _victim(conn: sqlite3.Connection, claim: Claim, people: set[str]) -> str | None:
    """Whom an act concerns: the person it was done to, or the rightful owner of the thing."""
    if claim.object in people:
        return claim.object
    row = conn.execute("SELECT rightful_owner_id FROM objects WHERE id = ?", (claim.object,)).fetchone()
    return row[0] if row and row[0] and row[0] != claim.subject else None


def _believers(conn: sqlite3.Connection, claim_id: int) -> dict[str, tuple[int, float, int]]:
    """Who holds this claim: person -> (first memory's minute, best confidence, memory id)."""
    out: dict[str, tuple[int, float, int]] = {}
    for obs, ts, conf, mid in conn.execute("SELECT observer_id, created_at, confidence, memory_id FROM memories "
                                           "WHERE claim_id = ? ORDER BY memory_id", (claim_id,)):
        if obs not in out:
            out[obs] = (ts, conf, mid)
        else:
            out[obs] = (out[obs][0], max(out[obs][1], conf), out[obs][2])
    return out


def analyse(conn: sqlite3.Connection) -> dict:
    conn.row_factory = sqlite3.Row
    names = _names(conn)
    animals = {r[0] for r in conn.execute("SELECT person_id FROM personas WHERE json_extract(traits, '$.species') "
                                          "IS NOT NULL AND json_extract(traits, '$.species') <> 'human'")}
    people = {r[0] for r in conn.execute("SELECT id FROM people")} - animals
    end = conn.execute("SELECT MAX(timestamp) FROM events").fetchone()[0] or 0
    days = end // 1440 + 1
    found: list[dict] = []

    from world.domains.base import situation

    def add(kind: str, day: int, who: list[str], why: str, question: str, events: list[int], build: float = 0.0,
            stakes: float = 0.0, until: int | None = None) -> None:
        found.append(situation(kind, KIND_WEIGHT[kind], day, who, why, question, events, build, stakes, until,
                               lasts=7 if kind in ("secret", "live_lie", "misbelief") else 1))

    # -- secrets: truth nobody told the one it concerns -----------------------------------------------------------
    for r in conn.execute("SELECT ec.event_id, c.claim_id, c.subject, c.act, c.object, c.polarity, e.timestamp "
                          "FROM event_claims ec JOIN claims c USING (claim_id) JOIN events e USING (event_id) "
                          "WHERE ec.role = 'truth' AND c.polarity = 'affirm' ORDER BY ec.event_id").fetchall():
        if r["act"] not in HARMFUL or r["subject"] not in people:
            continue
        claim = Claim(r["subject"], r["act"], r["object"], r["polarity"])
        victim = _victim(conn, claim, people)
        if victim is None or victim == claim.subject:
            continue
        know = _believers(conn, r["claim_id"])
        learnt = know.get(victim, (None,))[0]
        others = sorted(set(know) - {claim.subject, victim} - animals)
        kept_days = ((learnt if learnt is not None else end) - r["timestamp"]) / 1440
        if kept_days < 0.5 or r["act"] == "speak_hostile":
            continue  # said to their face, or found out at once: not a secret
        text = describe_claim(claim, names)
        add("secret", r["timestamp"] // 1440, [claim.subject, victim] + others,
            f"{text}；{names.get(victim, victim)}{'直到第 ' + str(learnt // 1440) + ' 天才知道' if learnt is not None else '到最後都不知道'}"
            + (f"；知情的還有{'、'.join(names.get(o, o) for o in others)}" if others else ""),
            f"{names.get(victim, victim)}會發現{text}嗎？", [r["event_id"]], build=kept_days / 7,
            stakes=abs(belief_effect(claim)) * 2, until=learnt // 1440 if learnt is not None else None)

    # -- misbeliefs: harmful beliefs about a person that the world contradicts --------------------------------------
    seen = {}
    for m in conn.execute("SELECT m.memory_id, m.observer_id, m.claim_id, m.about_event_id, m.confidence, m.created_at, "
                          "m.source_type, m.source_id, m.event_id, c.subject, c.act, c.object, c.polarity FROM memories m "
                          "JOIN claims c USING (claim_id) WHERE m.confidence >= 0.5 ORDER BY m.memory_id").fetchall():
        claim = Claim(m["subject"], m["act"], m["object"], m["polarity"])
        if m["observer_id"] in animals or m["subject"] not in people or m["subject"] == m["observer_id"]:
            continue
        if belief_effect(claim) >= 0 or claim.act not in HARMFUL:
            continue
        key = (m["claim_id"], m["about_event_id"])
        if key not in seen:
            seen[key] = evaluate(conn, claim, m["about_event_id"])
        verdict = seen[key]
        if verdict not in (FALSE, PARTIAL) and not (verdict == "UNKNOWN" and claim.act in ("steal", "take")):
            continue
        if any(f["kind"] == "misbelief" and f["people"][:2] == [m["observer_id"], m["subject"]] and f["_claim"] == m["claim_id"]
               for f in found):
            continue
        src = f"聽{names.get(m['source_id'], m['source_id'])}說的" if m["source_type"] == "told_by" else "自己推測的" if m["source_type"] == "inference" else "親眼所見（卻看錯了）"
        truth = {"FALSE": "事實正好相反", "PARTIAL": "事實不完全是這樣", "UNKNOWN": "事實上沒有這回事"}[verdict]
        add("misbelief", m["created_at"] // 1440, [m["observer_id"], m["subject"]] + ([m["source_id"]] if m["source_id"] in people else []),
            f"{names.get(m['observer_id'])}以為{describe_claim(claim, names)}（{src}，把握 {round(m['confidence'] * 100)}%）；{truth}",
            f"{names.get(m['observer_id'])}會發現自己誤會了{names.get(m['subject'])}嗎？", [m["event_id"], m["about_event_id"]],
            build=m["confidence"], stakes=abs(belief_effect(claim)) * 2)
        found[-1]["_claim"] = m["claim_id"]

    # -- lies, and whether they were ever exposed ---------------------------------------------------------------------
    exposed = defaultdict(list)
    for r in conn.execute("SELECT event_id, timestamp, truth FROM events WHERE type = 'confront'"):
        t = json.loads(r["truth"])
        if t.get("tell_event"):
            exposed[t["tell_event"]].append((r["event_id"], r["timestamp"], t.get("outcome")))
    for r in conn.execute("SELECT event_id, timestamp, truth FROM events WHERE type = 'tell'"):
        t = json.loads(r["truth"])
        if t.get("mode") not in ("lie", "distortion", "omission"):
            continue
        hits = exposed.get(r["event_id"], [])
        caught = [h for h in hits if h[2] and h[2].endswith("_exposed")]
        a, b = t["actor"], t["target"]
        mode = {"lie": "說謊", "distortion": "扭曲", "omission": "隱瞞"}[t["mode"]]
        if caught:
            add("turning_point", caught[0][1] // 1440, [b, a], f"{names.get(a)}對{names.get(b)}{mode}（「{t.get('text', '')}」），第 {caught[0][1] // 1440} 天被拆穿",
                f"{names.get(b)}還會再相信{names.get(a)}嗎？", [r["event_id"], caught[0][0]], build=(caught[0][1] - r["timestamp"]) / 1440 / 7, stakes=0.8)
        else:
            add("live_lie", r["timestamp"] // 1440, [a, b], f"{names.get(a)}對{names.get(b)}{mode}：「{t.get('text', '')}」，至今沒人拆穿"
                + (f"（被質問過 {len(hits)} 次都沒結果）" if hits else ""),
                f"{names.get(a)}的{mode}會被拆穿嗎？", [r["event_id"]] + [h[0] for h in hits],
                build=(end - r["timestamp"]) / 1440 / 7, stakes=0.6 + 0.2 * bool(hits))

    # -- near misses --------------------------------------------------------------------------------------------------
    for r in conn.execute("SELECT event_id, timestamp, type, truth FROM events WHERE type IN ('confront', 'accuse')"):
        t = json.loads(r["truth"])
        if t.get("outcome") in ("inconclusive", "denied"):
            a, b = t["actor"], t["target"]
            add("near_miss", r["timestamp"] // 1440, [a, b],
                f"{names.get(a)}{'質問' if r['type'] == 'confront' else '指控'}{names.get(b)}「{t.get('text', '')}」，"
                + ("對方否認，而且沒露餡" if t["outcome"] == "denied" else "沒有問出結果"),
                f"{names.get(a)}會找到證據嗎？", [r["event_id"]], stakes=0.7 if t["outcome"] == "denied" else 0.4)
    # the keeper and the one kept from, face to face, while the secret is alive
    for s in [f for f in found if f["kind"] == "secret"]:
        keeper, victim = s["people"][:2]
        hi = (s["until"] if s["until"] is not None else days) * 1440
        rows = conn.execute("SELECT e.event_id, e.timestamp, e.location_id FROM events e WHERE e.type = 'talk' AND e.timestamp BETWEEN ? AND ? "
                            "AND ((json_extract(truth, '$.actor') = ? AND json_extract(truth, '$.target') = ?) OR "
                            "(json_extract(truth, '$.actor') = ? AND json_extract(truth, '$.target') = ?)) ORDER BY e.event_id LIMIT 50",
                            (s["day"] * 1440, hi, keeper, victim, victim, keeper)).fetchall()
        if rows:
            add("near_miss", rows[0]["timestamp"] // 1440, [keeper, victim],
                f"秘密還在的時候，{names.get(keeper)}和{names.get(victim)}面對面說過 {len(rows)} 次話",
                f"{names.get(keeper)}會說出來嗎？", [rows[0]["event_id"]] + s["events"], build=len(rows) / 10, stakes=0.5)

    # -- contradictions (subtext) ----------------------------------------------------------------------------------
    trust_at: dict[tuple, list] = defaultdict(list)  # (a, b) -> [(minute, trust)] from the deltas
    for ent, ts, new in conn.execute("SELECT d.entity_id, e.timestamp, d.new_value FROM event_deltas d JOIN events e USING (event_id) "
                                     "WHERE d.entity_type = 'relationship' AND d.field IN ('trust') ORDER BY d.delta_id"):
        a, b = ent.split(":", 1)
        trust_at[(a, b)].append((ts, float(new)))
    aff_at: dict[tuple, list] = defaultdict(list)
    for ent, ts, new in conn.execute("SELECT d.entity_id, e.timestamp, d.new_value FROM event_deltas d JOIN events e USING (event_id) "
                                     "WHERE d.entity_type = 'relationship' AND d.field IN ('affection') ORDER BY d.delta_id"):
        a, b = ent.split(":", 1)
        aff_at[(a, b)].append((ts, float(new)))

    def value_at(series: list, ts: int, default: float) -> float:
        v = default
        for t, x in series:
            if t < ts:
                v = x
            else:
                break
        return v

    first = {}
    for a, b, tr, af in conn.execute("SELECT actor_id, target_id, trust, affection FROM relationships"):
        first[(a, b)] = (tr, af)
    for (a, b), series in trust_at.items():  # the value before any change: the delta's old value
        row = conn.execute("SELECT old_value FROM event_deltas WHERE entity_type = 'relationship' AND entity_id = ? AND field = 'trust' "
                           "ORDER BY delta_id LIMIT 1", (f"{a}:{b}",)).fetchone()
        first[(a, b)] = (float(row[0]), first.get((a, b), (0, 0))[1])
    subtext = Counter()
    for r in conn.execute("SELECT event_id, timestamp, truth FROM events WHERE type = 'talk'"):
        t = json.loads(r["truth"])
        a, b, tone = t.get("actor"), t.get("target"), t.get("tone")
        if a in animals or b in animals:
            continue
        tr = value_at(trust_at[(a, b)], r["timestamp"], first.get((a, b), (0, 0))[0])
        af = value_at(aff_at[(a, b)], r["timestamp"], first.get((a, b), (0, 0))[1])
        if tone == "warm" and tr < -0.3:
            key = ("smile", a, b)
            subtext[key] += 1
            if subtext[key] == 1:
                add("contradiction", r["timestamp"] // 1440, [a, b], f"{names.get(a)}不信任{names.get(b)}（信任 {tr:.2f}），卻對他說話很親切",
                    f"{names.get(a)}在掩飾什麼？", [r["event_id"]], stakes=min(1.0, -tr))
        elif tone in ("cold", "hostile") and af > 0.4:
            key = ("care", a, b)
            subtext[key] += 1
            if subtext[key] == 1:
                add("contradiction", r["timestamp"] // 1440, [a, b], f"{names.get(a)}明明很在乎{names.get(b)}（好感 {af:.2f}），說話卻{'冷淡' if tone == 'cold' else '帶刺'}",
                    f"{names.get(a)}為什麼要推開{names.get(b)}？", [r["event_id"]], stakes=af)
    for r in conn.execute("SELECT e.event_id, e.timestamp, e.truth, p.traits FROM events e JOIN personas p ON p.person_id = "
                          "json_extract(e.truth, '$.actor') WHERE e.type = 'tell' AND json_extract(e.truth, '$.mode') IN ('lie', 'distortion')"):
        t, tr = json.loads(r["truth"]), json.loads(r["traits"] or "{}")
        if tr.get("honesty", 0) >= 0.65:
            add("contradiction", r["timestamp"] // 1440, [t["actor"], t["target"]],
                f"一向誠實的{names.get(t['actor'])}（誠實 {tr['honesty']}）這次沒說真話：「{t.get('text', '')}」",
                f"{names.get(t['actor'])}為什麼要這樣做？", [r["event_id"]], stakes=tr["honesty"])

    # -- goal clashes (at the end: the open goals that pull against each other) -----------------------------------
    goals = conn.execute("SELECT person_id, kind, target, object, status FROM goals WHERE status IN ('active', 'blocked', 'formed')").fetchall()
    holders = {r[0]: r[1] for r in conn.execute("SELECT id, owner_person_id FROM objects")}
    for g in goals:
        if g["kind"] == "recover" and g["object"]:
            h = holders.get(g["object"])
            if h and h != g["person_id"] and h in people:
                add("goal_clash", days - 1, [g["person_id"], h], f"{names.get(g['person_id'])}想找回{names.get(g['object'])}，而它在{names.get(h)}手上",
                    f"{names.get(g['person_id'])}拿得回{names.get(g['object'])}嗎？", [], stakes=0.8)
        if g["kind"] in ("revenge", "expose", "outshine") and g["target"]:
            opp = [x for x in goals if x["person_id"] == g["target"] and x["kind"] in ("keep_secret", "clear_name", "reconcile", "make_amends", "befriend")]
            add("goal_clash", days - 1, [g["person_id"], g["target"]],
                f"{names.get(g['person_id'])}想{ {'revenge': '報復', 'expose': '揭穿', 'outshine': '壓過'}[g['kind']] }{names.get(g['target'])}"
                + (f"，而{names.get(g['target'])}想{ {'keep_secret': '守住秘密', 'clear_name': '洗清名聲', 'reconcile': '和好', 'make_amends': '彌補', 'befriend': '和他做朋友'}[opp[0]['kind']] }" if opp else ""),
                f"{names.get(g['person_id'])}和{names.get(g['target'])}誰會贏？", [], stakes=0.6 + 0.3 * bool(opp))

    # -- turning points: trust changing sign ---------------------------------------------------------------------------
    for r in conn.execute("SELECT event_id, timestamp, type, truth FROM events WHERE json_extract(truth, '$.trust_flipped') = 1"):
        t = json.loads(r["truth"])
        a, b = t.get("actor"), t.get("target")
        if a and b:
            add("turning_point", r["timestamp"] // 1440, [b, a], f"{names.get(b)}對{names.get(a)}的信任在這裡翻了面（{r['type']}）",
                f"{names.get(b)}和{names.get(a)}回得去嗎？", [r["event_id"]], stakes=0.5)

    for f in found:
        f.pop("_claim", None)
        f["metric"] = METRIC_VERSION
    ext = _extensions(conn, names)
    found.sort(key=lambda f: (-f["potential"], f["day"]))
    ext.sort(key=lambda f: (-f["potential"], f["day"]))
    v1, more = _curve(found, days), _curve(ext, days)
    return {"metric": METRIC_VERSION, "days": days, "count": dict(Counter(f["kind"] for f in found)), "curve": v1,
            "extensions": {"count": dict(Counter(f["kind"] for f in ext)), "curve": more},
            "curve_all": [round(a + b, 2) for a, b in zip(v1, more)], "situations": found + ext}


def _curve(found: list[dict], days: int) -> list[float]:
    curve = [0.0] * days
    for f in found:
        lo, hi = f["day"], (f["until"] if f["until"] is not None else f["day"] + f.get("lasts", 1))
        for d in range(max(0, lo), min(days, hi + 1)):
            curve[d] += f["potential"]
    return [round(x, 2) for x in curve]


def _extensions(conn: sqlite3.Connection, names: dict) -> list[dict]:
    """Each active domain pack's own drama (a quiet job search, an offer to take or refuse, ...), apart from v1."""
    from world.domains import active
    from world.recipes import RecipeError
    try:
        doms = active(conn)
    except (RecipeError, FileNotFoundError):
        return []  # a world from a recipe this code does not have: no extensions, v1 still stands
    out = []
    for dom in doms:
        for s in dom.situations(conn, names):
            out.append({**s, "metric": f"ext:{dom.id}"})
    return out + [{**s, "metric": "ext:values"} for s in _dilemmas(conn, names)]


VALUE_WORDS = {"truth": "真相", "loyalty": "忠誠", "security": "安穩", "belonging": "歸屬", "ambition": "野心",
               "freedom": "自由", "family": "家人", "fairness": "公平", "revenge": "報復"}


def _dilemmas(conn: sqlite3.Connection, names: dict) -> list[dict]:
    """Choices someone made against themselves (world/values.py records them on the event): an extension, not v1."""
    from world.domains.base import situation
    from runtime.godview import caption
    out = []
    for eid, ts, etype, place, truth in conn.execute(
            "SELECT event_id, timestamp, type, location_id, truth FROM events WHERE json_extract(truth, '$.dilemma.tension') >= 0.4 "
            "ORDER BY event_id"):
        t = json.loads(truth)
        d = t["dilemma"]
        who = t.get("actor")
        gave = "、".join(VALUE_WORDS.get(k, k) for k, _ in sorted(d["serves"].items(), key=lambda x: -x[1]))
        lost = "、".join(VALUE_WORDS.get(k, k) for k, _ in sorted(d["costs"].items(), key=lambda x: -x[1]))
        out.append(situation("dilemma", 0.5, ts // 1440, [who] + ([t["target"]] if t.get("target") else []),
                             f"{caption(etype, t, place or '', names)}：為了{gave}，付出了{lost}",
                             f"{names.get(who, who)}會後悔嗎？", [eid], stakes=d["tension"], lasts=2))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("db")
    ap.add_argument("--out")
    ap.add_argument("--top", type=int, default=25)
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    from world.reader import open_world_reader
    conn = open_world_reader(a.db)  # read-only: this analysis can never change the world
    rep = analyse(conn)
    if a.out:
        Path(a.out).write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    from world.domains import all_domains
    kinds = {**KIND_NAME, **{k: v for d in all_domains() for k, v in d.situation_kinds.items()}}
    print(f"{rep['days']} 天，找到的戲劇資源：", {kinds.get(k, k): v for k, v in rep["count"].items()})
    print(f"每天的潛在張力（{rep['metric']}）：", rep["curve"])
    if any(rep["extensions"]["curve"]):
        print("加上領域套件的戲（extensions）：", rep["curve_all"])
    for f in rep["situations"][:a.top]:
        print(f"[{f['potential']}] 第{f['day']}天 {kinds.get(f['kind'], f['kind'])}：{f['why']}  →  {f['question']}  {f['events'][:4]}")


if __name__ == "__main__":
    main()
