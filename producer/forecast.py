"""Forecast: what might come of arranging something, found by imagining the next days under other luck (never by reading the answer).

For each thing the producer is weighing (and for doing nothing) a copy of the world is run a few days forward, several times, each
time under a different imagined luck (world/rollout.py). The same lucks are used for every option, so the *difference* between
an option and silence is what is measured, not the noise of one lucky draw. What comes back is a probability, never an answer:

  p_payoff         the share of imagined futures in which anybody had a payoff
  expected_earned  the mean of the earned payoff over them (payoff_metric_v0.1, agency counted)
  p_played         the share in which somebody the story was about played it (the bout, the courtship, the vote)
  gain             expected_earned minus what the same luck gave with nothing done

The producer weighs gain against what it costs. It cannot pick an outcome from this: the lucks are not the world's, the copy is
thrown away, and a gain is an average over futures that the people themselves live out differently each time.
"""
from __future__ import annotations

import json
import sqlite3

from contracts.intervention import InterventionProposal
from contracts.opportunity import Forecast
from narrative import payoff
from producer.intervention import Ledger
from world import rollout

SAMPLES = 3
HORIZON = 4              # imagined days: an occasion two days ahead still has time to be used
LUCKS = (1_000_003, 1_000_033, 1_000_081, 1_000_099)
COST_WEIGHT = 0.03       # one unit of intervention must buy at least this much more earned payoff
MIN_GAIN = 0.03          # below this the futures with and without it are not told apart


def _lucks(clean: sqlite3.Connection, k: int) -> list[int]:
    ours = rollout.world_seed(clean)
    return [x for x in LUCKS if str(x) != ours][:k]


def _says(ledger: Ledger, proposals: list[InterventionProposal]):
    fork = ledger.fork()   # the imagined weeks spend the same budget the real one has left

    def say(conn: sqlite3.Connection, now: int) -> None:
        for p in proposals:
            fork.admit(conn, p, now)
    return say


def _outcome(mem: sqlite3.Connection, day: int, who: set[str]) -> dict:
    found = [p for p in payoff.payoffs(mem) if p["day"] >= day]
    lo, hi = day * 1440, (day + HORIZON) * 1440
    played = False
    for (t,) in mem.execute("SELECT truth FROM events WHERE type IN ('duel', 'flirt', 'confession', 'succession') AND timestamp >= ? AND timestamp < ?", (lo, hi)):
        truth = json.loads(t)
        played = played or bool(who & {truth.get(k) for k in ("winner", "loser", "actor", "target")})
    return {"n": len(found), "earned": sum(p["earned"] for p in found), "played": played}


def evaluate(clean: sqlite3.Connection, day: int, ledger: Ledger, bundles: dict[str, tuple[list[InterventionProposal], set[str]]],
             samples: int = SAMPLES) -> dict[str, Forecast]:
    """Imagine each bundle (and silence) under the same few lucks. `bundles` maps a name to (its proposals, the people it is about)."""
    lucks = _lucks(clean, samples)
    results: dict[str, list[dict]] = {name: [] for name in ("silence", *bundles)}
    everyone = {p for _, w in bundles.values() for p in w}   # what "played" means for silence: any of the people any option is about
    for luck in lucks:
        for name in results:
            props, who = ([], set()) if name == "silence" else bundles[name]
            mem = rollout.imagine(clean, day, HORIZON, luck, _says(ledger, props))
            results[name].append(_outcome(mem, day, who or everyone))
            mem.close()
    base = [r["earned"] for r in results["silence"]]
    out = {}
    for name, rs in results.items():
        n = len(rs)
        earned = sum(r["earned"] for r in rs) / n
        out[name] = Forecast(name, n, round(sum(1 for r in rs if r["n"]) / n, 3), round(earned, 4),
                             round(sum(1 for r in rs if r["played"]) / n, 3), round(earned - sum(base) / n, 4))
    return out
