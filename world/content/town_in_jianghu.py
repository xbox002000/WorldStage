"""The town's ten people, cast into the jianghu: the same persons (their profiles, temperaments, the old business of
Mei's ring), another world. Five of them are disciples of a sect under an offstage master, the others live at the
inn. A cross-domain test of Character OS: who someone is stays, what their life offers them changes.

Places, paths and stage layouts are the jianghu's (world/content/jianghu_v1.py); the people are the town's
(world/seed.py, world/content/profiles/town_v1.json), cast by world/content/profiles/town_in_jianghu.json.
"""
from __future__ import annotations

from contracts.claim import Claim
from world.claims import describe_claim
from world.content import jianghu_v1 as J
from world.events import Change, ClaimSpec, EventSpec, MemorySpec, apply_event
from world.goals import INITIAL
from world import seed as town

LOCATIONS = J.LOCATIONS
EDGES = J.EDGES
LAYOUTS = J.LAYOUTS

DISCIPLES = ("ming", "jun", "hao", "kai", "tao")  # the town's workers: here they train in a sect
PEOPLE = [(pid, name, {"ming": "在師門出人頭地，證明自己", "jun": "在師門站穩腳跟", "hao": "和師兄弟們打成一片",
                       "kai": "得到掌門的認可", "tao": "攢夠銀兩"}.get(pid, goal)) for pid, name, goal, _ in town.PEOPLE]
# the sect was there before the story: its master is offstage, so the chief disciple's seat is the highest place on stage,
# and it is decided at the assessment on day 14 (world/domains/factions.py)
FACTIONS = [("qingyun", "青雲門", None, "在江湖上保住青雲門的名聲",
             [(pid, "disciple") for pid in DISCIPLES])]
SEATS = [("chief_disciple", "首席弟子", "ming", 14, "qingyun")]
PROPS = [("manual_secret", "秘傳劍訣", ["manual", "paper"], 0)]  # waits offstage: an opportunity that can arrive
PERSONAS = dict(town.PERSONAS)
TRAITS = {pid: {**town.TRAITS[pid], "sect": "qingyun" if pid in DISCIPLES else "",
                "home": "qingyun" if pid in DISCIPLES else "inn"} for pid, *_ in town.PEOPLE}
SKILL = {"ming": 0.5, "jun": 0.35, "hao": 0.3, "kai": 0.5, "tao": 0.4, "mei": 0.1, "lan": 0.05, "yun": 0.15,
         "ning": 0.05, "rui": 0.05}
OBJECTS = [
    # id, name, rightful owner, value (cents), tags: the same belongings, in this world's shape
    ("wallet_ming", "錢袋", "ming", 5000, []), ("diary_ning", "日記", "ning", 0, ["paper"]),
    ("key_yun", "鑰匙", "yun", 500, []), ("watch_jun", "玉佩", "jun", 15000, ["jade"]),
    ("ring_mei", "戒指", "mei", 20000, []),
]
WORLD_VARS = {"price_food": 600.0, "visibility": 1.0, "job_security": 1.0}
DISCIPLE = {480: "train", 720: "move:inn", 750: "eat", 800: "move:qingyun", 900: "decide", 1080: "move:market",
            1260: "move:qingyun"}
HOME_A = {600: "move:market", 720: "move:inn", 750: "eat", 900: "decide", 1080: "move:market", 1260: "move:inn"}
HOME_B = {480: "move:road", 720: "move:inn", 750: "eat", 840: "move:market", 900: "decide", 1080: "move:inn"}
SCHEDULES = {pid: DISCIPLE if pid in DISCIPLES else (HOME_A if i % 2 == 0 else HOME_B)
             for i, (pid, *_) in enumerate(town.PEOPLE)}
# the same wants about the same people (a debt does not cross worlds: Jun's goal to repay Tao has no debt here)
INITIAL_GOALS = {pid: g for pid, g in INITIAL.items() if g[0] != "repay"}


def EXTRA_VARS(pid: str) -> dict[str, float]:
    return {f"skill.{pid}": SKILL[pid], f"rep.{pid}": 0.4}


def relation(a: str, b: str, rng) -> tuple[float, float, float]:
    """As in the town: how they feel about each other does not depend on the world they are in."""
    return round(rng.uniform(-0.3, 0.5), 2), round(rng.uniform(-0.2, 0.4), 2), 0.0


def backstory(conn) -> None:
    """The same old business: long ago Yun took Mei's ring; Mei only knows it is gone."""
    names = {r[0]: r[1] for r in conn.execute("SELECT id, name FROM people UNION ALL SELECT id, name FROM objects")}
    took, lost = Claim("yun", "take", "ring_mei"), Claim("mei", "lose", "ring_mei")
    apply_event(conn, EventSpec(
        timestamp=0, type="backstory", trigger_type="rule", location_id="inn", importance=0.6,
        truth={"actor": "yun", "object": "ring_mei", "rightful_owner": "mei", "text": "很久以前，小雲拿走了小美的戒指"},
        participants=[("yun", "actor"), ("mei", "victim")],
        changes=[Change("object", "ring_mei", "owner_person_id", value="yun"),
                 Change("var", "missing.ring_mei", "value", delta=1.0)],
        memories=[MemorySpec("yun", describe_claim(took, names), 1.0, claim=took),
                  MemorySpec("mei", describe_claim(lost, names), 1.0, claim=lost)],
        claims=[ClaimSpec(took), ClaimSpec(lost)],
    ))
