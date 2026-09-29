"""Claim: a proposition about the world. It is not a fact.

Whether a claim is true is decided by comparing it with event_claims(role='truth'), never by the claim itself.
World truth, a character's belief and an audience rumour all reference the same Claim rows.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace

AFFIRM, DENY = "affirm", "deny"

# act -> family. Two different acts in one family describe "roughly the same thing" (a PARTIAL match).
ACT_FAMILY: dict[str, str] = {
    "steal": "acquire", "borrow": "acquire", "take": "acquire",
    "speak_warm": "speech", "speak_neutral": "speech", "speak_cold": "speech", "speak_hostile": "speech",
}
# Fixed, rule-owned distortions: the model never writes a proposition, it picks a mode.
DISTORTION: dict[str, str] = {
    "borrow": "steal", "take": "steal", "steal": "take",
    "speak_warm": "speak_cold", "speak_neutral": "speak_hostile", "speak_cold": "speak_hostile", "speak_hostile": "speak_cold",
}


@dataclass(frozen=True)
class Claim:
    subject: str
    act: str
    object: str
    polarity: str = AFFIRM

    def __post_init__(self) -> None:
        if self.act not in ACT_FAMILY:
            raise ValueError(f"unknown act {self.act!r}")
        if self.polarity not in (AFFIRM, DENY):
            raise ValueError(f"unknown polarity {self.polarity!r}")

    @property
    def proposition(self) -> tuple[str, str, str]:
        return (self.subject, self.act, self.object)

    @property
    def family(self) -> str:
        return ACT_FAMILY[self.act]

    def hash(self) -> str:
        payload = json.dumps([self.subject, self.act, self.object, self.polarity], separators=(",", ":"), ensure_ascii=False)
        return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def negate(claim: Claim) -> Claim:
    """The `lie` transform (P1): same proposition, opposite polarity."""
    return replace(claim, polarity=DENY if claim.polarity == AFFIRM else AFFIRM)


def distort(claim: Claim) -> Claim:
    """The `distortion` transform: a different act from the same family."""
    return replace(claim, act=DISTORTION[claim.act])


TRUE, FALSE, PARTIAL, UNKNOWN = "TRUE", "FALSE", "PARTIAL", "UNKNOWN"
