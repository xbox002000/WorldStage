"""Character agents: a person thinks only when their life asks them to.

Most of the time everyone lives by the rule agent (agent/volition.py): routine, habits, motives. A character agent
wakes at a wake point — an offer to answer, a decision made today, a strong feeling, a clash within reach, someone in
front of them who went against what they value most — and then an LLM (or any outside agent) chooses for them.

What it gets is a CognitiveState (contracts/cognition.py): who they are, what they want and fear, how they feel,
their goals, the people here as they see them, what they remember, and the options the rule agent found possible,
numbered. What it may give back is a CognitiveChoice: one number and a reason. It cannot invent an action, a target
or a fact; the world's validator still decides whether the choice is legal, and the rules what follows.

A daily budget caps the wake-ups. Without a client, over the budget, or when the answer is unusable, the rule agent
decides. Answers are cached by request hash in the LLM client, so a world replays exactly.
"""
from __future__ import annotations

import json
import sqlite3
from collections import Counter
from dataclasses import replace

from contracts.base import to_dict
from contracts.cognition import CognitiveChoice, CognitiveState, OptionView, PersonHere
from world.intent import Intent

TONE_WORDS = {"warm": "親切地", "neutral": "", "cold": "冷淡地", "hostile": "不客氣地"}
STRONG = ("angry", "hurt", "ashamed", "scared")
VALUE_ACTS = {  # what goes against a value one holds dear (acts in claims): serious things, not a sharp word
    "truth": ("deceive", "conceal"), "fairness": ("steal", "take"), "loyalty": ("resign", "seek_job", "deceive"),
    "security": ("steal",), "family": ("deceive",),
}
VALUE_WORDS = {"truth": "真相", "loyalty": "忠誠", "security": "安穩", "belonging": "歸屬", "ambition": "野心",
               "freedom": "自由", "family": "家人", "fairness": "公平", "revenge": "報復"}
BACKGROUND_WORDS = {"birthplace": "出生地", "family": "家庭", "education": "出身"}
CHOICE_SCHEMA = {
    "type": "object",
    "properties": {"option": {"type": "integer"}, "reason": {"type": "string"}, "inner": {"type": "string"}},
    "required": ["option", "reason"],
}
PROMPT = """你是一個持續運轉的虛擬世界裡的一個人。下面是你此刻知道的一切（JSON）：你是誰、你想要和害怕什麼、你的感受、
你的目標、你眼前的人和你對他們的看法、你記得的事，以及你現在做得到的事（options，已編號）。

只能從 options 裡選一個（回答它的編號 n）。你不知道清單以外的任何事，也不能做清單以外的事。
像這個人一樣選：照他的個性、價值、傷口、此刻的心情和處境，而不是照「正確答案」。好人也會選錯，會嘴硬，會逃避。

{state}

用 JSON 回答：option（編號）、reason（一句話，用他的口吻，繁體中文）、inner（他心裡真正的想法，不會說出口，可以留空）。
"""


def _names(conn: sqlite3.Connection) -> dict[str, str]:
    from world.claims import labels
    out = labels(conn)
    out.update({r[0]: r[1] for r in conn.execute("SELECT id, name FROM locations")})
    return out


def describe_intent(conn: sqlite3.Connection, it: Intent | None, names: dict[str, str]) -> str:
    """An option as the person would think of it."""
    if it is None:
        return "什麼都不做"
    t = names.get(it.target or "", it.target or "")
    if it.action == "talk":
        topic = ""
        if it.topic:
            topic = f"（聊{names.get(it.topic[1:], it.topic[1:])}的事）" if it.topic.startswith("@") else f"（聊{names.get(it.topic, it.topic)}）"
        return f"{TONE_WORDS.get(it.tone or '', '')}對{t}說話{topic}"
    if it.action == "tell" and it.claim_id is not None:
        from world.claims import describe_claim, load_claim
        mode = {"truth": "照實說", "lie": "說反話", "distortion": "加油添醋", "omission": "只說一半"}.get(it.mode or "", "")
        return f"告訴{t}：「{describe_claim(load_claim(conn, it.claim_id), names)}」（{mode}）"
    words = {"confront": "當面質問{t}", "accuse": "指控{t}", "steal": "偷{t}", "take": "撿起{t}", "give": "把{t}還回去",
             "lend": "借錢給{t}", "repay": "還錢給{t}", "move": "離開，去{t}", "drop": "放下{t}"}
    if it.action in words:
        return words[it.action].format(t=t)
    from world.domains import action_spec
    spec = action_spec(it.action)
    if spec is not None and spec[1].label:
        return spec[1].label.format(t=t)
    return f"{it.action} {t}".strip()


