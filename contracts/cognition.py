"""CognitiveState: what a character knows of themselves and their moment when they have to think — the whole input a
character agent (an LLM, or any outside agent framework) gets, and CognitiveChoice, the whole output it may give.

The state is built only from what this person could know: their own profile, feelings, goals, memories, the people
in front of them and how they feel about them, what they have learnt of those people's tastes. Never world truth
they did not witness. The options are the ones the world's own rule agent found possible right now (so every domain
pack's actions are there, and nothing else is); the agent can only pick one by its number, and the world's
validator still has the last word.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from contracts.base import hash_without

COGNITION_VERSION = 1


@dataclass(frozen=True)
class PersonHere:
    id: str
    name: str
    trust: float
    affection: float
    fear: float
    likes: list[str] = field(default_factory=list)     # what I have learnt they like
    dislikes: list[str] = field(default_factory=list)  # ... and dislike


@dataclass(frozen=True)
class OptionView:
    n: int              # the number the agent answers with
    action: str
    target: str = ""    # a person, a thing or a place id ("" for none)
    text: str = ""      # how it reads: 冷淡地對阿凱說話（聊釣魚）


@dataclass(frozen=True)
class CognitiveState:
    person: str
    name: str
    who: dict[str, str]              # age, role, background: who I am
    core: dict[str, str]             # want, fear, wound, false belief, need, life question
    values: dict[str, float]
    habits: list[str]
    feeling: str                     # the emotion now
    life: dict[str, dict]            # each domain pack's view of my life (工作: 壓力 0.7 ...)
    goals: list[str]                 # open goals, most important first
    place: str
    people: list[PersonHere]
    memories: list[str]              # a few recent and weighty memories, as I believe them
    options: list[OptionView]
    wake: list[str]                  # why I have to think now
    version: int = COGNITION_VERSION

    def hash(self) -> str:
        return hash_without(self)


@dataclass(frozen=True)
class CognitiveChoice:
    option: int          # an OptionView.n
    reason: str = ""     # one sentence, in the character's voice
    inner: str = ""      # what they would not say aloud (read models may show it; it changes nothing)
