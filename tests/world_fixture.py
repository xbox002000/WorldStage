"""A small deterministic world shared by the production-layer tests (built once, read-only afterwards)."""
from __future__ import annotations

import functools
import os
import tempfile

from agent.decision import SeededDecider
from narrative.compiler import compile_packet
from narrative.scene_spec import build_scene_specs
from narrative.selector import select_top
from world.db import connect, init_db
from world.reader import open_world_reader
from world.seed import build_world
from world.simulation import Simulation

SEED = 184729


@functools.lru_cache(maxsize=None)
def world_path(days: int = 7) -> str:
    """A file-backed world (so a read-only connection can open it), created once per process."""
    path = os.path.join(tempfile.mkdtemp(prefix="worldfx_"), "world.db")
    conn = connect(path)
    init_db(conn, SEED)
    build_world(conn, SEED)
    d = SeededDecider(SEED)
    Simulation(conn, d, d, set()).run(days)
    conn.close()
    return path


def reader():
    return open_world_reader(world_path())


def build_specs(top: int = 3):
    r = reader()
    return build_scene_specs(r, select_top(r, top)[0])


def compile_all(top: int = 3, **kw):
    return [compile_packet(s, **kw) for s in build_specs(top)]
