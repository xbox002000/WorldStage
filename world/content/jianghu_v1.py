"""Jianghu v1: two rival sects, an inn, a market and a mountain road; ten people; one stolen sword manual.

Only content. The rules are the shared core plus the recipe's primitives (martial_arts, reputation, duel,
sect_factions): world/jianghu.py.
"""
from __future__ import annotations

from contracts.claim import Claim
from world.claims import describe_claim
from world.events import Change, ClaimSpec, EventSpec, MemorySpec, apply_event

LOCATIONS = [
    # id, name, x, y, capacity, tags
    ("qingyun", "青雲門", 0, 0, 12, ["home", "training", "social"]),
    ("manor", "鐵劍山莊", 6, 0, 10, ["home", "training", "social"]),
    ("inn", "悅來客棧", 3, 2, 14, ["food", "social", "home", "work"]),
    ("market", "市集", 3, 5, 14, ["social", "work"]),
    ("road", "山道", 6, 4, 10, ["transit"]),
]
EDGES = [
    ("qingyun", "inn", 15), ("manor", "inn", 15), ("inn", "market", 8), ("market", "road", 10),
    ("road", "manor", 12), ("qingyun", "market", 18), ("inn", "road", 10),
]
# which white-box layout stages each place (narrative/layouts.py)
LAYOUTS = {"qingyun": "office", "manor": "office", "inn": "cafe", "market": "station", "road": "park"}

PEOPLE = [
    # id, name, goal (text shown in prompts; the structured goal is INITIAL_GOALS)
    ("lin", "林遠山", "找回失竊多年的《青雲劍譜》"),
    ("lu", "陸青", "守住偷走劍譜的秘密"),
    ("su", "蘇小婉", "和那位遊俠交上朋友"),
    ("shi", "石頭", "有一天打贏鐵驚鴻"),
    ("tie", "鐵萬鈞", "讓鐵劍山莊壓過青雲門"),
    ("hong", "鐵驚鴻", "打敗青雲門的大師兄"),
    ("han", "韓七", "在莊主面前立功"),
    ("hua", "花三娘", "把客棧的生意做好"),
    ("zhou", "老周", "說出一段沒人聽過的江湖故事"),
    ("yan", "燕飛", "和天下第一的劍客交手"),
]
# two groups that were there before the story: the sects of the master (lin) and of the lord (tie)
FACTIONS = [("qingyun", "青雲門", "lin", "守住門派的名聲", [("lin", "master"), ("lu", "disciple"), ("su", "disciple"), ("shi", "disciple")]),
            ("tiejian", "鐵劍山莊", "tie", "壓過青雲門一頭", [("tie", "master"), ("hong", "heir"), ("han", "retainer")])]
SEATS = [("senior_disciple", "大師兄", "lu", 0, "qingyun")]
PERSONAS = {
    "lin": "青雲門掌門，沉穩重名聲，劍譜失竊多年一直耿耿於懷",
    "lu": "大師兄，武功出眾卻心虛，多年前偷了劍譜偷偷練",
    "su": "師妹，單純熱心，對來歷不明的遊俠很好奇",
    "shi": "小師弟，憨直好勝，總被鐵驚鴻看不起",
    "tie": "鐵劍山莊莊主，霸氣好面子，處處想壓青雲門一頭",
    "hong": "少莊主，驕傲，想靠打敗青雲門大師兄揚名",
    "han": "山莊門客，心機重，會為了討好莊主搬弄是非",
    "hua": "客棧老闆娘，八面玲瓏，什麼消息都聽得到",
    "zhou": "說書人，最愛把聽來的事加油添醋",
    "yan": "遊俠，來歷不明，劍法極高，只想找高手過招",
}
BASE_TRAIT = {"honesty": 0.6, "temper": 0.4, "gossip": 0.4, "generosity": 0.4, "absent_minded": 0.2, "curiosity": 0.4}
TRAITS = {
    "lin": {**BASE_TRAIT, "honesty": 0.8, "temper": 0.4, "sect": "qingyun", "home": "qingyun"},
    "lu": {**BASE_TRAIT, "honesty": 0.3, "temper": 0.5, "gossip": 0.2, "sect": "qingyun", "home": "qingyun"},
    "su": {**BASE_TRAIT, "honesty": 0.8, "temper": 0.2, "curiosity": 0.8, "generosity": 0.7, "absent_minded": 0.5,
           "sect": "qingyun", "home": "qingyun"},
    "shi": {**BASE_TRAIT, "honesty": 0.7, "temper": 0.7, "absent_minded": 0.4, "sect": "qingyun", "home": "qingyun"},
    "tie": {**BASE_TRAIT, "honesty": 0.5, "temper": 0.7, "sect": "iron", "home": "manor"},
    "hong": {**BASE_TRAIT, "honesty": 0.5, "temper": 0.8, "sect": "iron", "home": "manor"},
    "han": {**BASE_TRAIT, "honesty": 0.3, "temper": 0.4, "gossip": 0.7, "sect": "iron", "home": "manor"},
    "hua": {**BASE_TRAIT, "honesty": 0.6, "temper": 0.3, "gossip": 0.8, "generosity": 0.6, "sect": "", "home": "inn"},
    "zhou": {**BASE_TRAIT, "honesty": 0.5, "temper": 0.2, "gossip": 0.95, "curiosity": 0.9, "sect": "", "home": "inn"},
    "yan": {**BASE_TRAIT, "honesty": 0.7, "temper": 0.5, "gossip": 0.1, "curiosity": 0.7, "sect": "", "home": "inn"},
}
RIVAL_SECTS = {("qingyun", "iron"), ("iron", "qingyun")}
SKILL = {"lin": 0.85, "lu": 0.62, "su": 0.4, "shi": 0.3, "tie": 0.8, "hong": 0.58, "han": 0.45, "hua": 0.15,
         "zhou": 0.05, "yan": 0.78}
