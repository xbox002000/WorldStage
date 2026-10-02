"""The jianghu_drama content pack and recipe, the night before a vote, and prompt v2 with its checked answers.

What must hold: the pack is a jianghu all the way down (names, past, habits, topics: no modern word anywhere), its cast is the story world's
cast with other names; the old recipes are untouched (the succession of jianghu_story_v1 has no night before it, and its result no cause);
prompt v1 is byte for byte the prompt the recorded worlds were asked; v2 says the era and who is he or she; and a v2 answer that names a
modern thing, is about another option, or uses the wrong he or she is not acted on.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from agent.cognition import (ERA_LINES, MODERN_WORDS, PROMPT, PROMPT_V2, AnswerRejected, CharacterAgent, check_answer, cognitive_state,
                             describe_intent, pronoun_line, world_era)
from agent.volition import VolitionDecider
from contracts.base import to_dict
from contracts.character import check_roster
from world.content import content_module
from world.db import connect, init_db
from world.succession import STANCES
from world.events import Change, EventSpec, apply_event
from world.intent import Intent
from world.profiles import load_roster, profile
from world.recipes import compiled, load_recipe
from world.seed import build_world
from world.simulation import Simulation

ROOT = Path(__file__).resolve().parent.parent
RECIPES = ("jianghu_drama_v1", "jianghu_drama_spatial_v1")
# a jianghu has no word for these (not the same list as the agent's: this is the author's check of a content pack)
MODERN = ("手機", "咖啡", "辦公室", "加班", "上班", "下班", "同事", "老闆", "主管", "公司", "電影", "電視", "籃球", "足球", "大學", "電腦", "網路",
          "專輯", "電玩", "遊戲", "汽車", "捷運", "機票", "超商", "銀行", "薪水", "業績", "音樂", "閱讀", "穿搭", "畫畫", "理財", "旅行", "公園",
          "車站", "公寓", "台中", "台北", "高雄", "基隆", "花蓮", "專科", "研究所", "西裝", "襯衫", "牛仔", "毛衣", "洋裝", "背包", "手錶", "新聞",
          "眼鏡", "筆電", "設計學校")
# names of people from the novels this pack must not use, a few of the best known (it is not a complete list: the names were made up)
FAMOUS = ("令狐沖", "楊過", "蕭峰", "郭靖", "黃蓉", "小龍女", "張無忌", "韋小寶", "段譽", "虛竹", "喬峰", "任盈盈", "東方不敗", "岳不群", "李尋歡", "楚留香",
          "陸小鳳", "花滿樓", "西門吹雪", "傅紅雪", "燕南天", "蕭十一郎", "沈浪", "王憐花", "朱七七", "林仙兒", "葉孤城", "司空摘星", "丁鵬", "謝曉峰", "小李飛刀")
# the names of the other packs in the repository (a name must be this world's own)
OTHER_PACKS = ("jianghu_v1", "town_v1")


def pack_texts() -> list[str]:
    mod = content_module("jianghu_drama")
    out = [(ROOT / "world/content/profiles/jianghu_drama.json").read_text(encoding="utf-8"),
           (ROOT / "world/content/genomes/jianghu_drama.json").read_text(encoding="utf-8")]
    out += [n + g for _, n, g in mod.PEOPLE]
    out += list(mod.PERSONAS.values()) + [o[1] for o in mod.OBJECTS] + [loc[1] for loc in mod.LOCATIONS]
    out += [f[1] + f[3] for f in mod.FACTIONS] + [s[1] for s in mod.SEATS]
    return out


class ThePack(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.roster = load_roster("jianghu_drama")
        cls.mod = content_module("jianghu_drama")

    def test_the_roster_passes_the_roster_check_and_is_the_story_worlds_cast(self):
        self.assertIsNotNone(self.roster)
        self.assertEqual(check_roster(self.roster), [])
        story = content_module("jianghu_story")
        self.assertEqual([p.id for p in self.roster.people], [p[0] for p in story.PEOPLE])
        self.assertEqual([p[0] for p in self.mod.PEOPLE], [p[0] for p in story.PEOPLE])
        self.assertEqual(self.mod.SKILL, story.SKILL)
        self.assertEqual(self.mod.UNDERRATED, story.UNDERRATED)  # the two who are better than they are taken for
        self.assertEqual({p.id: p.gender for p in self.roster.people}, {p.id: p.gender for p in load_roster("jianghu_story").people})
        self.assertEqual({p.id: p.age for p in self.roster.people}, {p.id: p.age for p in load_roster("jianghu_story").people})

    def test_everyone_is_an_adult(self):
        self.assertTrue(all(p.age >= 18 for p in self.roster.people), [p.age for p in self.roster.people])

    def test_names_have_a_family_name_and_a_given_name_and_are_nobody_elses(self):
        names = [p.name for p in self.roster.people]
        self.assertEqual(len(set(names)), len(names))
        self.assertEqual(names, [n for _, n, _ in self.mod.PEOPLE])  # one name in the roster and the world
        for n in names:
            self.assertGreaterEqual(len(n), 2, n)
            self.assertNotIn(n[0], "阿小老", n)  # not the town's 阿X, 小X
        self.assertFalse(set(names) & set(FAMOUS))
        self.assertFalse([f for f in FAMOUS if any(f in t for t in pack_texts())])
        for other in OTHER_PACKS:
            self.assertFalse(set(names) & {p.name for p in load_roster(other).people}, other)

    def test_not_one_modern_word_in_the_pack(self):
        texts = pack_texts()
        hits = {w: [t[:30] for t in texts if w in t] for w in MODERN if any(w in t for t in texts)}
        self.assertEqual(hits, {})

    def test_the_built_world_has_no_modern_word_either(self):
        c = connect()
        init_db(c, 3)
        build_world(c, 3, "jianghu_drama_v1")
        rows = [r[0] for r in c.execute("SELECT name FROM people")] + [r[0] for r in c.execute("SELECT text FROM personas")]
        rows += [r[0] for r in c.execute("SELECT name FROM locations")] + [r[0] for r in c.execute("SELECT name FROM objects")]
        rows += [r[0] for r in c.execute("SELECT label FROM content_topics")] + [r[0] for r in c.execute("SELECT profile FROM character_profiles")]
        rows += [r[0] for r in c.execute("SELECT genome FROM character_genomes")] + [r[0] for r in c.execute("SELECT belief FROM memories")]
        rows += [r[0] for r in c.execute("SELECT goal FROM people")]
        self.assertGreater(len(rows), 60)
        self.assertEqual({w for w in MODERN for t in rows if w in t}, set())
        # and the topic words are the jianghu's: the town's topics are not here
        topics = {r[0] for r in c.execute("SELECT topic FROM content_topics")}
        self.assertFalse(topics & {"music", "reading", "basketball", "coffee", "old_movies", "fashion", "drawing", "games"}, topics)
        self.assertTrue({"manuals", "tea", "wine", "chess", "horses", "escort", "legends", "herbs"} <= topics)
        for want in (self.roster.topics, ):
            self.assertTrue(all(label for label in want.values()))

    def test_the_story_and_the_background_are_the_jianghus(self):
        for p in self.roster.people:
            self.assertTrue(p.background.get("birthplace") and p.background.get("family"), p.id)
            self.assertTrue(all(h.label for h in p.habits) and p.habits, p.id)
            for t in list(p.interests) + list(p.dislikes):
                self.assertIn(t, self.roster.topics)
        disciples = [p for p in self.roster.people if p.occupation is not None]
        self.assertEqual(sorted(p.id for p in disciples), sorted(self.mod.DISCIPLES))
        for p in disciples:  # a job here is the sect's: the words are the sect's
            self.assertEqual(p.occupation.words["quit"], "離開師門")
            self.assertEqual(p.occupation.words["overtime"], "加練")
            self.assertEqual(p.occupation.place, "qingyun")
        # the old business is still there, in these names
        c = connect()
        init_db(c, 3)
        build_world(c, 3, "jianghu_drama_v1")
        text = c.execute("SELECT json_extract(truth, '$.text') FROM events WHERE type = 'backstory'").fetchone()[0]
        self.assertIn("江映月", text)
        self.assertIn("沈青璃", text)

    def test_the_recipe_is_the_story_recipe_with_the_night_before_a_vote(self):
        story = load_recipe("jianghu_story_v1")
        story_sp = load_recipe("jianghu_story_spatial_v1")
        for rid, base in (("jianghu_drama_v1", story), ("jianghu_drama_spatial_v1", story_sp)):
            r = load_recipe(rid)
            compiled(rid)  # compiles
            self.assertEqual(r.content, "jianghu_drama")
            self.assertEqual((r.core, r.pillars, r.accents, r.narrative, r.style), (base.core, base.pillars, base.accents, base.narrative, base.style))
            added = ("social.succession_process", "social.impression", "goals.earned")   # the night before a vote, first impressions, goals that are earned
            self.assertEqual([b for b in r.base if b not in added], base.base)
            for p in added:
                self.assertIn(p, r.base)
        self.assertNotIn("social.succession_process", story.base)


class TheNightBeforeTheVote(unittest.TestCase):
    """A seat falls vacant with some standing for it; the vote is the dawn of day 2. Same people, same seed: only the recipe differs."""

    @staticmethod
    def scenario(recipe: str, seed: int = 9):
        c = connect()
        init_db(c, seed)
        build_world(c, seed, recipe)
        d = VolitionDecider(seed)
        sim = Simulation(c, d, d, set())
        sim.run(1)
        decide_by = c.execute("SELECT decide_by FROM seats WHERE seat_id = 'chief_disciple'").fetchone()[0]
        last = c.execute("SELECT MAX(timestamp) FROM events").fetchone()[0]
        apply_event(c, EventSpec(timestamp=last, type="intervention", trigger_type="rule", importance=0.1, truth={"text": "the seat falls vacant"},
                                 changes=[Change("seat", "chief_disciple", "status", value="vacant"),
                                          Change("seat", "chief_disciple", "decide_by", delta=2 - decide_by)]
                                 + [Change("var", f"cand.{p}", "value", delta=1.0) for p in ("hao", "kai", "jun")]))
        sim.run(2)
        return c

    @classmethod
    def setUpClass(cls):
        cls.new = cls.scenario("jianghu_drama_v1")
        cls.old = cls.scenario("jianghu_story_v1")

    def rows(self, c, types):
        return [(r["event_id"], r["type"], r["timestamp"], r["parent_event_id"], json.loads(r["truth"]))
                for r in c.execute(f"SELECT * FROM events WHERE type IN ({','.join('?' * len(types))}) ORDER BY event_id", types)]

    def test_pledges_then_asking_then_council_then_the_vote_then_the_result(self):
        pledges = self.rows(self.new, ("succession_pledge",))
        council = self.rows(self.new, ("succession_council",))
        result = self.rows(self.new, ("succession",))
        self.assertEqual(len(council), 1)
        self.assertEqual(len(result), 1)
        standing = {t["actor"] for *_, t in pledges}
        self.assertTrue({"hao", "kai", "jun"} <= standing)          # each one standing says what they stand for (and nobody who is not)
        self.assertEqual(standing, set(council[0][4]["candidates"]))
        for _, _, ts, _, t in pledges:
            self.assertEqual(ts % 1440, 1439)                      # the night of day 1: the vote is the dawn of day 2
            self.assertIn(t["stance"], STANCES)                    # a closed list
            self.assertTrue(t["stance_label"] and t["line"])
        cid, _, cts, _, ct = council[0]
        self.assertEqual(ct["eve_of"], 2)
        self.assertEqual(set(ct["view"]), set(ct["candidates"]))   # what the elders saw in each of them
        self.assertTrue(ct["favoured"] == "" or ct["favoured"] in ct["view"])
        sid, _, sts, parent, st = result[0]
        self.assertEqual(sts // 1440, 2)
        self.assertEqual(parent, cid)                              # the result names the council as its cause
        self.assertTrue(all(p[0] < cid for p in pledges))          # pledges come first, the council last of the night
        self.assertLess(cid, sid)
        self.assertEqual(st["eve"][-1], cid)
        self.assertTrue(set(st["eve"]) >= {p[0] for p in pledges})
        asking = [r for r in self.rows(self.new, ("campaign",)) if r[4].get("eve_of") == 2]
        for aid, _, ats, _, at in asking:                          # the last round of asking is the ordinary campaign, resolved by the ordinary rule
            self.assertEqual(ats % 1440, 1439)
            self.assertEqual(at["reason"], "succession_eve")
            self.assertLess(aid, cid)
            self.assertGreater(aid, max(p[0] for p in pledges))

    def test_the_vote_still_decides(self):
        _, _, _, _, st = self.rows(self.new, ("succession",))[0]
        tally = st["tally"]
        self.assertEqual(sum(tally.values()), float(len(st["votes"])))   # one vote each (nobody leads the sect on stage)
        self.assertGreaterEqual(tally[st["winner"]], max(tally.values()))  # the winner is among those with the most votes
        self.assertEqual(self.new.execute("SELECT holder_id FROM seats WHERE seat_id = 'chief_disciple'").fetchone()[0], st["winner"])

    def test_the_old_recipe_has_no_night_before_and_its_result_no_cause(self):
        self.assertEqual(self.rows(self.old, ("succession_pledge", "succession_council")), [])
        result = self.rows(self.old, ("succession",))
        self.assertEqual(len(result), 1)
        _, _, _, parent, st = result[0]
        self.assertIsNone(parent)
        self.assertNotIn("eve", st)
        self.assertEqual([r for r in self.rows(self.old, ("campaign",)) if r[4].get("eve_of")], [])

    def test_the_new_events_can_be_read_by_the_story_machinery(self):
        from narrative.dramaturgy import analyse
        from runtime.godview import caption
        names = {r[0]: r[1] for r in self.new.execute("SELECT id, name FROM people")}
        for _, ty, _, _, t in self.rows(self.new, ("succession_pledge", "succession_council", "succession")):
            cap = caption(ty, t, "qingyun", names)
            self.assertTrue(cap and "{" not in cap, cap)
        self.assertIn("接下了", caption("succession", {"actor": "hao"}, "qingyun", names))  # the result no longer reads as losing the seat
        self.assertTrue(analyse(self.new)["situations"] is not None)


class PromptVersions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = connect()
        init_db(cls.c, 5)
        build_world(cls.c, 5, "jianghu_drama_v1")
        cls.names = {r[1]: r[0] for r in cls.c.execute("SELECT id, name FROM people")}

    def option(self, actor, action, target, **kw):
        return (0.5, Intent(actor, action, target, reason="volition", **kw))

    def test_prompt_v1_is_byte_for_byte_what_the_recorded_worlds_were_asked(self):
        import hashlib
        self.assertEqual(hashlib.sha256(PROMPT.encode("utf-8")).hexdigest(), "38a88fe4652081a51c84ea1c80fad51cd0c70a0183170d7f8ee0511f2670422e")
        self.assertNotEqual(PROMPT, PROMPT_V2)
        self.assertEqual(CharacterAgent(VolitionDecider(1)).prompt_version, 1)  # the default
        self.assertEqual(CharacterAgent(VolitionDecider(1), prompt_version=2).prompt_version, 2)
        with self.assertRaises(ValueError):
            CharacterAgent(VolitionDecider(1), prompt_version=4)

    def test_a_v1_agent_asks_exactly_the_v1_prompt(self):
        class Spy:
            model = "spy"
            prompts: list[str] = []

            def generate_json(self, prompt, schema, temperature=0.7):
                self.prompts.append(prompt)
                return {"option": 0, "reason": "x", "inner": ""}
        spy = Spy()
        c = connect()
        init_db(c, 8)
        build_world(c, 8, "jianghu_story_v1")
        agent = CharacterAgent(VolitionDecider(8), spy, budget=6, tier="A", per_person_day=2)
        Simulation(c, agent, agent, set()).run(2)
        self.assertTrue(spy.prompts)
        head, tail = PROMPT.split("{state}")
        for p in spy.prompts:
            self.assertTrue(p.startswith(head) and p.endswith(tail), p[:80])
            self.assertNotIn("性別", p)
            self.assertNotIn("古代", p)

    def test_v2_says_the_era_and_who_is_he_or_she(self):
        shown = [self.option("ming", "talk", "mei", tone="warm", topic="zither"), (0.1, None)]
        state = cognitive_state(self.c, "ming", 3000, shown, ["test"], 2)
        text = json.dumps(to_dict(state), ensure_ascii=False)
        self.assertEqual(state.who["性別"], "男（他）")
        self.assertIn("聊琴曲", state.options[0].text)          # the world's word for it, not a town's 聊音樂
        line = pronoun_line(self.c, text)
        self.assertIn("林嘯＝他", line)
        self.assertIn("沈青璃＝她", line)
        self.assertEqual(world_era(self.c), "martial_arts")
        prompt = PROMPT_V2.format(state=text, era=ERA_LINES[world_era(self.c)], pronouns=line)
        self.assertIn("古代的江湖", prompt)
        self.assertIn("沒有手機", prompt)
        self.assertIn("不要提到別的選項裡的人或事", prompt)
        # v1 of the same state has none of it
        v1 = cognitive_state(self.c, "ming", 3000, shown, ["test"])
        self.assertNotIn("性別", v1.who)

    def test_v2_in_a_world_with_no_era_says_none_and_refuses_no_word(self):
        c = connect()
        init_db(c, 5)
        build_world(c, 5, "town_v1")
        self.assertEqual(ERA_LINES.get(world_era(c), ""), "")
        shown = [(0.5, Intent("ming", "talk", "mei", tone="warm")), (0.1, None)]
        check_answer(c, "ming", shown, ["a", "b"], 0, "下班後想去喝咖啡，順便買新手機", "")  # a town has phones and coffee

    def test_v2_work_options_use_the_persons_own_words(self):
        look = describe_intent(self.c, Intent("jun", "look_for_work", reason="volition"), {}, 2)
        self.assertEqual(look, "偷偷打聽別的門派")
        self.assertEqual(describe_intent(self.c, Intent("jun", "accept_offer", reason="volition"), {}, 2), "接受邀請，離開師門")
        self.assertIn("找別的工作", describe_intent(self.c, Intent("jun", "look_for_work", reason="volition"), {}, 1))  # v1 as it was

    def _shown(self):
        shown = [self.option("kai", "talk", "mei", tone="warm", topic="tea"), self.option("kai", "confront", "hao"),
                 self.option("kai", "talk", "ming", tone="cold"), (0.0, None)]
        return shown, [describe_intent(self.c, it, {**{p: n for n, p in self.names.items()}}, 2) if it else "什麼都不做" for _, it in shown]

    def test_check_answer_refuses_a_modern_word_in_the_reason_or_the_thought(self):
        shown, texts = self._shown()
        check_answer(self.c, "kai", shown, texts, 0, "我想跟她聊聊茶", "")
        for word in ("手機", "咖啡", "辦公室", "大學"):
            self.assertIn(word, MODERN_WORDS)
        with self.assertRaises(AnswerRejected):
            check_answer(self.c, "kai", shown, texts, 0, "我想跟她聊聊新手機", "")
        with self.assertRaises(AnswerRejected):
            check_answer(self.c, "kai", shown, texts, 0, "聊聊茶", "下了班想去喝咖啡")

    def test_check_answer_refuses_a_reason_about_another_option(self):
        shown, texts = self._shown()
        # option 0 is for 沈青璃; this reason is about 顧長風, whom only option 1 is for
        with self.assertRaises(AnswerRejected):
            check_answer(self.c, "kai", shown, texts, 0, "顧長風又在搶功，我不能忍", "")
        check_answer(self.c, "kai", shown, texts, 1, "顧長風又在搶功，我不能忍", "")
        check_answer(self.c, "kai", shown, texts, 0, "沈青璃不會多問，跟她說說話就好", "")   # names the one it is for
        check_answer(self.c, "kai", shown, texts, 0, "想找個人說說話", "")                    # names nobody: nothing to contradict
        check_answer(self.c, "kai", shown, texts, 3, "顧長風的事我不想管", "")                 # doing nothing has no one it is for

    def test_check_answer_refuses_the_wrong_he_or_she(self):
        shown, texts = self._shown()
        with self.assertRaises(AnswerRejected):
            check_answer(self.c, "kai", shown, texts, 0, "他一向不愛說話，我就陪他喝茶", "")   # 沈青璃 is a she
        with self.assertRaises(AnswerRejected):
            check_answer(self.c, "kai", shown, texts, 1, "她太愛出風頭了", "")                  # 顧長風 is a he
        check_answer(self.c, "kai", shown, texts, 0, "她不愛說話，我陪她喝茶", "")
        check_answer(self.c, "kai", shown, texts, 1, "他總是搶在我前面", "我恨他")
        check_answer(self.c, "kai", shown, texts, 0, "其他人都在看，我陪她說說話", "")          # 其他 is not a pronoun

    def test_a_refused_answer_is_not_acted_on_and_is_not_an_answer(self):
        class Modern:
            model = "stub"

            def generate_json(self, prompt, schema, temperature=0.7):
                return {"option": 0, "reason": "想買新手機", "inner": "想去喝咖啡"}

        def run(version):
            c = connect()
            init_db(c, 8)
            build_world(c, 8, "jianghu_drama_v1")
            agent = CharacterAgent(VolitionDecider(8), Modern(), budget=6, tier="A", per_person_day=2, pause_on_quota=True, prompt_version=version)
            Simulation(c, agent, agent, set()).run(2)
            return c, agent
        c2, a2 = run(2)
        self.assertGreater(a2.stats["agent_rejected"], 0)
        self.assertEqual(a2.stats["agent"], 0)                       # nothing was taken as an answer
        self.assertEqual(a2.stats["agent_failed"], a2.stats["agent_rejected"])
        self.assertTrue(all(e.get("error") == "AnswerRejected" and e["why"] for e in a2.log))
        self.assertEqual(a2._streak, 0)                              # the provider did answer: it never stops a run
        self.assertEqual(c2.execute("SELECT COUNT(*) FROM events WHERE json_extract(truth, '$.reason') LIKE 'agent:%'").fetchone()[0], 0)
        c1, a1 = run(1)                                              # v1 does not check: the same words are taken
        self.assertGreater(a1.stats["agent"], 0)
        self.assertEqual(a1.stats["agent_rejected"], 0)


if __name__ == "__main__":
    unittest.main()


class PromptV3(unittest.TestCase):
    def test_v3_is_v2_asking_also_for_the_words_said_and_v1_v2_are_unchanged(self):
        from agent import cognition as C
        self.assertIn("say（你此刻開口說出的那一句話", C.PROMPT_V3)
        self.assertEqual(C.PROMPT_V3.replace("say（你此刻開口說出的那一句話，直接對著對方說，用你自己的口吻；你選的是不說話或不對人的事，就留空）、", ""), C.PROMPT_V2)
        self.assertIn("say", C.CHOICE_SCHEMA_V3["properties"])
        self.assertNotIn("say", C.CHOICE_SCHEMA["properties"])
        self.assertEqual(C.PROMPT_VERSIONS, (1, 2, 3))
