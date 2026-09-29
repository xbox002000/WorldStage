from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import replace

from agent.llm import CacheMiss, LLMClient
from agent.perception import observe, social_options
from contracts.claim import Claim
from contracts.tell import TELL_MODES
from world.claims import describe_claim, labels
from world.intent import TONES, Intent, parse_intent
from world.rng import rng as make_rng
from world.social import belief_effect
from world.state import WorldError

PROMPT_VERSION = "p1.2"

INTENT_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["idle", "talk", "steal", "tell", "confront"]},
        "target": {"type": "string", "description": "person id for talk, tell and confront; object id for steal"},
        "tone": {"type": "string", "enum": list(TONES), "description": "talk only"},
        "claim_id": {"type": "integer", "description": "tell only: the claim_id to pass on"},
        "mode": {"type": "string", "enum": list(TELL_MODES), "description": "tell only"},
        "withheld_claim_id": {"type": "integer", "description": "tell with mode omission only: another claim_id you keep quiet about"},
        "memory_id": {"type": "integer", "description": "confront only: the memory_id you are challenging"},
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

What you remember (the words in brackets say how you know it):
{memories}

What you could do right now (choose exactly one; use the ids exactly as given):
{options}

Real people are not always friendly. Choose what your personality, your feelings toward the people here and what you remember justify. Warm is not a default: if someone slighted you, stands in the way of your goal, or you distrust them (trust below 0), cold or hostile is natural. People lie to protect themselves or someone they care about, or to hurt someone they dislike; they pass on what they know to people they trust; they confront someone only when what that person told them does not add up. Never lie or confront without a reason grounded in your personality, feelings and memories. Do not act on things you have no memory of.

