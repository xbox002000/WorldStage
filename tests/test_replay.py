from __future__ import annotations

import json
import re
import unittest

from agent.decision import GeminiDecider, SeededDecider
from agent.llm import CacheMiss, FallbackClient, LLMClient
from agent.llm_cache import LLMCache, canonical_request, request_hash
from world.db import connect, init_db
from world.seed import build_world
from world.simulation import Simulation
from world.snapshot import snapshot_hash


def fresh_world(seed=5):
    conn = connect()
    init_db(conn, seed)
    build_world(conn, seed)
    return conn


class RequestHashTests(unittest.TestCase):
    def base(self, **over):
        args = dict(provider="gemini", model="m", system_prompt="s", user_prompt="u",
                    response_schema={"type": "object"}, generation_config={"temperature": 0.8})
        args.update(over)
        return request_hash(canonical_request(**args))

    def test_every_part_of_the_request_changes_the_hash(self):
        base = self.base()
        for change in (dict(provider="openrouter"), dict(model="m2"), dict(system_prompt="s2"), dict(user_prompt="u2"),
                       dict(response_schema={"type": "array"}), dict(generation_config={"temperature": 0.0})):
            self.assertNotEqual(base, self.base(**change), change)

    def test_key_order_does_not_matter(self):
        a = self.base(response_schema={"a": 1, "b": 2})
        b = self.base(response_schema={"b": 2, "a": 1})
        self.assertEqual(a, b)


class CacheModeTests(unittest.TestCase):
    def setUp(self):
        self.conn = fresh_world()
        self.cache = LLMCache(self.conn)
        self.calls = []

    def backend(self, prompt, schema, temp):
        self.calls.append(prompt)
        return json.dumps({"answer": len(self.calls)})

    def client(self, mode, model="m", backend=None):
        return LLMClient(model, mode=mode, cache=self.cache, backend=backend or self.backend, min_interval=0,
                         sleep=lambda s: None)

    def test_record_then_replay_makes_no_calls(self):
        recorded = self.client("record").generate_json("p", {})
        replayed = self.client("replay", backend=lambda *a: self.fail("replay must not call the model")).generate_json("p", {})
        self.assertEqual(recorded, replayed)
        self.assertEqual(len(self.calls), 1)

    def test_replay_misses_loudly_and_a_different_model_does_not_hit(self):
        self.client("record", model="m1").generate_json("p", {})
        with self.assertRaises(CacheMiss):
            self.client("replay", model="m1").generate_json("other prompt", {})
        with self.assertRaises(CacheMiss):
            self.client("replay", model="m2").generate_json("p", {})

    def test_first_recorded_answer_wins(self):
        first = self.client("record").generate_json("p", {})
        self.client("record").generate_json("p", {})  # second live call for the same request
        self.assertEqual(self.client("replay").generate_json("p", {}), first)

    def test_modes_that_need_a_cache_refuse_to_start_without_one(self):
        with self.assertRaises(ValueError):
            LLMClient("m", mode="replay")

    def test_fallback_chain_replays_from_whichever_model_answered(self):
        self.client("record", model="second").generate_json("p", {})
        chain = FallbackClient([self.client("replay", model="first"), self.client("replay", model="second")])
        self.assertEqual(chain.generate_json("p", {}), {"answer": 1})
        self.assertEqual(chain.model, "second")
        with self.assertRaises(CacheMiss):
            chain.generate_json("unseen", {})


class SimulationReplayTests(unittest.TestCase):
    ACTIVE = {"ming", "mei", "jun", "lan"}

    @staticmethod
    def fake_model(prompt, schema, temperature):
        """Stands in for Gemini: talks to the first person listed, tone chosen from the prompt length."""
        target = re.search(r"^- (\w+) \(", prompt, re.M).group(1)
        return json.dumps({"action": "talk", "target": target, "tone": ("warm", "cold", "hostile")[len(prompt) % 3],
                           "reason": "fake"})

    def run_world(self, mode, cache_conn=None):
        conn = fresh_world()
        cache = LLMCache(cache_conn or conn)
        backend = self.fake_model if mode == "record" else (lambda *a: self.fail("replay must not call a model"))
        client = LLMClient("gemini-test", mode=mode, cache=cache, backend=backend, min_interval=0, sleep=lambda s: None)
        sim = Simulation(conn, GeminiDecider(client), SeededDecider(5), self.ACTIVE)
        sim.run(2)
        return conn, client

    def test_same_seed_and_recorded_answers_replay_to_an_identical_world(self):
        recorded, client = self.run_world("record")
        self.assertGreater(client.calls, 0)
        replayed, again = self.run_world("replay", cache_conn=recorded)
        self.assertEqual(again.calls, 0)
        self.assertEqual(snapshot_hash(recorded), snapshot_hash(replayed))
        llm_events = recorded.execute(
            "SELECT COUNT(*) FROM events WHERE json_extract(truth,'$.source') <> ''").fetchone()[0]
        self.assertGreater(llm_events, 0)  # the model really did drive some of the world


if __name__ == "__main__":
    unittest.main()
