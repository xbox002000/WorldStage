"""Why someone did what they did: the record that goes into the event's truth (`influences`).

A decision is a softmax over scored options. The record keeps what is needed to explain it afterwards, and nothing that
could change it: the best few options with their exact probabilities, how likely the chosen one was, and the factors
that were leaning the options in play: the self-models someone holds (and by how much), a goal that pushed the option, the
state of the body (a domain pack's `influences`), and, for an answer, what it was an answer to. narrative/causal_audit.py
follows these factors back to the events that made them.

Reading only: nothing here draws a random number or writes to the world.
"""
from __future__ import annotations

import math
import sqlite3

from world.intent import Intent

TOP = 3
# which self_bias keys (world/psyche.py SELF_BIAS) lean an answer, by its stance (agent/reply.py)
STANCE_KEYS = {"retort": {"retort", "defend"}, "deny": {"defend"}, "apologize": {"apologize"}, "soothe": {"soothe"}}


def bias_keys(it: Intent | None) -> set[str]:
    """The self_bias keys that lean this option up or down."""
    if it is None:
        return {"withdraw"}  # letting it pass, doing nothing
    if it.action in ("accuse", "tell", "lend"):
        return {it.action}
    stance = it.reason.split(":")[1] if it.reason.startswith("reply:") and it.reason.count(":") >= 1 else ""
    if stance in STANCE_KEYS:
        return set(STANCE_KEYS[stance])
    if it.action == "talk" and it.tone == "warm":
        return {"warm"}
    return set()


def _how(it: Intent | None) -> dict:
    if it is None:
        return {"action": "idle"}
    out = {"action": it.action}
    if it.target:
        out["target"] = it.target
    if it.reason.startswith("reply:"):
        out["how"] = it.reason.split(":")[1]  # the stance of an answer: retort, deny, apologize ...
    if it.tone:
        out["tone"] = it.tone
    return out


def build(conn: sqlite3.Connection, actor: str, scored: list, chosen: Intent | None, temperature: float, now: int,
          situation: dict | None = None) -> dict:
    """The record of one choice among `scored` (the list the pick drew from)."""
    top = max(s for s, _ in scored)
    weights = [math.exp((s - top) / temperature) for s, _ in scored]
    total = sum(weights)
    probs = [w / total for w in weights]
    at = next((i for i, (_, it) in enumerate(scored) if it is chosen), 0)
    ranked = sorted(range(len(scored)), key=lambda i: (-probs[i], i))[:TOP]
    if at not in ranked:
        ranked = ranked[:TOP - 1] + [at]
    out: dict = {"p": round(probs[at], 3),
                 "options": [{**_how(scored[i][1]), "p": round(probs[i], 3)} for i in ranked]}
    in_play: set[str] = set()
    for i in ranked:
        in_play |= bias_keys(scored[i][1])
    factors = _self_models(conn, actor, in_play)
    if chosen is not None and chosen.reason.startswith("goal:"):
        factors.append({"kind": "goal", "slot": chosen.reason.split(":", 1)[1]})
    from world.domains import active
    for dom in active(conn):
        factors.extend(dom.influences(conn, actor, now))
    if factors:
        out["factors"] = factors
    if situation:
        out["situation"] = situation
    return out


def _self_models(conn: sqlite3.Connection, actor: str, in_play: set[str]) -> list[dict]:
    from world.psyche import SELF_BIAS, self_models
    out = []
    for key, strength in self_models(conn, actor).items():
        leans = {k: round(v * strength, 3) for k, v in SELF_BIAS.get(key, {}).items() if k in in_play}
        if leans:
            out.append({"kind": "self_model", "key": key, "strength": strength, "leans": leans})
    return out
