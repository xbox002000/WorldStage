from __future__ import annotations

import json
import sqlite3

from contracts.claim import Claim
from world.claims import describe_claim
from world.events import Change, ClaimSpec, EventSpec, MemorySpec, apply_event
from world.rng import rng as make_rng

LOCATIONS = [
    # id, name, x, y, capacity, tags
    ("apartment", "公寓", 0, 0, 20, ["home"]),
    ("cafe", "咖啡店", 3, 1, 12, ["food", "social"]),
    ("office", "辦公室", 6, 0, 6, ["work"]),
    ("park", "公園", 1, 4, 10, ["social"]),
    ("station", "車站", 5, 4, 10, ["transit"]),
]
EDGES = [
    ("apartment", "cafe", 10), ("apartment", "park", 8), ("apartment", "office", 15),
    ("apartment", "station", 12), ("cafe", "office", 12), ("cafe", "station", 6),
    ("cafe", "park", 9), ("park", "station", 7), ("office", "station", 9), ("office", "park", 11),
]
# id, name, goal, works
PEOPLE = [
    ("ming", "阿明", "升職加薪，證明自己", True),
    ("mei", "小美", "離開這座城市", False),
    ("jun", "阿俊", "還清欠款", True),
    ("lan", "阿蘭", "找回失去的友誼", False),
    ("hao", "阿豪", "成為咖啡店常客的朋友", True),
    ("yun", "小雲", "保守一個秘密", False),
    ("kai", "阿凱", "得到主管的認可", True),
    ("ning", "阿寧", "寫完一本日記", False),
    ("tao", "阿濤", "存錢買一支新手機", True),
    ("rui", "小瑞", "讓大家和好", False),
]
PERSONAS = {
    "ming": "好勝、愛面子，被冷落會記仇，但對上司很恭敬",
    "mei": "冷靜疏離，心裡只想離開這裡；對挽留她的人不耐煩",
    "jun": "負債焦慮，容易疑心別人瞧不起他，對錢的事很敏感",
    "lan": "想修復友誼但容易受傷，被拒絕會退縮或反擊",
    "hao": "熱情但愛打聽，想和大家交朋友，有時太黏人",
    "yun": "守著秘密，防備心重，被追問會變冷淡",
    "kai": "想討好主管，看不慣搶功的人，對競爭者帶刺",
    "ning": "內向敏感，在意隱私，日記被碰會發火",
    "tao": "節儉固執，不喜歡被借錢，直來直往",
    "rui": "和事佬，但被連續冷淡會失去耐心",
}
OBJECTS = [
    # id, name, rightful owner, value (cents)
    ("wallet_ming", "錢包", "ming", 5000), ("phone_mei", "手機", "mei", 30000), ("diary_ning", "日記", "ning", 0),
    ("key_yun", "鑰匙", "yun", 500), ("watch_jun", "手錶", "jun", 15000), ("ring_mei", "戒指", "mei", 20000),
]
# Props that only outside events bring in; they wait offstage (no holder, no place) until then.
PROPS = [
    # id, name, tags, value (cents)
    ("ticket", "樂透彩券", ["paper"], 0),
    ("parrot", "鸚鵡", ["fixed", "repeater", "animal"], 0),
    ("package", "包裹", ["parcel"], 12000),
]
# Static traits, each 0..1. They drive rule motives (agent/volition.py) and small rules such as misplacing things.
TRAITS = {
    "ming": {"honesty": 0.5, "temper": 0.7, "gossip": 0.4, "generosity": 0.3, "absent_minded": 0.2, "curiosity": 0.4},
    "mei": {"honesty": 0.7, "temper": 0.3, "gossip": 0.2, "generosity": 0.3, "absent_minded": 0.3, "curiosity": 0.3},
    "jun": {"honesty": 0.35, "temper": 0.5, "gossip": 0.3, "generosity": 0.2, "absent_minded": 0.5, "curiosity": 0.4},
    "lan": {"honesty": 0.7, "temper": 0.5, "gossip": 0.5, "generosity": 0.6, "absent_minded": 0.3, "curiosity": 0.5},
    "hao": {"honesty": 0.6, "temper": 0.2, "gossip": 0.9, "generosity": 0.7, "absent_minded": 0.4, "curiosity": 0.9},
    "yun": {"honesty": 0.4, "temper": 0.4, "gossip": 0.1, "generosity": 0.3, "absent_minded": 0.2, "curiosity": 0.3},
    "kai": {"honesty": 0.5, "temper": 0.6, "gossip": 0.6, "generosity": 0.3, "absent_minded": 0.2, "curiosity": 0.5},
    "ning": {"honesty": 0.8, "temper": 0.6, "gossip": 0.2, "generosity": 0.4, "absent_minded": 0.5, "curiosity": 0.4},
    "tao": {"honesty": 0.7, "temper": 0.6, "gossip": 0.3, "generosity": 0.1, "absent_minded": 0.2, "curiosity": 0.3},
    "rui": {"honesty": 0.8, "temper": 0.2, "gossip": 0.5, "generosity": 0.8, "absent_minded": 0.6, "curiosity": 0.5},
}
DEBTS = [("jun", "tao", 6000), ("ming", "kai", 3000)]  # (debtor, lender, cents): old debts the town starts with
WORLD_VARS = {"price_food": 800.0, "visibility": 1.0, "job_security": 1.0}

