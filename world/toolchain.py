"""Simulation toolchain fingerprint: what the world was computed with.

Deliberately NOT part of world_snapshot_hash. The snapshot describes data, so moving the same data to another
machine must give the same hash. This fingerprint travels in provenance and the experiment freeze instead.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCK_FILE = ROOT / "requirements.lock"


def _lock_pins() -> dict[str, str]:
    pins: dict[str, str] = {}
    if LOCK_FILE.exists():
        for line in LOCK_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith(("#", "-")) and "==" in line:
                name, _, version = line.partition("==")
                pins[name.strip().lower()] = version.strip()
    return pins


def lock_drift() -> dict[str, tuple[str, str | None]]:
    """Packages whose installed version differs from the lock file: {name: (locked, installed)}."""
    drift = {}
    for name, locked in _lock_pins().items():
        try:
            installed = metadata.version(name)
        except metadata.PackageNotFoundError:
            installed = None
        if installed != locked:
            drift[name] = (locked, installed)
    return drift


def simulation_toolchain() -> dict:
    lock_bytes = LOCK_FILE.read_bytes().replace(b"\r\n", b"\n") if LOCK_FILE.exists() else b""
    return {
        "python": f"{sys.version_info.major}.{sys.version_info.minor}",
        "sqlite": sqlite3.sqlite_version,
        "lock": "sha256:" + hashlib.sha256(lock_bytes).hexdigest(),
    }


def simulation_toolchain_hash() -> str:
    text = json.dumps(simulation_toolchain(), sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()
