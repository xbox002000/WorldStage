"""Kinship terms inside a sect, and the coin word of a save-goal.

address() only reads. A jianghu recipe (meta key recipe contains "jianghu") and a shared faction are required.
The head's affiliations.role is "master" in the jianghu cast and "leader" when a faction is founded; both are 掌門.
An older listener is 師兄／師姐; a younger or same-aged one is 師弟／師妹. "存到{o}元" stays for every recipe that
does not turn on goals.earned; jianghu_drama_v1 says 文錢.
"""
from __future__ import annotations

import unittest

from contracts.base import canonical_json, to_dict
from contracts.character import CharacterProfile
from narrative.address import address
from narrative.speech import _apply_kinship, _open_as_kin, in_own_words, speak
from world.db import connect, init_db, mutation
from world.goals import SAVE_EARNED, TEXT, describe, find, text_of
from world.profiles import profile
from world.seed import build_world


def world(recipe: str, seed: int = 1):
    conn = connect()
    init_db(conn, seed)
    build_world(conn, seed, recipe)
    return conn


def _names(conn) -> dict:
    return {r[0]: r[1] for r in conn.execute("SELECT id, name FROM people")}


def handmade():
    """A sect small enough to hold a same-aged pair, a head of each role value, and an outsider."""
    conn = connect()
    init_db(conn, 1)
    conn.execute("INSERT INTO meta(key, value) VALUES ('recipe', 'jianghu_drama_v1')")
    conn.execute("INSERT INTO locations VALUES ('hall', '廳', 0, 0, 10, '[]')")
    conn.execute("INSERT INTO factions(faction_id, name, status) VALUES ('qingyun', '青雲門', 'active')")
    conn.execute("INSERT INTO factions(faction_id, name, status) VALUES ('other', '別派', 'active')")
    people = [
        ("a", "林遠", 30, "male", "qingyun", "disciple"),
        ("b", "周平", 30, "male", "qingyun", "disciple"),
        ("c", "蘇晚", 30, "female", "qingyun", "disciple"),
        ("d", "趙姐", 40, "female", "qingyun", "disciple"),
        ("e", "錢弟", 20, "male", "qingyun", "disciple"),
        ("elder", "林正", 60, "male", "qingyun", "master"),
        ("boss", "陳掌", 50, "female", "qingyun", "leader"),
        ("out", "外門", 55, "male", "other", "master"),
    ]
    for pid, name, age, gender, fid, role in people:
        conn.execute("INSERT INTO people VALUES (?,?,?,?,?,?,?,?,?,?)",
                     (pid, name, "hall", 100, 100, 20, "", "calm", "{}", "active"))
        person = CharacterProfile(id=pid, name=name, age=age, gender=gender)
        conn.execute("INSERT INTO character_profiles(person_id, profile, profile_hash) VALUES (?,?,?)",
                     (pid, canonical_json(to_dict(person)), person.hash()))
        conn.execute("INSERT INTO affiliations(person_id, faction_id, role) VALUES (?,?,?)", (pid, fid, role))
    return conn


class AddressTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.v1 = world("jianghu_v1")
        cls.drama = world("jianghu_drama_v1")
        cls.story = world("jianghu_story_v1")
        cls.town = world("town_v1")
        cls.hand = handmade()
        with mutation(cls.town):
            cls.town.execute("UPDATE affiliations SET faction_id = 'f1', role = 'member' WHERE person_id IN ('ming', 'mei')")

    def test_the_jianghu_cast_uses_age_gender_and_the_head_role(self):
        """jianghu_v1: 林遠山 is role master; 蘇小婉 is the older woman; 石頭 is the younger man."""
        c = self.v1
        self.assertEqual(c.execute("SELECT value FROM meta WHERE key = 'recipe'").fetchone()[0], "jianghu_v1")
        self.assertEqual(c.execute("SELECT role FROM affiliations WHERE person_id = 'lin'").fetchone()[0], "master")
        self.assertEqual(c.execute("SELECT faction_id FROM affiliations WHERE person_id = 'su'").fetchone()[0], "qingyun")
        self.assertNotEqual(c.execute("SELECT faction_id FROM affiliations WHERE person_id = 'hong'").fetchone()[0], "qingyun")
        su, shi, lu, lin = profile(c, "su"), profile(c, "shi"), profile(c, "lu"), profile(c, "lin")
        self.assertGreater(su.age, shi.age)
        self.assertEqual((su.gender, shi.gender, lu.gender, lin.gender), ("female", "male", "male", "male"))
        self.assertGreater(lu.age, su.age)
        changes = c.total_changes
        rows = list(c.execute("SELECT person_id, faction_id, role FROM affiliations ORDER BY person_id"))
        events = c.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        self.assertEqual(address(c, "shi", "lu"), "師兄")
        self.assertEqual(address(c, "shi", "su"), "師姐")
        self.assertEqual(address(c, "lu", "shi"), "師弟")
        self.assertEqual(address(c, "lu", "su"), "師妹")
        self.assertEqual(address(c, "su", "lin"), "掌門")
        self.assertIsNone(address(c, "lu", "hong"))
        self.assertIsNone(address(c, "lu", "lu"))
        self.assertEqual(c.total_changes, changes)
        self.assertEqual(list(c.execute("SELECT person_id, faction_id, role FROM affiliations ORDER BY person_id")), rows)
        self.assertEqual(c.execute("SELECT COUNT(*) FROM events").fetchone()[0], events)

    def test_the_drama_sects_disciples_and_a_person_outside_it(self):
        c = self.drama
        sect = {r[0] for r in c.execute("SELECT person_id FROM affiliations WHERE faction_id = 'qingyun'")}
        self.assertIn("tao", sect)
        self.assertIn("jun", sect)
        self.assertNotIn("mei", sect)
        tao, jun = profile(c, "tao"), profile(c, "jun")
        self.assertGreater(tao.age, jun.age)
        self.assertEqual(tao.gender, "male")
        self.assertEqual(jun.gender, "male")
        changes = c.total_changes
        self.assertEqual(address(c, "jun", "tao"), "師兄")
        self.assertEqual(address(c, "tao", "jun"), "師弟")
        self.assertIsNone(address(c, "jun", "mei"))
        self.assertEqual(c.total_changes, changes)

    def test_the_same_age_is_a_younger_sibling_and_both_head_roles_are_掌門(self):
        c = self.hand
        self.assertEqual(profile(c, "a").age, profile(c, "b").age)
        self.assertEqual(address(c, "a", "b"), "師弟")
        self.assertEqual(address(c, "a", "c"), "師妹")
        self.assertEqual(address(c, "e", "a"), "師兄")
        self.assertEqual(address(c, "a", "d"), "師姐")
        self.assertEqual(address(c, "a", "elder"), "掌門")
        self.assertEqual(address(c, "a", "boss"), "掌門")
        self.assertIsNone(address(c, "a", "out"))
        changes = c.total_changes
        c.execute("UPDATE meta SET value = 'town_v1' WHERE key = 'recipe'")
        self.assertIsNone(address(c, "a", "b"))
        c.execute("UPDATE meta SET value = 'jianghu_drama_v1' WHERE key = 'recipe'")
        self.assertEqual(address(c, "a", "b"), "師弟")
        self.assertEqual(c.total_changes, changes + 2)   # the two recipe edits; address() itself wrote nothing

    def test_a_town_is_not_a_sect_even_when_two_people_share_a_faction(self):
        c = self.town
        self.assertNotIn("jianghu", c.execute("SELECT value FROM meta WHERE key = 'recipe'").fetchone()[0])
        same = c.execute("SELECT faction_id FROM affiliations WHERE person_id = 'ming'").fetchone()[0]
        self.assertEqual(same, c.execute("SELECT faction_id FROM affiliations WHERE person_id = 'mei'").fetchone()[0])
        self.assertIsNone(address(c, "ming", "mei"))

    def test_a_line_that_opens_with_the_listeners_name_uses_the_surname_and_the_term(self):
        c, names = self.v1, _names(self.v1)
        self.assertEqual(_open_as_kin(c, "shi", "lu", "陸青，今日請教。", names), "陸師兄，今日請教。")
        self.assertEqual(_open_as_kin(c, "su", "lin", "林遠山，弟子有禮。", names), "林掌門，弟子有禮。")
        self.assertEqual(_open_as_kin(c, "lu", "su", "蘇小婉，你來了。", names), "蘇師妹，你來了。")
        gossip = "蘇小婉弄丟了東西，你知道嗎？"
        self.assertEqual(_open_as_kin(c, "lu", "shi", gossip, names), gossip)
        self.assertEqual(_open_as_kin(c, "lu", "hong", "鐵驚鴻，久仰。", names), "鐵驚鴻，久仰。")
        out = {"say": "陸青，接招！", "subtext": "陸青，心裡有事", "reactions": [{"who": "su", "say": "陸青，好身手！"}]}
        _apply_kinship(c, out, "shi", "lu", names)
        self.assertEqual(out["say"], "陸師兄，接招！")
        self.assertEqual(out["subtext"], "陸青，心裡有事")
        self.assertEqual(out["reactions"][0]["say"], "陸青，好身手！")
        said = in_own_words({"say": "最近好嗎？", "subtext": "x"}, {"reason": "陸青，今日向你請教。"}, (), "talk",
                            conn=c, speaker="shi", listener="lu", names=names)
        self.assertEqual(said["say"], "陸師兄，今日向你請教。")
        self.assertEqual(said["template"], "最近好嗎？")
        aloud = in_own_words({"say": "最近好嗎？"}, {"reason": "agent:我上前。", "say": "陸青，今日請教。"}, (), "talk",
                             conn=c, speaker="shi", listener="lu", names=names)
        self.assertEqual((aloud["say"], aloud["monologue"]), ("陸師兄，今日請教。", "我上前。"))
        duel = in_own_words({"say": "技不如人，我認了。"}, {"reason": "陸青，今天跟你分個高下！"}, (), "duel",
                            conn=c, speaker="shi", listener="lu", names=names)
        self.assertEqual((duel["opening"], duel["say"]), ("陸師兄，今天跟你分個高下！", "技不如人，我認了。"))
        thought = in_own_words({"say": "最近好嗎？"}, {"reason": "陸青今天看起來不一樣。"}, (), "talk",
                               conn=c, speaker="shi", listener="lu", names=names)
        self.assertEqual(thought["say"], "最近好嗎？")
        self.assertEqual(thought["monologue"], "陸青今天看起來不一樣。")
        plain = speak(c, 3, "talk", {"actor": "shi", "target": "lu", "tone": "neutral"}, names)
        self.assertFalse(plain["say"].startswith("陸"))


class CoinTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.drama = world("jianghu_drama_v1")
        cls.story = world("jianghu_story_v1")

    def test_only_a_world_that_earns_its_goals_says_文錢(self):
        self.assertEqual(TEXT["save"], "存到{o}元")
        self.assertEqual(SAVE_EARNED, "攢下{o}文錢")
        self.assertEqual(text_of("save"), "存到{o}元")
        self.assertEqual(text_of("save", self.story), "存到{o}元")
        self.assertEqual(text_of("save", self.drama), "攢下{o}文錢")
        self.assertEqual(text_of("repay", self.drama), "還清欠{t}的錢")
        self.assertEqual(describe(self.drama, find(self.drama, "mei", "save")), "攢下500文錢")
        self.assertEqual(describe(self.drama, find(self.drama, "tao", "save")), "攢下400文錢")
        self.assertEqual(describe(self.story, find(self.story, "mei", "save")), "存到500元")
        self.assertEqual(describe(self.story, find(self.story, "tao", "save")), "存到400元")


if __name__ == "__main__":
    unittest.main()
