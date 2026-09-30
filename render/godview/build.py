"""A world save (runtime/godview.py) -> a self-contained God View project (three.js, the cast, the save).

    python -m render.godview.build out/godview/world.json out/godview/site
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

from render.presentation.build import FILES, HERE as PRESENTATION

HERE = Path(__file__).resolve().parent

PAGE = """<!doctype html>
<html lang="zh-Hant"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>上帝視角</title>
<script type="importmap">{"imports": {"three": "./three/three.module.js", "three/addons/": "./addons/"}}</script>
<style>
:root{--bg:#f4f1ea;--ink:#1d1d24;--dim:#77737a;--panel:#fffdf8;--line:#ddd6ca;--pos:#2f7d4f;--neg:#b23b3b}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--bg:#15151b;--ink:#ecebf0;--dim:#9a97a3;--panel:#1d1d25;--line:#33323d;--pos:#6fcf97;--neg:#ff8080}}
html,body{margin:0;height:100%;background:var(--bg);color:var(--ink);font:14px/1.5 "Microsoft JhengHei","PingFang TC",sans-serif;overflow:hidden}
#app{display:grid;grid-template-columns:1fr 380px;grid-template-rows:1fr 64px;height:100vh}
#view{grid-row:1;grid-column:1;position:relative;overflow:hidden}
#side{grid-row:1/3;grid-column:2;background:var(--panel);border-left:1px solid var(--line);overflow:auto;padding:12px 16px}
#bar{grid-row:2;grid-column:1;display:flex;gap:8px;align-items:center;padding:0 12px;border-top:1px solid var(--line);flex-wrap:wrap}
#clock{font:600 16px/1 ui-monospace,Consolas,monospace;min-width:230px}
button,select{font:inherit;padding:4px 10px;border:1px solid var(--line);border-radius:8px;background:var(--panel);color:var(--ink);cursor:pointer}
#live{background:#c0392b;color:#fff;border-color:#c0392b}
h2{margin:4px 0}h3{margin:12px 0 4px;font-size:13px;color:var(--dim)}ul{margin:0;padding-left:18px}
table td{padding:1px 8px 1px 0;vertical-align:top}.dim{color:var(--dim)}.pos{color:var(--pos)}.neg{color:var(--neg)}
#log{list-style:none;padding:0;margin:0}#log li{cursor:pointer;padding:2px 0;border-bottom:1px dashed var(--line)}
.hint{color:var(--dim)}
</style></head><body><div id="app"><div id="view"></div>
<div id="side"><div id="who"></div><h3>世界正在發生</h3><ul id="log"></ul>
<p class="dim" style="margin-top:14px">唯讀：這一頁只能看，不能改變世界。LIVE 會請本機的模擬器（唯一的寫入者）讓世界再走一天。</p></div>
<div id="bar"><span id="clock"></span><button id="play">▶/⏸</button><button id="back">⏪ 10 分</button><span id="speeds"></span>
<label><input id="skip" type="checkbox" checked> 跳過沒事的時間</label>
<select id="mode"><option value="god">上帝視角</option><option value="follow">跟著他</option><option value="eyes">他的眼睛</option></select>
<select id="place"></select><button id="live">▶ LIVE：讓世界再走一天</button></div></div>
<script type="module" src="godview.js"></script></body></html>
"""


def build(save: Path, out: Path) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    for rel, src in FILES.items():
        dst = out / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
    (out / "assets").mkdir(exist_ok=True)
    for glb in sorted((PRESENTATION / "assets").glob("*.glb")):
        shutil.copyfile(glb, out / "assets" / glb.name)
    shutil.copyfile(HERE / "godview.js", out / "godview.js")
    shutil.copyfile(save, out / "world.json")
    (out / "index.html").write_text(PAGE, encoding="utf-8")
    return out


if __name__ == "__main__":
    print(build(Path(sys.argv[1]), Path(sys.argv[2])))
