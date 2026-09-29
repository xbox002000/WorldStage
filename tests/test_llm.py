from __future__ import annotations

import json
import unittest

from agent.decision import GeminiDecider
from agent.llm import BudgetExceeded, LLMClient
from tests.helpers import seeded


class ApiError(Exception):
    def __init__(self, code: int):
        self.code = code


def client(backend, **kw):
    now = [0.0]
    sleeps: list[float] = []

    def sleep(s):
        sleeps.append(s)
        now[0] += s

    c = LLMClient(backend=backend, sleep=sleep, clock=lambda: now[0], **kw)
    return c, sleeps


class LLMClientTests(unittest.TestCase):
    def test_retries_transient_errors_then_succeeds(self):
        calls = []

        def backend(prompt, schema, temp):
            calls.append(1)
            if len(calls) < 3:
                raise ApiError(503)
            return '{"ok": true}'

        c, sleeps = client(backend, min_interval=0)
        self.assertEqual(c.generate_json("p", {}), {"ok": True})
        self.assertEqual((c.calls, c.failures), (3, 2))
        self.assertEqual(sleeps, [2.0, 4.0])

    def test_non_retryable_error_is_raised_immediately(self):
        def backend(*a):
            raise ApiError(400)

        c, _ = client(backend, min_interval=0)
        with self.assertRaises(ApiError):
            c.generate_json("p", {})
        self.assertEqual(c.calls, 1)

    def test_rate_floor_spaces_calls(self):
        c, sleeps = client(lambda *a: "{}", min_interval=4.0)
        c.generate_json("p", {})
        c.generate_json("p", {})
        self.assertEqual(sleeps, [4.0])

    def test_call_budget_is_hard(self):
        c, _ = client(lambda *a: "{}", min_interval=0, max_calls=2)
        c.generate_json("p", {})
        c.generate_json("p", {})
        with self.assertRaises(BudgetExceeded):
            c.generate_json("p", {})


class DeciderTests(unittest.TestCase):
    def setUp(self):
        self.conn = seeded()

    def decider(self, reply):
        c, _ = client(lambda *a: json.dumps(reply), min_interval=0)
        return GeminiDecider(c), c

    def test_prompt_contains_only_what_the_actor_may_know(self):
        from agent.decision import build_prompt

        prompt = build_prompt(self.conn, "mary")
        self.assertIn("tom", prompt)
        self.assertNotIn("john", prompt)  # john is at home, not visible to mary

    def test_no_call_when_alone(self):
        d, c = self.decider({"action": "idle", "reason": "x"})
        self.assertIsNone(d.decide(self.conn, "john", 1))
        self.assertEqual(c.calls, 0)

    def test_idle_and_talk(self):
        d, _ = self.decider({"action": "idle", "reason": "quiet"})
        self.assertIsNone(d.decide(self.conn, "mary", 1))
        d, _ = self.decider({"action": "talk", "target": "tom", "tone": "warm", "reason": "hi"})
        it = d.decide(self.conn, "mary", 1)
        self.assertEqual((it.actor, it.action, it.target, it.tone), ("mary", "talk", "tom", "warm"))

    def test_failed_call_counts_error_and_returns_none(self):
        def boom(*a):
            raise ApiError(400)

        c, _ = client(boom, min_interval=0)
        d = GeminiDecider(c)
        self.assertIsNone(d.decide(self.conn, "mary", 1))
        self.assertEqual(d.errors, 1)


if __name__ == "__main__":
    unittest.main()


class FallbackTests(unittest.TestCase):
    def chain(self, backends, cooldown=300.0, max_calls=None):
        from agent.llm import FallbackClient

        now = [0.0]
        clients = [
            LLMClient(f"m{i}", backend=b, min_interval=0, retries=0, sleep=lambda s: None,
                      clock=lambda: now[0], max_calls=max_calls)
            for i, b in enumerate(backends)
        ]
        return FallbackClient(clients, cooldown=cooldown, clock=lambda: now[0]), now

    def test_switches_when_first_model_fails_and_records_which_answered(self):
        def down(*a):
            raise ApiError(429)

        chain, _ = self.chain([down, lambda *a: '{"from": "second"}'])
        self.assertEqual(chain.generate_json("p", {}), {"from": "second"})
        self.assertEqual((chain.model, chain.switches), ("m1", 1))

    def test_failed_model_is_skipped_during_cooldown_then_retried(self):
        state = {"up": False}
        calls = []

        def flaky(*a):
            calls.append(1)
            if not state["up"]:
                raise ApiError(503)
            return '{"from": "first"}'

        chain, now = self.chain([flaky, lambda *a: '{"from": "second"}'], cooldown=100)
        chain.generate_json("p", {})
        chain.generate_json("p", {})
        self.assertEqual(len(calls), 1)  # second request did not touch the cooling-down model
        state["up"] = True
        now[0] = 101
        self.assertEqual(chain.generate_json("p", {}), {"from": "first"})
        self.assertEqual(chain.model, "m0")

    def test_exhausted_budget_is_permanent(self):
        chain, now = self.chain([lambda *a: "{}", lambda *a: '{"from": "second"}'], max_calls=1)
        chain.clients[1].max_calls = None
        chain.generate_json("p", {})
        now[0] = 10_000
        self.assertEqual(chain.generate_json("p", {}), {"from": "second"})
        self.assertEqual(chain.generate_json("p", {}), {"from": "second"})

    def test_raises_when_everything_is_down(self):
        def down(*a):
            raise ApiError(503)

        chain, _ = self.chain([down, down])
        with self.assertRaises(ApiError):
            chain.generate_json("p", {})
