"""Script lint: what is wrong with an episode as a piece of writing (read only; it adds no event, changes nothing, decides nothing).

The world's causes are real; an *episode* is a reading of them, and a reading can be badly written even when every event in it happened:
somebody tells a story about themselves in the third person, a rumour is a line of the system's own caption, an event of the first week
is filmed on day 8, the same question is asked four times in a fortnight. This is the ruler for that, one code for each kind of fault
(the numbers are the plan's table L1-L9, docs/episode_planner.md):

  L1  a person speaks of themselves by name ("我聽說阿明弄丟了錢袋" said by 阿明), or tells the person a thing about themselves
      as if news (a tell whose subject is the listener)
  L2  a rumour that is a *tone* ("冷淡地對X說話", "敵意地質問X") passed on word for word: a tone is not news
  L3  an event of another day on the screen without being marked as a recap; the same event filmed in two episodes
  L4  the steps of the web-novel line out of time order (the set-up after the reversal); a caption that is still the system's word
      ("intervention", "小雲backstory")
  L5  the core question asked again within 7 days; an ending question used again in the last three episodes, about people who are not
      in the episode, or missing; a question whose premise is false ("誰拿了X" when X was lost by its owner and never taken)
  L6  a word of our own time ("手機", "咖啡", "辦公室", ...) in the speech or the captions of a martial-arts world
  L8  after a duel, the loser speaks like a winner (or the winner like a loser)

and the repetition measures (`metrics`): the same line twice in an episode, the same people in a row, how much of an episode is people
talking (talk + tell + confront), and how many of the hard events of a day (a duel, an outburst, leaving the sect, an exposure, a
confession, a succession) an episode took in.

The input is one episode of the control room's `studio.json` (`days[].episode`: beats with their events resolved: caption, speech,
mind, day) or an `EpisodePlan` resolved against its world (`resolve`). `prior` is the episodes before it, so that the ledgers (questions
asked, events filmed) can be checked; `lint_season` does that for a whole season. `script_lint_v0.1`: a draft; the word lists are the
first writing and are meant to be extended.
"""
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from typing import Iterable

LINT_VERSION = "script_lint_v0.1"
QUESTION_DAYS = 7          # the same core question is not asked again within this many days
ENDING_EPISODES = 3        # nor the same ending question within this many episodes
CHAT_TYPES = ("talk", "tell", "confront")
ORDER_LOOKBACK = 12        # a retort belongs to a duel when it comes within this many events of it

# the words of our own time. A martial-arts world has none of them (the speech pools and the character agent's options are the places
# it leaks from: the small town's profiles). Extend freely: a word listed here is a line a reader would stop at.
MODERN_WORDS = ("手機", "電話", "唱片", "專輯", "咖啡", "拿鐵", "辦公室", "加班", "上班", "下班", "公司", "薪水", "薪資", "老闆", "同事", "面試", "履歷",
                "籃球", "電影", "電視", "電腦", "網路", "網站", "多肉", "盆栽", "音樂", "閱讀", "遊戲", "電動", "健身", "瑜伽", "大學", "台中", "捷運",
                "公車", "便利商店", "咖啡廳", "冰咖啡", "手遊", "社群", "訊息", "簡訊", "打卡", "週末", "放假", "網紅", "直播", "影片", "app", "wifi")

# raw event / system words that must never be a caption
SYSTEM_WORD = re.compile(r"[A-Za-z_]{3,}")
TONE_CLAIM = re.compile(r"敵意地|冷淡地|親切地|不客氣地|閒聊")
# what only the winner / only the loser of a duel says
WINNER_VOICE = ("承讓", "這就是你的本事", "再練練", "你也不錯")
LOSER_VOICE = ("我輸了", "我服了", "今天算你贏", "輸得心服", "技不如人")
LOSER_WRONG = ("你才是", "要比，就來比", "你自己又好到哪裡去", "你再說一次看看") + WINNER_VOICE      # a loser who answers like one who won
WINNER_WRONG = LOSER_VOICE

