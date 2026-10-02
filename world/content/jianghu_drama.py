"""Jianghu drama: the story world's people and bones (world/content/jianghu_story.py), but a jianghu all the way down.

The same ten, in the same places, with the same relations, skills, the two disciples who are better than their sect knows
(UNDERRATED), the old business of the ring, and the chief disciple's seat. What changes is who they are *to be read as*:

  * names with a family name and a given name (林嘯, 沈青璃), none of them a name from the novels;
  * a past of the jianghu: villages, escort agencies, an inn, a sect (the town's 台中, university and iced coffee are gone);
  * habits, tastes and dislikes in the jianghu's own words (a roster of its own: world/content/profiles/jianghu_drama.json, not a
    casting of the town's: a casting changes a job, not a birthplace);
  * the seat is decided on day 10, so that a fortnight holds it (the story world's day 14 is the end of one).

The numbers that move the world (temperaments, values, interests per topic, skills, relations at the start) are the story world's: only
words changed, so the same people, the same quarrels and the same ring. Every id stays, so goals, defaults and tools that name a person keep
working. Which rules run is the recipe's (world/recipes/jianghu_drama_v1.json), never this file's.
"""
from __future__ import annotations

from contracts.claim import Claim
from world.claims import describe_claim
from world.content.jianghu_story import *  # noqa: F401,F403
from world.content import jianghu_story as S
from world.events import Change, ClaimSpec, EventSpec, MemorySpec, apply_event

DRAMA_VERSION = "jianghu_drama_content_v0.1"

# id, name, what they want (text for prompts; the structured goals are INITIAL_GOALS, the same as the story world's)
PEOPLE = [
    ("ming", "林嘯", "在師門出人頭地，證明自己"),
    ("mei", "沈青璃", "離開這片江湖"),
    ("jun", "秦硯舟", "在師門站穩腳跟"),
    ("lan", "柳含霜", "找回失去的情誼"),
    ("hao", "顧長風", "和師兄弟們打成一片"),
    ("yun", "江映月", "保守一個秘密"),
    ("kai", "謝臨川", "得到掌門的認可"),
    ("ning", "宋清晏", "寫完一本日記"),
    ("tao", "魏山河", "攢夠銀兩買一匹馬"),
    ("rui", "薛采薇", "讓大家和好"),
]
# the sect before the story: its master is offstage, so the chief disciple's seat is the highest place on stage; it can fall vacant (the producer, or
# the story) and is then decided by the sect's vote, with a night of campaigning before it (world/domains/factions.py)
SEATS = [("chief_disciple", "首席弟子", "ming", 10, "qingyun")]
PERSONAS = {
    "ming": "好勝、愛面子，被冷落會記仇，但對掌門很恭敬",
    "mei": "冷靜疏離，心裡只想離開江湖；對挽留她的人不耐煩",
    "jun": "背著家裡的債，容易疑心別人瞧不起他窮，對銀兩的事很敏感",
    "lan": "想修復姊妹情誼但容易受傷，被拒絕會退縮或反擊",
    "hao": "熱情但愛打聽，想和大家交朋友，有時太黏人",
    "yun": "守著秘密，防備心重，被追問會變冷淡",
    "kai": "想討掌門歡心，看不慣搶功的人，對競爭者帶刺",
    "ning": "內向敏感，在意心事被人窺看，日記被碰會發火",
    "tao": "節儉固執，不喜歡被借銀兩，直來直往",
    "rui": "和事佬，但被連續冷淡會失去耐心",
}


def backstory(conn) -> None:
    """The same old business as the story world's, in these names: long ago Yun took Mei's ring; Mei only knows it is gone."""
    names = {r[0]: r[1] for r in conn.execute("SELECT id, name FROM people UNION ALL SELECT id, name FROM objects")}
    took, lost = Claim("yun", "take", "ring_mei"), Claim("mei", "lose", "ring_mei")
    apply_event(conn, EventSpec(
        timestamp=0, type="backstory", trigger_type="rule", location_id="inn", importance=0.6,
        truth={"actor": "yun", "object": "ring_mei", "rightful_owner": "mei", "text": f"很久以前，{names['yun']}拿走了{names['mei']}的戒指"},
        participants=[("yun", "actor"), ("mei", "victim")],
        changes=[Change("object", "ring_mei", "owner_person_id", value="yun"),
                 Change("var", "missing.ring_mei", "value", delta=1.0)],
        memories=[MemorySpec("yun", describe_claim(took, names), 1.0, claim=took),
                  MemorySpec("mei", describe_claim(lost, names), 1.0, claim=lost)],
        claims=[ClaimSpec(took), ClaimSpec(lost)],
    ))
