"""Dialogue for scene cards: written by a language model, from what each speaker knows, and checked before it is kept.

On the plot engine's path this replaces the fixed line bank of narrative/lines.py: the model gets the scene card (POV,
question, turn) and, for each person, only the facts the knowledge gate allows them at the scene's time; it answers with lines
that name the facts they stand on. Every line goes through `KnowledgeGate.check_line` before the scene is accepted. A scene whose
lines fail is asked again once with the reasons; if it still fails it is written by the offline writer instead, and the
failure is kept in the scene's record.

`OfflineWriter` is deterministic and needs no network (tests, `--dry`): the anchor's own spoken line (lines.py's phrasing, the
world's words), the other one's answer, and the POV's thought on the latest fact they know of the story, in their own belief.
"""
from __future__ import annotations

import json

from worldstage.narrative.ledger import FactLedger, KnowledgeGate
from worldstage.narrative.lines import line as bank_line
from worldstage.narrative.scene_cards import SceneCard

NARRATOR = "旁白"
PRICES = {"gemini-3.5-flash-lite": (0.30, 2.50)}   # USD per 1M tokens (input, output), ai.google.dev pricing, standard paid tier
OUT_TOKENS_PER_SCENE = 450
RETRY_RATE = 0.3
SCHEMA = {
    "type": "object",
    "properties": {"lines": {"type": "array", "items": {"type": "object", "properties": {
        "speaker": {"type": "string"}, "text": {"type": "string"}, "uses": {"type": "array", "items": {"type": "integer"}},
        "kind": {"type": "string", "enum": ["say", "inner", "action"]}}, "required": ["speaker", "text", "uses", "kind"]}}},
    "required": ["lines"],
}


def _narration(ledger: FactLedger, card: SceneCard) -> dict:
    f = ledger.facts[card.anchor]
    return {"speaker": NARRATOR, "text": f"【{card.location or '某處'}・第{f.day + 1}天】{f.summary}。", "uses": [card.anchor], "kind": "narration"}


class OfflineWriter:
    name = "offline"

    def write(self, ledger: FactLedger, card: SceneCard, gate: KnowledgeGate) -> list[dict]:
        f = ledger.facts[card.anchor]
        out = [_narration(ledger, card)]
        b = bank_line(f.fact_id, f.type, f.truth, ledger.names)
        if b and f.actor:
            say = _address(b["say"], ledger.name(f.actor), ledger.name(f.target) if f.target else "")
            out.append({"speaker": f.actor, "text": say, "uses": [f.fact_id], "kind": "say"})
            if b.get("answer") and f.target:
                answer = b["answer"]
                if f.truth.get("outcome") == "caught" and (f.truth.get("claim") or {}).get("act") not in ("steal", "take"):
                    answer = "……是，是我。"
                out.append({"speaker": f.target, "text": answer, "uses": [f.fact_id], "kind": "say"})
        # the POV's thought: the latest earlier fact of the story they know, in their own belief (it may be wrong)
        mine = [x for x in card.known.get(card.pov, []) if x != f.fact_id and ledger.facts[x].ts < f.ts
                and ledger.facts[x].type != "talk" and ledger.facts[x].importance >= 0.4]
        story = [x for x in mine if set(ledger.facts[x].participants) & set(card.cast) - {card.pov}] or mine
        if card.recall:
            story = [x for x in story if x in card.recall] or story
        if story:
            fid = story[-1]
            k = ledger.how(card.pov, fid)
            out.append({"speaker": card.pov, "text": f"（心想）{_address(k.belief, ledger.name(card.pov), '')}……{_feel(card)}", "uses": [fid], "kind": "inner"})
        else:
            out.append({"speaker": card.pov, "text": f"（心想）{_feel(card)}", "uses": [], "kind": "inner"})
        return out


def _address(text: str, speaker: str, listener: str) -> str:
    """Spoken to somebody, a sentence names its speaker as 我 and its listener as 你."""
    if speaker:
        text = text.replace(speaker, "我")
    if listener:
        text = text.replace(listener, "你")
    return text


def _feel(card: SceneCard) -> str:
    return f"本來是{card.turn['before']}，現在{card.turn['after']}了。"


def prompt_for(ledger: FactLedger, card: SceneCard) -> str:
    def fact_line(pid: str, fid: int) -> str:
        k = ledger.how(pid, fid)
        return f"  - [{fid}] 第{ledger.facts[fid].day + 1}天：{k.belief}（{k.how}）"
    people = []
    for p in card.cast:
        facts = card.known.get(p, [])[-12:]
        people.append(f"{ledger.name(p)}（id={p}）只知道：\n" + ("\n".join(fact_line(p, x) for x in facts) or "  （沒有）"))
    f = ledger.facts[card.anchor]
    return (
        "你是武俠劇的對白編劇。只根據下列世界事實寫這一場的台詞，不得新增事件。\n"
        f"場景：{card.location}，第{f.day + 1}天。這場真正發生的事：{f.summary}（事件 {f.fact_id}）\n"
        f"視角人物：{ledger.name(card.pov)}。懸念問題：{card.question}\n"
        f"轉折：{card.turn['before']} → {card.turn['after']}\n"
        "每個人只能說或想自己知道的事；用到哪件事就把它的編號放進 uses。說話者只能是在場的人。\n"
        + "\n".join(people) +
        "\n寫 4 到 8 行，繁體中文，口語、有潛台詞，最後一行要落在轉折上。"
    )


def estimate_tokens(text: str) -> int:
    cjk = sum(1 for ch in text if ord(ch) > 0x2E80)
    return cjk + (len(text) - cjk) // 4 + 1


def estimate_cost(ledger: FactLedger, cards: list[SceneCard], model: str) -> dict:
    tin = sum(estimate_tokens(prompt_for(ledger, c)) for c in cards)
    tout = OUT_TOKENS_PER_SCENE * len(cards)
    tin, tout = int(tin * (1 + RETRY_RATE)), int(tout * (1 + RETRY_RATE))
    pin, pout = PRICES.get(model, (0.30, 2.50))
    return {"model": model, "scenes": len(cards), "input_tokens": tin, "output_tokens": tout,
            "usd": round(tin / 1e6 * pin + tout / 1e6 * pout, 4)}


class LLMWriter:
    name = "llm"

    def __init__(self, client, fallback: OfflineWriter | None = None) -> None:
        self.client, self.fallback = client, fallback or OfflineWriter()
        self.rejected: list[dict] = []

    def write(self, ledger: FactLedger, card: SceneCard, gate: KnowledgeGate) -> list[dict]:
        prompt = prompt_for(ledger, card)
        for attempt in range(2):
            raw = self.client.generate_json(prompt, SCHEMA, temperature=0.8)
            lines = [dict(x, uses=[int(u) for u in x.get("uses", [])]) for x in raw.get("lines", [])]
            bad = []
            for x in lines:
                if x["speaker"] not in card.cast:
                    bad.append(f"{x['speaker']} 不在場")
                    continue
                bad += [v.detail for v in gate.check_line(x["speaker"], x["text"], x["uses"], card.ts)]
            if not bad and lines:
                return [_narration(ledger, card)] + lines
            self.rejected.append({"scene": card.scene_id, "attempt": attempt, "why": bad})
            prompt += "\n上一版被退回，原因：" + json.dumps(bad, ensure_ascii=False) + "。請改正。"
        return self.fallback.write(ledger, card, gate)
