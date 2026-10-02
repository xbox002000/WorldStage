"""A ledger of the free quota spent: every attempt that reaches the provider, by model, by the provider's day.

Gemini's free quota resets at midnight Pacific time. The ledger is a small json file next to the run, so a second
process (or tomorrow's run) knows what is already gone and can refuse to start what it cannot finish. It only counts;
the limit, when one is known, is passed in by whoever runs (the provider's own 429 is still the final word).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path


def provider_day(now: datetime | None = None) -> str:
    """The calendar date at the provider (Pacific time)."""
    now = now or datetime.now(timezone.utc)
    try:
        from zoneinfo import ZoneInfo
        return now.astimezone(ZoneInfo("America/Los_Angeles")).strftime("%Y-%m-%d")
    except Exception:  # noqa: BLE001 - no tz database on this machine: Pacific daylight time is the right offset for most of the year
        return now.astimezone(timezone(timedelta(hours=-7))).strftime("%Y-%m-%d")


class Ledger:
    def __init__(self, path: str | Path, today=provider_day) -> None:
        self.path = Path(path)
        self._today = today

    def _load(self) -> dict:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def used(self, model: str) -> int:
        return int(self._load().get(self._today(), {}).get(model, 0))

    def add(self, model: str, n: int = 1) -> int:
        data = self._load()
        day = data.setdefault(self._today(), {})
        day[model] = int(day.get(model, 0)) + n
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
        return day[model]

    def left(self, model: str, limit: int | None) -> int | None:
        return None if limit is None else max(0, limit - self.used(model))
