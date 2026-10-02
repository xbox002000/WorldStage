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

When the provider's free quota is what runs out (not one bad answer), a run that wants a pure world stops instead of
letting the rule agent finish the day: `pause_on_quota` raises QuotaPause, the day is thrown away and replayed later
from the cache, where everything already paid for costs nothing (soul_lab.py).
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
MOOD_ONLY = "心情很糟"       # a wake point with nothing else behind it: tier B (a bad mood alone seldom changes what is chosen)


def option_order(world_seed, actor: str, now: int, n: int) -> list[int]:
    """The order the options are shown in: a shuffle that is the same every time for the same world, person and moment."""
    from world.rng import rng
    order = list(range(n))
    rng(world_seed, now, actor, "soul_option_order").shuffle(order)
    return order


class QuotaPause(RuntimeError):
    """The free quota is spent: stop at this decision, do not let the rule agent finish the day."""
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
# Prompt v2 (CharacterAgent(prompt_version=2)): v1 above stays byte for byte what the recorded worlds were asked (their answers are cached by the
# whole prompt). v2 adds the era of the world, who is a he and who a she, and that the reason must be about the option chosen; and its answers are
# checked (check_answer). It is for worlds made from now on: a v2 prompt is a different prompt, so it never meets a v1 answer.
PROMPT_V2 = """你是一個持續運轉的虛擬世界裡的一個人。{era}下面是你此刻知道的一切（JSON）：你是誰、你想要和害怕什麼、你的感受、
你的目標、你眼前的人和你對他們的看法、你記得的事，以及你現在做得到的事（options，已編號）。

只能從 options 裡選一個（回答它的編號 n）。你不知道清單以外的任何事，也不能做清單以外的事。
像這個人一樣選：照他的個性、價值、傷口、此刻的心情和處境，而不是照「正確答案」。好人也會選錯，會嘴硬，會逃避。

{state}

{pronouns}用 JSON 回答：option（編號）、reason（一句話，用你自己的口吻，繁體中文。它說的必須是你選的那一項：選了誰、做什麼，就講那個人和那件事，不要提到別的選項裡的人或事）、inner（你心裡真正的想法，不會說出口，可以留空）。
"""
# v3 = v2 and one more answer: `say`, the words said out loud to the other (or nothing). v2's reason came back as first-person narration
# ("我走近柳含霜身旁…") in 59 of 59 answers, so nobody on screen ever said anything of their own. v1 and v2 are unchanged (their caches stay valid).
PROMPT_V3 = PROMPT_V2.replace("、inner（你心裡真正的想法，不會說出口，可以留空）。",
                              "、say（你此刻開口說出的那一句話，直接對著對方說，用你自己的口吻；你選的是不說話或不對人的事，就留空）、"
                              "inner（你心裡真正的想法，不會說出口，可以留空）。")
CHOICE_SCHEMA_V3 = {"type": "object",
                    "properties": {"option": {"type": "integer"}, "reason": {"type": "string"}, "say": {"type": "string"}, "inner": {"type": "string"}},
                    "required": ["option", "reason"]}
PROMPT_VERSIONS = (1, 2, 3)
PROMPT_V2_VERSION = "cognition_prompt_v2"
PROMPT_V3_VERSION = "cognition_prompt_v3"   # contracts/versions.py: the newest prompt
# the era a world is in, from its recipe's core (what the world is about): said once in a v2 prompt, and the modern words below are refused in it
ERA_LINES = {
    "martial_arts": "這裡是古代的江湖：沒有手機、咖啡、辦公室、電影，也沒有大學或公司；人們說的是師門、鏢局、客棧、銀兩，用的是劍、茶與酒。你想的和說的，都要像這個時代的人。",
}
ERA_LABELS = {  # how an option reads in an era whose people would not say it the way the domain's label does (a v2 prompt only)
    "martial_arts": {"break_up": "向{t}說清楚，從此不再往來", "date": "和{t}相處"},
}
MODERN_WORDS = (  # things a jianghu has no word for: a reason or an inner thought with one of these is refused (v2, a jianghu world)
    "手機", "電話", "簡訊", "電腦", "網路", "網站", "影片", "直播", "社群", "咖啡", "冰咖啡", "辦公室", "加班", "上班", "下班", "同事",
    "老闆", "主管", "公司", "薪水", "業績", "電影", "電視", "專輯", "籃球", "足球", "電玩", "遊戲機", "大學", "學校", "汽車", "機車", "捷運",
    "火車", "飛機", "機票", "超商", "便利商店", "信用卡", "銀行", "多肉", "新手機", "咖啡店", "手錶", "眼鏡", "耳機",
)
SINGULAR_PRONOUN = {"他": "male", "她": "female"}
NOT_A_PERSON = ("他們", "她們", "其他", "他人", "他鄉", "他日", "他處", "他方", "他事", "別他", "其他人", "吉他", "排他")
GENDER_WORD = {"male": "男", "female": "女"}
PRONOUN_OF = {"male": "他", "female": "她"}


