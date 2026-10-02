"""What people say, in the situation they are in (a read model for the God View, the control room and, later, the camera; $0, no model).

`narrative/lines.py` gave each kind of event a handful of fixed sentences, chosen by the event's number. The same cold word was the
same five sentences for everybody, a duel had two, and most of what people did (training, a breakthrough, a loss, an outburst) was
silent. This keeps those as the fall-back and says more, from the state the world was in *just before* the event:

  who is speaking and to whom: how well they know each other, what lies between them (trust, grudge, respect, attraction), who
  they are (honest, hot-tempered, generous, ambitious), what they feel, what each believes the other can do (a duel is asked
  differently of somebody taken for weak), where they are, what time it is, and who is watching.

A line comes with its *subtext* where the situation has one (a cold word to somebody loved, a polite word through a grudge, a
threat out of fear), with the other side's answer, and with what the people watching say (a duel that overturned what the crowd
believed makes the doubters gasp). It is chosen among the lines whose conditions hold, by the event's number, so the same event
always reads the same; and it is not fed back to anyone: characters act on claims, never on these words. Romance stays within
what a public channel shows (a look, an offer of tea, a confession), and every speaker is an adult.

Besides the subtext the relationship gives (the rules in `_talk_subtext`), a line carries what is *underneath the speaker's feeling*
when narrative/inner_state.py can name it from the event that set the feeling and from what held between the two people just
before (surface: angry, underneath: afraid of being left, because event 61). It says nothing when it cannot trace one.

`speech_v0.1`: a draft. The pools are the first writing, in the file to be argued with and extended.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Callable

SPEECH_VERSION = "speech_v0.1"
INNER_SUBTEXT = True      # a switch for experiments (the before/after in docs/speech.md): False says only what the relationship gives
Guard = Callable[["Ctx", str, str], bool] | None


class Ctx:
    """The situation of one event, as of just before it (lazily read, cached)."""

    def __init__(self, conn: sqlite3.Connection, event_id: int, truth: dict, ts: int = 0, place: str = "", names: dict | None = None) -> None:
        self.conn, self.event_id, self.truth, self.ts, self.place = conn, event_id, truth, ts, place
        self.names = names or {}
        self.variant = 0          # a later reading of the same event picks another line (the control room does it for a line already said in the episode)
        self._cache: dict = {}

    def underneath(self, pid: str, addressee: str = "") -> dict | None:
        """What is under what `pid` shows, if it can be traced and has not been said yet (narrative/inner_state.py); None without a world."""
        key = ("inner", pid, addressee)
        if key not in self._cache:
            if self.conn is None or not pid or not INNER_SUBTEXT:
                self._cache[key] = None
            else:
                from narrative.inner_state import inner_subtext
                self._cache[key] = inner_subtext(self.conn, pid, self.event_id, addressee, self.names)
        return self._cache[key]

    def rel(self, a: str, b: str, field: str) -> float:
        key = ("rel", a, b, field)
        if key not in self._cache and self.conn is None:
            return 0.0                                  # (a situation made without a world: nothing is known of it)
        if key not in self._cache:
            from narrative.audience import value_at
            v = value_at(self.conn, "relationship", f"{a}:{b}", field, self.event_id - 1)
            self._cache[key] = float(v) if isinstance(v, (int, float)) else 0.0
        return self._cache[key]

    def trait(self, pid: str, name: str, default: float = 0.5) -> float:
        if ("traits", pid) not in self._cache and self.conn is None:
            return default
        if ("traits", pid) not in self._cache:
            row = self.conn.execute("SELECT traits FROM personas WHERE person_id = ?", (pid,)).fetchone()
            self._cache[("traits", pid)] = json.loads(row[0]) if row else {}
        v = self._cache[("traits", pid)].get(name, default)
        return float(v) if isinstance(v, (int, float)) else default

    def emotion(self, pid: str) -> str:
        if ("emo", pid) not in self._cache and self.conn is None:
            return ""
        if ("emo", pid) not in self._cache:
            from narrative.audience import value_at
            self._cache[("emo", pid)] = str(value_at(self.conn, "person", pid, "emotion", self.event_id - 1) or "")
        return self._cache[("emo", pid)]

    def skill(self, pid: str) -> float:
        if ("skill", pid) not in self._cache and self.conn is None:
            return 0.0
        if ("skill", pid) not in self._cache:
            from narrative.audience import value_at
            v = value_at(self.conn, "var", f"skill.{pid}", "value", self.event_id - 1)
            self._cache[("skill", pid)] = float(v) if isinstance(v, (int, float)) else 0.0
        return self._cache[("skill", pid)]

    @property
    def jianghu(self) -> bool:
        if "jianghu" not in self._cache:
            row = self.conn.execute("SELECT value FROM meta WHERE key = 'recipe_id'").fetchone() if self.conn is not None else None
            if row is None and self.conn is not None:
                try:
                    from world.recipes import recipe_of
                    self._cache["jianghu"] = "jianghu" in str(recipe_of(self.conn))
                except Exception:
                    self._cache["jianghu"] = False
            else:
                self._cache["jianghu"] = bool(row) and "jianghu" in str(row[0])
        return self._cache["jianghu"]

    @property
    def hour(self) -> int:
        return (self.ts % 1440) // 60


def _hash(text: str) -> int:
    return sum((i + 1) * ord(c) for i, c in enumerate(text))


def _pick(pool: list[tuple[str, Guard]], ctx: Ctx, a: str, b: str, salt: str = "") -> str | None:
    """Among the lines whose conditions hold; a line with a condition counts double, so the situation shows."""
    ok = []
    for text, guard in pool:
        if guard is None:
            ok.append(text)
        elif guard(ctx, a, b):
            ok += [text, text]
    if not ok:
        return None
    return ok[(ctx.event_id * 7 + _hash(a + salt) + ctx.variant * 13) % len(ok)]


def _g(*pairs):
    """A pool: plain strings are unconditional, (string, guard) pairs are conditional."""
    return [(p, None) if isinstance(p, str) else p for p in pairs]


# -- conditions -----------------------------------------------------------------------------------------------------
def fond(c, a, b):        return c.rel(a, b, "attraction") >= 0.3 or c.rel(a, b, "affection") >= 0.5
def bitter(c, a, b):      return c.rel(a, b, "resentment") >= 0.3
def knows_well(c, a, b):  return c.rel(a, b, "familiarity") >= 0.4
def respects(c, a, b):    return c.rel(a, b, "respect") >= 0.3
def scorns(c, a, b):      return c.rel(a, b, "respect") <= -0.1 or c.rel(a, b, "estimate") <= c.skill(a) - 0.2
def generous(c, a, b):    return c.trait(a, "generosity") >= 0.6
def honest(c, a, b):      return c.trait(a, "honesty") >= 0.6
def liar(c, a, b):        return c.trait(a, "honesty") <= 0.35
def hot(c, a, b):         return c.trait(a, "temper") >= 0.6
def shy(c, a, b):         return c.trait(a, "temper") <= 0.35 and c.trait(a, "honesty") >= 0.5
def hurting(c, a, b):     return c.emotion(b) in ("hurt", "scared", "uneasy", "ashamed", "embarrassed")
def morning(c, a, b):     return 5 <= c.hour < 11
def evening(c, a, b):     return c.hour >= 18 or c.hour < 4
def stronger(c, a, b):    return c.skill(a) - c.skill(b) >= 0.15
def weaker(c, a, b):      return c.skill(b) - c.skill(a) >= 0.15
def at(*tags):
    def g(c, a, b):
        r = c.conn.execute("SELECT tags FROM locations WHERE id = ?", (c.place,)).fetchone()
        return bool(r) and any(f'"{t}"' in (r[0] or "") for t in tags)
    return g


# -- talk ---------------------------------------------------------------------------------------------------------------
TALK = {
    "warm": _g("今天還好嗎？", "謝謝你啊。", "有你在真好。", "要不要一起坐？", "你今天氣色不錯。",
               ("早啊！昨晚睡得好嗎？", morning), ("還沒回去休息？來，坐一下。", evening),
               ("和你說話，總是特別自在。", fond), ("你來了，我才覺得今天有點意思。", fond),
               ("老樣子？我幫你留了位子。", knows_well), ("需要幫忙的話，儘管開口。", generous),
               ("你看起來不太好，說說看？", hurting), ("你的實力，我是服氣的。", respects)),
    "neutral": _g("嗯。", "喔，是喔。", "最近在忙什麼？", "今天人好多。", "還行吧。",
                  ("這裡的茶還不錯。", at("social")), ("練得怎麼樣？", at("training")), ("早。", morning),
                  ("這麼晚了。", evening), ("你怎麼也在這裡？", knows_well)),
    "cold": _g("隨便你。", "我現在沒空。", "喔。", "你有事嗎？", "別煩我。",
               ("別以為我忘了上次的事。", bitter), ("你說完了嗎？", scorns), ("……沒什麼好說的。", fond),
               ("我很忙，改天。", hot)),
    "hostile": _g("你到底想怎樣？", "你以為你是誰？", "少在那邊裝了！", "我受夠你了！", "你給我說清楚！",
                  ("上次的帳，今天一起算！", bitter), ("就憑你也敢這樣跟我說話？", stronger), ("你再這樣，我不會客氣。", hot),
                  ("別以為沒人看得出來你在做什麼。", scorns)),
}


def _talk_subtext(c: Ctx, a: str, b: str, tone: str) -> str:
    if tone == "warm" and bitter(c, a, b):
        return "話說得客氣，心裡其實還在氣"
    if tone in ("cold", "hostile") and fond(c, a, b):
        return "嘴上冷淡，其實很在意"
    if tone == "hostile" and c.rel(a, b, "fear") >= 0.3:
        return "兇，是因為怕"
    if tone == "neutral" and c.rel(a, b, "attraction") >= 0.4:
        return "想多說幾句，又怕說多了"
    if tone == "warm" and c.rel(a, b, "trust") <= -0.2:
        return "笑著，卻不太相信他"
    if tone in ("neutral", "warm") and c.emotion(a) in ("hurt", "ashamed", "embarrassed", "uneasy"):
        return "心裡有事，沒說出口"
    if tone in ("neutral", "cold") and c.emotion(a) == "angry":
        return "壓著火氣"
    return ""


# what is said when the talk is *about* something (the topics pack records the topic and how it landed)
TOPIC_ZH = {"basketball": "籃球", "fishing": "釣魚", "music": "音樂", "cats": "貓", "cooking": "做菜", "plants": "花草", "old_movies": "老電影", "coffee": "咖啡",
            "reading": "讀書", "money": "錢的事", "gossip": "八卦", "drawing": "畫畫", "games": "遊戲", "travel": "旅行", "fashion": "穿著",
            "swordplay": "劍術", "tea": "茶", "wine": "酒", "poetry": "詩", "herbs": "草藥", "horses": "馬", "chess": "下棋"}
# the same topics, in a martial-arts world's words (the profiles keep the town's topic names; what is *said* should not be anachronistic)
TOPIC_JIANGHU = {"basketball": "拳腳功夫", "fishing": "垂釣", "music": "琴曲", "cooking": "廚藝", "old_movies": "戲文", "coffee": "茶", "money": "銀兩",
                 "drawing": "丹青", "games": "棋局", "travel": "遠遊", "fashion": "衣飾", "reading": "兵書", "plants": "花草", "cats": "貓"}
ABOUT = {
    "bonded": _g("你也喜歡{topic}？太好了！", "說到{topic}，我可以聊一整天。", "原來你也懂{topic}。", ("和你聊{topic}，特別投緣。", fond)),
    "small_talk": _g("最近有碰{topic}嗎？", "你覺得{topic}怎麼樣？", "對了，你對{topic}有什麼看法？", ("上次你說的{topic}，我回去想了很久。", knows_well)),
    "irritated": _g("別再提{topic}了。", "我現在沒心情聊{topic}。", ("你就不能換個話題嗎？", hot)),
    "grated": _g("{topic}？你就只會說這個。", "又是{topic}……"),
    "cheered_up": _g("聊聊{topic}，心情好多了。", "謝謝你，陪我說說{topic}。"),
    "backbiting_refused": _g("別在背後說{other}的壞話。", "我不想聊{other}的事。", ("{other}不在，我們別這樣說他。", honest)),
}


def _about(c: "Ctx", t: dict, a: str, b: str, names: dict) -> tuple[str, str] | None:
    topic, effect = t.get("topic") or "", t.get("topic_effect") or ""
    if not topic or effect not in ABOUT or c.event_id % 10 >= 7:     # most, not all: a person does not always say the topic aloud
        return None
    third = topic[1:] if topic.startswith("@") else ""
    label = names.get(third, third) if third else (TOPIC_JIANGHU if c.jianghu else TOPIC_ZH).get(topic, TOPIC_ZH.get(topic, topic))
    text = _pick(ABOUT[effect], c, a, b, effect)
    return (_fill(text, topic=label, other=label), effect) if text else None


REPLY = {
    "chat": _g("對啊。", "哈哈，真的。", "你也是。", "改天再聊。", "好啊。", ("跟你聊天最輕鬆了。", fond),
               "是啊，我也這麼想。", "說得也是。", "那就這麼說定了。", "有空再坐坐。", "嗯，我記下了。", "哈，你這話倒有意思。",
               ("和你說話，一點也不累。", fond), ("咱們幾個，就數你最懂我。", knows_well)),
    "soothe": _g("好了好了，別生氣。", "我們冷靜一點好不好？", "我不是那個意思。", ("你別這樣，我會難過。", fond),
                 "先消消氣，有話慢慢說。", "是我說重了，你別放在心上。", "別動氣，傷身子。", "咱們坐下來談，行嗎？",
                 ("你生氣，我也不好受。", fond), ("我知道你不是故意的。", respects), "這事不值得鬧僵。", "算了算了，各退一步吧。"),
    "apologize": _g("對不起，是我不好。", "我錯了……", "是我不對，對不起。", ("我說得太過分了，真的抱歉。", honest),
                    "是我欠考慮，你別怪我。", "這件事，我認錯。", "我不該那樣說你。", ("我知道傷了你，我心裡也不好過。", fond),
                    "都是我的不是，給你賠個禮。", "你說得對，是我疏忽了。", "抱歉，讓你難堪了。", "我欠你一句道歉。"),
    "explain": _g("你聽我解釋……", "事情不是你想的那樣。", "我可以說明。", ("你先聽我說完，好嗎？", shy),
                  "你誤會了，聽我從頭說起。", "這裡面有些緣故，容我說說。", "我沒有惡意，你先聽我講。", "別急著下結論。",
                  "我有我的難處。", ("我若有半句假話，你儘管罵我。", honest), "不是這樣的，事情得從頭說。", "給我一點時間，我解釋給你聽。"),
    "deny": _g("我才沒有！", "不是我！", "你有什麼證據？", ("你憑什麼這樣說我？", hot), ("我……沒有，真的沒有。", liar),
               "這話從何說起？", "你找錯人了。", "我連碰都沒碰過。", "誰說的？叫他來當面對質！", "我行得正，坐得直。",
               ("你別血口噴人！", hot), "你這是冤枉好人。"),
    "rebuff": _g("關你什麼事。", "你管太多了。", "我不想談。", ("這是我的事，你別插手。", scorns),
                 "這事你不必過問。", "你還是管好自己吧。", "我的事，我自己會處理。", "別問了。",
                 "你不覺得你問得太多了嗎？", "這不是你該操心的。", ("輪不到你來說我。", scorns), "免談。"),
    "retort": _g("你才是！", "你少管我！", "講這什麼話？", "你憑什麼這樣說我？", "你再說一次看看！",
                 ("你自己又好到哪裡去？", bitter), ("要比，就來比啊！", hot),
                 "有本事你再說一遍！", "你算老幾？", "我的事，輪不到你教訓！", "彼此彼此！", "嘴上說得好聽！",
                 ("別以為我怕你。", hot), ("你別忘了你自己做過什麼。", bitter)),
    "storm_off": _g("我不想再聽了！", "我走了。", "算了！", ("你好自為之。", scorns),
                    "不談了！", "話不投機半句多。", "隨你怎麼想。", "我先走一步。", "夠了，我不奉陪了。",
                    ("你自己想想吧。", scorns), "我去別處待著。", "別跟過來。"),
}
# what two people say to each other just after a duel between them: the one who lost and the one who won (a quarrel's retort after a
# bout is not "你才是！"; whoever lost does not talk like the one who won)
AFTER_DUEL = {
    "lost": _g("……今天算你贏。", "技不如人，我認了。", "我會再練的。", ("下次，我不會輸。", hot), ("你贏了，我服。", honest),
               "你比我強，這我承認。", ("別得意，我還會再來。", bitter), "輸給你，我不甘心。", "這一招，我記住了。", ("……我輸得不冤。", respects)),
    "won": _g("承讓。", "你也不弱，只差一點。", ("別往心裡去。", generous), "今天我運氣好些。", ("想再比，我隨時奉陪。", hot),
              "各憑本事罷了。", ("我不是想羞辱你。", honest), "好好養傷。", ("早就說過，別小看我。", scorns), "這一場，我也不輕鬆。"),
}
DUEL_WINDOW = 12     # events: the talk of the two that comes this soon after their duel is about the duel


INTERVENE = {
    "comfort": _g("別理他，你還好嗎？", "沒事的，我在這。", ("有我在，沒人能欺負你。", fond)),
    "side": _g("你夠了吧！", "有必要這樣嗎？", "你說話客氣一點。", ("人家是我朋友，你說話小心點。", knows_well)),
}
ACCUSE = {"self": _g("是你{act}吧？", "你是不是{act}？", ("我早就知道是你{act}！", bitter), ("我不想這樣想你……可是，是你{act}，對不對？", fond)),
          "other": _g("{text}，你敢說你不知道？", ("{text}。我說得沒錯吧？", hot))}
CONFRONT = {
    "other": _g("你說過{c}，是真的嗎？", "我聽說了：{c}。你要不要解釋一下？", ("你說過{c}。我想聽你親口說。", fond), ("{c}，你還有什麼話要說？", bitter)),
    "self": _g("你說過{c}，是真的嗎？", "有人告訴我，{c}。這是你說的嗎？", ("我不信你會這樣說我。{c}，是真的嗎？", fond), ("{c}，你敢當著我的面再說一次？", bitter)),
    "you": _g("有人說{c}，是真的嗎？", "我聽說了：{c}。你要不要解釋一下？", ("外頭說{c}。我想聽你親口說。", fond), ("{c}，你還有什麼話要說？", bitter)),
}
# What is passed on is a *claim*: somebody did something. It is told in the person's own terms: a thing about the speaker is said in the first
# person ("我弄丟了戒指"), a thing about the listener is "大家都在說你……" (never news about themselves in a stranger's voice), a thing about
# a third person names them. A *tone* claim (a cold word, a hard one) is not news: what is passed on is only that two people are on bad
# (or good) terms, never the system's caption of the event.
TELL = {
    "other": _g("你知道嗎？{c}。", "跟你說喔，{c}。", "我聽說{c}。", ("別告訴別人，{c}。", knows_well), ("你相信嗎？{c}。", fond),
                "聽說了嗎？{c}。", "外頭都在傳，{c}。", ("這話我只跟你說：{c}。", knows_well)),
    "you": _g("大家都在說，{c}。", "有件事你該知道：外頭都在傳，{c}。", ("我不想瞞你，有人說{c}。", fond), "你可能還不知道，有人在說{c}。",
              ("我覺得你應該知道：{c}。", knows_well)),
    "self": _g("我跟你說，{c}。", "有件事我想讓你知道：{c}。", ("這事別往外說，{c}。", knows_well), "{c}，我只告訴你。", ("我只跟你一個人說：{c}。", fond)),
}
TONE_ACTS = ("speak_warm", "speak_neutral", "speak_cold", "speak_hostile")
TONE_GIST = {"speak_cold": ("最近不太對勁", "之間好像隔著什麼", "最近很生分"), "speak_hostile": ("鬧得不愉快", "最近不和", "彼此看不順眼"),
             "speak_warm": ("走得很近", "處得不錯"), "speak_neutral": ("常在一起說話", "時常往來")}


def _ref(pid: str, speaker: str, listener: str, names: dict) -> str:
    return "我" if pid == speaker else "你" if pid == listener else names.get(pid, pid)


def _claim_view(c: "Ctx", t: dict, speaker: str, listener: str, names: dict) -> tuple[str, str]:
    """(the claim as the speaker would put it to the listener, whose business it is: "self" | "you" | "other"). Pronouns for the two of them."""
    claim = t.get("asserted_claim") or t.get("claim") or {}
    subj, act, obj = claim.get("subject", ""), claim.get("act", ""), claim.get("object", "")
    text = t.get("text") or ""
    sname = names.get(subj, "")
    if act in TONE_ACTS and subj and obj:
        gist = TONE_GIST[act][(c.event_id + c.variant) % len(TONE_GIST[act])]
        whose = "you" if listener in (subj, obj) else "self" if speaker in (subj, obj) else "other"
        return f"{_ref(subj, speaker, listener, names)}和{_ref(obj, speaker, listener, names)}{gist}", whose
    if not (sname and text.startswith(sname)):
        return text, "other"
    phrase = text[len(sname):]
    oname = names.get(obj, "")
    if oname and obj in (speaker, listener) and obj != subj:
        phrase = phrase.replace(oname, "我" if obj == speaker else "你")
    return _ref(subj, speaker, listener, names) + phrase, ("self" if subj == speaker else "you" if subj == listener else "other")


OUTCOME = {
    "caught": _g("……好，是我拿的。", ("是又怎樣？", hot), ("對不起……我一時糊塗。", honest)),
    "denied": _g("我沒有拿！", ("你有證據嗎？", liar), ("你怎麼可以這樣懷疑我！", hot)),
    "false": _g("你冤枉我！", ("我什麼都沒做，你為什麼不信我？", fond), ("你這是汙衊！", hot)),
    "lie_exposed": _g("……我說謊了。", ("好吧，我承認。", honest), ("那又怎樣！", hot)),
    "distortion_exposed": _g("我只是說得誇張了一點……", ("我沒有惡意。", generous)),
    "concealment_exposed": _g("我只是沒說全部……", ("我是怕你擔心。", fond)),
    "unfounded": _g("那根本是真的，你在懷疑什麼？", ("你這樣讓我很難受。", fond)),
    "misinformed": _g("我也是聽別人說的……", ("我沒想到會這樣。", shy)),
    "inconclusive": _g("我不知道你在說什麼。", ("你在說什麼？", None)),
}

# -- the martial world ----------------------------------------------------------------------------------------------------
CHALLENGE = _g("來吧，一決高下！", "接招！",
               ("就憑你？來，讓我看看。", scorns), ("聽說你很能打，我不信。", stronger), ("久仰大名，請賜教。", respects),
               ("上次的事，今天了斷！", bitter), ("你比我強，我知道。但我要試試。", weaker), ("我等這一天很久了。", hot))
DUEL_WON = _g("承讓了。", ("你也不錯，再練練吧。", generous), ("這就是你的本事？", scorns), ("好險……", None))
DUEL_LOST = _g("……我輸了。", ("再來一次！", hot), ("我服了。", honest), ("今天算你贏。", bitter))
GASP_SNEERER = _g("怎麼可能……", "這……不可能。", "他什麼時候變得這麼強？", "我看錯他了……", "這不是真的吧？", "我竟然小看了他。",
                  "剛才那一招，我連看都沒看清。", "是我眼拙……", "他藏得真深。", "難道這些年都是我們錯了？")
GASP_OTHER = _g("好身手！", "他竟然贏了！", "沒想到……", "太精彩了。", "原來他一直藏著。", "這一手漂亮！", "今天可開了眼界。",
                "果然不簡單。", "這下子，大家要重新認識他了。", "好！痛快！")

# -- romance (within what a public channel shows) -------------------------------------------------------------------------
FLIRT = _g("今天……有空嗎？", "你笑起來很好看。", "我請你喝一杯？",
           ("那個……你喜歡吃什麼？", shy), ("跟你在一起的時候，時間過得特別快。", fond), ("我留了位子，你要不要坐？", knows_well))
CONFESS = _g("我……喜歡你。", "我想和你在一起。", ("我想了很久，還是得告訴你：我喜歡你。", honest), ("你不用現在回答，我只是不想再瞞著。", shy))
CONFESS_YES = _g("我也是。", "我等你這句話很久了。", ("你終於說了。", fond))
CONFESS_NO = _g("對不起，我只把你當朋友。", "我……沒辦法回應你。", ("謝謝你，可是我不能騙你。", honest))
DATE = _g("和你在一起，很安心。", ("慢慢走吧，不趕時間。", fond))
BREAK_UP = _g("我們……到這裡吧。", ("對不起，我變了。", honest), ("我不想再騙你，也不想再騙我自己。", honest))
BREAK_UP_ANSWER = _g("……我知道了。", "為什麼？", ("我早該想到的。", None))

# -- factions and seats -----------------------------------------------------------------------------------------------------
CAMPAIGN = _g("這次，請支持我。", "我需要你的一票。", ("{title}的位子，我想爭取。", None), ("你知道我會怎麼對待自己人。", generous))
RECRUIT = _g("跟著我，不會虧待你。", "我們這邊需要你。", ("你的本事不該被埋沒。", respects), ("我們都是被看輕的人，不如一起。", scorns))
DEFECT = _g("這裡，我待不下去了。", ("我對得起自己的良心。", honest), ("有些話，我忍了很久。", bitter))
SUCCESSION = _g("我會不負大家所託。", ("從今天起，這個位子我來坐。", hot), ("謝謝大家。我會做給你們看。", generous))
CONGRATS = _g("……恭喜。", "選得好。", ("早晚輪到我。", bitter), ("我輸得心服。", respects))

# -- alone ------------------------------------------------------------------------------------------------------------------
SELF = {
    "train": _g("再一次。", "還差一點。", "呼……再一招。", ("他們都小看我……我要練到讓他們閉嘴。", None)),
    "breakthrough": _g("原來……是這樣！", "我感覺到了。", "這一步，終於跨過去了。"),
    "take": _g("沒人看見……", "只拿這一次。"), "steal": _g("沒人看見……", "對不起，我真的需要。"),
    "misplace": _g("咦，我放哪去了？", "剛剛明明還在手上。"), "find": _g("找到了！", "原來在這裡。"),
    "notice_missing": _g("我的{object}呢？", "{object}不見了……"),
    "regret": _g("我剛才……不該那樣。", "我怎麼會說出那種話。"),
    "smash": _g("夠了！", "我受夠了！"), "break_down": _g("我受不了了……", "為什麼都是我……"),
    "goal_change": _g("{goal}。", "我決定了：{goal}。", "從今天起，{goal}。", "{goal}，我說到做到。"),
}
SELF_STANCE = {"train": "self", "breakthrough": "warm", "take": "self", "steal": "self", "misplace": "self", "find": "warm", "notice_missing": "cool",
               "regret": "cool", "smash": "hot", "break_down": "cool", "goal_change": "self"}
SELF_RARE = {"train": 3}     # these are said once in so many, or the day is all murmuring


def _hidden_gap(c: Ctx, pid: str) -> bool:
    """Does the crowd take somebody for less than they are? (their training is then a thing to hear)"""
    row = c.conn.execute("SELECT AVG(estimate) FROM relationships WHERE target_id = ? AND actor_id != ?", (pid, pid)).fetchone()
    return row is not None and row[0] is not None and c.skill(pid) - float(row[0]) >= 0.15


def _fill(template: str, **kw) -> str:
    class _M(dict):
        def __missing__(self, k):
            return "{" + k + "}"
    return template.format_map(_M(kw))


def _who(truth: dict, key: str) -> str:
    return truth.get(key) or ""


def _after_duel(c: Ctx, a: str, b: str) -> str:
    """"won" or "lost" when `a` has just fought a duel with `b` (within DUEL_WINDOW events and half an hour before this talk), else ""."""
    if c.conn is None or not a or not b or ("duel", a, b) in c._cache:
        return c._cache.get(("duel", a, b), "")
    got = ""
    for ts, truth in c.conn.execute("SELECT timestamp, truth FROM events WHERE type = 'duel' AND event_id < ? AND event_id >= ? ORDER BY event_id DESC",
                                    (c.event_id, c.event_id - DUEL_WINDOW)):
        d = json.loads(truth)
        if {d.get("winner"), d.get("loser")} == {a, b} and (not c.ts or c.ts - ts <= 30):
            got = "won" if d.get("winner") == a else "lost"
            break
    c._cache[("duel", a, b)] = got
    return got


def speak(conn: sqlite3.Connection, event_id: int, etype: str, truth: dict | str, names: dict | None = None, ts: int = 0, place: str = "",
          variant: int = 0) -> dict | None:
    """{"say", "stance", and where there are: "answer", "subtext", "reactions": [{"who", "say"}]} or None for what nobody says aloud.
    `variant`: another reading of the same event (the control room asks for one when a line has already been said in the episode)."""
    t = json.loads(truth) if isinstance(truth, str) else truth
    names = names or {}
    c = Ctx(conn, event_id, t, ts, place, names)
    c.variant = variant
    a, b = _who(t, "actor"), _who(t, "target") or _who(t, "victim") or _who(t, "suspect")
    reason = t.get("reason") or ""
    kind, _, stance = reason.partition(":")
    out: dict | None = None

    if etype == "talk":
        after = _after_duel(c, a, b)
        if after:                                           # just after their bout, the two speak as the one who lost and the one who won
            out = {"say": _pick(AFTER_DUEL[after], c, a, b, after), "stance": stance if kind == "reply" else (t.get("tone") or "neutral")}
        elif kind == "reply" and stance in REPLY:
            out = {"say": _pick(REPLY[stance], c, a, b, stance), "stance": stance}
        elif kind == "intervene" and stance in INTERVENE:
            out = {"say": _pick(INTERVENE[stance], c, a, b, stance), "stance": stance}
        else:
            tone = t.get("tone") or "neutral"
            about = _about(c, t, a, b, names)
            out = {"say": about[0] if about else _pick(TALK.get(tone, TALK["neutral"]), c, a, b, tone), "stance": tone}
            sub = _talk_subtext(c, a, b, tone)
            if sub:
                out["subtext"] = sub
    elif etype == "move" and reason == "reply:storm_off":
        out = {"say": _pick(REPLY["storm_off"], c, a, b), "stance": "storm_off"}
    elif etype == "accuse":
        view, whose = _claim_view(c, t, a, b, names)       # in the two people's own terms: "你拿走了…", never the accused's or the accuser's name
        key, act = ("self", view[1:]) if whose == "you" else ("other", view)
        out = {"say": _fill(_pick(ACCUSE[key], c, a, b) or "", text=view, act=act), "stance": "accuse"}
    elif etype == "confront":
        view, whose = _claim_view(c, t, a, b, names)
        out = {"say": _fill(_pick(CONFRONT[whose], c, a, b) or "", c=view), "stance": "confront"}
    elif etype == "tell":
        view, whose = _claim_view(c, t, a, b, names)
        out = {"say": _fill(_pick(TELL[whose], c, a, b) or "", c=view), "stance": "tell"}
    elif etype in ("lend", "repay"):
        out = {"say": "這些你先拿去用。" if etype == "lend" else "上次借的，還你。", "stance": etype}
    elif etype == "duel":
        out = _duel(c, t, a, b, names)
    elif etype == "flirt":
        out = {"say": _pick(FLIRT, c, a, b), "stance": "flirt"}
    elif etype == "confession":
        accepted = t.get("outcome") == "accepted"
        out = {"say": _pick(CONFESS, c, a, b), "stance": "confession", "answer": _pick(CONFESS_YES if accepted else CONFESS_NO, c, b, a, "ans")}
    elif etype == "date":
        out = {"say": _pick(DATE, c, a, b), "stance": "warm"}
    elif etype == "break_up":
        out = {"say": _pick(BREAK_UP, c, a, b), "stance": "cool", "answer": _pick(BREAK_UP_ANSWER, c, b, a, "ans")}
    elif etype == "campaign":
        title = names.get(t.get("seat") or "", "") or "那個"
        out = {"say": _fill(_pick(CAMPAIGN, c, a, b) or "", title=title), "stance": "campaign"}
    elif etype == "recruit":
        out = {"say": _pick(RECRUIT, c, a, b), "stance": "recruit"}
    elif etype == "defect":
        out = {"say": _pick(DEFECT, c, a, b), "stance": "defect"}
    elif etype == "succession":
        out = _succession(c, t, a)
    elif etype in SELF and a:
        every = SELF_RARE.get(etype, 1)
        if event_id % every:
            return None
        if etype == "train" and not _hidden_gap(c, a):
            pool = [p for p in SELF["train"] if "小看" not in p[0]]
        else:
            pool = SELF[etype]
        goal = (t.get("text") or "").rstrip("。")
        text = _fill(_pick(pool, c, a, a, etype) or "", object=names.get(t.get("object", ""), "東西"), goal=goal or "我換了個目標")
        if text:
            out = {"say": text, "stance": SELF_STANCE.get(etype, "self")}
    if out is not None and not out.get("say"):
        out = None
    if out is not None:
        _with_inner(c, out, etype, a, b)
    if out is None:
        from narrative.lines import line
        out = line(event_id + variant, etype, t, names)         # a domain's event says what the domain gives it (a later reading takes the next line)
    elif t.get("outcome") in OUTCOME and etype in ("accuse", "confront"):
        out["answer"] = _pick(OUTCOME[t["outcome"]], c, b, a, "ans")
    if out is not None:
        _apply_kinship(conn, out, a, b, names)
    return out


GENERIC_SUBTEXT = ("心裡有事，沒說出口", "壓著火氣")      # what a bare emotion gives; a traced reading says more and replaces them


def _with_inner(c: Ctx, out: dict, etype: str, a: str, b: str) -> None:
    """Hang on a line what is underneath the speaker's feeling, where it can be traced to the event that made it (and has not been said)."""
    from narrative.inner_state import ALONE, VOICED_ON
    if etype not in VOICED_ON or not a:
        return                                       # (a thing taken, a goal changed, a drill: murmurs that do not carry a feeling out)
    if out.get("subtext") and out["subtext"] not in GENERIC_SUBTEXT:
        return                                       # the relationship already gave this line its subtext
    state = c.underneath(a, "" if etype in ALONE else b)
    if state is None:
        return
    from narrative.inner_state import phrase
    out["subtext"] = phrase(state)
    out["inner"] = {"surface": state["surface"], "underneath": state["underneath"], "because": state["because"],
                    "confidence": state["confidence"], "rule": state["rule"]}


