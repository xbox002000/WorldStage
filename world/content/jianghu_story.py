"""The story world: the saga's jianghu (world/content/town_in_jianghu.py) with some stories already in it.

Two disciples have more in them than their sect knows. Nobody has hidden anything on purpose: they have simply been the quiet ones, and what the
others take them for (the starting estimates) lags what they can do by UNDERRATED. It is a fact about the world at the start, like a debt or an old
quarrel: not an intervention. What comes of it, if anything, is theirs and the others': they have to train, to be seen, to be tested.
"""
from __future__ import annotations

from world.content.town_in_jianghu import *  # noqa: F401,F403
from world.content import town_in_jianghu as T

SKILL = {**T.SKILL, "jun": 0.56, "hao": 0.5}      # what they can really do
UNDERRATED = {"jun": 0.32, "hao": 0.28}             # and how much less the others take it to be


def EXTRA_VARS(pid: str) -> dict[str, float]:
    return {f"skill.{pid}": SKILL[pid], f"rep.{pid}": 0.4}