# the hard events of a day: what a viewer would call "something happened"
HARD_TYPES = ("duel", "shove", "strike", "smash", "break_down", "defect", "found_faction", "succession", "confession", "break_up", "steal")
HARD_NAMES = {"duel": "比武", "shove": "推人", "strike": "動手", "smash": "砸東西", "break_down": "崩潰", "defect": "離開師門", "found_faction": "自立門戶",
              "succession": "繼位", "confession": "告白", "break_up": "分手", "steal": "偷竊", "exposure": "揭穿", "betrayal": "背叛", "switch": "改投"}


@dataclass(frozen=True)
class Issue:
    code: str                  # L1 ... L8
    kind: str                  # which fault of that code
    day: int
    event_id: int | None
    text: str                  # what is wrong, in words a writer can act on

    def as_dict(self) -> dict:
        return {"code": self.code, "kind": self.kind, "day": self.day, "event_id": self.event_id, "text": self.text}


# ---------------------------------------------------------------------------------------------------------------------------
def _ep(ep) -> dict:
    if isinstance(ep, dict):
        return ep
    from contracts.base import to_dict
    return to_dict(ep)


def shot(ep: dict) -> list[dict]:
    """The beats that are filmed, and are not the second look at an event already in the episode (a reaction beat)."""
    return [b for b in ep.get("beats", []) if b.get("shoot")]


def _events(ep: dict, derived: bool = False) -> list[dict]:
    """Every event on screen, once each (a reaction beat shows the same event again; that is not a second event)."""
    seen: set[int] = set()
    out = []
    for b in shot(ep):
        if b.get("derived") and not derived:
            continue
        for e in b.get("events", []):
            if e["id"] not in seen:
                seen.add(e["id"])
                out.append(e)
    return out


def _speeches(e: dict) -> list[tuple[str, str]]:
    """(who speaks, the words) of an event: the line, the answer, and what the watchers say."""
    sp = e.get("speech") or {}
    out = []
    if sp.get("say"):
        out.append((sp.get("speaker", ""), sp["say"]))
    if sp.get("answer"):
        out.append((sp.get("listener", ""), sp["answer"]))
    out += [(r.get("who", ""), r.get("say", "")) for r in sp.get("reactions", []) if r.get("say")]
    return out


def _texts(ep: dict) -> Iterable[tuple[int | None, str, str]]:
    """Every piece of words a viewer reads in the episode: (event id, where, text)."""
    yield None, "核心問題", ep.get("core_question", "")
    yield None, "結尾問題", ep.get("ending_question", "")
    if ep.get("cold_open"):
        yield None, "冷開場", ep["cold_open"]
    for b in ep.get("beats", []):
        if not b.get("shoot"):
            continue
        for e in b.get("events", []):
            yield e["id"], "字幕", e.get("caption", "")
            for who, say in _speeches(e):
                yield e["id"], "台詞", say
            sp = e.get("speech") or {}
            if sp.get("subtext"):
                yield e["id"], "潛台詞", sp["subtext"]
            m = e.get("mind") or {}
            for k in ("reason", "inner"):
                if m.get(k):
                    yield e["id"], "心智", m[k]
        if (b.get("checklist") or {}).get("leaves_question"):
            yield None, "留下的問題", b["checklist"]["leaves_question"]


def _name_in(name: str, text: str) -> bool:
    return len(name) >= 2 and name in text