class AnswerRejected(ValueError):
    """The mind answered, and the answer is not one to act on (a word the world does not have, a reason about another option, the wrong he or she):
    the rule agent decides this time. It is not a failure of the provider, so it does not count towards stopping a run."""


def world_era(conn: sqlite3.Connection) -> str:
    """What kind of world this is, from its recipe's core ('' when nothing is said of it)."""
    try:
        from world.recipes import load_recipe, recipe_of
        return load_recipe(recipe_of(conn)).core
    except Exception:
        return ""


def _gender_of(conn: sqlite3.Connection, pid: str) -> str:
    from world.profiles import profile
    p = profile(conn, pid)
    return p.gender if p is not None and p.gender in PRONOUN_OF else ""


def pronoun_line(conn: sqlite3.Connection, state_text: str) -> str:
    """Who is a he and who a she, for every person the state names (empty when nobody's sex is known)."""
    rows = [(r[0], r[1]) for r in conn.execute("SELECT id, name FROM people ORDER BY id")]
    named = [f"{name}＝{PRONOUN_OF[g]}" for pid, name in rows if name and name in state_text and (g := _gender_of(conn, pid))]
    return ("人物的稱呼（說到他們時，男的只用「他」，女的只用「她」，不要用錯）：" + "、".join(named) + "。\n\n") if named else ""


def check_answer(conn: sqlite3.Connection, actor: str, shown: list, texts: list[str], chosen: int, reason: str, inner: str) -> None:
    """Is the answer one to act on? Raises AnswerRejected (with why) when it is not. `texts` are the options as the mind read them. Three things are refused (v2):
      - a word the world's era does not have (MODERN_WORDS) in the reason or the inner thought;
      - a reason that is about another option: it names a person or a thing that belongs to other options only, and none of the chosen one's;
      - a he or a she that is not who the answer is about: with the people the answer names (and the one the chosen option is aimed at) all of
        one sex, the other pronoun is wrong.
    These are checks of the words, not of the thought: a reason that is fine and merely odd is let through."""
    text = f"{reason}{inner}"
    if ERA_LINES.get(world_era(conn)):
        hit = next((w for w in MODERN_WORDS if w in text), "")
        if hit:
            raise AnswerRejected(f"a word the world does not have: {hit}")
    people = {r[0]: r[1] for r in conn.execute("SELECT id, name FROM people") if r[1] and r[0] != actor}
    things = {r[0]: r[1] for r in conn.execute("SELECT id, name FROM objects") if r[1]}
    mine = conn.execute("SELECT name FROM people WHERE id = ?", (actor,)).fetchone()
    self_name = mine[0] if mine else ""
    known = {**people, **things}

    def belongs(k: int) -> set[str]:
        it = shown[k][1]
        if it is None:
            return set()
        label = texts[k].replace(self_name, "") if self_name else texts[k]
        return {i for i, n in known.items() if n in label or i == (it.target or "")}

    chosen_set = belongs(chosen)
    others = set().union(*[belongs(k) for k in range(len(shown)) if k != chosen]) - chosen_set
    named = {i for i, n in known.items() if n in reason}
    if chosen_set and named and not (named & chosen_set) and (named & others):
        raise AnswerRejected("the reason is about another option: " + "、".join(sorted(known[i] for i in named & others)))
    plain = text
    for w in NOT_A_PERSON:
        plain = plain.replace(w, "")
    used = {g for p_, g in SINGULAR_PRONOUN.items() if p_ in plain}
    referents = {i for i in people if people[i] in text} | {i for i in chosen_set if i in people}
    if used and referents:
        sexes = {_gender_of(conn, i) for i in referents} - {""}
        if len(sexes) == 1 and not (used & sexes):
            raise AnswerRejected(f"the pronoun is for {'/'.join(sorted(used))}, the answer is about {next(iter(sexes))}")


