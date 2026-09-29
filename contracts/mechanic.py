"""NarrativeMechanicPack: which story machinery runs in a world (rebirth, a system, ...). Not how it looks: that is
the StylePack.

A mechanic works only through the kernel: events via apply_event, beliefs as claims, choices as Intents that the
validator judges. The pack a world runs with is recorded in the world as a `mechanic` event, so replays pin it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from contracts.base import hash_without

MECHANIC_VERSION = 1

MechanicKind = Literal["world", "character", "constraint"]


@dataclass(frozen=True)
class MechanicSpec:
    id: str  # rebirth | system | ...
    kind: MechanicKind
    target: str | None = None  # the person a character mechanic belongs to
    params: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class NarrativeMechanicPack:
    pack_id: str
    mechanics: list[MechanicSpec]
    version: int = MECHANIC_VERSION

    def hash(self) -> str:
        return hash_without(self)