# -- the checks ---------------------------------------------------------------------------------------------------------------
def check_speech(ep: dict) -> list[Issue]:
    """L1, L2, L8: what a person says, and to whom."""
    day, out = ep.get("day", 0), []
    events = _events(ep)
    for e in events:
        sp = e.get("speech") or {}
        speaker, listener = sp.get("speaker", ""), sp.get("listener", "")
        say = sp.get("say", "")
        if say and e["type"] in ("tell", "confront", "accuse", "talk") and _name_in(speaker, say):
            out.append(Issue("L1", "self_third", day, e["id"], f"{speaker}說自己的事卻用名字：「{say}」"))
        elif say and e["type"] == "tell" and _name_in(listener, say):
            out.append(Issue("L1", "told_about_self", day, e["id"], f"{speaker}告訴{listener}一件關於{listener}自己的事，像新聞一樣：「{say}」"))
        if say and e["type"] in ("tell", "confront", "accuse") and TONE_CLAIM.search(say):
            out.append(Issue("L2", "tone_gossip", day, e["id"], f"把語氣當八卦原文傳：「{say}」"))
    out += check_duel_voice(ep)
    return out


def check_duel_voice(ep: dict) -> list[Issue]:
    """L8: after a duel, the loser says what a winner says (or the reverse). Judged on the lines of the two, within a few events of the duel."""
    day, out = ep.get("day", 0), []
    events = sorted(_events(ep), key=lambda e: e["id"])
    for d in events:
        f = d.get("facts") or {}
        if d["type"] != "duel" or not f.get("winner") or not f.get("loser"):
            continue
        pair = {f["winner"], f["loser"]}
        for e in events:
            if e["id"] <= d["id"] or e["id"] > d["id"] + ORDER_LOOKBACK or e["id"] == d["id"]:
                continue
            sp = e.get("speech") or {}
            if not sp.get("say") or {sp.get("speaker"), sp.get("listener")} != pair:
                continue
            who, say = sp["speaker"], sp["say"]
            if who == f["loser"] and any(w in say for w in LOSER_WRONG):
                out.append(Issue("L8", "loser_sounds_like_winner", day, e["id"], f"{who}輸了比武，卻說：「{say}」"))
            elif who == f["winner"] and any(w in say for w in WINNER_WRONG):
                out.append(Issue("L8", "winner_sounds_like_loser", day, e["id"], f"{who}贏了比武，卻說：「{say}」"))
    # the duel's own answer: the one challenged speaks as who they were that day
    for d in events:
        f, sp = d.get("facts") or {}, d.get("speech") or {}
        if d["type"] == "duel" and sp.get("answer") and f.get("winner") and f.get("loser"):
            answerer = sp.get("listener", "")
            if answerer == f["loser"] and any(w in sp["answer"] for w in WINNER_VOICE) or answerer == f["winner"] and any(w in sp["answer"] for w in LOSER_VOICE):
                out.append(Issue("L8", "duel_answer_mismatch", day, d["id"], f"{answerer}回應比武的話與勝負不符：「{sp['answer']}」"))
    return out


def check_time(ep: dict, prior: Iterable[dict] = ()) -> list[Issue]:
    """L3 (an event of another day not marked as a recap; an event filmed before) and L4 (the line out of order, a caption in the system's words)."""
    day, out = ep.get("day", 0), []
    earlier: dict[int, int] = {}
    for p in prior:
        for e in _events(p):
            earlier.setdefault(e["id"], p.get("day", 0))
    recap = {i for b in shot(ep) if b.get("recap") for i in b.get("event_ids", [])}
    for e in _events(ep):
        if e.get("day", day) != day and e["id"] not in recap:
            out.append(Issue("L3", "stale_event", day, e["id"], f"第 {e['day'] + 1} 天的事放在第 {day + 1} 天的集，沒有標「前情」：{e.get('caption', e['type'])}"))
        if e["id"] in earlier:
            out.append(Issue("L3", "replayed_event", day, e["id"], f"這件事第 {earlier[e['id']] + 1} 天的集已經播過：{e.get('caption', e['type'])}"))
    for b in ep.get("beats", []):
        for e in b.get("events", []):
            cap = e.get("caption", "")
            if b.get("shoot") or not b.get("derived"):
                if cap == e["type"] or SYSTEM_WORD.search(cap):
                    out.append(Issue("L4", "untranslated_caption", day, e["id"], f"字幕還是系統的詞：「{cap}」"))
    out += check_grammar_order(ep)
    return out