def _duel(c: Ctx, t: dict, a: str, b: str, names: dict) -> dict:
    out = {"say": _pick(CHALLENGE, c, a, b), "stance": "duel"}
    winner, loser = t.get("winner"), t.get("loser")
    if winner and loser:
        # the answer comes from the one challenged: how they take the result
        target = b if b in (winner, loser) else loser
        out["answer"] = _pick(DUEL_WON if target == winner else DUEL_LOST, c, target, a if target == b else b, "ans")
    reactions = []
    slap = t.get("slap") or {}
    sneered = set(slap.get("sneered") or [])
    for pid in sorted((t.get("gaps") or {}).keys()):
        if pid in (a, b) or len(reactions) >= 3:
            continue
        pool = GASP_SNEERER if pid in sneered else GASP_OTHER
        if slap or pid in sneered:
            base, line = c.variant, _pick(_g(*pool), c, pid, winner or a, "react")
            for _ in range(len(pool)):                    # two watchers do not gasp the same words
                if line not in {r["say"] for r in reactions}:
                    break
                c.variant += 1
                line = _pick(_g(*pool), c, pid, winner or a, "react")
            c.variant = base
            reactions.append({"who": pid, "say": line})
    if reactions:
        out["reactions"] = reactions
    return out


def _succession(c: Ctx, t: dict, a: str) -> dict:
    winner = t.get("winner") or a
    out = {"say": _pick(SUCCESSION, c, winner, winner), "stance": "succession"}
    reactions = []
    for pid in t.get("candidates") or []:
        if pid != winner and len(reactions) < 2:
            reactions.append({"who": pid, "say": _pick(CONGRATS, c, pid, winner, "react")})
    if reactions:
        out["reactions"] = reactions
    return out