def wake_reasons(conn: sqlite3.Connection, pid: str, now: int, scored: list) -> list[str]:
    """Why this person has to think now (empty: they live by habit)."""
    from world.attention import var
    from world.claims import labels
    names = labels(conn)
    me = conn.execute("SELECT emotion, location_id FROM people WHERE id = ?", (pid,)).fetchone()
    out = []
    if var(conn, f"work.offer.{pid}", -1.0) >= 0:
        out.append("手上有一份邀請，要決定接不接受")
    if me["emotion"] in STRONG:
        out.append(f"心情很糟（{me['emotion']}）")
    from agent.volition import conflict_actions
    top3 = sorted(scored, key=lambda s: -s[0])[:3]
    if any(it is not None and (it.action in conflict_actions() or (it.action == "talk" and it.tone == "hostile"))
           for _, it in top3):
        out.append("眼前可能起衝突")  # a clash is among what they most want to do
    if conn.execute("SELECT 1 FROM events WHERE type = 'goal_change' AND json_extract(truth, '$.actor') = ? AND "
                    "json_extract(truth, '$.to') IN ('formed', 'transformed') AND timestamp >= ? LIMIT 1",
                    (pid, now // 1440 * 1440)).fetchone():
        out.append("今天剛下了決心")
    from world.profiles import profile
    p = profile(conn, pid)
    if p is not None and p.values:
        top, weight = max(p.values.items(), key=lambda kv: (kv[1], kv[0]))
        acts = VALUE_ACTS.get(top, ())
        if weight >= 0.75 and acts:
            here = [r[0] for r in conn.execute("SELECT id FROM people WHERE location_id = ? AND id <> ?", (me["location_id"], pid))]
            marks = ",".join("?" * len(acts))
            for other in here:
                if conn.execute(f"SELECT 1 FROM memories m JOIN claims c USING (claim_id) WHERE m.observer_id = ? AND c.subject = ? "
                                f"AND c.act IN ({marks}) AND c.polarity = 'affirm' AND m.confidence >= 0.6 LIMIT 1",
                                (pid, other, *acts)).fetchone():
                    out.append(f"{names.get(other, other)}做過違背我最看重的事（{VALUE_WORDS.get(top, top)}）")
                    break
    return out


def cognitive_state(conn: sqlite3.Connection, pid: str, now: int, options: list, wake: list[str]) -> CognitiveState:
    from agent.perception import memory_lines, observe
    from world.domains import active
    from world.goals import describe, goals_of
    from world.profiles import profile, topics
    names = _names(conn)
    label = topics(conn)
    p = profile(conn, pid)
    me = conn.execute("SELECT * FROM people WHERE id = ?", (pid,)).fetchone()
    who, core, values, habits = {}, {}, {}, []
    if p is not None:
        who = {"年齡": str(p.age), **({"工作": p.occupation.role} if p.occupation else {}),
               **{BACKGROUND_WORDS.get(k, k): v for k, v in p.background.items()}}
        core = {k: v for k, v in (("想要", p.core.want), ("害怕", p.core.fear), ("傷口", p.core.wound),
                                  ("錯誤的信念", p.core.false_belief), ("真正需要", p.core.need),
                                  ("人生的問題", p.core.life_question), ("一生的目標", p.life_goal),
                                  ("這一陣子的目標", p.season_goal)) if v}
        values, habits = {VALUE_WORDS.get(k, k): v for k, v in p.values.items()}, [h.label for h in p.habits]
    from agent.volition import rel
    from world.domains.topics import known_taste
    people = []
    for o in observe(conn, pid)["others_here"]:
        oid = o["id"]
        r = rel(conn, pid, oid)
        likes, dislikes = [], []
        for t in sorted(label):
            k = known_taste(conn, pid, oid, t)
            if k is not None:
                (likes if k > 0 else dislikes).append(label[t])
        people.append(PersonHere(oid, names.get(oid, oid), round(r["trust"], 2), round(r["affection"], 2), round(r["fear"], 2),
                                 likes, dislikes))
    life = {}
    for dom in active(conn):
        d = dom.describe(conn, pid)
        if d:
            life[dom.title or dom.id] = {k: (v if isinstance(v, (int, float, str)) else str(v)) for k, v in d.items()}
    return CognitiveState(
        person=pid, name=me["name"], who=who, core=core, values=values, habits=habits, feeling=me["emotion"], life=life,
        goals=[describe(conn, g) for g in goals_of(conn, pid) if g["status"] in ("active", "formed", "blocked")],
        place=names.get(me["location_id"], me["location_id"]), people=people,
        memories=[f"{m['text']}（{m['how']}）" for m in memory_lines(conn, pid, names)],
        options=[OptionView(n, it.action if it else "idle", (it.target or "") if it else "", describe_intent(conn, it, names))
                 for n, (_, it) in enumerate(options)],
        wake=wake)


class CharacterAgent:
    """A decider: the rule agent's life, and a mind that wakes at wake points.

    client: anything with generate_json(prompt, schema, temperature) -> dict (agent/llm.py LLMClient or FallbackClient,
    a stub in tests). budget: wake-ups a day for the whole world. top_k: how many of the most wanted options it sees.
    """

    def __init__(self, rule, client=None, budget: int = 20, top_k: int = 7) -> None:
        self.rule = rule
        self.client = client
        self.budget = budget
        self.top_k = top_k
        self.used: Counter = Counter()   # day -> wake-ups
        self.stats: Counter = Counter()
        self.log: list[dict] = []        # what each woken mind saw and chose (for the Observatory and tests)

    @property
    def mechanics(self):
        return self.rule.mechanics

    @mechanics.setter
    def mechanics(self, value) -> None:
        self.rule.mechanics = value

    def decide(self, conn: sqlite3.Connection, actor: str, now: int) -> Intent | None:
        from agent.volition import seizure
        seized = seizure(conn, actor, now)  # losing control is not something a mind decides
        if seized is not None:
            self.stats["seized"] += 1
            return seized
        scored = self.rule.scored(conn, actor, now)
        wake = wake_reasons(conn, actor, now, scored) if self.client is not None else []
        day = now // 1440
        if not wake or self.used[day] >= self.budget or len(scored) < 2:
            self.stats["rule"] += 1
            return self.rule.pick(scored, actor, now, conn)
        self.used[day] += 1
        top = sorted(scored, key=lambda s: -s[0])[: self.top_k]
        if not any(it is None for _, it in top):
            top.append(next(s for s in scored if s[1] is None) if any(s[1] is None for s in scored) else (0.0, None))
        state = cognitive_state(conn, actor, now, top, wake)
        prompt = PROMPT.format(state=json.dumps(to_dict(state), ensure_ascii=False, sort_keys=True))
        try:
            raw = self.client.generate_json(prompt, CHOICE_SCHEMA, temperature=0.7)
            choice = CognitiveChoice(int(raw["option"]), str(raw.get("reason", ""))[:120], str(raw.get("inner", ""))[:200])
            it = top[choice.option][1]
        except Exception as e:  # unusable or unavailable: live by habit this time
            self.stats["agent_failed"] += 1
            self.log.append({"person": actor, "t": now, "wake": wake, "error": type(e).__name__})
            return self.rule.pick(scored, actor, now, conn)
        self.stats["agent"] += 1
        self.log.append({"person": actor, "t": now, "wake": wake, "chose": state.options[choice.option].text,
                         "reason": choice.reason, "inner": choice.inner})
        if it is None:
            return None
        source = getattr(self.client, "model", "") or "agent"
        return replace(it, reason=f"agent:{choice.reason}"[:300], source=str(source))
