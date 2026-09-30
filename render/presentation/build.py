"""A scene (runtime/stage.py) -> a HyperFrames project that plays it with the three.js Presentation Runtime.

    python -m render.presentation.build out/sandbox/wallet.json B_dog_pov out/present/B      # one version, renderable
    python -m render.presentation.build out/sandbox/wallet.json --sandbox out/present/sandbox # all versions, interactive

The project is self-contained (three.js, the addons it needs, the Blender assets, the scene) and is a pure function
of its inputs, so the same scene, version and assets always give the same pixels.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
HERE = Path(__file__).resolve().parent
THREE = ROOT / "render" / "node_modules" / "three"
GSAP = ROOT / "render" / "node_modules" / "gsap" / "dist" / "gsap.min.js"
FILES = {"three/three.module.js": THREE / "build" / "three.module.js", "three/three.core.js": THREE / "build" / "three.core.js",
         "addons/loaders/GLTFLoader.js": THREE / "examples" / "jsm" / "loaders" / "GLTFLoader.js",
         "addons/utils/SkeletonUtils.js": THREE / "examples" / "jsm" / "utils" / "SkeletonUtils.js",
         "addons/utils/BufferGeometryUtils.js": THREE / "examples" / "jsm" / "utils" / "BufferGeometryUtils.js",
         "runtime_rule.js": HERE / "runtime_rule.js", "presentation.js": HERE / "presentation.js", "gsap.min.js": GSAP}

PAGE = """<!doctype html>
<html lang="zh-Hant"><head><meta charset="UTF-8"><meta name="viewport" content="width=%(w)d, height=%(h)d">
<script src="gsap.min.js"></script>
<script type="importmap">{"imports": {"three": "./three/three.module.js", "three/addons/": "./addons/"}}</script>
<style>html,body{margin:0;background:#101018;overflow:hidden}#root{position:relative;width:%(w)dpx;height:%(h)dpx}
#hud{position:absolute;left:16px;top:12px;font:18px/1.45 "Microsoft JhengHei",sans-serif;color:#14141c;
background:rgba(255,255,255,.72);padding:8px 12px;border-radius:10px;white-space:pre;display:none}</style></head>
<body><div id="root" data-composition-id="main" data-start="0" data-duration="%(total)s" data-width="%(w)d" data-height="%(h)d">
<div id="host"></div><div id="hud"></div></div>
<script type="module">
import { start } from "./presentation.js";
const doc = await (await fetch("scene.json")).json();
const q = new URLSearchParams(location.search), sandbox = q.has("sandbox");
const rt = await start(doc, { host: document.getElementById("host"), width: %(w)d, height: %(h)d, version: %(version)s,
                              pass: q.get("pass") || %(pass)s });
window.__timelines = window.__timelines || {};
window.__rt = rt;  // for inspection (the sandbox and the tests); it exposes no way to change the world
if (!sandbox) {  // HyperFrames seeks this timeline; the frame is drawn from the film time alone
  const clock = { film: 0 };
  const tl = gsap.timeline({ paused: true });
  tl.to(clock, { film: rt.duration(rt.state.version), duration: rt.duration(rt.state.version), ease: "none",
                 onUpdate: () => rt.frame(clock.film) }, 0);
  window.__timelines["main"] = tl;
  tl.seek(0);
  rt.frame(0);
} else {
  const hud = document.getElementById("hud"); hud.style.display = "block";
  let film = 0, paused = false, last = performance.now();
  const keys = new Set();
  addEventListener("keydown", e => {
    keys.add(e.key.toLowerCase());
    if (e.key === " ") paused = !paused;
    if (e.key === "ArrowLeft") film = Math.max(0, film - 2);
    if (e.key === "ArrowRight") film += 2;
    if (e.key === "r" || e.key === "R") film = 0;
    if (e.key === "l" || e.key === "L") rt.state.lensBoost = ((rt.state.lensBoost + 30) %% 40) - 20;
    if (e.key === "f" || e.key === "F") rt.state.free = rt.state.free ? null : { init: true };
    const i = "123".indexOf(e.key);
    if (i >= 0 && i < rt.versions.length) {  // the same moment of the world, in the other version's edit
      const t = rt.worldAt(film); rt.state.version = rt.versions[i]; film = rt.filmAt(t);
    }
  });
  addEventListener("keyup", e => keys.delete(e.key.toLowerCase()));
  addEventListener("mousemove", e => { if (rt.state.free && e.buttons) { rt.state.free.yaw -= e.movementX * 0.005;
    rt.state.free.pitch = Math.max(-1.5, Math.min(1.5, rt.state.free.pitch - e.movementY * 0.005)); } });
  const loop = now => {
    const dt = Math.min(0.1, (now - last) / 1000); last = now;
    if (!paused) film = Math.min(rt.duration(rt.state.version), film + dt);
    if (rt.state.free) rt.freeMove(keys, dt);
    const { cut, t, debug } = rt.frame(film);
    const held = Object.entries(debug.things).filter(([, s]) => s !== "ground" && s !== "offstage").map(([k, s]) => `${k} ${s}`).join(" · ");
    hud.textContent = `版本 ${rt.state.version}${paused ? "（暫停）" : ""}   影片 ${film.toFixed(1)} / ${rt.duration(rt.state.version)} s   世界 ${t.toFixed(1)} s\\n` +
      `鏡頭 ${cut.scale} ${cut.angle} ${cut.relation} ${cut.motion} · 觀點 ${cut.focal || "全知"} · ${cut.function} · ${cut.info}\\n` +
      `攝影機 ${cut.camera ? cut.camera.solution.why : ""}${held ? "   物品 " + held : ""}\\n` +
      `空白鍵 暫停 · ←/→ 跳 2 秒 · 1/2/3 版本 · F 自由鏡頭（WASD Q/E、拖曳）· L 焦距 · R 重播 · 世界唯讀`;
    requestAnimationFrame(loop);
  };
  requestAnimationFrame(loop);
}
</script></body></html>
"""


PASSES = ("rgb", "depth", "normal", "id", "pose")


def build(scene: Path, version: str | None, out: Path, width: int = 1080, height: int = 1920, pass_: str = "rgb") -> Path:
    doc = json.loads(scene.read_text(encoding="utf-8"))
    versions = sorted(doc["cuts"])
    version = next((v for v in versions if version and v.startswith(version)), versions[0])
    out.mkdir(parents=True, exist_ok=True)
    for rel, src in FILES.items():
        dst = out / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
    (out / "assets").mkdir(exist_ok=True)
    for glb in sorted((HERE / "assets").glob("*.glb")):
        shutil.copyfile(glb, out / "assets" / glb.name)
    shutil.copyfile(scene, out / "scene.json")
    (out / "index.html").write_text(PAGE % {"w": width, "h": height, "total": doc["cuts"][version]["film_duration"],
                                            "version": json.dumps(version), "pass": json.dumps(pass_)}, encoding="utf-8")
    (out / "meta.json").write_text(json.dumps({"id": "presentation", "name": f"{scene.stem} {version}"}), encoding="utf-8")
    return out


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--sandbox"]
    if "--sandbox" in sys.argv:
        print(build(Path(args[0]), None, Path(args[1]), 720, 1280))
    else:
        print(build(Path(args[0]), args[1], Path(args[2])))
