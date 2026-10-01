"""What an event would sound like: one short spoken line per social event, for the God View's speech bubbles.

A read model, not dialogue truth. The world records who said what kind of thing to whom (a tone, a stance, a claim);
this turns that into a line a viewer can read, chosen by the event id among a few phrasings, so the same event always
reads the same. Nothing here is fed back to anyone: characters act on claims, never on these words.
"""
from __future__ import annotations

import json

LINES = {
    ("talk", "warm"): ["今天還好嗎？", "謝謝你啊。", "有你在真好。", "要不要一起坐？", "你今天氣色不錯。"],
    ("talk", "neutral"): ["嗯。", "喔，是喔。", "最近在忙什麼？", "今天人好多。", "還行吧。"],
    ("talk", "cold"): ["隨便你。", "我現在沒空。", "喔。", "你有事嗎？", "別煩我。"],
    ("talk", "hostile"): ["你到底想怎樣？", "你以為你是誰？", "少在那邊裝了！", "我受夠你了！", "你給我說清楚！"],
    ("reply", "chat"): ["對啊。", "哈哈，真的。", "你也是。", "改天再聊。", "好啊。"],
    ("reply", "soothe"): ["好了好了，別生氣。", "我們冷靜一點好不好？", "我不是那個意思。"],
    ("reply", "apologize"): ["對不起，是我不好。", "我錯了……", "是我不對，對不起。"],
    ("reply", "explain"): ["你聽我解釋……", "事情不是你想的那樣。", "我可以說明。"],
    ("reply", "deny"): ["我才沒有！", "不是我！", "你有什麼證據？"],
    ("reply", "rebuff"): ["關你什麼事。", "你管太多了。", "我不想談。"],
    ("reply", "retort"): ["你才是！", "你少管我！", "講這什麼話？", "你憑什麼這樣說我？", "你再說一次看看！"],
    ("reply", "storm_off"): ["我不想再聽了！", "我走了。", "算了！"],
    ("intervene", "comfort"): ["別理他，你還好嗎？", "沒事的，我在這。"],
    ("intervene", "side"): ["你夠了吧！", "有必要這樣嗎？", "你說話客氣一點。"],
    ("confront", ""): ["你說過「{text}」，是真的嗎？", "我聽說了：{text}。你要不要解釋一下？"],
    ("accuse", ""): ["是你{act}吧？", "你是不是{act}？"],
    ("accuse", "other"): ["{text}，你敢說你不知道？"],
    ("tell", ""): ["你知道嗎？{text}。", "跟你說喔，{text}。", "我聽說{text}。"],
    ("lend", ""): ["這些你先拿去用。"], ("repay", ""): ["上次借的，還你。"],
}
OUTCOME = {  # how the other one's answer to an accusation or a confrontation sounds, by what the world decided
    "caught": "……好，是我拿的。", "denied": "我沒有拿！", "false": "你冤枉我！",
    "lie_exposed": "……我說謊了。", "distortion_exposed": "我只是說得誇張了一點……", "concealment_exposed": "我只是沒說全部……",
    "unfounded": "那根本是真的，你在懷疑什麼？", "misinformed": "我也是聽別人說的……", "inconclusive": "我不知道你在說什麼。",
}


class _Words(dict):
    """A domain's line may use the event's own words ({overtime} -> 加練); a missing one stays as it is."""

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def _pick(options: list[str], event_id: int) -> str:
    return options[event_id % len(options)]


def line(event_id: int, etype: str, truth: dict | str, names: dict | None = None) -> dict | None:
    """{"say": the line, "answer": the other's answer (accusations and confrontations), "stance": how it was meant}
    or None for events nobody says aloud."""
    t = json.loads(truth) if isinstance(truth, str) else truth
    reason = t.get("reason") or ""
    kind, _, stance = reason.partition(":")
    if etype == "talk":
        if kind in ("reply", "intervene") and (kind, stance) in LINES:
            return {"say": _pick(LINES[(kind, stance)], event_id), "stance": stance}
        tone = t.get("tone") or "neutral"
        return {"say": _pick(LINES[("talk", tone)], event_id), "stance": tone}
    if etype == "move" and reason == "reply:storm_off":
        return {"say": _pick(LINES[("reply", "storm_off")], event_id), "stance": "storm_off"}
    if (etype, "") not in LINES:
        from world.domains import style
        st = style(etype)  # a domain's event says what the domain gives it
        if st is None or not st.lines:
            return None
        return {"say": _pick(list(st.lines), event_id).format_map(_Words(t)), "stance": etype}
    text = t.get("text") or ""
    key = (etype, "")
    act = text
    if etype == "accuse":  # "阿俊拿走了錢包", said to 阿俊: "是你拿走了錢包吧？"
        subject = (t.get("claim") or {}).get("subject")
        name = (names or {}).get(subject, "")
        if subject == t.get("target") and name and text.startswith(name):
            act = text[len(name):]
        else:
            key = ("accuse", "other")
    out = {"say": _pick(LINES[key], event_id).format(text=text, act=act), "stance": etype}
    if t.get("outcome") in OUTCOME:
        out["answer"] = OUTCOME[t["outcome"]]
    return out