def check_grammar_order(ep: dict) -> list[Issue]:
    """L4: the set-up of the line (belittled, hidden growth, the gathering) must come before the reversal, and what it leaves behind after."""
    day, out = ep.get("day", 0), []
    steps = {g["step"]: g for g in ep.get("grammar", []) if g.get("present")}
    rev = steps.get("reversal")
    if not rev or not rev.get("event_ids"):
        return out
    r = rev["event_ids"][0]
    for name in ("belittled", "hidden_growth", "gathering"):
        late = [i for i in steps.get(name, {}).get("event_ids", []) if i > r]
        if late:
            out.append(Issue("L4", "step_out_of_order", day, late[0], f"爽文的「{GRAMMAR_ZH[name]}」發生在高潮之後（事件 {late[0]} 在 {r} 之後）"))
    early = [i for i in steps.get("new_state", {}).get("event_ids", []) if i < r]
    if early:
        out.append(Issue("L4", "step_out_of_order", day, early[0], f"「新的局面」發生在高潮之前（事件 {early[0]}）"))
    return out


GRAMMAR_ZH = {"belittled": "被看輕", "hidden_growth": "暗中變強", "gathering": "公開場合", "reversal": "逆轉", "bystanders": "旁人", "new_state": "新的局面"}
ASKED = re.compile(r"誰(?:拿|偷|拿走|偷走|動)了(?P<obj>[^？?，。]+)")


def _people_in(text: str, names: Iterable[str]) -> list[str]:
    return [n for n in names if _name_in(n, text)]


def check_questions(ep: dict, prior: Iterable[dict] = (), names: Iterable[str] = (), facts: dict | None = None) -> list[Issue]:
    """L5: the questions an episode asks, against the ones already asked, the people in it, and what the world has already settled."""
    day, out = ep.get("day", 0), []
    prior = list(prior)
    core, ending = ep.get("core_question", ""), ep.get("ending_question", "")
    names = list(names) or list(ep.get("people_names", []))
    for p in prior:
        if core and p.get("core_question") == core and 0 < day - p.get("day", 0) < QUESTION_DAYS:
            out.append(Issue("L5", "core_repeated", day, None, f"核心問題「{core}」第 {p['day'] + 1} 天才問過（{QUESTION_DAYS} 天內不重問）"))
            break
    if not ending:
        out.append(Issue("L5", "no_ending", day, None, "這集沒有留下結尾問題"))
    else:
        for p in prior[-ENDING_EPISODES:]:
            if p.get("ending_question") == ending:
                out.append(Issue("L5", "ending_repeated", day, None, f"結尾問題「{ending}」前幾集已經問過（第 {p['day'] + 1} 天）"))
                break
        named = _people_in(ending, names)
        here = set(ep.get("people_names", []))
        if named and not (set(named) & here):
            out.append(Issue("L5", "ending_not_here", day, None, f"結尾問題「{ending}」問的是{'、'.join(named)}，他們不在這一集"))
        elif not named:
            out.append(Issue("L5", "ending_unnamed", day, None, f"結尾問題「{ending}」沒有說是誰"))
    for q in (core, ending):
        m = ASKED.search(q or "")
        info = (facts or {}).get("objects", {}).get(m.group("obj")) if m else None
        if info is not None:
            if not info.get("other_takes"):
                out.append(Issue("L5", "false_premise", day, None, f"問「{q}」，但{m.group('obj')}沒有被別人拿過（是{info.get('owner', '主人')}自己弄丟的）"))
            elif info.get("found_day") is not None and info["found_day"] < day and not info.get("retaken"):
                out.append(Issue("L5", "already_answered", day, None, f"問「{q}」，但第 {info['found_day'] + 1} 天{m.group('obj')}已經找回來了"))
    return out


