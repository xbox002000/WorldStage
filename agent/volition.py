"""Rule motives: every character lives by their needs, traits, feelings and memories, with no model and no script.

Each option the world offers right now gets a score from:
- the person's static traits (honesty, temper, gossip, generosity, curiosity);
- their needs (money, arrears, debt, job security);
- their feelings toward the people present;
- their emotion and what they believe.

A deterministic weighted draw (world seed + time + person) picks one. Nothing here writes the world: the choice is
an Intent that the validator may still refuse, and every consequence comes from the rules. Pressure raises the
scores of desperate or angry options, so drama follows from circumstances, not from anyone asking for it.
"""
from __future__ import annotations

import json
import math
import sqlite3

from agent.perception import social_options
from contracts.claim import Claim
from world.attention import var
from world.intent import LEND_CENTS, TONES, Intent
from world.rng import rng as make_rng
from world.social import belief_effect

TEMPERATURE = 0.35
IDLE = 0.35


def traits(conn: sqlite3.Connection, pid: str) -> dict:
    row = conn.execute("SELECT traits FROM personas WHERE person_id = ?", (pid,)).fetchone()
    base = {"honesty": 0.6, "temper": 0.4, "gossip": 0.4, "generosity": 0.4, "absent_minded": 0.3, "curiosity": 0.4}
    try:
        base.update(json.loads(row[0]) if row else {})
    except (IndexError, TypeError):
        pass
    return base


def need(conn: sqlite3.Connection, pid: str) -> float:
    """0..1: how pressed for money someone is (what they know about themselves)."""
    p = conn.execute("SELECT money_cents, schedule FROM people WHERE id = ?", (pid,)).fetchone()
    owed = conn.execute("SELECT COALESCE(SUM(debt_cents), 0) FROM relationships WHERE actor_id = ?", (pid,)).fetchone()[0]
    n = 0.5 * (var(conn, f"arrears.{pid}", 0) > 0) + 0.4 * max(0.0, 1 - p["money_cents"] / 4000) + 0.2 * (owed > 0)
    if '"work"' in p["schedule"]:
        n += 0.3 * (1 - var(conn, "job_security", 1.0))
    return min(1.0, n)


def rel(conn: sqlite3.Connection, a: str, b: str) -> sqlite3.Row:
    return conn.execute("SELECT trust, affection, fear, rivalry, debt_cents FROM relationships "
                        "WHERE actor_id = ? AND target_id = ?", (a, b)).fetchone()


def value_factor(cents: int) -> float:
    return min(1.0, cents / 20000)


def _tone(conn: sqlite3.Connection, me: str, other: str, t: dict, emotion: str, rng) -> tuple[str, float]:
    """How someone would speak to another, and how much they want to."""
    r = rel(conn, me, other)
    owed_to_me = rel(conn, other, me)["debt_cents"]
    warmth = r["trust"] + r["affection"] - r["rivalry"] - 0.3 * (owed_to_me > 0) * (1 - t["generosity"])
    heat = t["temper"] * (1.2 if emotion in ("angry", "hurt", "embarrassed") else 0.6)
    weights = {
        "warm": max(0.02, 0.4 + warmth),
        "neutral": 0.5,
        "cold": max(0.02, 0.2 - warmth + 0.3 * (emotion in ("hurt", "uneasy", "scared"))),
        "hostile": max(0.0, heat * (0.1 - warmth) + 0.3 * (owed_to_me > 0 and r["trust"] < 0)),
    }
    tone = rng.choices(TONES, [weights[k] for k in TONES])[0]
    want = 0.45 + 0.25 * t["curiosity"] + 0.25 * abs(r["affection"]) + 0.2 * max(0.0, r["rivalry"])
    return tone, want