# slot (minute of day) -> action, for people who work / people who do not. "decide" is a moment to choose what to
# do with whoever is there (besides the town-wide DECISION_SLOTS). Workers go back to the office after lunch, so
# colleagues spend an afternoon together; people at home spread out instead of all sitting in the cafe from noon on.
WORKER_DAY = {480: "move:office", 540: "work", 720: "move:cafe", 750: "eat", 800: "move:office", 900: "decide",
              1080: "move:park", 1260: "move:apartment"}
HOME_DAY = {480: "move:cafe", 720: "eat", 800: "move:park", 900: "decide", 1080: "move:cafe", 1260: "move:apartment"}
HOME_DAY_ALT = {480: "move:park", 720: "move:cafe", 750: "eat", 840: "move:apartment", 900: "decide", 1080: "move:park",
                1260: "move:apartment"}


# Animals: perceivers without language (world/animals.py). They wait offstage (inactive) until a seed brings them.
ANIMALS = [
    # id, name, place it will turn up, traits
    ("dog", "小狗", "park", {"species": "dog", "curiosity": 0.7, "honesty": 1.0, "temper": 0.3, "gossip": 0.0,
                            "generosity": 0.5, "absent_minded": 0.8}),
]


def build_world(conn: sqlite3.Connection, world_seed: int, recipe: str = "town_v1") -> None:
    """Fill an initialised database: 5 places, 10 people, their things, props offstage, and one old secret."""
    from world.recipes import compiled, load_recipe
    compiled(recipe)  # refuses a recipe that does not compile
    content = load_recipe(recipe).content
    if content != "town_v1":
        from world.content import build_content_world, content_module
        return build_content_world(conn, world_seed, recipe, content_module(content))
    conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('recipe', ?)", (recipe,))
    rng = make_rng(world_seed, 0, "world", "seed_world")
    for lid, name, x, y, cap, tags in LOCATIONS:
        conn.execute("INSERT INTO locations VALUES (?,?,?,?,?,?)", (lid, name, x, y, cap, json.dumps(tags)))
    for a, b, minutes in EDGES:
        conn.execute("INSERT INTO location_edges VALUES (?,?,?)", (a, b, minutes))
        conn.execute("INSERT INTO location_edges VALUES (?,?,?)", (b, a, minutes))

    homebodies = 0
    for pid, name, goal, works in PEOPLE:
        if works:
            schedule = WORKER_DAY
        else:
            schedule = HOME_DAY if homebodies % 2 == 0 else HOME_DAY_ALT
            homebodies += 1
        conn.execute(
            "INSERT INTO people VALUES (?,?,?,?,?,?,?,?,?,?)",
            (pid, name, "apartment", 100, rng.randint(6000, 20000), rng.randint(20, 50), goal, "calm",
             json.dumps({str(k): v for k, v in schedule.items()}), "active"),
        )
    for pid, text in PERSONAS.items():
        conn.execute("INSERT INTO personas(person_id, text, traits) VALUES (?,?,?)",
                     (pid, text, json.dumps(TRAITS[pid], sort_keys=True)))
    for aid, name, place, traits in ANIMALS:
        conn.execute("INSERT INTO people VALUES (?,?,?,?,?,?,?,?,?,?)",
                     (aid, name, place, 100, 0, 40, "", "calm", "{}", "inactive"))
        conn.execute("INSERT INTO personas(person_id, text, traits) VALUES (?,?,?)",
                     (aid, "一隻會跟著喜歡的人走、什麼都想叼走的小狗", json.dumps(traits, sort_keys=True)))
    ids = [p[0] for p in PEOPLE]
    debts = {(debtor, lender): cents for debtor, lender, cents in DEBTS}
    for aid, *_ in ANIMALS:  # an animal starts neutral toward everyone, and everyone toward it
        for pid in ids:
            conn.execute("INSERT INTO relationships(actor_id, target_id) VALUES (?,?)", (aid, pid))
            conn.execute("INSERT INTO relationships(actor_id, target_id) VALUES (?,?)", (pid, aid))
    for a in ids:
        for b in ids:
            if a != b:
                conn.execute(
                    "INSERT INTO relationships(actor_id, target_id, trust, affection, debt_cents) VALUES (?,?,?,?,?)",
                    (a, b, round(rng.uniform(-0.3, 0.5), 2), round(rng.uniform(-0.2, 0.4), 2), debts.get((a, b), 0)),
                )
    for oid, name, owner, value in OBJECTS:
        conn.execute("INSERT INTO objects(id, name, owner_person_id, rightful_owner_id, value_cents) VALUES (?,?,?,?,?)",
                     (oid, name, owner, owner, value))
    for oid, name, tags, value in PROPS:
        conn.execute("INSERT INTO objects(id, name, tags, status, value_cents) VALUES (?,?,?,'offstage',?)",
                     (oid, name, json.dumps(tags), value))
    variables = dict(WORLD_VARS)
    variables.update({f"arrears.{p[0]}": 0.0 for p in PEOPLE})
    variables.update({f"missing.{o[0]}": 0.0 for o in OBJECTS + PROPS})
    variables.update({f"revert.{k}": -1.0 for k in WORLD_VARS})  # day a seed's temporary change wears off
    from world.psyche import keys_for
    for p in PEOPLE:
        variables.update(keys_for(p[0]))
    variables.update(_profiles_and_domains(conn, "town_v1", [p[0] for p in PEOPLE]))
    for key, value in sorted(variables.items()):
        conn.execute("INSERT INTO world_vars(key, value) VALUES (?,?)", (key, value))
    from world.goals import initial_rows
    for row in initial_rows([p[0] for p in PEOPLE]):
        conn.execute("INSERT INTO goals(person_id, slot, kind, target, object, status, priority, since_day, setbacks, parent) "
                     "VALUES (?,?,?,?,?,?,?,?,?,?)", row)
    backstory(conn)
    _persona_layer(conn, recipe, world_seed)