def check_modern(ep: dict, words: Iterable[str] = MODERN_WORDS) -> list[Issue]:
    """L6: a word of our own time in a world that has none."""
    out, seen = [], set()
    for eid, where, text in _texts(ep):
        for w in words:
            if w in text.lower() and (eid, w, where) not in seen:
                seen.add((eid, w, where))
                out.append(Issue("L6", "modern_word", ep.get("day", 0), eid, f"{where}裡有現代詞「{w}」：{text}"))
    return out


# -- measures -----------------------------------------------------------------------------------------------------------------
def is_hard(etype: str, truth: dict) -> bool:
    if etype in HARD_TYPES:
        return True
    return (etype == "confront" and str(truth.get("outcome", "")).endswith("_exposed")) or (etype == "accuse" and truth.get("outcome") == "caught")


def hard_events(conn: sqlite3.Connection, day: int) -> list[dict]:
    """The hard events of one day of a world (read only): [{id, type, kind}], kind being the word the page shows."""
    lo, hi = day * 1440, (day + 1) * 1440
    out = []
    for r in conn.execute("SELECT event_id, type, truth FROM events WHERE timestamp >= ? AND timestamp < ? ORDER BY event_id", (lo, hi)):
        eid, etype, t = r[0], r[1], json.loads(r[2])
        if is_hard(etype, t):
            out.append({"id": eid, "type": etype, "kind": "exposure" if etype in ("confront", "accuse") else etype})
    switched = {r[0] for r in conn.execute("SELECT DISTINCT d.event_id FROM event_deltas d JOIN events e USING (event_id) WHERE d.entity_type = 'affiliation' "
                                           "AND d.field = 'faction_id' AND d.old_value IS NOT d.new_value AND e.timestamp >= ? AND e.timestamp < ?", (lo, hi))}
    have = {h["id"] for h in out}
    for r in conn.execute("SELECT event_id, type FROM events WHERE event_id IN (%s)" % ",".join("?" * len(switched)), tuple(switched)) if switched else ():
        if r[0] not in have:
            out.append({"id": r[0], "type": r[1], "kind": "switch"})
    return sorted(out, key=lambda h: h["id"])


def object_facts(conn: sqlite3.Connection, through_day: int) -> dict:
    """What the world has settled about each thing, as of the end of `through_day`: who owns it, whether anybody else ever took it, when it came back."""
    objs: dict[str, dict] = {}
    rows = {r[0]: (r[1], r[2]) for r in conn.execute("SELECT id, name, rightful_owner_id FROM objects")}
    people = {r[0]: r[1] for r in conn.execute("SELECT id, name FROM people")}
    for r in conn.execute("SELECT event_id, timestamp, type, truth FROM events WHERE type IN ('take', 'steal', 'misplace', 'find', 'give', 'backstory') "
                          "AND timestamp < ? ORDER BY event_id", ((through_day + 1) * 1440,)):
        t = json.loads(r[3])
        oid = t.get("object")
        if oid not in rows:
            continue
        name, owner = rows[oid]
        o = objs.setdefault(name, {"owner": people.get(owner, owner), "other_takes": 0, "found_day": None, "retaken": False})
        actor = t.get("actor")
        if r[2] in ("take", "steal") and actor != owner or r[2] == "backstory" and actor != owner:
            if o["found_day"] is not None:
                o["retaken"] = True
            o["other_takes"] += 1
        elif r[2] in ("find", "give") and (t.get("own") or actor == owner or r[2] == "give"):
            o["found_day"] = r[1] // 1440
            o["retaken"] = False
    return {"objects": objs}


