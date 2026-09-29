"""Ruleset provenance: which code produced this world."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

KERNEL_VERSION = "0.2.0"
ROOT = Path(__file__).resolve().parent.parent
RULESET_FILES = (
    "world/rules.py", "world/intent.py", "world/seed.py", "world/simulation.py", "world/events.py",
    "world/state.py", "world/claims.py", "world/rng.py", "world/db.py", "world/schema.sql",
)
RULESET_GLOBS = ("world/migrations/*.sql", "contracts/*.py")


def file_hash(path: Path) -> str:
    # Normalise line endings so a CRLF checkout hashes the same as LF.
    data = path.read_bytes().replace(b"\r\n", b"\n")
    return "sha256:" + hashlib.sha256(data).hexdigest()


def ruleset_manifest() -> dict:
    files = [ROOT / f for f in RULESET_FILES]
    for pattern in RULESET_GLOBS:
        files += sorted(ROOT.glob(pattern))
    return {
        "kernel_version": KERNEL_VERSION,
        "files": {p.relative_to(ROOT).as_posix(): file_hash(p) for p in sorted(set(files))},
    }


def ruleset_hash() -> str:
    payload = json.dumps(ruleset_manifest(), sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()