OUTCOME_EVENTS = ("duel", "challenge", "confront", "accuse")   # their line reads the result; a mind's reason was written before it


def _listener_name(conn: sqlite3.Connection | None, listener: str, names: dict | None) -> str:
    if names and names.get(listener):
        return str(names[listener])
    if conn is None or not listener:
        return ""
    row = conn.execute("SELECT name FROM people WHERE id = ?", (listener,)).fetchone()
    return row[0] if row else ""


def _open_as_kin(conn: sqlite3.Connection | None, speaker: str, listener: str, text: str, names: dict | None) -> str:
    """A line said *to* the listener that opens with their name ("林嘯，……") uses the kinship term ("林師兄，……").

    The surname is the first character of the name. A line that does not open that way — gossip that names somebody else,
    a subtitle, a thought — is returned unchanged. No term (another sect, not a jianghu world) leaves the name as it is.
    """
    if not isinstance(text, str) or not text or conn is None or not speaker or not listener or speaker == listener:
        return text
    name = _listener_name(conn, listener, names)
    if not name or not text.startswith(name + "，"):
        return text
    from narrative.address import address
    term = address(conn, speaker, listener)
    if not term:
        return text
    return name[0] + term + text[len(name):]


def _apply_kinship(conn: sqlite3.Connection | None, out: dict, speaker: str, listener: str, names: dict | None) -> dict:
    """Direct speech only: what the speaker says to the listener, and the listener's answer back. Not reactions or subtext."""
    if out.get("say"):
        out["say"] = _open_as_kin(conn, speaker, listener, out["say"], names)
    if out.get("answer"):
        out["answer"] = _open_as_kin(conn, listener, speaker, out["answer"], names)
    if out.get("opening"):
        out["opening"] = _open_as_kin(conn, speaker, listener, out["opening"], names)
    return out


