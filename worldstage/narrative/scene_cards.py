"""Scene cards: what a scene is for, before a word of it is written (plot engine, phase 1).

Every scene stands on one real event (its anchor) and carries:
  pov       whose scene it is: the one whose knowledge bounds what the scene may show from the inside
  question  the one suspense question it raises
  turn      the value it walks in with and the value it walks out with; a scene whose value does not turn is not written
  cast      who is in it (the anchor's actor, target and witnesses)
  known     per person, the facts they know at the scene's time (narrative/ledger.py): the only facts a line may stand on
  irony     facts in the scene's story that the audience has seen and the POV does not know
The turn is read from the world: the anchor's relationship deltas between the two people in it, or its outcome.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from worldstage.narrative.ledger import Fact, FactLedger, KnowledgeGate

REL_FIELDS = {"trust": ("信任", "不信任"), "affection": ("好感", "嫌隙"), "resentment": ("怨氣", "釋懷"), "respect": ("敬重", "輕視"),
              "attraction": ("心動", "冷卻")}
OUTCOME_TURN = {"caught": ("懷疑", "坐實"), "false": ("指控", "反被冤枉"), "denied": ("追問", "被否認"), "declined": ("期待", "被拒"),
                "accepted": ("忐忑", "被接受"), "lie_exposed": ("隱瞞", "被拆穿"), "inconclusive": ("懸念", "仍懸而未決")}
QUESTION = {
    "steal": "{actor}拿走的東西，會不會被{target}發現？", "take": "{actor}拿走的東西，會不會被{target}發現？",
    "misplace": "{actor}丟掉的東西，會讓誰背黑鍋？", "notice_missing": "{actor}會懷疑誰？",
    "confront": "{actor}當面質問{target}，{target}會說實話嗎？", "accuse": "{actor}指控{target}，這指控站得住嗎？",
    "shove": "{actor}和{target}之間的火氣，會不會一發不可收拾？", "duel": "{actor}和{target}這一戰，誰會在眾人面前落敗？",
    "flirt": "{actor}的心意，{target}接不接得住？", "confession": "{actor}這一告白，{target}會怎麼回答？",
    "praise": "{actor}這次被看見，會換來什麼？", "regret": "{actor}會不會後悔已經太遲？", "tell": "{actor}說出口的事，會傳到誰耳裡？",
    "talk": "{actor}和{target}這番話，會把兩人推向哪裡？",
}


@dataclass
class SceneCard:
    scene_id: str
    episode: int
    line: str                       # A | B
    beat_id: str | None             # the main-line beat it carries, if any
    anchor: int                     # the real event it stands on
    ts: int
    location: str
    pov: str
    cast: list[str]
    question: str
    turn: dict                      # {"field", "before", "after"}
    known: dict[str, list[int]] = field(default_factory=dict)
    irony: list[int] = field(default_factory=list)
    recall: list[int] = field(default_factory=list)    # facts from earlier episodes the POV knows, which the scene may call back
    lines: list[dict] = field(default_factory=list)     # written later: {"speaker", "text", "uses", "kind"}


def _turn(ledger: FactLedger, f: Fact) -> dict | None:
    out = f.truth.get("outcome")
    if out in OUTCOME_TURN:
        a, b = OUTCOME_TURN[out]
        return {"field": "outcome", "before": a, "after": b}
    if f.type == "duel" and f.truth.get("winner"):
        return {"field": "standing", "before": "勝負未分", "after": f"{ledger.name(f.truth['winner'])}勝"}
    if f.type == "flirt":
        return {"field": "attraction", "before": "試探", "after": "被接住" if f.truth.get("landed") else "落空"}
    if f.actor and f.target:
        best = None
        for fld, new, old in ledger.conn.execute(
                "SELECT field, new_value, old_value FROM event_deltas WHERE event_id = ? AND entity_type = 'relationship' AND entity_id IN (?, ?)",
                (f.fact_id, f"{f.actor}:{f.target}", f"{f.target}:{f.actor}")):
            if fld in REL_FIELDS and isinstance(new, (int, float)) and isinstance(old, (int, float)) and (best is None or abs(new - old) > abs(best[1])):
                best = (fld, new - old)
        if best is not None and abs(best[1]) > 1e-9:
            up, down = REL_FIELDS[best[0]]
            if best[1] > 0:
                return {"field": best[0], "before": f"{up}未起", "after": f"{up}加深"}
            return {"field": best[0], "before": f"{up}尚在", "after": f"{down}浮現"}
    if f.claim_text:
        return {"field": "secret", "before": "沒人說破", "after": "說破了"}
    return None


def card_for(ledger: FactLedger, fact: Fact, scene_id: str, episode: int, line: str, beat_id: str | None, pov: str,
             story_people: set[str], first_day_of_episode: int) -> SceneCard | None:
    turn = _turn(ledger, fact)
    if turn is None:
        return None                              # nothing turns: not a scene
    names = {"actor": ledger.name(fact.actor), "target": ledger.name(fact.target) if fact.target else "對方"}
    q = QUESTION.get(fact.type, "{actor}這一步，會改變什麼？").format(**names)
    cast = sorted(set(fact.participants) | {fact.actor} - {""})
    gate = KnowledgeGate(ledger)
    known = {p: sorted(f for f in gate.allowed(p, fact.ts) if ledger.facts[f].ts >= (first_day_of_episode - 14) * 1440) for p in cast}
    story = [f for f in ledger.facts.values() if f.ts <= fact.ts and (set(f.participants) & set(cast)) and f.importance >= 0.5
             and f.type != "talk" and f.day >= first_day_of_episode - 7]
    irony = [f.fact_id for f in story if not ledger.knows(pov, f.fact_id, fact.ts)][-3:]
    recall = [f for f in known.get(pov, []) if ledger.facts[f].day < first_day_of_episode and (set(ledger.facts[f].participants) & story_people)
              and ledger.facts[f].importance >= 0.5][-2:]
    return SceneCard(scene_id, episode, line, beat_id, fact.fact_id, fact.ts, ledger.names.get(fact.location, fact.location), pov, cast, q,
                     turn, known, irony, recall)