def _persona_layer(conn: sqlite3.Connection, recipe: str, world_seed: int) -> None:
    """What made each person (as background events), then which run this is (the branch)."""
    from world.personas import write_branch, write_formative
    write_formative(conn)
    write_branch(conn, recipe, world_seed)


def _profiles_and_domains(conn: sqlite3.Connection, content: str, people: list[str]) -> dict[str, float]:
    """Store who everyone is (their CharacterProfile) and return the life state each active domain gives them."""
    from world.domains import active
    from world.profiles import load_roster, profile, store
    store(conn, load_roster(content), people)
    from world.personas import store as store_genomes
    store_genomes(conn, content, people)
    out: dict[str, float] = {}
    for dom in active(conn):
        for pid in people:
            p = profile(conn, pid)
            out.update(dom.initial_vars(pid, p))
    return out


def backstory(conn: sqlite3.Connection) -> None:
    """A secret the town starts with, as real history: long ago Yun took Mei's ring; Mei only knows it is gone.

    It is Yun's goal to keep a secret, and because it is world truth, lies, notes and accusations about it can be
    judged like anything else.
    """
    names = {r[0]: r[1] for r in conn.execute("SELECT id, name FROM people UNION ALL SELECT id, name FROM objects")}
    took, lost = Claim("yun", "take", "ring_mei"), Claim("mei", "lose", "ring_mei")
    apply_event(conn, EventSpec(
        timestamp=0, type="backstory", trigger_type="rule", location_id="apartment", importance=0.6,
        truth={"actor": "yun", "object": "ring_mei", "rightful_owner": "mei", "text": "很久以前，小雲拿走了小美的戒指"},
        participants=[("yun", "actor"), ("mei", "victim")],
        changes=[Change("object", "ring_mei", "owner_person_id", value="yun"),
                 Change("var", "missing.ring_mei", "value", delta=1.0)],
        memories=[MemorySpec("yun", describe_claim(took, names), 1.0, claim=took),
                  MemorySpec("mei", describe_claim(lost, names), 1.0, claim=lost)],
        claims=[ClaimSpec(took), ClaimSpec(lost)],
    ))
