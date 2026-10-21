"""Pacing: how much has been happening lately, and so whether the story wants more, or air (read model, never truth).

Left 4 Dead's Director does not ask "what next?" first; it asks how hard the last stretch was and builds, peaks or relaxes
accordingly. This is the same question for a town: the weight of the turning points of the last few days, each fading as it
recedes. `phase` is "calm" (nothing has happened: a producer may arrange something), "warm" (something is under way) or "peak"
(a great deal has just happened: arranging more would only bury it, so a producer should keep still).

`pacing_v0.1`: a draft. The weights and thresholds are a first guess and are in this file to be argued with.
"""
from __future__ import annotations

import json
import sqlite3

PACING_VERSION = "pacing_v0.1"
WINDOW_DAYS = 3
FADE = 0.6          # each day back, a moment counts this much of the day before
WEIGHTS = {"duel": 1.0, "confession": 1.2, "succession": 1.5, "break_up": 1.0, "defect": 0.8, "found_faction": 0.8, "breakthrough": 0.5}
SLAP_BONUS = 0.6    # a duel that overturned what the crowd thought is worth more
CALM_BELOW = 0.8
PEAK_AT = 2.5


def intensity(conn: sqlite3.Connection, day: int) -> float:
    """The weight of the turning points of the days before `day`, newest heaviest (events of `day` itself are not yet seen)."""
    marks = ",".join("?" * len(WEIGHTS))
    total = 0.0
    for r in conn.execute(f"SELECT timestamp, type, truth FROM events WHERE type IN ({marks}) AND timestamp >= ? AND timestamp < ?",
                          (*WEIGHTS, (day - WINDOW_DAYS) * 1440, day * 1440)):
        w = WEIGHTS[r["type"]]
        if r["type"] == "duel" and json.loads(r["truth"]).get("slap"):
            w += SLAP_BONUS
        total += w * FADE ** (day - 1 - r["timestamp"] // 1440)
    return round(total, 3)


def phase(conn: sqlite3.Connection, day: int) -> str:
    x = intensity(conn, day)
    return "peak" if x >= PEAK_AT else "calm" if x < CALM_BELOW else "warm"
