"""The Director Reality benchmark's main versions -> one sandbox scene (runtime/stage.py) for the presentation runtime.

    python -m runtime.scene_from_benchmark out/reality_v2 out/sandbox/wallet.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from contracts.base import from_dict
from contracts.packet import ProductionPacket
from runtime.stage import export_scene
from runtime.world_runtime import WorldRuntime
from world.db import connect


def main(bench_out: Path, scene: Path, versions=("A_ming_pov", "B_dog_pov", "C_omniscient")) -> dict:
    conn = connect(bench_out / "world.db")
    packets = {v: from_dict(ProductionPacket, json.loads((bench_out / v / "packet.json").read_text(encoding="utf-8")))
               for v in versions}
    ids = sorted({s.event_id for p in packets.values() for s in p.shots})
    return export_scene(conn, WorldRuntime(conn).trace(ids), packets, scene)


if __name__ == "__main__":
    doc = main(Path(sys.argv[1]), Path(sys.argv[2]))
    print("scene", sys.argv[2], doc["duration"], sorted(doc["cuts"]))
