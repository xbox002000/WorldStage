"""Behaviour fingerprints of a few worlds: the content hash of every history and state table, without the code hashes.

    python -m tests.refactor_baseline > out/refactor_baseline.json     # before a refactor
    python -m tests.refactor_baseline --check out/refactor_baseline.json   # after: every table must be identical

A refactor that only moves code must not change a single event, delta or memory in any recipe.
"""
from __future__ import annotations

import json
import sys

from agent.volition import VolitionDecider
from world.db import connect, init_db
from world.seed import build_world
from world.simulation import Simulation
from world.snapshot import table_hash, TABLES

WORLDS = [("town_v1", 184729, 4, "synthetic_v1"), ("jianghu_v1", 7, 4, None), ("town_spatial_v1", 260934, 1, "synthetic_v1")]


def fingerprint(recipe: str, seed: int, days: int, feed: str | None) -> dict:
    c = connect()
    init_db(c, seed)
    build_world(c, seed, recipe)
    d = VolitionDecider(seed)
    Simulation(c, d, d, set(), feed=feed).run(days)
    return {t: table_hash(c, t) for t in TABLES if c.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (t,)).fetchone()}


def main() -> None:
    got = {f"{r}:{s}:{d}": fingerprint(r, s, d, f) for r, s, d, f in WORLDS}
    if len(sys.argv) > 2 and sys.argv[1] == "--check":
        want = json.load(open(sys.argv[2], encoding="utf-8"))
        bad = {w: [t for t in want[w] if want[w][t] != got[w].get(t)] for w in want}
        bad = {w: ts for w, ts in bad.items() if ts}
        print(json.dumps(bad or "identical", ensure_ascii=False))
        sys.exit(1 if bad else 0)
    print(json.dumps(got, indent=1))


if __name__ == "__main__":
    main()
