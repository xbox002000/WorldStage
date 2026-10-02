"""Putting a mind in people without wasting the free quota: what was paid for is not asked twice, a day the quota cannot
finish is not half-lived by the rules, and a world that was stopped and resumed is the world that was never stopped."""
from __future__ import annotations

import argparse
import json
import sqlite3
import tempfile
import unittest
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import soul_lab
from agent.cognition import CharacterAgent, QuotaPause
from agent.llm import FAILED, BudgetExceeded, LLMClient, QuotaExhausted
from agent.llm_cache import LLMCache
from agent.llm_ledger import Ledger, provider_day
from agent.volition import VolitionDecider
from world.db import connect


class ApiError(Exception):
    def __init__(self, code):
        self.code = code


def cache_db() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:", isolation_level=None)
    c.execute(soul_lab.CACHE_DDL)
    return c


def client(backend, **kw):
    return LLMClient("m", backend=backend, sleep=lambda s: None, min_interval=0, **kw)


class Ledgers(unittest.TestCase):
    def test_it_counts_by_model_and_by_the_providers_day(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            day = ["2026-10-01"]
            led = Ledger(Path(d) / "l.json", today=lambda: day[0])
            led.add("a")
            led.add("a")
            led.add("b")
            self.assertEqual((led.used("a"), led.used("b")), (2, 1))
            self.assertEqual(led.left("a", 5), 3)
            self.assertIsNone(led.left("a", None))
            day[0] = "2026-10-02"                                  # the quota resets: a new day, nothing spent
            self.assertEqual(led.used("a"), 0)
            self.assertEqual(Ledger(Path(d) / "l.json", today=lambda: "2026-10-01").used("a"), 2)   # and it is kept between runs

    def test_the_providers_day_is_pacific_time(self):
        self.assertEqual(provider_day(datetime(2026, 10, 2, 5, 0, tzinfo=timezone.utc)), "2026-10-01")   # 22:00 the evening before there
        self.assertEqual(provider_day(datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc)), "2026-10-02")


