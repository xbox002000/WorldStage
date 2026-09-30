"""Scene script -> one HyperFrames project in the "cast" look: vector characters in vector places, cut like a
conversation, with dialogue. A pure function of the script: same script, same files."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
SHELL = """<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=1080, height=1920" />
<script src="gsap.min.js"></script>
<style>
%(css)s
</style>
</head>
<body>
<div id="root" data-composition-id="main" data-start="0" data-duration="%(total)s" data-width="1080" data-height="1920">
  <svg id="scene" width="1080" height="1920" viewBox="0 0 1080 1920"><g id="world"></g></svg>
  <div id="ui"></div>
  <div id="fade"></div>
%(audio)s</div>
<script>
%(js)s
const SCRIPT = %(script)s;
window.__timelines = window.__timelines || {};
const tl = STAGE.build(SCRIPT, gsap);
window.__timelines["main"] = tl;
tl.seek(0);
</script>
</body>
</html>
"""
AUDIO = ('  <audio id="mix" src="assets/mix.wav" data-start="0" data-duration="%s" data-volume="1" '
         'data-track-index="9"></audio>\n')


def render_html(script: dict, with_audio: bool = False) -> str:
    js = "\n".join((HERE / f).read_text(encoding="utf-8") for f in ("characters.js", "backgrounds.js", "stage.js"))
    return SHELL % {"css": (HERE / "style.css").read_text(encoding="utf-8"), "js": js, "total": script["total"],
                    "audio": AUDIO % script["total"] if with_audio else "",
                    "script": json.dumps(script, ensure_ascii=False, sort_keys=True)}


DIRECTED_SHELL = SHELL.replace('<div id="fade"></div>', '<div id="flash"></div>' + chr(10) + '  <div id="fade"></div>').replace(
    "STAGE.build(SCRIPT, gsap)", "DIRECTED.build(SCRIPT, gsap)")
DIRECTED_JS = ("characters.js", "animals.js", "props.js", "backgrounds.js", "directed.js")


def render_directed_html(script: dict, with_audio: bool = False) -> str:
    """A directed episode (render/cast/packet_script.py builds the script from a ProductionPacket)."""
    js = chr(10).join((HERE / f).read_text(encoding="utf-8") for f in DIRECTED_JS)
    return DIRECTED_SHELL % {"css": (HERE / "style.css").read_text(encoding="utf-8"), "js": js, "total": script["total"],
                             "audio": AUDIO % script["total"] if with_audio else "",
                             "script": json.dumps(script, ensure_ascii=False, sort_keys=True)}


def build_project(script: dict, outdir: Path, gsap: Path, mix: bytes | None = None, directed: bool = False) -> Path:
    outdir.mkdir(parents=True, exist_ok=True)
    if mix is not None:
        (outdir / "assets").mkdir(exist_ok=True)
        (outdir / "assets" / "mix.wav").write_bytes(mix)
    html = (render_directed_html if directed else render_html)(script, with_audio=mix is not None)
    (outdir / "index.html").write_text(html, encoding="utf-8")
    (outdir / "meta.json").write_text(json.dumps({"id": "cast", "name": script["title"]}, ensure_ascii=False), encoding="utf-8")
    shutil.copyfile(gsap, outdir / "gsap.min.js")
    return outdir
