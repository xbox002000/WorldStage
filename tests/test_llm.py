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


class OpenRouterBackendTests(unittest.TestCase):
    class Reply:
        def __init__(self, status, body):
            self.status_code, self._body, self.text = status, body, json.dumps(body)

        def json(self):
            return self._body

    def call(self, reply):
        from unittest import mock

        from agent import llm

        with mock.patch.object(llm, "load_api_key", return_value="k"), mock.patch("httpx.post", return_value=reply):
            return llm._openrouter_backend("some/model", True)("p", {}, 0.5)

    def test_returns_the_message_content(self):
        body = {"choices": [{"message": {"content": '{"a": 1}'}}]}
        self.assertEqual(self.call(self.Reply(200, body)), '{"a": 1}')

    def test_http_200_carrying_an_error_becomes_a_retryable_http_error(self):
        from agent.llm import RETRYABLE, HttpError

        body = {"error": {"code": 429, "message": "rate limited upstream"}}
        with self.assertRaises(HttpError) as cm:
            self.call(self.Reply(200, body))
        self.assertEqual(cm.exception.code, 429)
        self.assertIn("rate limited upstream", str(cm.exception))
        self.assertIn(429, RETRYABLE)

    def test_an_answer_with_neither_choices_nor_error_code_is_a_bad_gateway(self):
        from agent.llm import RETRYABLE, HttpError

        with self.assertRaises(HttpError) as cm:
            self.call(self.Reply(200, {"weird": True}))
        self.assertEqual(cm.exception.code, 502)
        self.assertIn(502, RETRYABLE)


class DailyQuotaTests(unittest.TestCase):
    class Api429(Exception):
        code = 429

    PER_DAY = "429 RESOURCE_EXHAUSTED quotaId: GenerateRequestsPerDayPerProjectPerModel-FreeTier"
    PER_MINUTE = "429 RESOURCE_EXHAUSTED quotaId: GenerateRequestsPerMinutePerProjectPerModel-FreeTier"

    def test_only_a_per_day_429_counts_as_a_used_up_quota(self):
        from agent.llm import _daily_quota_hit

        self.assertTrue(_daily_quota_hit(self.Api429(self.PER_DAY)))
        self.assertFalse(_daily_quota_hit(self.Api429(self.PER_MINUTE)))  # that one clears within a minute

        class Overloaded(Exception):
            code = 503

        self.assertFalse(_daily_quota_hit(Overloaded("PerDay")))

    def test_the_gemini_backend_reports_a_used_up_day_as_quota_exhausted(self):
        from unittest import mock

        from agent import llm

        class Models:
            def generate_content(self, **kw):
                raise DailyQuotaTests.Api429(DailyQuotaTests.PER_DAY)

        class FakeClient:
            def __init__(self, **kw):
                self.models = Models()

        with mock.patch.object(llm, "load_api_key", return_value="k"), mock.patch("google.genai.Client", FakeClient):
            with self.assertRaises(llm.QuotaExhausted):
                llm._gemini_backend("gemini-x")("p", {}, 0.5)

    def test_a_used_up_model_is_not_retried_and_stays_skipped_for_the_run(self):
        from agent.llm import FallbackClient, QuotaExhausted

        calls = []

        def spent(*a):
            calls.append(1)
            raise QuotaExhausted("gemini-x: the free daily quota is used up")

        now = [0.0]
        clients = [
            LLMClient("m0", backend=spent, min_interval=0, retries=3, sleep=lambda s: None, clock=lambda: now[0]),
            LLMClient("m1", backend=lambda *a: '{"from": "second"}', min_interval=0, retries=0, sleep=lambda s: None,
                      clock=lambda: now[0]),
        ]
        chain = FallbackClient(clients, cooldown=1.0, clock=lambda: now[0])
        self.assertEqual(chain.generate_json("p", {}), {"from": "second"})
        now[0] = 10_000  # far past any cooldown: a used-up day does not come back on its own
        self.assertEqual(chain.generate_json("p", {}), {"from": "second"})
        self.assertEqual(len(calls), 1)  # one attempt, no retries, never asked again

    def test_a_comma_separated_model_names_a_chain_in_order(self):
        from agent.llm import build_chain

        chain = build_chain("gemini-3.5-flash, gemini-3.5-flash-lite", use_openrouter=False)
        self.assertEqual([c.model for c in chain.clients], ["gemini-3.5-flash", "gemini-3.5-flash-lite"])
        self.assertEqual([c.model for c in build_chain(use_openrouter=False).clients], ["gemini-3.5-flash-lite"])


if __name__ == "__main__":
    unittest.main()
