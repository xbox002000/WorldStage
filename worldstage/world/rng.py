"""All randomness in the engine comes from here.

Never use Python's built-in hash() (randomised per process) or an unseeded random module.
A stream is fully determined by (world_seed, world_time, entity_id, purpose).
"""
from __future__ import annotations

import hashlib
import json
import random


def derive_seed(world_seed: int | str, world_time: int, entity_id: str, purpose: str) -> int:
    payload = json.dumps([str(world_seed), int(world_time), entity_id, purpose], separators=(",", ":"), ensure_ascii=False)
    return int.from_bytes(hashlib.sha256(payload.encode("utf-8")).digest()[:8], "big")


def rng(world_seed: int | str, world_time: int, entity_id: str, purpose: str) -> random.Random:
    return random.Random(derive_seed(world_seed, world_time, entity_id, purpose))
