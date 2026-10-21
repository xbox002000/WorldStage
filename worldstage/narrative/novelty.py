"""Pattern saturation: the same kind of moment, between the same people, is worth less each time it is told (read model).

A producer that is paid by payoffs finds the cheapest reliable one and tells it again and again (the first Producer 2 opened a
seat about every nine days: 48 of its 56 followed votes paid off). That is Goodhart's law, and it is what generated stories are
known for ("10,000 bowls of oatmeal"). So repetition is counted, on two axes that can be read from what happened:

  mechanic   the kind of moment (a face slap, a chosen one, a succession)
  pair       the same two people, or the same seat

Each earlier occurrence in the same world counts: the factor is 1.0, 0.6, 0.3, then 0.1. A moment's novelty is the product of its
two factors. The same mechanic between new people, or the same people in a new mechanic, is worth more than the same thing again.

Used twice, by the same table: as a *measure* (`saturate`: the earned payoff of a world, discounted for what was repeated; a
sibling of payoff_metric_v0.1, which is left as it was), and by the director as a *gate and a weight* (`PatternMemory`), so that what it
chooses to arrange and what it is judged by agree. `novelty_v0.1`: a draft; the table is a first guess.
"""
from __future__ import annotations

NOVELTY_VERSION = "novelty_v0.1"
FACTORS = (1.0, 0.6, 0.3, 0.1)
MECHANIC_OF_STORY = {"reversal": "face_slap", "triangle": "chosen", "succession": "succession"}   # what each kind of story, told, becomes


def factor(seen: int) -> float:
    return FACTORS[min(seen, len(FACTORS) - 1)]


def pair_of(p: dict) -> str:
    if p["kind"] == "succession":
        return f"seat:{p.get('seat', '')}"
    return "|".join(sorted(x for x in (p["protagonist"], p.get("against")) if x))


class PatternMemory:
    """What has been told in this world so far: how many of each mechanic, and of each pair."""

    def __init__(self) -> None:
        self.mechanics: dict[str, int] = {}
        self.pairs: dict[str, int] = {}

    def novelty(self, mechanic: str, pair: str) -> float:
        return round(factor(self.mechanics.get(mechanic, 0)) * factor(self.pairs.get(pair, 0)), 4)

    def tell(self, mechanic: str, pair: str) -> float:
        n = self.novelty(mechanic, pair)
        self.mechanics[mechanic] = self.mechanics.get(mechanic, 0) + 1
        self.pairs[pair] = self.pairs.get(pair, 0) + 1
        return n

    @classmethod
    def of(cls, found: list[dict]) -> "PatternMemory":
        m = cls()
        for p in found:
            m.tell(p["kind"], pair_of(p))
        return m


def saturate(found: list[dict]) -> list[dict]:
    """The payoffs of a world in order, each with its novelty and the earned payoff after it (`earned_novel`)."""
    m = PatternMemory()
    out = []
    for p in found:
        n = m.tell(p["kind"], pair_of(p))
        out.append({**p, "novelty": n, "earned_novel": round(p["earned"] * n, 4)})
    return out


def summary(found: list[dict]) -> dict:
    s = saturate(found)
    return {"model": NOVELTY_VERSION, "earned": round(sum(p["earned"] for p in s), 3), "earned_novel": round(sum(p["earned_novel"] for p in s), 3),
            "mean_novelty": round(sum(p["novelty"] for p in s) / len(s), 3) if s else 0.0,
            "mechanics": len({p["kind"] for p in s}), "pairs": len({pair_of(p) for p in s})}
