from __future__ import annotations

import json
import random
import sqlite3
from dataclasses import replace

from agent.llm import LLMClient
from agent.perception import candidates, observe
from world.intent import TONES, Intent, parse_intent

INTENT_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["idle", "talk", "steal"]},
        "target": {"type": "string", "description": "person id for talk, object id for steal"},
        "tone": {"type": "string", "enum": list(TONES)},
        "reason": {"type": "string"},
    },
    "required": ["action", "reason"],
}

PROMPT = """You play {name} in a small-town drama simulation. Stay in character; you only know what is listed below.

Personality: {persona}
Goal: {goal}
Current mood: {emotion}. Energy {energy}/100, hunger {hunger}/100, money {money:.2f}.
Location: {location}.

People here and how you feel about them (trust and affection range -1..1):
{others}

Your most recent memories:
{memories}

Options right now (choose exactly one, using the ids given):
{options}

Real people are not always friendly. Choose the tone that your personality, your feelings toward this person and what you remember justify. Warm is not a default: if someone slighted you, stands in the way of your goal, or you distrust them (trust below 0), cold or hostile is natural. Do not act on things you have no memory of.

Reply as JSON: action (idle, talk or steal), target (an id from the options), tone (for talk only), reason (one short sentence in Traditional Chinese).
Pick "idle" if nothing you know gives you a reason to act."""


def build_prompt(conn: sqlite3.Connection, actor: str) -> str:
    obs = observe(conn, actor)
    me = obs["me"]
    others = "\n".join(
        f"- {o['id']} ({o['name']}): trust {o['trust']:+.2f}, affection {o['affection']:+.2f}" for o in obs["others_here"]
    ) or "- nobody"
    memories = "\n".join(f"- {m['belief']} (confidence {m['confidence']:.1f})" for m in obs["memories"]) or "- nothing notable"
    options = json.dumps(candidates(conn, actor), ensure_ascii=False)
    return PROMPT.format(
        name=me["name"], persona=obs["persona"] or "none", goal=me["goal"], emotion=me["emotion"], energy=me["energy"], hunger=me["hunger"],
        money=me["money_cents"] / 100, location=me["location_id"], others=others, memories=memories, options=options,
    )


class GeminiDecider:
    """Active-tier decisions. The model only proposes; validation happens in the simulator."""

    def __init__(self, client: LLMClient) -> None:
        self.client = client
        self.errors = 0

    def decide(self, conn: sqlite3.Connection, actor: str, now: int) -> Intent | None:
        if not observe(conn, actor)["others_here"]:
            return None
        try:
            raw = self.client.generate_json(build_prompt(conn, actor), INTENT_SCHEMA)
        except Exception:  # noqa: BLE001 - a failed call must not stop the world
            self.errors += 1
            return None
        if raw.get("action") == "idle":
            return None
        return replace(parse_intent(actor, raw), source=self.client.model)


class SeededDecider:
    """Ambient tier: no LLM. Randomness comes only from world seed + time + actor, so it replays."""

    def __init__(self, world_seed: int, act_probability: float = 0.6) -> None:
        self.world_seed = world_seed
        self.act_probability = act_probability

    def decide(self, conn: sqlite3.Connection, actor: str, now: int) -> Intent | None:
        rng = random.Random(f"{self.world_seed}:{now}:{actor}")
        options = [c for c in candidates(conn, actor) if c["action"] != "idle"]
        if not options or rng.random() > self.act_probability:
            return None
        pick = rng.choice(options)
        if pick["action"] == "steal":
            return Intent(actor, "steal", pick["target"], reason="seeded") if rng.random() < 0.15 else None
        trust = conn.execute(
            "SELECT trust FROM relationships WHERE actor_id = ? AND target_id = ?", (actor, pick["target"])
        ).fetchone()[0]
        if trust > 0.3:
            weights = (0.5, 0.4, 0.1, 0.0)
        elif trust > -0.1:
            weights = (0.2, 0.5, 0.25, 0.05)
        else:
            weights = (0.0, 0.2, 0.4, 0.4)
        return Intent(actor, "talk", pick["target"], rng.choices(TONES, weights)[0], reason="seeded")
