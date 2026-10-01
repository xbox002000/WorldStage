"""Layering: which package may import which. The graph below is what the code does today; a new edge fails here until it is
added on purpose (and, if it points the wrong way, explained in docs/architecture/layers.md)."""
from __future__ import annotations

import ast
import unittest
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGES = ("agent", "audio", "capability", "channel", "contracts", "narrative", "producer", "production", "render",
            "runtime", "world")

# package -> the packages it may import (lazily or not)
ALLOWED = {
    "contracts": {"world"},                                 # world_api.py re-exports the world's kernel types
    "world": {"contracts", "agent", "runtime"},             # simulation.py runs the deciders, the replier and the runtime
    "agent": {"contracts", "world"},
    "producer": {"contracts", "world", "narrative", "agent"},
    "narrative": {"contracts", "world", "agent", "runtime"},
    "runtime": {"contracts", "world", "narrative"},         # the white-box layouts and the spatial plan live in narrative/
    "audio": {"contracts", "world"},
    "production": {"contracts", "world", "narrative", "runtime", "agent", "capability", "render"},
    "capability": {"contracts", "audio", "production", "render"},
    "render": {"contracts", "audio", "world", "narrative", "production"},
    "channel": set(PACKAGES) - {"channel"},
}
# the edges that point against the intended direction (truth <- decision <- story <- space <- production <- providers),
# each with its reason: they are debts, listed so that they stay the only ones
KNOWN_UPWARD = {
    ("world", "agent"): "the simulation calls the deciders and the replier it is given; intent.py reads what an agent perceives",
    ("world", "runtime"): "the simulation can play the runtime along (world/simulation.py, optional)",
    ("contracts", "world"): "contracts/world_api.py re-exports the kernel types",
    ("runtime", "narrative"): "layouts and the spatial plan are in narrative/",
}
ORDER = ["contracts", "world", "agent", "runtime", "narrative", "producer", "audio", "production", "capability", "render"]
# the provider direction (production asks the capability layer, which wires the renderers) is not an upward edge
PROVIDER_SIDE = {("production", "capability"), ("production", "render"), ("capability", "render"), ("capability", "production"),
                 ("render", "production"), ("render", "narrative"), ("render", "world"), ("render", "audio"),
                 ("capability", "audio"), ("production", "runtime"), ("production", "narrative")}
# nothing outside these may import the producer
PRODUCER_USERS = {"channel"}
# the producer reaches the world through the seed layer only
PRODUCER_FORBIDDEN_NAMES = {"apply_event", "mutation", "EventSpec"}
PRODUCER_FORBIDDEN_SQL = ("INSERT ", "UPDATE ", "DELETE ", "REPLACE ")


def imports(path: Path) -> list[str]:
    out = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            out += [a.name.split(".")[0] for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            out.append(node.module.split(".")[0])
    return out


def edges() -> dict[str, dict[str, list[str]]]:
    got: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for pkg in PACKAGES:
        base = ROOT / pkg
        if not base.exists():
            continue
        for f in base.rglob("*.py"):
            if "node_modules" in f.parts:
                continue
            for top in imports(f):
                if top in PACKAGES and top != pkg:
                    got[pkg][top].append(str(f.relative_to(ROOT)).replace("\\", "/"))
    return got


class Layers(unittest.TestCase):
    def test_every_edge_is_allowed(self):
        bad = []
        for pkg, targets in edges().items():
            for top, files in targets.items():
                if top not in ALLOWED.get(pkg, set()):
                    bad.append(f"{pkg} -> {top}: {sorted(set(files))[:3]}")
        self.assertEqual(bad, [], "a package imports one it is not allowed to (tests/test_layers.py ALLOWED)")

    def test_every_allowed_edge_is_used(self):
        """A stale allowance is a hole waiting for the next import: the list only holds what the code does."""
        got = edges()
        stale = [(p, t) for p, ts in ALLOWED.items() for t in ts
                 if p not in ("channel", "producer") and t not in got.get(p, {})]
        self.assertEqual(stale, [])

    def test_the_wrong_way_edges_are_only_the_known_ones(self):
        rank = {p: i for i, p in enumerate(ORDER)}
        upward = {(p, t) for p, ts in ALLOWED.items() for t in ts
                  if p in rank and t in rank and rank[t] > rank[p] and (p, t) not in PROVIDER_SIDE}
        self.assertEqual(sorted(upward - set(KNOWN_UPWARD)), [], "a new upward edge: add it with its reason, or remove it")

    def test_only_the_channel_uses_the_producer(self):
        users = {p for p, ts in edges().items() if "producer" in ts}
        self.assertLessEqual(users, PRODUCER_USERS)

    def test_the_producer_has_one_door_into_the_world(self):
        """No apply_event, no SQL that writes: the seed layer (world/seeds.py) is the only way it changes anything."""
        for f in (ROOT / "producer").rglob("*.py"):
            tree = ast.parse(f.read_text(encoding="utf-8"))
            names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | \
                    {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names}
            self.assertEqual(names & PRODUCER_FORBIDDEN_NAMES, set(), f.name)
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    up = node.value.upper().lstrip()
                    self.assertFalse(any(up.startswith(s) for s in PRODUCER_FORBIDDEN_SQL), (f.name, node.value[:40]))

    def test_the_producer_imagines_only_through_the_rollout(self):
        """It may ask for futures under other luck (world/rollout.py); it never runs the world itself."""
        for f in (ROOT / "producer").rglob("*.py"):
            tree = ast.parse(f.read_text(encoding="utf-8"))
            mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
            names = {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names} |                     {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
            self.assertNotIn("world.simulation", mods, f.name)
            self.assertNotIn("Simulation", names, f.name)

    def test_the_seed_vocabulary_stays_closed(self):
        """Nothing a seed can say names a person's action, feeling, relationship or verdict (contracts/seed.py). A new word
        is added here on purpose (the showrunner's, phase 2B.2), never by accident."""
        from typing import get_args

        from contracts.seed import SEED_VARS, EffectOp
        self.assertEqual(set(get_args(EffectOp)), {"set_var", "place_object", "deliver_object", "set_object_value", "news",
                                                    "animal_arrives"})
        self.assertEqual(set(SEED_VARS), {"price_food", "visibility", "job_security"})


if __name__ == "__main__":
    unittest.main()