def _names(conn: sqlite3.Connection) -> dict[str, str]:
    from world.claims import labels
    out = labels(conn)
    out.update({r[0]: r[1] for r in conn.execute("SELECT id, name FROM locations")})
    return out


def describe_intent(conn: sqlite3.Connection, it: Intent | None, names: dict[str, str], version: int = 1) -> str:
    """An option as the person would think of it. Version 2 says it in the world's own words: the topic by the roster's label of it (a jianghu's
    劍法, never a town's 音樂), a job's actions by the person's own words for it (偷偷打聽別的門派), and a few labels by the era's."""
    if it is None:
        return "什麼都不做"
    t = names.get(it.target or "", it.target or "")
    if version >= 2:
        from world.profiles import topics as world_topics
        label = world_topics(conn)
        if it.action == "talk" and it.topic and not it.topic.startswith("@") and it.topic in label:
            return f"{TONE_WORDS.get(it.tone or '', '')}對{t}說話（聊{label[it.topic]}）"
        if it.action in ("look_for_work", "accept_offer"):
            from world.domains.work import words
            w = words(conn, it.actor)
            return f"偷偷{w['look']}" if it.action == "look_for_work" else f"接受邀請，{w['quit']}"
        era = ERA_LABELS.get(world_era(conn), {})
        if it.action in era:
            return era[it.action].format(t=t)
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


def cognitive_state(conn: sqlite3.Connection, pid: str, now: int, options: list, wake: list[str], version: int = 1) -> CognitiveState:
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
        if version >= 2 and p.gender in PRONOUN_OF:
            who = {"性別": f"{GENDER_WORD[p.gender]}（{PRONOUN_OF[p.gender]}）", **who}
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
        options=[OptionView(n, it.action if it else "idle", (it.target or "") if it else "", describe_intent(conn, it, names, version))
                 for n, (_, it) in enumerate(options)],
        wake=wake)


