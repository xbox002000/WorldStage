from __future__ import annotations

import json
import os
import time
from typing import Callable

from agent.llm_cache import LLMCache, canonical_request, request_hash

DEFAULT_MODEL = "gemini-3.5-flash-lite"
RETRYABLE = {429, 500, 502, 503, 504}


class BudgetExceeded(RuntimeError):
    pass


class QuotaExhausted(BudgetExceeded):
    """The provider's daily quota for this model is used up: asking again today is pointless, so the model is
    skipped for the rest of the run instead of being retried."""


def _daily_quota_hit(e: Exception) -> bool:
    return getattr(e, "code", None) == 429 and "PerDay" in str(e)  # quotaId ...RequestsPerDayPerProjectPerModel...


FAILED = "__failed__"  # a cache entry meaning "every model failed to answer this request"


class CacheMiss(RuntimeError):
    """Replay mode asked for a request that was never recorded."""


def load_api_key(*names: str) -> str:
    """Process environment first, then the Windows user environment (setx does not reach running apps)."""
    names = names or ("GEMINI_API_KEY", "GOOGLE_API_KEY")
    for name in names:
        if os.environ.get(name):
            return os.environ[name]
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
            for name in names:
                try:
                    return winreg.QueryValueEx(k, name)[0]
                except FileNotFoundError:
                    continue
    except (ImportError, OSError):
        pass
    raise RuntimeError(f"{' / '.join(names)} is not set")


def has_api_key(*names: str) -> bool:
    try:
        return bool(load_api_key(*names))
    except RuntimeError:
        return False


def _gemini_backend(model: str) -> Callable[[str, dict, float], str]:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=load_api_key("GEMINI_API_KEY", "GOOGLE_API_KEY"))

    def call(prompt: str, schema: dict, temperature: float) -> str:
        try:
            resp = client.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json", response_json_schema=schema, temperature=temperature
                ),
            )
        except Exception as e:  # noqa: BLE001 - SDK raises its own error types
            if _daily_quota_hit(e):
                raise QuotaExhausted(f"{model}: the free daily quota is used up") from e
            raise
        return resp.text

    return call


class LLMClient:
    """Structured-JSON calls with retry/backoff, a request-rate floor and a hard call budget."""

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        *,
        max_calls: int | None = None,
        min_interval: float = 4.0,
        retries: int = 5,
        backend: Callable[[str, dict, float], str] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        provider: str = "gemini",
        mode: str = "live",
        cache: LLMCache | None = None,
        system_prompt: str = "",
        ledger=None,
        daily_limit: int | None = None,
    ) -> None:
        if mode not in ("live", "record", "replay", "cache"):   # cache: ask the cache first, and only what it lacks goes out (then it is kept)
            raise ValueError(f"unknown mode {mode!r}")
        if mode != "live" and cache is None:
            raise ValueError(f"mode {mode!r} needs a cache")
        self.provider = provider
        self.mode = mode
        self.cache = cache
        self.system_prompt = system_prompt
        self.model = model
        self.max_calls = max_calls
        self.min_interval = min_interval
        self.retries = retries
        self._backend = backend
        self._sleep = sleep
        self._clock = clock
        self._last = -1e9
        self.ledger = ledger              # agent/llm_ledger.py: what is spent today, kept across runs
        self.daily_limit = daily_limit    # the free calls a day this model has, when known: asking past it is refused here, not by the provider
        self.calls = 0  # every attempt counts against quota
        self.failures = 0

    def request(self, prompt: str, schema: dict, temperature: float) -> tuple[dict, str]:
        """The effective request and its hash: what a cached answer is valid for."""
        req = canonical_request(self.provider, self.model, self.system_prompt, prompt, schema,
                                {"temperature": temperature})
        return req, request_hash(req)

    def lookup(self, prompt: str, schema: dict, temperature: float = 0.8) -> dict | None:
        return self.cache.get(self.request(prompt, schema, temperature)[1]) if self.cache else None

    def record_failure(self, prompt: str, schema: dict, error: Exception, temperature: float = 0.8) -> None:
        """Remember that this request could not be answered, so a replay follows the same path (no answer)."""
        if self.mode == "record":
            req, h = self.request(prompt, schema, temperature)
            self.cache.put(h, req, {FAILED: True, "error": str(error)[:200]})

    def generate_json(self, prompt: str, schema: dict, temperature: float = 0.8) -> dict:
        req, h = self.request(prompt, schema, temperature)
        if self.mode == "replay":
            hit = self.cache.get(h)
            if hit is None:
                raise CacheMiss(h)
            return hit
        if self.mode == "cache":
            hit = self.cache.get(h)
            if hit is not None and FAILED not in hit:
                return hit
        result = self._call(prompt, schema, temperature)
        if self.mode in ("record", "cache"):
            self.cache.put(h, req, result)
        return result

    def _call(self, prompt: str, schema: dict, temperature: float) -> dict:
        if self._backend is None:
            self._backend = _gemini_backend(self.model)
        for attempt in range(self.retries + 1):
            if self.max_calls is not None and self.calls >= self.max_calls:
                raise BudgetExceeded(f"call budget of {self.max_calls} reached")
            if self.ledger is not None and self.daily_limit is not None and self.ledger.used(self.model) >= self.daily_limit:
                raise QuotaExhausted(f"{self.model}: {self.daily_limit} calls today are spent (ledger)")
            wait = self._last + self.min_interval - self._clock()
            if wait > 0:
                self._sleep(wait)
            self._last = self._clock()
            self.calls += 1
            if self.ledger is not None:
                self.ledger.add(self.model)
            try:
                return json.loads(self._backend(prompt, schema, temperature))
            except Exception as e:  # noqa: BLE001 - SDK raises its own error types
                code = getattr(e, "code", None)
                retryable = code in RETRYABLE or isinstance(e, json.JSONDecodeError)
                self.failures += 1
                if not retryable or attempt == self.retries:
                    raise
                self._sleep(min(60.0, 2.0 ** attempt * 2))
        raise AssertionError("unreachable")