REPUTATION = {"lin": 0.8, "lu": 0.55, "su": 0.4, "shi": 0.3, "tie": 0.75, "hong": 0.5, "han": 0.3, "hua": 0.55,
              "zhou": 0.4, "yan": 0.3}
OBJECTS = [
    # id, name, rightful owner, value (cents), tags
    ("manual", "青雲劍譜", "lin", 50000, ["manual", "paper"]),
    ("sword_hong", "寒鐵劍", "hong", 30000, ["weapon"]),
    ("jade_su", "玉佩", "su", 8000, ["jade"]),
    ("token_tie", "莊主令", "tie", 20000, ["token"]),
    ("gourd_yan", "酒葫蘆", "yan", 500, []),
]
WORLD_VARS = {"price_food": 600.0, "visibility": 1.0, "job_security": 1.0}
DISCIPLE = {480: "train", 720: "move:inn", 750: "eat", 1080: "move:market", 1260: "move:{home}"}
MASTER = {480: "train", 720: "move:inn", 750: "eat", 1260: "move:{home}"}
INNFOLK = {540: "work", 750: "eat", 1080: "move:market", 1260: "move:inn"}
WANDERER = {480: "move:road", 720: "move:inn", 750: "eat", 1080: "move:market", 1260: "move:inn"}
ROLE = {"lin": MASTER, "tie": MASTER, "lu": DISCIPLE, "su": DISCIPLE, "shi": DISCIPLE, "hong": DISCIPLE,
        "han": DISCIPLE, "hua": INNFOLK, "zhou": INNFOLK, "yan": WANDERER}
SCHEDULES = {pid: {k: v.format(home=TRAITS[pid]["home"]) for k, v in ROLE[pid].items()} for pid in ROLE}
INITIAL_GOALS = {
    "lin": ("recover", "", "manual", 0.8), "lu": ("keep_secret", "", "lu:take:manual", 0.9),
    "su": ("befriend", "yan", "", 0.5), "shi": ("surpass", "hong", "", 0.6), "tie": ("outshine", "lin", "", 0.6),
    "hong": ("surpass", "lu", "", 0.7), "yan": ("surpass", "lin", "", 0.6),
}


def EXTRA_VARS(pid: str) -> dict[str, float]:
    return {f"skill.{pid}": SKILL[pid], f"rep.{pid}": REPUTATION[pid]}


def relation(a: str, b: str, rng) -> tuple[float, float, float]:
    """Trust, affection and rivalry at the start: warmer within a sect, cooler and sharper across rival sects."""
    sa, sb = TRAITS[a]["sect"], TRAITS[b]["sect"]
    trust, affection = round(rng.uniform(-0.2, 0.4), 2), round(rng.uniform(-0.1, 0.3), 2)
    if sa and sa == sb:
        return round(min(1.0, trust + 0.3), 2), round(min(1.0, affection + 0.25), 2), 0.0
    if (sa, sb) in RIVAL_SECTS:
        return round(max(-1.0, trust - 0.2), 2), round(max(-1.0, affection - 0.2), 2), 0.3
    return trust, affection, 0.0


def backstory(conn) -> None:
    """Years ago Lu took the sect's sword manual and trains from it in secret. Lin only knows it is gone."""
    names = {r[0]: r[1] for r in conn.execute("SELECT id, name FROM people UNION ALL SELECT id, name FROM objects")}
    took, lost = Claim("lu", "take", "manual"), Claim("lin", "lose", "manual")
    apply_event(conn, EventSpec(
        timestamp=0, type="backstory", trigger_type="rule", location_id="qingyun", importance=0.7,
        truth={"actor": "lu", "object": "manual", "rightful_owner": "lin", "text": "多年前，陸青偷走了《青雲劍譜》"},
        participants=[("lu", "actor"), ("lin", "victim")],
        changes=[Change("object", "manual", "owner_person_id", value="lu"),
                 Change("var", "missing.manual", "value", delta=1.0)],
        memories=[MemorySpec("lu", describe_claim(took, names), 1.0, claim=took),
                  MemorySpec("lin", describe_claim(lost, names), 1.0, claim=lost)],
        claims=[ClaimSpec(took), ClaimSpec(lost)],
    ))