class CharacterAgent:
    """A decider: the rule agent's life, and a mind that wakes at wake points.

    client: anything with generate_json(prompt, schema, temperature) -> dict (agent/llm.py LLMClient or FallbackClient,
    a stub in tests). budget: wake-ups a day for the whole world. top_k: how many of the most wanted options it sees.
    """

    def __init__(self, rule, client=None, budget: int = 20, top_k: int = 7, tier: str = "AB", pause_on_quota: bool = False,
                 per_person_day: int | None = None, shuffle=False, prompt_version: int = 1) -> None:
        if tier not in ("A", "AB"):
            raise ValueError("tier is 'A' (a value crossed, a clash, a resolve) or 'AB' (and a bad mood on its own)")
        if prompt_version not in PROMPT_VERSIONS:
            raise ValueError(f"prompt_version is one of {PROMPT_VERSIONS}")
        # 1 (the default): the prompt the recorded worlds were asked; 2: era, who is he or she, a reason about the option chosen, and a checked answer.
        # A world made with v2 says so (meta 'prompt_version', written by soul_lab.py --prompt-version 2): whoever replays it from its cache passes that.
        self.prompt_version = prompt_version
        self.tier = tier
        self.per_person_day = per_person_day   # most times one person's mind wakes in a day: the same wake point fires again and again with nearly the same state
        # the options are shown in a deterministic shuffled order, so the first line is not the rule's favourite: True, or a function
        # (actor, now, n) -> a permutation (soul_lab keeps the one its recorded answers were asked with)
        self.shuffle = shuffle
        self.woke_today: Counter = Counter()   # (day, person) -> wake-ups
        self.pause_on_quota = pause_on_quota
        self.max_streak = 5              # with pause_on_quota: this many failures in a row (a wrong model name, a dead key) stop the run
        self._streak = 0
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
        if self.tier == "A" and wake and all(w.startswith(MOOD_ONLY) for w in wake):
            self.stats["mood_only_skipped"] += 1
            wake = []
        day = now // 1440
        if wake and self.per_person_day is not None and self.woke_today[(day, actor)] >= self.per_person_day:
            self.stats["person_capped"] += 1
            wake = []
        if not wake or self.used[day] >= self.budget or len(scored) < 2:
            self.stats["rule"] += 1
            return self.rule.pick(scored, actor, now, conn)
        self.used[day] += 1
        self.woke_today[(day, actor)] += 1
        top = sorted(scored, key=lambda s: -s[0])[: self.top_k]
        if not any(it is None for _, it in top):
            top.append(next(s for s in scored if s[1] is None) if any(s[1] is None for s in scored) else (0.0, None))
        order = list(range(len(top)))                # order[k] = the rank (0 = what the rules want most) of the option shown k-th
        if self.shuffle:
            order = self.shuffle(actor, now, len(top)) if callable(self.shuffle) else option_order(self.rule.world_seed, actor, now, len(top))
        shown = [top[i] for i in order]
        version = self.prompt_version
        state = cognitive_state(conn, actor, now, shown, wake, version)
        state_text = json.dumps(to_dict(state), ensure_ascii=False, sort_keys=True)
        if version >= 2:
            era = ERA_LINES.get(world_era(conn), "")
            prompt = (PROMPT_V3 if version >= 3 else PROMPT_V2).format(state=state_text, era=era, pronouns=pronoun_line(conn, state_text))
        else:
            prompt = PROMPT.format(state=state_text)
        try:
            raw = self.client.generate_json(prompt, CHOICE_SCHEMA_V3 if version >= 3 else CHOICE_SCHEMA, temperature=0.7)
            choice = CognitiveChoice(int(raw["option"]), str(raw.get("reason", ""))[:120], str(raw.get("inner", ""))[:200])
            say = str(raw.get("say", "") or "").strip()[:120] if version >= 3 else ""
            if not 0 <= choice.option < len(shown):   # a negative number would silently count from the end
                raise ValueError(f"option {choice.option} is not on the list")
            if version >= 2:
                check_answer(conn, actor, shown, [o.text for o in state.options], choice.option, choice.reason, choice.inner + say)
            it = shown[choice.option][1]
            rank = order[choice.option]
        except Exception as e:  # unusable or unavailable: live by habit this time
            from agent.llm import BudgetExceeded
            if self.pause_on_quota and (isinstance(e, BudgetExceeded) or "all models are unavailable" in str(e)):
                self.used[day] -= 1
                self.woke_today[(day, actor)] -= 1
                raise QuotaPause(str(e)) from e
            if isinstance(e, AnswerRejected):  # the provider did answer: this is about the words, not about a dead key or a spent quota
                self._streak = 0
                self.stats["agent_failed"] += 1
                self.stats["agent_rejected"] += 1
                self.log.append({"person": actor, "t": now, "wake": wake, "error": "AnswerRejected", "why": str(e)})
                return self.rule.pick(scored, actor, now, conn)
            self._streak += 1
            if self.pause_on_quota and self._streak >= self.max_streak:
                self.used[day] -= 1
                self.woke_today[(day, actor)] -= 1
                raise QuotaPause(f"{self._streak} answers in a row failed (last: {type(e).__name__}: {str(e)[:120]})") from e
            self.stats["agent_failed"] += 1
            self.log.append({"person": actor, "t": now, "wake": wake, "error": type(e).__name__})
            return self.rule.pick(scored, actor, now, conn)
        self._streak = 0
        self.stats["agent"] += 1
        self.log.append({"person": actor, "t": now, "wake": wake, "chose": state.options[choice.option].text,
                         "reason": choice.reason, "inner": choice.inner, "option": rank, "shown_at": choice.option,
                         "rule_top": state.options[order.index(0)].text, "differs": rank != 0, "of": len(state.options), **({"say": say} if say else {})})
        if it is None:
            return None
        source = getattr(self.client, "model", "") or "agent"
        return replace(it, reason=f"agent:{choice.reason}"[:300], source=str(source))
