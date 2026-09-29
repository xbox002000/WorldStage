"""Request-addressed cache of LLM responses, so a run can be replayed without calling any model."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time


def canonical_request(provider: str, model: str, system_prompt: str, user_prompt: str, response_schema: dict,
                      generation_config: dict) -> dict:
    return {
        "provider": provider, "model": model, "system_prompt": system_prompt, "user_prompt": user_prompt,
        "response_schema": response_schema, "generation_config": generation_config,
    }


def request_hash(request: dict) -> str:
    text = json.dumps(request, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


class LLMCache:
    """Stored in the world database's llm_cache table. Not part of the world snapshot: it is an input log."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def get(self, h: str) -> dict | None:
        row = self.conn.execute("SELECT response_json FROM llm_cache WHERE request_hash = ?", (h,)).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, h: str, request: dict, response: dict) -> None:
        # First answer wins: a replay must keep seeing the answer the original run acted on.
        self.conn.execute(
            "INSERT OR IGNORE INTO llm_cache(request_hash, provider, model, request_json, response_json, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (h, request["provider"], request["model"], json.dumps(request, sort_keys=True, ensure_ascii=False),
             json.dumps(response, sort_keys=True, ensure_ascii=False), int(time.time())),
        )
