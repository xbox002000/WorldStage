"""studio.json (channel/studio.py) -> a self-contained page: no server needed to read it, no network, no build step.

    python -m render.studio.build out/studio/studio.json out/studio/site
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def build(data: Path, out: Path) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    for name in ("index.html", "studio.css", "studio.js"):
        shutil.copyfile(HERE / name, out / name)
    shutil.copyfile(data, out / "studio.json")
    # the same data as a script, so that the page also opens straight from the file system (fetch is refused on file://)
    (out / "studio-data.js").write_text("window.STUDIO = " + Path(data).read_text(encoding="utf-8") + ";", encoding="utf-8")
    return out


if __name__ == "__main__":
    print(build(Path(sys.argv[1]), Path(sys.argv[2])))
