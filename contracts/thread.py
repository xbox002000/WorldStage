"""StoryThread: a causal line that is still developing in the world, as seen from the production side.

A thread is an interpretation of world history, never a second truth. It is derived read-only from world.db at a
known revision, so the same world always yields the same threads. Following a thread (the story director's choice)
never changes what happens next in the world.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from contracts.base import hash_without

THREAD_VERSION = 1

ThreadKind = Literal["item", "debt", "rumor", "feud"]
ThreadStatus = Literal["seeded", "forming", "active", "escalating", "climax", "resolved", "dormant"]


@dataclass(frozen=True)
class StoryThread:
    thread_id: str  # e.g. item:wallet_ming, debt:jun:tao, rumor:412, feud:kai:ming
    kind: ThreadKind
    central_question: str  # in Traditional Chinese, e.g. 誰拿走了阿明的錢包？
    participants: list[str]
    event_ids: list[int]  # every event of the thread, in order
    decision_event_ids: list[int]  # the ones a character chose (not rules, seeds or props)
    first_day: int
    last_day: int
    status: ThreadStatus
    stakes: float  # 0..1
    momentum: float  # weight of the last two days' events
    tension: float  # 0..1: how open the central question still is
    information_asymmetry: int  # beliefs about this thread that world truth does not support
    cross_threads: list[str]  # threads sharing an event or a principal on the same day
    seed_origins: list[str] = field(default_factory=list)  # external_event_ids of seeds in the thread
    world_revision: int = 0
    version: int = THREAD_VERSION

    def hash(self) -> str:
        return hash_without(self)


@dataclass(frozen=True)
class ThreadScore:
    thread_id: str
    score: float
    parts: dict[str, float]
