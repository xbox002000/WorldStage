from __future__ import annotations

import json
import random
import sqlite3

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
    ("cafe", "park", 9), ("park", "station", 7), ("office", "station", 9),
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
    ("wallet_ming", "錢包", "ming"), ("phone_mei", "手機", "mei"), ("diary_ning", "日記", "ning"),
    ("key_yun", "鑰匙", "yun"), ("watch_jun", "手錶", "jun"),
]

# slot (minute of day) -> action, for people who work / people who do not
WORKER_DAY = {480: "move:office", 540: "work", 720: "move:cafe", 750: "eat", 1080: "move:park", 1260: "move:apartment"}
HOME_DAY = {480: "move:cafe", 720: "eat", 1080: "move:park", 1260: "move:apartment"}
HOME_DAY_ALT = {480: "move:park", 720: "move:cafe", 750: "eat", 1080: "move:cafe", 1260: "move:apartment"}


def build_world(conn: sqlite3.Connection, world_seed: int) -> None:
    """Fill an initialised database with the V0 world: 5 places, 10 people, 5 objects."""
    rng = random.Random(f"{world_seed}:seed")
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
        conn.execute("INSERT INTO personas VALUES (?,?)", (pid, text))
    ids = [p[0] for p in PEOPLE]
    for a in ids:
        for b in ids:
            if a != b:
                conn.execute(
                    "INSERT INTO relationships(actor_id, target_id, trust, affection) VALUES (?,?,?,?)",
                    (a, b, round(rng.uniform(-0.3, 0.5), 2), round(rng.uniform(-0.2, 0.4), 2)),
                )
    for oid, name, owner in OBJECTS:
        conn.execute("INSERT INTO objects(id, name, owner_person_id) VALUES (?,?,?)", (oid, name, owner))
