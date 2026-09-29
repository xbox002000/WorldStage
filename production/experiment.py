"""Experiment freeze: a run of the channel is only comparable if nothing that shapes it changes half-way.

The frozen config records the world rules, the prompt, the models, the story-selection code and style, and the
toolchain. `check_frozen` compares it with what is about to run; any difference stops the run, and the only way
forward is a new experiment.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from pathlib import Path

from agent.decision import PROMPT_VERSION, prompt_fingerprint
from contracts.base import canonical_json, content_hash
from contracts.stylepack import StylePack
from world.ruleset import ROOT, file_hash, ruleset_hash
from world.toolchain import simulation_toolchain_hash

# What decides which stories get told is frozen. How they look and sound is only recorded: restyling the
# episodes mid-run does not change what the world did or which of it was chosen.
STORY_FILES = ("narrative/arcs.py", "narrative/scorer.py", "narrative/selector.py", "narrative/continuity.py",
               "narrative/scene_spec.py", "contracts/scene_spec.py", "contracts/stylepack.py",
               "production/series.py", "channel/daily.py")
PRESENTATION_GLOBS = ("narrative/compiler.py", "narrative/audio_plan.py", "narrative/color.py", "contracts/packet.py",
                      "render/packet_html.py", "audio/*.py", "production/qa.py", "production/publisher.py")
INFORMATIONAL = {"days", "presentation_hash", "render"}


class ExperimentDrift(RuntimeError):
    def __init__(self, differences: dict) -> None:
        self.differences = differences
        super().__init__("frozen experiment config no longer matches: " + ", ".join(sorted(differences)))


def _hash_of(patterns) -> str:
    files = sorted({p for pattern in patterns for p in ROOT.glob(pattern)})
    return content_hash({p.relative_to(ROOT).as_posix(): file_hash(p) for p in files})


def story_hash() -> str:
    """The code that chooses which of the world's events become an episode."""
    return _hash_of(STORY_FILES)


def presentation_hash() -> str:
    """The code that decides how an episode looks, sounds and is described."""
    return _hash_of(PRESENTATION_GLOBS)


def build_config(*, experiment_id: str, world_seed: int | str, active_ids: set[str] | list[str], style: StylePack,
                 models: list[str], days: int, orientation: str, quality: str, temperature: float = 0.8) -> dict:
    return {
        "experiment_id": experiment_id,
        "days": days,
        "world_seed": str(world_seed),
        "active_ids": sorted(active_ids),
        "ruleset_hash": ruleset_hash(),
        "story_hash": story_hash(),
        "presentation_hash": presentation_hash(),
        "stylepack": {"id": style.id, "version": style.version, "hash": style.hash()},
        "scorer_weights": dict(sorted(style.weights.items())),
        "prompt_version": PROMPT_VERSION,
        "prompt_fingerprint": prompt_fingerprint(),
        "models": list(models),
        "temperature": temperature,
        "simulation_toolchain_hash": simulation_toolchain_hash(),
        "render": {"orientation": orientation, "quality": quality},
    }


def differences(frozen: dict, current: dict) -> dict:
    keys = sorted(set(frozen) | set(current))
    return {k: {"frozen": frozen.get(k), "now": current.get(k)} for k in keys if frozen.get(k) != current.get(k)}


def freeze(conn: sqlite3.Connection, config: dict) -> str:
    """Record the config under its experiment id, or verify it matches the one already recorded."""
    row = conn.execute("SELECT config_json FROM experiments WHERE experiment_id = ?", (config["experiment_id"],)).fetchone()
    if row is not None:
        check_frozen(conn, config["experiment_id"], config)
        return config["experiment_id"]
    conn.execute("INSERT INTO experiments(experiment_id, config_json, config_hash, created_at) VALUES (?,?,?,?)",
                 (config["experiment_id"], canonical_json(config), content_hash(config), int(time.time())))
    conn.commit()
    return config["experiment_id"]


def check_frozen(conn: sqlite3.Connection, experiment_id: str, current: dict) -> None:
    row = conn.execute("SELECT config_json FROM experiments WHERE experiment_id = ?", (experiment_id,)).fetchone()
    if row is None:
        raise KeyError(f"experiment {experiment_id!r} has not been frozen yet")
    diff = differences(json.loads(row[0]), json.loads(canonical_json(current)))
    for key in INFORMATIONAL:  # how many days, and how they look, do not make runs incomparable
        diff.pop(key, None)
    if diff:
        raise ExperimentDrift(diff)
