"""Opportunities: places in the world where a story is close to happening, and what it lacks (read model, never truth).

The producer does not write a story; it finds one that the world is already half-making and arranges the one thing it lacks. So
what it reasons over is not an event to send but an `Opportunity`: who, what kind of story, how much it would be worth, how
likely the protagonist is to come out ahead (so how much is still open), and which conditions are missing. A `Forecast` is what
an imagined few days said about doing something about it (producer/forecast.py); it is a probability, never an answer.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from contracts.base import hash_without

OPPORTUNITY_VERSION = 1

OpportunityKind = Literal["reversal", "triangle", "succession"]
# what is lacking: an occasion (a public place and day), a challenger (somebody who would stand against them), a vacancy (a place to
# win), strength (the hero is a little short), recovery (somebody is hurt: nothing to be done but wait)
Lack = Literal["occasion", "challenger", "vacancy", "strength", "recovery"]


@dataclass(frozen=True)
class MissingCondition:
    lack: Lack
    detail: str = ""


@dataclass(frozen=True)
class Opportunity:
    opportunity_id: str
    kind: OpportunityKind
    protagonist: str
    others: list[str]                   # the ones it is played against (or between)
    day: int                            # the day it was seen
    potential: float                    # 0..1: what it would be worth if it came off (irony x pressure x suspense)
    suspense: float                     # 0..1: 1 when the outcome is a toss-up, 0 when it is already decided
    p_success: float                    # the chance the protagonist comes out ahead if it is played out
    missing: list[MissingCondition] = field(default_factory=list)
    evidence: dict = field(default_factory=dict)

    def hash(self) -> str:
        return hash_without(self)


@dataclass(frozen=True)
class Forecast:
    """What imagining the next days said about one thing the producer might do (or not do). Probabilities only."""

    candidate: str                      # the proposal's id, or "silence"
    samples: int
    p_payoff: float                     # share of imagined futures in which the protagonist had their moment
    expected_earned: float              # mean earned payoff of the protagonist's moment (0 where there was none)
    p_played: float                     # share in which the story was played at all (the bout, the courtship, the vote took place)
    gain: float = 0.0                   # expected_earned minus what the same luck gave with nothing done
