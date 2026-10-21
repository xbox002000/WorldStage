"""TellIntent: A tells B something A believes. The model picks a mode and which held claim to talk about.

It never writes the proposition: the asserted claim is derived by fixed rules (world/tell.py), so a character
can lie or distort but cannot invent a fact about an entity or act that the world has no words for.
"""
from __future__ import annotations

from dataclasses import dataclass

TELL_MODES = ("truth", "omission", "lie", "distortion")


@dataclass(frozen=True)
class TellIntent:
    actor: str
    target: str
    mode: str
    source_claim_id: int  # a claim the actor holds in memory
    withheld_claim_ids: list[int]  # omission only: other held claims the actor chooses not to say