def deliberate(conn: sqlite3.Connection, actor: str, oid: str) -> bool:
    """Did the actor get this on purpose (stole it, or took it long ago) rather than find it or receive it?"""
    row = conn.execute(
        "SELECT type FROM events WHERE type IN ('steal', 'backstory', 'take', 'seed') AND json_extract(truth, '$.object') = ? "
        "AND (json_extract(truth, '$.actor') = ? OR json_extract(truth, '$.picks.holder') = ?) ORDER BY event_id DESC LIMIT 1",
        (oid, actor, actor)).fetchone()
    return row is not None and row[0] in ("steal", "backstory")


def owner_suspects(conn: sqlite3.Connection, owner: str, actor: str, oid: str) -> float:
    """How sure the owner is that the actor has it (0..1), from the owner's own beliefs."""
    row = conn.execute(
        "SELECT MAX(m.confidence) FROM memories m JOIN claims c USING (claim_id) WHERE m.observer_id = ? "
        "AND c.subject = ? AND c.object = ? AND c.act IN ('take', 'steal') AND c.polarity = 'affirm'",
        (owner, actor, oid)).fetchone()
    return row[0] or 0.0


class VolitionDecider:
    """Decides for any character. Same world, same seed, same time: same choice."""

    def __init__(self, world_seed: int | str, temperature: float = TEMPERATURE) -> None:
        self.world_seed = world_seed
        self.temperature = temperature
        self.errors = 0
        self.unparseable = 0
        self.mechanics: list = []  # set by the simulation from the world's recorded mechanic pack

    def options(self, conn: sqlite3.Connection, actor: str, now: int) -> list[tuple[float, Intent]]:
        rng = make_rng(self.world_seed, now, actor, "volition_detail")
        me = conn.execute("SELECT * FROM people WHERE id = ?", (actor,)).fetchone()
        t = traits(conn, actor)
        n = need(conn, actor)
        opts = social_options(conn, actor)
        here = [o["id"] for o in opts["here"]]
        crowd = len(here)
        out: list[tuple[float, Intent]] = [(IDLE, None)]

        for other in here:
            tone, want = _tone(conn, actor, other, t, me["emotion"], rng)
            out.append((want, Intent(actor, "talk", other, tone, reason="volition")))

        for tl in opts["tell"]:
            claim: Claim = tl["claim"]
            juicy = abs(belief_effect(claim)) * 2 + 0.1
            for target in tl["targets"]:
                about = rel(conn, actor, claim.subject) if claim.subject != actor else None
                liking = about["affection"] if about is not None else 0.0
                harmful = belief_effect(claim) < 0
                if claim.subject == actor and harmful:
                    continue  # nobody brings up their own misdeed unasked; a denial comes when accused
                if claim.subject == actor:
                    mode, score = "truth", 0.3
                elif harmful and liking >= 0.25:
                    mode = rng.choices(["lie", "omission", "truth"], [1 - t["honesty"], 0.3, t["honesty"]])[0]
                    score = 0.3 + 0.5 * t["gossip"] * juicy
                elif harmful and liking <= -0.05:
                    mode = rng.choices(["truth", "distortion"], [t["honesty"], 1 - t["honesty"]])[0]
                    score = 0.4 + 0.8 * t["gossip"] * juicy
                else:
                    mode = "truth"
                    score = 0.2 + 0.6 * t["gossip"] * juicy
                if mode == "distortion" and not tl["can_distort"]:
                    mode = "truth"
                withheld = ()
                if mode == "omission":
                    others = [x["claim_id"] for x in opts["tell"] if x["claim_id"] != tl["claim_id"]]
                    if not others:
                        mode = "truth"
                    else:
                        withheld = (others[0],)
                out.append((score, Intent(actor, "tell", target, mode=mode, claim_id=tl["claim_id"], withheld=withheld,
                                          reason="volition")))

        for c in opts["confront"]:
            out.append((0.6 + 0.5 * t["temper"], Intent(actor, "confront", c["target"], memory_id=c["memory_id"],
                                                        reason="volition")))

        for s in opts["steal"]:
            v = conn.execute("SELECT value_cents FROM objects WHERE id = ?", (s["target"],)).fetchone()[0]
            score = (1 - t["honesty"]) ** 2 * (0.2 + n) * (0.3 + value_factor(v)) * 1.5 - 0.08 * crowd
            if score > 0:
                out.append((score, Intent(actor, "steal", s["target"], reason="volition")))

        for it in opts["take"]:
            if it["rightful"] == actor:
                out.append((3.0, Intent(actor, "take", it["target"], reason="volition")))  # one's own lost thing
                continue
            keep = (1 - t["honesty"]) * (0.2 + n) * (0.3 + value_factor(it["value_cents"])) * 1.6
            pick_up_to_return = t["honesty"] * 0.5 if it["rightful"] else 0.0
            curiosity = 0.3 * t["curiosity"]
            out.append((max(keep, pick_up_to_return, curiosity) - 0.05 * crowd,
                        Intent(actor, "take", it["target"], reason="volition")))

        for g in opts["give"]:
            r = rel(conn, actor, g["owner"])
            keep_pull = (1 - t["honesty"]) * (0.2 + n) * value_factor(g["value_cents"])
            if deliberate(conn, actor, g["target"]):
                # handing back what one took on purpose is a confession: only when cornered
                score = -1.0 + 1.6 * t["honesty"] * owner_suspects(conn, g["owner"], actor, g["target"]) - keep_pull
            else:
                score = 0.3 + t["honesty"] + 0.3 * r["affection"] - 1.5 * keep_pull
            out.append((score, Intent(actor, "give", g["target"], reason="volition")))

        for rp in opts["repay"]:
            r = rel(conn, actor, rp["target"])
            spare = me["money_cents"] - min(rp["debt_cents"], LEND_CENTS)
            out.append((0.2 + 0.5 * t["honesty"] + 0.4 * max(0.0, r["fear"]) + 0.3 * (spare > 4000) - 0.5 * n,
                        Intent(actor, "repay", rp["target"], reason="volition")))

        in_debt = conn.execute("SELECT 1 FROM relationships WHERE actor_id = ? AND debt_cents > 0", (actor,)).fetchone()
        for ln in opts["lend"]:
            other = ln["target"]
            r = rel(conn, actor, other)
            if in_debt or rel(conn, other, actor)["debt_cents"] > 0 or conn.execute(
                    "SELECT 1 FROM events WHERE type = 'lend' AND json_extract(truth, '$.actor') = ? "
                    "AND json_extract(truth, '$.target') = ? AND timestamp > ?", (actor, other, now - 7 * 1440)).fetchone():
                continue
            emo = conn.execute("SELECT emotion FROM people WHERE id = ?", (other,)).fetchone()[0]
            distress = 1.0 if emo in ("uneasy", "scared", "hurt") else 0.2
            if r["affection"] > 0.1:
                out.append((t["generosity"] * r["affection"] * distress * 1.2 - 0.3 * n,
                            Intent(actor, "lend", other, reason="volition")))

        for a in opts["accuse"]:
            r = rel(conn, actor, a["target"])
            angry = 0.3 if me["emotion"] in ("angry", "hurt", "uneasy") else 0.0
            out.append((a["confidence"] * (0.6 + t["temper"]) + angry - 0.4 * max(0.0, r["fear"]) - 0.2 * r["affection"],
                        Intent(actor, "accuse", a["target"], memory_id=a["memory_id"], reason="volition")))
        return out

    def decide(self, conn: sqlite3.Connection, actor: str, now: int) -> Intent | None:
        scored = self.options(conn, actor, now)
        for m in self.mechanics:
            scored = m.bias(conn, actor, now, scored + m.options(conn, actor, now))
        if len(scored) == 1:
            return None
        weights = [math.exp(s / self.temperature) for s, _ in scored]
        rng = make_rng(self.world_seed, now, actor, "volition_pick")
        _, choice = rng.choices(scored, weights)[0]
        return choice
