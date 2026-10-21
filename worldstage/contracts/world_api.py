"""The world-side contracts, re-exported in one place. Implementations stay in world/; only the names are public.

ActionIntent -> EventSpec -> StateDelta(Change) -> Claim. Not imported by contracts/__init__ to avoid a cycle.
"""
from __future__ import annotations

from worldstage.contracts.claim import Claim  # noqa: F401
from worldstage.world.events import Change as StateDelta  # noqa: F401
from worldstage.world.events import ClaimSpec, EventSpec, MemorySpec  # noqa: F401
from worldstage.world.intent import Intent as ActionIntent  # noqa: F401

__all__ = ["ActionIntent", "EventSpec", "StateDelta", "Claim", "ClaimSpec", "MemorySpec"]