def in_own_words(spoken: dict | None, mind: dict | None, era_words: tuple[str, ...] = (), etype: str = "",
                 *, conn: sqlite3.Connection | None = None, speaker: str = "", listener: str = "",
                 names: dict | None = None) -> dict | None:
    """When a character's mind decided the event, let them be heard in their own words (a read model, like everything here).

    A mind's `reason` is either a line said to somebody ("阿豪，你少在那邊假好心打聽我的事。") or the person explaining to themselves
    ("小美懂音樂，和她聊這個比較不會踩到地雷。"). Measured on 230 recorded decisions, only 21 (9%) are addressed. So: an addressed reason
    is what they say (the template line is kept as `template`); anything else is a `monologue`, heard as a thought, never said to the other.
    A reason with a word out of its era (`era_words`) is not used at all: the template stays. In an event whose line reads its result (a duel
    won or lost), the reason was written before the result: it is said first (`opening`), and the line that reads the result stays.
    A line that opens by naming the listener ("林嘯，……") is said with the kinship term ("林師兄，……") when `conn` names the two of them.
    """
    if not mind or not str(mind.get("reason", "")).strip():
        return spoken
    said = str(mind.get("say", "") or "").strip()
    if said and not any(w in said for w in era_words):   # prompt v3: the words said out loud, given as such
        out = dict(spoken or {"say": "", "answer": "", "subtext": "", "reactions": []})
        if etype in OUTCOME_EVENTS:
            out["opening"] = said
        else:
            out["template"], out["say"], out["own"], out["subtext"] = out.get("say", ""), said, True, ""
        out["monologue"] = str(mind.get("reason", "")).strip()
        if out["monologue"].startswith("agent:"):
            out["monologue"] = out["monologue"][len("agent:"):].strip()
        return _apply_kinship(conn, out, speaker, listener, names)
    reason = str(mind["reason"]).strip()
    if reason.startswith("agent:"):
        reason = reason[len("agent:"):].strip()
    if any(w in reason for w in era_words):
        return spoken
    out = dict(spoken or {"say": "", "answer": "", "subtext": "", "reactions": []})
    if "你" in reason and etype in OUTCOME_EVENTS:
        out["opening"] = reason
    elif "你" in reason:
        out["template"], out["say"], out["own"] = out.get("say", ""), reason, True
        out["subtext"] = ""       # what they think underneath is the mind's own `inner`, shown beside it
    else:
        out["monologue"] = reason
    return _apply_kinship(conn, out, speaker, listener, names)
