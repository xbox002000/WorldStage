"""Write contracts/schemas/*.json from the dataclasses.   python -m contracts.generate_schemas"""
from __future__ import annotations

import json
from pathlib import Path

from contracts.base import schema_for
from contracts.packet import ProductionPacket
from contracts.render_request import RenderRequest, Take
from contracts.scene_spec import SceneSpec
from contracts.stylepack import StylePack
from contracts.tell import TellIntent

OUT = Path(__file__).with_name("schemas")
CONTRACTS = {"scene_spec": SceneSpec, "production_packet": ProductionPacket, "render_request": RenderRequest,
             "take": Take, "stylepack": StylePack, "tell_intent": TellIntent}


def render_all() -> dict[str, str]:
    return {name: json.dumps(schema_for(cls), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
            for name, cls in CONTRACTS.items()}


def main() -> None:
    OUT.mkdir(exist_ok=True)
    for name, text in render_all().items():
        (OUT / f"{name}.schema.json").write_text(text, encoding="utf-8", newline="\n")
        print("wrote", OUT / f"{name}.schema.json")


if __name__ == "__main__":
    main()
