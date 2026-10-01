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


if __name__ == "__main__":
    unittest.main()
