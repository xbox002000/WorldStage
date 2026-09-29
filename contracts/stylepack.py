"""NarrativeStylePack: how a channel wants its stories told. Affects selection and shooting, never world facts."""
from __future__ import annotations

from dataclasses import dataclass

from contracts.base import content_hash


@dataclass(frozen=True)
class StylePack:
    id: str
    version: int
    hook: str  # how an episode opens: cold_open | establishing
    ending: str  # how it closes: unresolved | resolved
    duration_scale: float  # multiplies every shot length (rhythm)
    title_seconds: float
    end_seconds: float
    camera_bias: str  # tight | balanced | wide

    def hash(self) -> str:
        return content_hash(self)


SUSPENSE_V1 = StylePack(id="suspense", version=1, hook="cold_open", ending="unresolved", duration_scale=1.0,
                        title_seconds=2.0, end_seconds=1.0, camera_bias="tight")