Reply as JSON: action, target (an id from the options), tone (talk only), claim_id and mode (tell only; withheld_claim_id too when the mode is omission), memory_id (confront only), reason (one short sentence in Traditional Chinese).
Pick "idle" if nothing you know gives you a reason to act."""

MODE_HELP = {
    "truth": "say it as you know it",
    "lie": "say the opposite",
    "distortion": "bend it into something milder or harsher",
    "omission": "say it but keep another claim quiet (set withheld_claim_id to one of the other claim ids)",
}


def prompt_fingerprint() -> str:
    """Identity of everything in the prompt that is not state: template, schema and mode help."""
    text = json.dumps([PROMPT_VERSION, PROMPT, INTENT_SCHEMA, MODE_HELP], sort_keys=True, ensure_ascii=False)
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def options_text(opts: dict, names: dict[str, str]) -> str:
    lines = ["- idle", "- talk with one of the people above; set tone (warm | neutral | cold | hostile)"]
    for s in opts["steal"]:
        lines.append(f"- steal {s['target']} ({s['object']}, belongs to {s['owner']}, who is here)")
    if opts["tell"]:
        lines.append("- tell one of the people who does not know it yet something you know; give claim_id, target and mode:")
        for t in opts["tell"]:
            lines.append(f"    claim_id {t['claim_id']}: {t['text']} ({t['how']}); could tell: {', '.join(t['targets'])}")
        modes = [m for m in TELL_MODES if m != "distortion" or any(t["can_distort"] for t in opts["tell"])]
        if len(opts["tell"]) < 2:
            modes = [m for m in modes if m != "omission"]
        lines.append("    modes: " + "; ".join(f"{m} = {MODE_HELP[m]}" for m in modes))
    for c in opts["confront"]:
        lines.append(f"- confront {c['target']} about memory_id {c['memory_id']}: they told you \"{c['text']}\", "
                     f"but you also know \"{c['grounds_text']}\"")
    return "\n".join(lines)


def build_prompt(conn: sqlite3.Connection, actor: str) -> str:
    obs = observe(conn, actor)
    opts = social_options(conn, actor)
    me = obs["me"]
    others = "\n".join(
        f"- {o['id']} ({o['name']}): trust {o['trust']:+.2f}, affection {o['affection']:+.2f}" for o in obs["others_here"]
    ) or "- nobody"
    memories = "\n".join(f"- [{m['how']}] {m['text']} (confidence {m['confidence']:.1f})" for m in obs["memories"]) or "- nothing notable"
    return PROMPT.format(
        name=me["name"], persona=obs["persona"] or "none", goal=me["goal"], emotion=me["emotion"], energy=me["energy"],
        hunger=me["hunger"], money=me["money_cents"] / 100, location=me["location_id"], others=others,
        memories=memories, options=options_text(opts, labels(conn)),
    )


class GeminiDecider:
    """Active-tier decisions. The model only proposes; validation happens in the simulator."""

    def __init__(self, client: LLMClient) -> None:
        self.client = client
        self.errors = 0
        self.unparseable = 0

    def decide(self, conn: sqlite3.Connection, actor: str, now: int) -> Intent | None:
        if not observe(conn, actor)["others_here"]:
            return None
        try:
            raw = self.client.generate_json(build_prompt(conn, actor), INTENT_SCHEMA)
        except CacheMiss:
            raise
        except Exception:  # noqa: BLE001 - a failed call must not stop the world
            self.errors += 1
            return None
        if raw.get("action") == "idle":
            return None
        try:
            return replace(parse_intent(actor, raw), source=self.client.model)
        except WorldError:
            self.unparseable += 1
            return None


class SeededDecider:
    """Ambient tier: no LLM. Randomness comes only from world seed + time + actor, so it replays."""

    def __init__(self, world_seed: int, act_probability: float = 0.6, confront_probability: float = 0.6) -> None:
        self.world_seed = world_seed
        self.act_probability = act_probability
        self.confront_probability = confront_probability

    def decide(self, conn: sqlite3.Connection, actor: str, now: int) -> Intent | None:
        rng = make_rng(self.world_seed, now, actor, "ambient_choice")
        opts = social_options(conn, actor)
        if not opts["here"] or rng.random() > self.act_probability:
            return None
        if opts["confront"] and rng.random() < self.confront_probability:
            c = rng.choice(opts["confront"])
            return Intent(actor, "confront", c["target"], memory_id=c["memory_id"], reason="seeded")

        kinds, weights = ["talk"], [1.0]
        if opts["tell"]:
            kinds.append("tell"), weights.append(0.8)
        if opts["steal"]:
            kinds.append("steal"), weights.append(0.15)
        kind = rng.choices(kinds, weights)[0]

        if kind == "steal":
            s = rng.choice(opts["steal"])
            return Intent(actor, "steal", s["target"], reason="seeded")
        if kind == "tell":
            return self._tell(conn, actor, opts, rng)
        target = rng.choice(opts["here"])["id"]
        trust = conn.execute("SELECT trust FROM relationships WHERE actor_id = ? AND target_id = ?", (actor, target)).fetchone()[0]
        if trust > 0.3:
            tone_weights = (0.5, 0.4, 0.1, 0.0)
        elif trust > -0.1:
            tone_weights = (0.2, 0.5, 0.25, 0.05)
        else:
            tone_weights = (0.0, 0.2, 0.4, 0.4)
        return Intent(actor, "talk", target, rng.choices(TONES, tone_weights)[0], reason="seeded")

    def _tell(self, conn: sqlite3.Connection, actor: str, opts: dict, rng) -> Intent:
        pairs = [(t, p) for t in opts["tell"] for p in t["targets"]]
        tell, target = rng.choice(pairs)
        claim: Claim = tell["claim"]
        row = conn.execute("SELECT affection FROM relationships WHERE actor_id = ? AND target_id = ?",
                           (actor, claim.subject)).fetchone()
        liking = row[0] if row else 0.0  # how the teller feels about who the claim is about
        others = [t["claim_id"] for t in opts["tell"] if t["claim_id"] != tell["claim_id"]]
        modes = ["truth", "lie"] + (["distortion"] if tell["can_distort"] else []) + (["omission"] if others else [])
        harmful = belief_effect(claim) < 0
        if harmful and liking >= 0.25:  # protecting someone they like
            table = {"truth": 0.25, "lie": 0.35, "distortion": 0.15, "omission": 0.25}
        elif harmful and liking <= -0.05:  # happy to see them exposed
            table = {"truth": 0.60, "lie": 0.05, "distortion": 0.25, "omission": 0.10}
        else:
            table = {"truth": 0.70, "lie": 0.10, "distortion": 0.10, "omission": 0.10}
        mode = rng.choices(modes, [table[m] for m in modes])[0]
        withheld = (rng.choice(others),) if mode == "omission" else ()
        return Intent(actor, "tell", target, mode=mode, claim_id=tell["claim_id"], withheld=withheld, reason="seeded")