def metrics(ep: dict) -> dict:
    """The repetition measures of one episode."""
    beats = [b for b in shot(ep) if not b.get("derived")]
    says: dict[str, int] = {}
    for e in _events(ep):
        for _, say in _speeches(e):
            says[say] = says.get(say, 0) + 1
    streak = best = 0
    prev = None
    for b in beats:
        key = frozenset(b.get("who", [])[:2])
        streak = streak + 1 if key == prev and len(key) == 2 else 1
        best, prev = max(best, streak), key
    groups: dict[tuple, int] = {}
    for b in beats:
        ev = b.get("events", [])
        if ev and ev[0]["type"] in CHAT_TYPES and len(b.get("who", [])) >= 2:
            quarrel = ev[0]["type"] == "talk" and (ev[0].get("facts") or {}).get("tone") in ("cold", "hostile")
            k = (frozenset(b["who"][:2]), "quarrel" if quarrel else ev[0]["type"])       # (a quarrel and a pleasant word are not the same back and forth)
            groups[k] = groups.get(k, 0) + 1
    chat = sum(1 for b in beats if b.get("events") and b["events"][0]["type"] in CHAT_TYPES)
    return {"beats": len(beats), "chat_beats": chat, "chat_share": round(chat / len(beats), 3) if beats else 0.0,
            "dup_lines": sum(n - 1 for n in says.values() if n > 1), "max_pair_streak": best,
            "pair_kind_repeats": sum(n - 1 for n in groups.values() if n > 1)}


def hard_taken(ep: dict, day_hard: list[dict]) -> tuple[int, int]:
    """(hard events of the day, how many of them are on screen)."""
    on = {i for b in shot(ep) for i in b.get("event_ids", [])}
    return len(day_hard), sum(1 for h in day_hard if h["id"] in on)


# -- one episode, a season -------------------------------------------------------------------------------------------------
def lint_episode(ep, *, prior: Iterable = (), names: Iterable[str] = (), facts: dict | None = None, jianghu: bool = True,
                 modern: Iterable[str] = MODERN_WORDS) -> list[Issue]:
    """Every fault of one episode (a studio episode dict, or an EpisodePlan that has been `resolve`d). `prior`: the episodes before it."""
    ep = _ep(ep)
    prior = [_ep(p) for p in prior if p]
    out = check_speech(ep) + check_time(ep, prior) + check_questions(ep, prior, names, facts)
    if jianghu:
        out += check_modern(ep, modern)
    return out


def lint_season(episodes: list[dict | None], *, names: Iterable[str] = (), facts: list[dict | None] | None = None, jianghu: bool = True,
                modern: Iterable[str] = MODERN_WORDS) -> list[list[Issue]]:
    """The faults of each day's episode (an empty list for a quiet day), each judged against the episodes before it."""
    out, prior = [], []
    for i, ep in enumerate(episodes):
        if ep is None:
            out.append([])
            continue
        out.append(lint_episode(ep, prior=prior, names=names, facts=(facts[i] if facts else None), jianghu=jianghu, modern=modern))
        prior.append(ep)
    return out


def summarize(issues: Iterable[Issue]) -> dict:
    """How many of each code and kind."""
    by_code: dict[str, int] = {}
    by_kind: dict[str, int] = {}
    for i in issues:
        by_code[i.code] = by_code.get(i.code, 0) + 1
        by_kind[f"{i.code}.{i.kind}"] = by_kind.get(f"{i.code}.{i.kind}", 0) + 1
    return {"total": sum(by_code.values()), "by_code": dict(sorted(by_code.items())), "by_kind": dict(sorted(by_kind.items()))}


