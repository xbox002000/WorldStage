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
    "tell": "tell", "deceive": "deception", "conceal": "deception", "confront": "confront",
    # World C
    "find": "acquire", "lose": "loss", "give": "return", "win": "windfall",
    "lend": "money", "repay": "money", "owe": "money",
    "accuse": "accuse", "threaten": "threat",
}
# What the claim's `object` names: an item id (objects table) or a person id.
ACT_OBJECT_KIND: dict[str, str] = {
    "steal": "item", "borrow": "item", "take": "item",
    "speak_warm": "person", "speak_neutral": "person", "speak_cold": "person", "speak_hostile": "person",
    "tell": "person", "deceive": "person", "conceal": "person", "confront": "person",
    "find": "item", "lose": "item", "give": "item", "win": "item",
    "lend": "person", "repay": "person", "owe": "person", "accuse": "person", "threaten": "person",
}
# Fixed, rule-owned distortions: the model never writes a proposition, it picks a mode.
DISTORTION: dict[str, str] = {
    "borrow": "steal", "take": "steal", "steal": "take", "find": "take",
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


def can_distort(claim: Claim) -> bool:
    return claim.act in DISTORTION


def distort(claim: Claim) -> Claim:
    """The `distortion` transform: a different act from the same family."""
    return replace(claim, act=DISTORTION[claim.act])


def contradicts(a: Claim, b: Claim) -> bool:
    """Two accounts of the same subject and object that cannot both stand as told.

    Same act with opposite polarity ("he stole it" / "he did not steal it"), or two different acts from one
    family, both affirmed ("he stole it" / "he only took it").
    """
    if a.subject != b.subject or a.object != b.object:
        return False
    if a.act == b.act:
        return a.polarity != b.polarity
    return a.family == b.family and a.polarity == AFFIRM and b.polarity == AFFIRM


TRUE, FALSE, PARTIAL, UNKNOWN = "TRUE", "FALSE", "PARTIAL", "UNKNOWN"
