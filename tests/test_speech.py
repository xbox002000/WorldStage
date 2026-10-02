"""Speech: what people say in the situation they are in. A read model: it never reaches back into the world."""
from __future__ import annotations

import json
import unittest

from narrative import speech as S
from narrative.lines import line
from world.db import connect, init_db
from world.seed import build_world


def stub(**cache):
    """A situation without a database: {"rel": {(a, b, field): value}, "traits": {pid: {name: v}}, "emo": {pid: x}, "skill": {pid: v}}."""
    c = S.Ctx(None, 100, {}, 12 * 60, "inn")
    for (a, b, f), v in cache.get("rel", {}).items():
        c._cache[("rel", a, b, f)] = v
    for pid, tr in cache.get("traits", {}).items():
        c._cache[("traits", pid)] = tr
    for pid, e in cache.get("emo", {}).items():
        c._cache[("emo", pid)] = e
    for pid, v in cache.get("skill", {}).items():
        c._cache[("skill", pid)] = v
    c._cache["jianghu"] = cache.get("jianghu", False)
    return c


class Choosing(unittest.TestCase):
    def test_the_same_event_always_says_the_same_thing(self):
        c = stub()
        self.assertEqual(S._pick(S.TALK["warm"], c, "a", "b"), S._pick(S.TALK["warm"], c, "a", "b"))

    def test_a_line_with_a_condition_is_said_only_when_the_condition_holds(self):
        cold = stub(rel={("a", "b", "attraction"): 0.0, ("a", "b", "affection"): 0.0})
        warm = stub(rel={("a", "b", "attraction"): 0.5})
        said_cold = {S._pick(S.TALK["warm"], _with_id(cold, i), "a", "b") for i in range(60)}
        said_warm = {S._pick(S.TALK["warm"], _with_id(warm, i), "a", "b") for i in range(60)}
        self.assertNotIn("和你說話，總是特別自在。", said_cold)
        self.assertIn("和你說話，總是特別自在。", said_warm)

    def test_who_is_speaking_changes_what_is_said(self):
        proud = _with_id(stub(rel={("a", "b", "respect"): -0.4}), 0)
        pool = [t for t, g in S.CHALLENGE if g is S.scorns]
        got = {S._pick(S.CHALLENGE, _with_id(stub(rel={("a", "b", "respect"): -0.4}), i), "a", "b") for i in range(80)}
        self.assertTrue(set(pool) & got)
        calm = {S._pick(S.CHALLENGE, _with_id(stub(rel={("a", "b", "respect"): 0.5}), i), "a", "b") for i in range(80)}
        self.assertFalse(set(pool) & calm)
        self.assertTrue(proud)

    def test_a_polite_word_through_a_grudge_has_a_subtext_and_a_cold_one_to_somebody_loved_too(self):
        grudge = stub(rel={("a", "b", "resentment"): 0.5})
        self.assertIn("還在氣", S._talk_subtext(grudge, "a", "b", "warm"))
        love = stub(rel={("a", "b", "attraction"): 0.6})
        self.assertIn("在意", S._talk_subtext(love, "a", "b", "cold"))
        scared = stub(rel={("a", "b", "fear"): 0.5})
        self.assertIn("怕", S._talk_subtext(scared, "a", "b", "hostile"))
        self.assertEqual(S._talk_subtext(stub(), "a", "b", "warm"), "")

    def test_what_the_speaker_feels_shows_through_an_ordinary_word(self):
        hurt = stub(emo={"a": "hurt"})
        self.assertIn("沒說出口", S._talk_subtext(hurt, "a", "b", "neutral"))
        angry = stub(emo={"a": "angry"})
        self.assertIn("火氣", S._talk_subtext(angry, "a", "b", "cold"))
        self.assertEqual(S._talk_subtext(angry, "a", "b", "hostile"), "")


def _with_id(ctx, i):
    ctx.event_id = i
    return ctx


class Duels(unittest.TestCase):
    def test_those_who_looked_down_gasp_and_the_others_cheer(self):
        c = stub()
        t = {"actor": "kai", "target": "hao", "winner": "hao", "loser": "kai", "gaps": {"mei": 0.3, "ning": 0.2, "kai": 0.4},
             "slap": {"underdog": "hao", "surprise": 0.3, "witnesses": 2, "sneered": ["mei"]}}
        out = S._duel(c, t, "kai", "hao", {})
        who = {r["who"]: r["say"] for r in out["reactions"]}
        self.assertEqual(set(who), {"mei", "ning"})
        self.assertIn(who["mei"], [x for x, _ in S.GASP_SNEERER])
        self.assertIn(who["ning"], [x for x, _ in S.GASP_OTHER])
        self.assertIn(out["answer"], [x for x, _ in S.DUEL_WON])     # the one challenged won: how a winner takes it

    def test_a_duel_with_no_surprise_has_no_gasping(self):
        out = S._duel(stub(), {"actor": "kai", "target": "hao", "winner": "kai", "loser": "hao", "gaps": {"mei": 0.01}}, "kai", "hao", {})
        self.assertNotIn("reactions", out)

    def test_a_succession_is_congratulated_by_the_ones_who_lost(self):
        out = S._succession(stub(), {"winner": "jun", "candidates": ["jun", "kai", "ming"]}, "jun")
        self.assertEqual({r["who"] for r in out["reactions"]}, {"kai", "ming"})