def season_report(doc: dict) -> dict:
    """The whole table for one `studio.json` document: the faults by kind, the repetition measures, the hard-event intake. Reads the file only."""
    days = doc["days"]
    eps = [d.get("episode") for d in days]
    names = [p["name"] for p in doc.get("people", [])]
    ld = doc.get("lint_days") or []
    # the hard events and the settled facts of each day: beside the days (studio.json `lint_days`), or on them (older documents); nothing is written back
    hards = [(ld[i]["hard"] if i < len(ld) else d.get("hard")) or [] for i, d in enumerate(days)]
    facts = [(ld[i]["facts"] if i < len(ld) else d.get("lint_facts")) for i, d in enumerate(days)]
    jianghu = "jianghu" in str(doc.get("meta", {}).get("recipe", ""))
    per_day = lint_season(eps, names=names, facts=facts if any(facts) else None, jianghu=jianghu)
    flat = [i for day in per_day for i in day]
    ms = [metrics(e) for e in eps if e]
    beats = sum(m["beats"] for m in ms)
    hard_days = [(d, h) for d, h in zip(days, hards) if h]
    taken = [hard_taken(d["episode"], h)[1] > 0 if d.get("episode") else False for d, h in hard_days]
    hard_all = sum(len(h) for _, h in hard_days)
    hard_on = sum(hard_taken(d["episode"], h)[1] if d.get("episode") else 0 for d, h in hard_days)
    return {"days": len(days), "episodes": len(ms), "issues": summarize(flat),
            "beats": beats, "chat_share": round(sum(m["chat_beats"] for m in ms) / beats, 3) if beats else 0.0,
            "dup_lines": sum(m["dup_lines"] for m in ms), "max_pair_streak": max((m["max_pair_streak"] for m in ms), default=0),
            "pair_kind_repeats": sum(m["pair_kind_repeats"] for m in ms),
            "hard_days": len(hard_days), "hard_days_taken": sum(taken), "hard_day_rate": round(sum(taken) / len(hard_days), 3) if hard_days else None,
            "hard_events": hard_all, "hard_events_on_screen": hard_on}


def resolve(conn: sqlite3.Connection, plan, names: dict | None = None) -> dict:
    """An `EpisodePlan` as the dict `lint_episode` reads: its beats' events resolved (type, day, caption, speech) from the world it came from."""
    from contracts.base import to_dict
    from narrative.speech import speak
    from runtime.godview import _names, caption
    d = to_dict(plan)
    nm = names or _names(conn)
    nm.update({r[0]: r[1] for r in conn.execute("SELECT seat_id, title FROM seats")})
    cache: dict[int, dict] = {}
    for b in d["beats"]:
        for eid in b["event_ids"]:
            if eid not in cache:
                r = conn.execute("SELECT type, timestamp, location_id, truth FROM events WHERE event_id = ?", (eid,)).fetchone()
                truth = json.loads(r["truth"])
                ev = {"id": eid, "type": r["type"], "day": r["timestamp"] // 1440, "caption": caption(r["type"], truth, r["location_id"] or "", nm),
                      "facts": event_facts(r["type"], truth, nm)}
                sp = speak(conn, eid, r["type"], truth, nm, r["timestamp"], r["location_id"] or "")
                if sp:
                    ev["speech"] = {"say": sp.get("say", ""), "answer": sp.get("answer", ""), "speaker": nm.get(truth.get("actor", ""), ""),
                                    "listener": nm.get(truth.get("target") or truth.get("victim") or "", ""),
                                    "reactions": [{"who": nm.get(x["who"], x["who"]), "say": x["say"]} for x in sp.get("reactions", [])]}
                cache[eid] = ev
        b["events"] = [cache[i] for i in b["event_ids"]]
        if b["events"] and all(e["day"] != d["day"] for e in b["events"]):
            b["recap"] = True              # what came before, told again as the background of the day's story (the control room marks it the same way)
    d["people_names"] = [nm.get(p, p) for p in d["people"]]
    return d


def event_facts(etype: str, truth: dict, names: dict) -> dict:
    """The few facts of an event that the lint needs and the page does not otherwise show (who won, the tone)."""
    n = lambda k: names.get(truth.get(k) or "", "")  # noqa: E731
    f = {}
    if etype == "duel":
        f = {"winner": n("winner"), "loser": n("loser")}
    elif etype == "talk":
        f = {"tone": truth.get("tone", "neutral")}
    elif etype in ("tell", "confront", "accuse"):
        c = truth.get("asserted_claim") or truth.get("claim") or {}
        f = {"claim_act": c.get("act", ""), "claim_subject": names.get(c.get("subject", ""), "")}
    return f