class Clients(unittest.TestCase):
    def test_what_was_paid_for_is_not_asked_again(self):
        asked = []
        c = client(lambda p, s, t: asked.append(p) or '{"option": 1}', mode="cache", cache=LLMCache(cache_db()))
        self.assertEqual(c.generate_json("same", {}), {"option": 1})
        self.assertEqual(c.generate_json("same", {}), {"option": 1})
        self.assertEqual(len(asked), 1)
        c.generate_json("other", {})
        self.assertEqual(len(asked), 2)

    def test_a_failure_is_not_kept_as_an_answer(self):
        cache = LLMCache(cache_db())
        c = client(lambda *a: '{"option": 0}', mode="cache", cache=cache)
        req, h = c.request("p", {}, 0.8)
        cache.put(h, req, {FAILED: True})
        self.assertEqual(c.generate_json("p", {}), {"option": 0})       # asked again (and then kept)
        self.assertNotIn(FAILED, cache.get(h))

    def test_a_known_daily_limit_is_refused_before_the_provider_has_to_say_no(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            asked = []
            led = Ledger(Path(d) / "l.json", today=lambda: "x")
            c = client(lambda *a: asked.append(1) or "{}", ledger=led, daily_limit=2)
            c.generate_json("a", {})
            c.generate_json("b", {})
            with self.assertRaises(QuotaExhausted):
                c.generate_json("c", {})
            self.assertEqual(len(asked), 2)
            self.assertEqual(led.used("m"), 2)
            self.assertIsInstance(QuotaExhausted("x"), BudgetExceeded)

    def test_every_try_counts_and_one_try_means_one(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            led = Ledger(Path(d) / "l.json", today=lambda: "x")

            def broken(*a):
                raise ApiError(503)

            c = client(broken, ledger=led, retries=1)
            with self.assertRaises(ApiError):
                c.generate_json("a", {})
            self.assertEqual(led.used("m"), 2)      # the try and its one retry: both spent


class Minds(unittest.TestCase):
    """A world with minds that is stopped by the quota and resumed."""
    args = argparse.Namespace(seed=501, recipe="jianghu_story_v1", budget=20, tier="A")

    @staticmethod
    def backend(prompt, schema, temperature):
        return json.dumps({"option": len(prompt) % 3, "reason": "照我的個性", "inner": "其實我很累"}, ensure_ascii=False)

    def minds(self, cache, **kw):
        return LLMClient("stub", backend=self.backend, sleep=lambda s: None, min_interval=0, mode="cache", cache=LLMCache(cache), **kw)

    def events(self, root: Path):
        c = connect(root / "world.db")
        rows = [(r["timestamp"], r["type"], r["truth"]) for r in c.execute("SELECT timestamp, type, truth FROM events ORDER BY event_id")]
        c.close()
        return rows

    def test_stopped_and_resumed_is_the_same_world_and_nothing_is_asked_twice(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            d = Path(d)
            whole_cache, cut_cache = cache_db(), cache_db()
            whole_client = self.minds(whole_cache)
            soul_lab.run_world(self.args, d / "whole", whole_client, 3, announce=lambda *_: None)
            total = whole_client.calls
            self.assertGreaterEqual(total, 4)                             # it is a world in which minds wake

            first = self.minds(cut_cache, max_calls=total // 2)           # the quota gives out in the middle
            res = soul_lab.run_world(self.args, d / "cut", first, 3, announce=lambda *_: None)
            self.assertIsNotNone(res["paused"])
            self.assertLess(res["days"], 3)
            stopped_at = res["days"]
            self.assertTrue(((d / "cut") / "world.db").exists())
            c = connect(d / "cut" / "world.db")                           # back at the end of a whole day, never half-lived
            last_end = c.execute("SELECT MAX(timestamp) FROM events WHERE type = 'day_end'").fetchone()[0]
            last_any = c.execute("SELECT MAX(timestamp) FROM events").fetchone()[0]
            c.close()
            self.assertEqual(last_end, last_any)

            second = self.minds(cut_cache)                                # tomorrow: the quota is back
            res2 = soul_lab.run_world(self.args, d / "cut", second, 3, announce=lambda *_: None)
            self.assertIsNone(res2["paused"])
            self.assertEqual(res2["days"], 3)
            self.assertGreaterEqual(stopped_at, 0)
            self.assertEqual(self.events(d / "whole"), self.events(d / "cut"))      # the world that was never stopped
            self.assertEqual(first.calls + second.calls, total)           # and every question was paid for once

    def test_a_broken_mind_stops_the_run_it_does_not_spend_the_day_failing(self):
        def broken(*a):
            raise ApiError(404)

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            c = LLMClient("stub", backend=broken, sleep=lambda s: None, min_interval=0, retries=0)
            res = soul_lab.run_world(self.args, Path(d) / "w", c, 2, announce=lambda *_: None)
            self.assertIsNotNone(res["paused"])
            self.assertIn("in a row", res["paused"])
            self.assertLessEqual(c.calls, 5)                              # five tries, not a day of them

    def test_tier_a_leaves_a_bad_mood_alone(self):
        from agent.cognition import MOOD_ONLY
        for tier, expect in (("A", True), ("AB", False)):
            with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
                a = argparse.Namespace(seed=501, recipe="jianghu_story_v1", budget=20, tier=tier)
                c = self.minds(cache_db())
                soul_lab.run_world(a, Path(d) / "w", c, 2, announce=lambda *_: None)
                rows = [json.loads(x) for x in (Path(d) / "w" / "decisions.jsonl").read_text(encoding="utf-8").splitlines()]
                only_mood = [r for r in rows if r["wake"] and all(w.startswith(MOOD_ONLY) for w in r["wake"])]
                self.assertEqual(not only_mood, expect, tier)

    @staticmethod
    def by_text(prompt, schema, temperature):
        """A mind that picks by what an option says, not where it is listed: the smallest text."""
        state = json.loads(prompt[prompt.index("{"):prompt.rindex("}") + 1])
        best = min(state["options"], key=lambda o: o["text"])
        return json.dumps({"option": best["n"], "reason": "x", "inner": ""}, ensure_ascii=False)

    def test_showing_the_options_in_another_order_does_not_change_what_is_chosen(self):
        events = {}
        for shuffle in (False, True):
            with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
                a = argparse.Namespace(seed=501, recipe="jianghu_story_v1", budget=20, tier="A", shuffle=shuffle)
                c = LLMClient("stub", backend=self.by_text, sleep=lambda s: None, min_interval=0)
                soul_lab.run_world(a, Path(d) / "w", c, 2, announce=lambda *_: None)
                events[shuffle] = self.events(Path(d) / "w")
                rows = [json.loads(x) for x in (Path(d) / "w" / "decisions.jsonl").read_text(encoding="utf-8").splitlines()]
                if shuffle:
                    self.assertTrue(any(r["shown_at"] != r["option"] for r in rows))   # it really was shown in another order
        self.assertEqual(events[False], events[True])

    def test_the_engines_own_shuffle_uses_the_worlds_rng_and_maps_back_too(self):
        from agent.cognition import option_order
        from world.db import init_db
        from world.seed import build_world
        from world.simulation import Simulation
        self.assertEqual(option_order(501, "kai", 100, 7), option_order(501, "kai", 100, 7))
        self.assertEqual(sorted(option_order(501, "kai", 100, 7)), list(range(7)))
        self.assertNotEqual({tuple(option_order(501, "kai", t, 7)) for t in range(0, 600, 30)}, {tuple(range(7))})
        events = {}
        for shuffle in (False, True):
            c = connect()
            init_db(c, 501)
            build_world(c, 501, "jianghu_story_v1")
            agent = CharacterAgent(VolitionDecider(501), LLMClient("stub", backend=self.by_text, sleep=lambda s: None, min_interval=0), tier="A", shuffle=shuffle)
            Simulation(c, agent, agent, set()).run(2)
            events[shuffle] = [(r["timestamp"], r["type"], r["truth"]) for r in c.execute("SELECT timestamp, type, truth FROM events ORDER BY event_id")]
        self.assertEqual(events[False], events[True])

    def test_one_person_wakes_only_so_often_in_a_day(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            a = argparse.Namespace(seed=501, recipe="jianghu_story_v1", budget=20, tier="A", per_person_day=1)
            c = self.minds(cache_db())
            soul_lab.run_world(a, Path(d) / "w", c, 3, announce=lambda *_: None)
            rows = [json.loads(x) for x in (Path(d) / "w" / "decisions.jsonl").read_text(encoding="utf-8").splitlines()]
            per = Counter((r["day"], r["person"]) for r in rows)
            self.assertTrue(rows)
            self.assertLessEqual(max(per.values()), 1)

    def test_a_choice_off_the_list_is_not_acted_on(self):
        c = connect()
        from world.db import init_db
        from world.seed import build_world
        init_db(c, 501)
        build_world(c, 501, "jianghu_story_v1")

        def off_the_list(*a):
            return json.dumps({"option": -1, "reason": "x", "inner": ""})

        agent = CharacterAgent(VolitionDecider(501), LLMClient("stub", backend=off_the_list, sleep=lambda s: None, min_interval=0, retries=0), tier="A")
        from world.simulation import Simulation
        Simulation(c, agent, agent, set()).run(2)
        self.assertEqual(agent.stats["agent"], 0)                         # no answer was taken, however many woke
        self.assertGreater(agent.stats["agent_failed"], 0)

    def test_a_world_says_which_prompt_it_was_asked_with_and_goes_on_with_it(self):
        def meta(root: Path) -> dict:
            c = sqlite3.connect(root / "world.db")
            try:
                return dict(c.execute("SELECT key, value FROM meta").fetchall())
            finally:
                c.close()
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            d = Path(d)
            v1 = argparse.Namespace(seed=501, recipe="jianghu_story_v1", budget=20, tier="A")          # no flag: prompt v1, as before, and it says nothing
            soul_lab.run_world(v1, d / "v1", soul_lab.DryMind(), 1, announce=lambda *_: None)
            self.assertNotIn("prompt_version", meta(d / "v1"))
            v2 = argparse.Namespace(seed=501, recipe="jianghu_drama_v1", budget=20, tier="A", prompt_version=2)
            soul_lab.run_world(v2, d / "v2", soul_lab.DryMind(), 1, announce=lambda *_: None)
            self.assertEqual(meta(d / "v2")["prompt_version"], "2")
            with self.assertRaises(SystemExit):                                                      # a v2 world is not gone on with v1 (its answers are cached by the prompt)
                soul_lab.run_world(argparse.Namespace(seed=501, recipe="jianghu_drama_v1", budget=20, tier="A"), d / "v2", soul_lab.DryMind(), 2,
                                   announce=lambda *_: None)
            with self.assertRaises(SystemExit):                                                      # nor a v1 world with v2
                soul_lab.run_world(argparse.Namespace(seed=501, recipe="jianghu_story_v1", budget=20, tier="A", prompt_version=2), d / "v1",
                                   soul_lab.DryMind(), 2, announce=lambda *_: None)
            soul_lab.run_world(v2, d / "v2", soul_lab.DryMind(), 2, announce=lambda *_: None)          # the same version goes on


if __name__ == "__main__":
    unittest.main()