class InAWorld(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from agent.volition import VolitionDecider
        from producer.director import Director
        from runtime.godview import _names
        from world.simulation import Simulation
        cls.c = connect()
        init_db(cls.c, 501)
        build_world(cls.c, 501, "jianghu_story_v1")
        d = VolitionDecider(501)
        Simulation(cls.c, d, d, set(), feed="synthetic_v1", producer=Director("greedy", 501)).run(10)
        cls.names = _names(cls.c)
        cls.rows = cls.c.execute("SELECT event_id, timestamp, type, location_id, truth FROM events ORDER BY event_id").fetchall()

    def lines(self):
        for r in self.rows:
            if r["type"] != "day_end":
                yield r, S.speak(self.c, r["event_id"], r["type"], r["truth"], self.names, r["timestamp"], r["location_id"] or "")

    def test_it_says_at_least_as_much_as_the_old_lines_and_far_more_kinds_of_it(self):
        old = new = 0
        kinds_old, kinds_new = set(), set()
        for r, got in self.lines():
            was = line(r["event_id"], r["type"], r["truth"], self.names)
            old += bool(was)
            new += bool(got)
            if was:
                kinds_old.add(r["type"])
            if got:
                kinds_new.add(r["type"])
        self.assertGreaterEqual(new, old)
        self.assertTrue(kinds_old <= kinds_new)
        self.assertTrue({"goal_change"} <= kinds_new)           # what used to be silent has a voice

    def test_talk_has_many_more_sentences_than_the_old_five_a_tone(self):
        said = {got["say"] for r, got in self.lines() if got and r["type"] == "talk"}
        old = {line(r["event_id"], r["type"], r["truth"], self.names)["say"] for r in self.rows if r["type"] == "talk"}
        self.assertGreater(len(said), len(old))

    def test_the_same_world_reads_the_same(self):
        a = [(r["event_id"], got and got["say"]) for r, got in self.lines()]
        b = [(r["event_id"], got and got["say"]) for r, got in self.lines()]
        self.assertEqual(a, b)

    def test_a_martial_world_does_not_talk_about_basketball(self):
        said = " ".join(got["say"] for _, got in self.lines() if got)
        self.assertNotIn("籃球", said)

    def test_it_only_reads(self):
        before = self.c.execute("SELECT COUNT(*) FROM events").fetchone()[0], self.c.execute("SELECT SUM(LENGTH(truth)) FROM events").fetchone()[0]
        list(self.lines())
        self.assertEqual((self.c.execute("SELECT COUNT(*) FROM events").fetchone()[0], self.c.execute("SELECT SUM(LENGTH(truth)) FROM events").fetchone()[0]), before)


    def test_what_is_underneath_a_feeling_is_said_only_with_its_cause_and_never_loses_the_old_subtext(self):
        carried = 0
        for r, got in self.lines():
            if got and "inner" in got:
                carried += 1
                self.assertTrue(got["subtext"].endswith(got["inner"]["underneath"]))
                self.assertTrue(self.c.execute("SELECT 1 FROM events WHERE event_id = ?", (got["inner"]["because"]["event_id"],)).fetchone())
                self.assertLess(got["inner"]["because"]["event_id"], r["event_id"])
        self.assertGreater(carried, 0)
        S.INNER_SUBTEXT = False
        try:
            plain = sum(1 for r, got in self.lines() if got and got.get("subtext"))
        finally:
            S.INNER_SUBTEXT = True
        self.assertGreater(sum(1 for r, got in self.lines() if got and got.get("subtext")), plain)


class Underneath(unittest.TestCase):
    def test_without_a_world_nothing_is_underneath(self):
        c = stub(emo={"a": "hurt"})
        self.assertIsNone(c.underneath("a", "b"))
        out = {"say": "嗯。", "stance": "neutral"}
        S._with_inner(c, out, "talk", "a", "b")
        self.assertEqual(out, {"say": "嗯。", "stance": "neutral"})

    def test_what_the_relationship_gave_is_not_replaced_but_a_bare_emotion_is_open_to_a_better_reading(self):
        class Fake(S.Ctx):
            def underneath(self, pid, addressee=""):
                return {"surface": "angry", "underneath": "怕被他丟下", "because": {"event_id": 1, "type": "talk", "text": "x"},
                        "confidence": 0.7, "rule": "r", "surface_zh": "生氣"}
        c = Fake(None, 100, {}, 0, "")
        kept = {"say": "嗯。", "subtext": "話說得客氣，心裡其實還在氣"}
        S._with_inner(c, kept, "talk", "a", "b")
        self.assertEqual(kept["subtext"], "話說得客氣，心裡其實還在氣")
        bare = {"say": "嗯。", "subtext": "壓著火氣"}
        S._with_inner(c, bare, "talk", "a", "b")
        self.assertEqual(bare["subtext"], "表面生氣，底下是怕被他丟下")
        self.assertEqual(bare["inner"]["underneath"], "怕被他丟下")
        murmur = {"say": "再一次。"}
        S._with_inner(c, murmur, "goal_change", "a", "")
        self.assertNotIn("subtext", murmur)


class Words(unittest.TestCase):
    def pools(self):
        for name in dir(S):
            v = getattr(S, name)
            if isinstance(v, list) and v and isinstance(v[0], tuple):
                yield name, v
            elif isinstance(v, dict) and v and all(isinstance(x, list) for x in v.values()):
                for k, pool in v.items():
                    yield f"{name}.{k}", pool

    def test_every_pool_has_a_line_that_is_always_available(self):
        for name, pool in self.pools():
            self.assertTrue(any(g is None for _, g in pool), name)

    def test_no_line_speaks_of_a_model_a_lens_or_the_producer(self):
        bad = ("cinematic", "8k", "producer", "製作人", "劇本", "爽點")
        for name, pool in self.pools():
            for text, _ in pool:
                self.assertFalse(any(b in text for b in bad), (name, text))

    def test_romance_stays_within_what_a_public_channel_shows(self):
        banned = ("上床", "做愛", "親吻", "身體", "裸")
        for pool in (S.FLIRT, S.CONFESS, S.CONFESS_YES, S.CONFESS_NO, S.DATE, S.BREAK_UP):
            for text, _ in pool:
                self.assertFalse(any(b in text for b in banned), text)

    def test_a_domains_own_lines_are_the_fall_back(self):
        c = connect()
        init_db(c, 1)
        got = S.speak(c, 1, "spell", {"actor": "x"}, {})
        self.assertEqual(got, line(1, "spell", {"actor": "x"}, {}))


NAMES = {"ming": "阿明", "kai": "阿凱", "mei": "小美", "hao": "阿豪", "tao": "阿濤", "ring": "戒指", "purse": "錢袋"}


def tell(speaker, listener, subject, act, obj, text, etype="tell", polarity="affirm", eid=100):
    truth = {"actor": speaker, "target": listener, "text": text, "asserted_claim": {"subject": subject, "act": act, "object": obj, "polarity": polarity}}
    if etype != "tell":
        truth["claim"] = truth.pop("asserted_claim")
    return S.speak(None, eid, etype, truth, NAMES)["say"]


class Telling(unittest.TestCase):
    """What is passed on is a claim, told in the speaker's and the listener's own terms (L1, L2 of narrative/lint.py)."""

    def test_somebody_who_tells_of_themselves_says_i(self):
        for eid in range(100, 140):
            say = tell("ming", "kai", "ming", "lose", "purse", "阿明弄丟了錢袋", eid=eid)
            self.assertNotIn("阿明", say)
            self.assertIn("我弄丟了錢袋", say)

    def test_a_thing_about_the_listener_is_told_as_what_people_say_not_as_news_in_a_strangers_voice(self):
        for eid in range(100, 140):
            say = tell("ming", "kai", "kai", "take", "ring", "阿凱拿走了戒指", eid=eid)
            self.assertNotIn("阿凱", say)
            self.assertIn("你拿走了戒指", say)

    def test_a_thing_about_somebody_else_names_them(self):
        say = tell("ming", "kai", "mei", "lose", "ring", "小美弄丟了戒指")
        self.assertIn("小美弄丟了戒指", say)
        self.assertNotIn("阿明", say)

    def test_a_denial_keeps_its_denial_in_every_voice(self):
        self.assertIn("你沒有拿走戒指", tell("ming", "kai", "kai", "take", "ring", "阿凱沒有拿走戒指", polarity="deny"))
        self.assertIn("我沒有拿走戒指", tell("ming", "kai", "ming", "take", "ring", "阿明沒有拿走戒指", polarity="deny"))

    def test_a_tone_is_never_passed_on_word_for_word(self):
        for act, word in (("speak_cold", "冷淡地"), ("speak_hostile", "敵意地"), ("speak_warm", "親切地")):
            for eid in range(100, 112):
                for who in (("ming", "kai", "tao", "hao"), ("ming", "kai", "kai", "hao"), ("ming", "kai", "ming", "hao"), ("ming", "kai", "mei", "kai")):
                    say = tell(who[0], who[1], who[2], act, who[3], f"{NAMES[who[2]]}{word}對{NAMES[who[3]]}說話", eid=eid)
                    for bad in ("冷淡地", "敵意地", "親切地", "質問", "閒聊"):
                        self.assertNotIn(bad, say)
                    self.assertNotIn(NAMES[who[0]], say)
                    if who[1] in (who[2], who[3]):
                        self.assertNotIn(NAMES[who[1]], say)

    def test_a_confrontation_is_put_in_the_confronters_terms_too(self):
        say = tell("tao", "mei", "tao", "speak_hostile", "hao", "阿濤敵意地質問阿豪", etype="confront")
        self.assertNotIn("阿濤", say)
        self.assertNotIn("敵意地", say)
        self.assertIn("我", say)
        say = tell("tao", "mei", "ming", "take", "ring", "阿明拿走了戒指", etype="confront")
        self.assertIn("阿明拿走了戒指", say)

    def test_the_same_event_always_says_the_same_and_another_variant_can_say_another_line(self):
        truth = {"actor": "ming", "target": "kai", "text": "小美弄丟了戒指", "asserted_claim": {"subject": "mei", "act": "lose", "object": "ring", "polarity": "affirm"}}
        a = S.speak(None, 100, "tell", truth, NAMES)["say"]
        self.assertEqual(a, S.speak(None, 100, "tell", truth, NAMES)["say"])
        self.assertTrue({S.speak(None, 100, "tell", truth, NAMES, variant=v)["say"] for v in range(9)} - {a})


class Replies(unittest.TestCase):
    def test_every_reply_pool_has_at_least_twelve_lines_and_none_is_from_our_own_time(self):
        from narrative.lint import MODERN_WORDS
        for name, pool in S.REPLY.items():
            self.assertGreaterEqual(len(pool), 12, name)
            self.assertEqual(len({t for t, _ in pool}), len(pool), name)
            for text, _ in pool:
                self.assertFalse(any(w in text for w in MODERN_WORDS), (name, text))

    def test_no_pool_of_the_martial_world_has_a_modern_word(self):
        from narrative.lint import MODERN_WORDS
        for pool in (*S.AFTER_DUEL.values(), *S.TELL.values(), *S.CONFRONT.values(), S.CHALLENGE, S.DUEL_WON, S.DUEL_LOST):
            for text, _ in pool:
                self.assertFalse(any(w in text for w in MODERN_WORDS), text)


class AfterTheDuel(unittest.TestCase):
    """The talk of two people who have just fought is about the fight: whoever lost does not talk like the one who won (L8)."""

    @classmethod
    def setUpClass(cls):
        from world.events import EventSpec, apply_event
        cls.c = connect()
        init_db(cls.c, 1)
        build_world(cls.c, 1, "jianghu_story_v1")
        cls.duel = apply_event(cls.c, EventSpec(timestamp=1000, type="duel", trigger_type="decision", importance=0.5,
                                                truth={"actor": "hao", "target": "tao", "winner": "hao", "loser": "tao"}, participants=[("hao", "actor"), ("tao", "target")]))

    def say(self, speaker, listener, eid=None, reason="reply:retort", ts=1001):
        truth = {"actor": speaker, "target": listener, "tone": "hostile", "reason": reason}
        return S.speak(self.c, self.duel + (eid or 2), "talk", truth, NAMES, ts)["say"]

    def test_the_loser_and_the_winner_each_have_their_own_pool(self):
        lost = {t for t, _ in S.AFTER_DUEL["lost"]}
        won = {t for t, _ in S.AFTER_DUEL["won"]}
        for eid in range(1, 13):
            self.assertIn(self.say("tao", "hao", eid), lost)
            self.assertIn(self.say("hao", "tao", eid), won)
        self.assertNotIn("你才是！", {self.say("tao", "hao", eid) for eid in range(1, 13)})

    def test_it_holds_for_a_plain_word_between_the_two_too_but_not_for_others_or_for_later(self):
        lost = {t for t, _ in S.AFTER_DUEL["lost"]}
        self.assertIn(self.say("tao", "hao", 3, reason="volition"), lost)
        self.assertNotIn(self.say("mei", "kai", 3), lost)                       # somebody else's quarrel
        self.assertNotIn(self.say("tao", "hao", S.DUEL_WINDOW + 1), lost)       # long after
        self.assertNotIn(self.say("tao", "hao", 3, ts=1000 + 31), lost)         # half an hour on, it is not about the bout

    def test_without_a_world_nothing_is_after_a_duel(self):
        self.assertEqual(S._after_duel(stub(), "tao", "hao"), "")


if __name__ == "__main__":
    unittest.main()
