"""The audience's view: a read model beside the world, never part of it.

    World truth  ->  what the story has shown  ->  what the audience knows

The audience can know what a character does not (somebody has secretly grown strong, two people love each other and
neither has said so) and can expect what the world has not settled (who is the favourite). Dramatic irony and payoff are
the distance between the two, so they have to exist *before* the event that resolves them: an expectation counts only if
it was already there at an earlier revision. These are read from the world's history (narrative/audience.py); nothing in
this file is ever written to world.db.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

AUDIENCE_VERSION = 1

ClaimKind = Literal["hidden_strength", "secret_couple", "unspoken_crush", "unrequited_love"]


@dataclass(frozen=True)
class AudienceClaim:
    """Something the audience can see is so, and the world (the people in it) has not caught up with."""

    kind: ClaimKind
    people: list[str]
    truth: float                  # what is the case (an ability, an attraction)
    believed: float               # what the people in the world take it to be (the crowd's estimate, or 0: nobody knows)
    gap: float                    # truth - believed
    as_of: int                    # the revision it was true at
    basis: list[int] = field(default_factory=list)  # the events that show the audience


@dataclass(frozen=True)
class AudienceExpectation:
    """What the audience expects of somebody, as of a revision: their standing in the crowd's eyes. It is compared with
    what happens next; it is never built after the fact."""

    subject: str
    expected: float               # the crowd's estimate of their ability
    knows: float                  # their true ability, as the audience has seen it grow
    as_of: int
    since_revision: int = 0       # from when the gap (knows - expected) has been at least GAP: how long the audience has waited
    since_day: int = 0


@dataclass(frozen=True)
class AudienceKnowledge:
    as_of: int
    claims: list[AudienceClaim] = field(default_factory=list)
    expectations: list[AudienceExpectation] = field(default_factory=list)