class HttpError(Exception):
    def __init__(self, code: int, body: str) -> None:
        super().__init__(f"HTTP {code}: {body}")
        self.code = code


OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
# Free models, in the order they are tried after Gemini. `structured` = accepts a JSON schema.
OPENROUTER_FALLBACKS = (
    ("nvidia/nemotron-3-super-120b-a12b:free", True),
    ("google/gemma-4-31b-it:free", False),
)


def _openrouter_backend(model: str, structured: bool) -> Callable[[str, dict, float], str]:
    import httpx

    key = load_api_key("OPENROUTER_API_KEY")

    def call(prompt: str, schema: dict, temperature: float) -> str:
        if structured:
            fmt = {"type": "json_schema", "json_schema": {"name": "intent", "strict": True, "schema": schema}}
            content = prompt
        else:
            fmt = {"type": "json_object"}
            content = prompt + "\n\nReturn only a JSON object matching this JSON Schema:\n" + json.dumps(schema)
        r = httpx.post(
            OPENROUTER_URL,
            headers={"Authorization": f"Bearer {key}"},
            json={"model": model, "temperature": temperature, "response_format": fmt,
                  "messages": [{"role": "user", "content": content}]},
            timeout=90,
        )
        if r.status_code >= 400:
            raise HttpError(r.status_code, r.text[:200])
        body = r.json()
        if "choices" not in body:
            # Some upstream failures come back as HTTP 200 with an error object instead of an answer.
            err = body.get("error") or {}
            code = err.get("code") if isinstance(err.get("code"), int) else 502
            raise HttpError(code, str(err.get("message") or body)[:200])
        return body["choices"][0]["message"]["content"]

    return call


class FallbackClient:
    """Tries clients in order; one that fails or runs out of budget is skipped for a cooldown.

    The first client is retried again after the cooldown, so the preferred model comes back on its own.
    """

    def __init__(self, clients: list[LLMClient], cooldown: float = 300.0,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.clients = clients
        self.cooldown = cooldown
        self._clock = clock
        self._blocked_until: dict[int, float] = {}
        self.last_model = clients[0].model
        self.switches = 0

    @property
    def calls(self) -> int:
        return sum(c.calls for c in self.clients)

    @property
    def failures(self) -> int:
        return sum(c.failures for c in self.clients)

    @property
    def model(self) -> str:
        return self.last_model

    def record_failure(self, prompt: str, schema: dict, error: Exception, temperature: float = 0.8) -> None:
        """Called when the whole chain failed: recorded under the primary model's request hash, which is the
        first place a replay looks."""
        self.clients[0].record_failure(prompt, schema, error, temperature)

    def generate_json(self, prompt: str, schema: dict, temperature: float = 0.8) -> dict:
        if any(c.mode == "replay" for c in self.clients):
            for client in self.clients:
                hit = client.lookup(prompt, schema, temperature)
                if hit is not None:
                    self.last_model = client.model
                    return hit
            raise CacheMiss("no recorded answer from any model in the chain")
        last_error: Exception | None = None
        for i, client in enumerate(self.clients):
            if self._blocked_until.get(i, -1.0) > self._clock():
                continue
            try:
                result = client.generate_json(prompt, schema, temperature)
            except BudgetExceeded as e:
                self._blocked_until[i] = float("inf")
                last_error = e
            except Exception as e:  # noqa: BLE001
                self._blocked_until[i] = self._clock() + self.cooldown
                last_error = e
            else:
                if client.model != self.last_model:
                    self.switches += 1
                self.last_model = client.model
                return result
        raise last_error or RuntimeError("all models are unavailable")


def build_chain(gemini_model: str = DEFAULT_MODEL, *, max_calls: int | None = None, min_interval: float = 4.0,
                use_openrouter: bool = True, openrouter_max_calls: int | None = None, mode: str = "live",
                cache: LLMCache | None = None, retries: int = 5, ledger=None, daily_limit: int | None = None) -> FallbackClient:
    """Gemini first, then OpenRouter free models when an OPENROUTER_API_KEY is available.

    In replay mode nothing is called, so the OpenRouter models are included whether or not a key exists.
    """
    cache_args = {"mode": mode, "cache": cache}
    # `gemini_model` may be a comma-separated chain ("gemini-3.5-flash,gemini-3.5-flash-lite"): a model whose daily
    # quota is used up hands over to the next one.
    names = [m.strip() for m in gemini_model.split(",") if m.strip()] or [DEFAULT_MODEL]
    clients = [LLMClient(m, max_calls=max_calls, min_interval=min_interval, retries=retries, ledger=ledger, daily_limit=daily_limit, **cache_args)
               for m in names]
    if use_openrouter and (mode == "replay" or has_api_key("OPENROUTER_API_KEY")):
        for model, structured in OPENROUTER_FALLBACKS:
            clients.append(LLMClient(
                model, max_calls=openrouter_max_calls, min_interval=min_interval, retries=2,
                backend=_openrouter_backend(model, structured), provider="openrouter", **cache_args,
            ))
    return FallbackClient(clients)
