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
<title>世界觀測台</title>
<script type="importmap">{"imports": {"three": "./three/three.module.js", "three/addons/": "./addons/"}}</script>
<style>
:root{--bg:#f4f1ea;--ink:#1d1d24;--dim:#77737a;--panel:#fffdf8;--line:#ddd6ca;--pos:#2f7d4f;--neg:#b23b3b;--accent:#c0392b;--hl:#ffc233}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--bg:#15151b;--ink:#ecebf0;--dim:#9a97a3;--panel:#1d1d25;--line:#33323d;--pos:#6fcf97;--neg:#ff8080}}
html,body{margin:0;height:100%;background:var(--bg);color:var(--ink);font:13px/1.5 "Microsoft JhengHei","PingFang TC",sans-serif;overflow:hidden}
#app{display:grid;grid-template-rows:58vh 40px 1fr;height:100vh}
#view{position:relative;overflow:hidden}
#labels{position:absolute;inset:0;pointer-events:none}
.label{position:absolute;transform:translate(-50%,-100%);font-size:12px;padding:1px 6px;border-radius:8px;background:rgba(255,255,255,.82);color:#222;white-space:nowrap;pointer-events:auto;cursor:pointer;border:1px solid transparent}
.label[data-feel=angry]{background:#ffc9bf}.label[data-feel=hurt],.label[data-feel=scared]{background:#cfe0f5}
.label[data-feel=uneasy],.label[data-feel=ashamed],.label[data-feel=embarrassed]{background:#fbe7b0}.label[data-feel=happy],.label[data-feel=relieved]{background:#d6f0d9}
.label.sel{background:#ff5a36;color:#fff}.label.story{border-color:var(--hl);box-shadow:0 0 0 2px var(--hl)}
#flash{position:absolute;left:50%;top:12px;transform:translateX(-50%);background:rgba(20,20,28,.85);color:#fff;padding:6px 14px;border-radius:10px;opacity:0;transition:opacity .4s;pointer-events:none}
#bar{display:flex;gap:6px;align-items:center;padding:0 10px;border-top:1px solid var(--line);border-bottom:1px solid var(--line);flex-wrap:wrap;overflow:hidden}
#clock{font:600 15px/1 ui-monospace,Consolas,monospace;min-width:250px}
button,select{font:inherit;padding:3px 9px;border:1px solid var(--line);border-radius:8px;background:var(--panel);color:var(--ink);cursor:pointer}
#live{background:var(--accent);color:#fff;border-color:var(--accent)}
#panels{display:grid;grid-template-columns:1fr 1.1fr 1fr;min-height:0}
#panels>section{overflow:auto;padding:8px 12px;border-right:1px solid var(--line);background:var(--panel);min-height:0}
h2{margin:2px 0 6px;font-size:17px}h3{margin:10px 0 4px;font-size:13px;color:var(--dim)}ul{margin:0;padding-left:18px}
.dim{color:var(--dim)}.pos{color:var(--pos)}.neg{color:var(--neg)}
#threads{list-style:none;padding:0}#threads li{padding:5px 4px;border-bottom:1px dashed var(--line);cursor:pointer}#threads li.on{background:rgba(255,194,51,.18)}
.bar{display:inline-block;position:relative;width:110px;height:7px;background:var(--line);border-radius:4px;vertical-align:middle}.bar>i{position:absolute;left:0;top:0;bottom:0;background:#e0892d;border-radius:4px}
.bar>u{position:absolute;top:-2px;bottom:-2px;width:2px;background:var(--ink)}
.why{background:rgba(255,194,51,.12);border-left:3px solid var(--hl);padding:6px 8px;margin:6px 0}
.day{border-left:2px solid var(--line);margin-left:6px;padding-left:10px}.dlabel{font-weight:600;margin:8px 0 2px -18px;background:var(--panel)}
.node{padding:4px 0;cursor:pointer}.node:hover{background:rgba(0,0,0,.04)}.cons{font-size:12px;margin:2px 0 0 8px}
.know{font-size:12px}.row{margin:3px 0}
#tabs{display:flex;gap:4px;flex-wrap:wrap;margin-bottom:6px}#tabs button.on{background:var(--ink);color:var(--panel)}
.lifeline{position:relative;height:18px;border-bottom:2px solid var(--line);margin:10px 0}.lifeline .dot{position:absolute;bottom:-6px;width:10px;height:10px;border-radius:50%;background:#888;cursor:pointer}
.k-betrayal,.k-wronged,.k-shame,.k-hostility,.k-loss{background:#c0392b!important}.k-kindness,.k-success,.k-discovery,.k-goal_completed{background:#2f7d4f!important}
.k-identity_shift,.k-value_shift,.k-turning_point{background:#6c4bd8!important}
.ms li,.bio{cursor:pointer}.ms li:hover,.bio:hover{background:rgba(0,0,0,.04)}
.spark{color:#e0892d;vertical-align:middle}
#ltabs{display:flex;gap:4px;margin-bottom:6px}#ltabs button.on{background:var(--ink);color:var(--panel)}
#scenes{list-style:none;padding:0}#scenes li{padding:5px 4px;border-bottom:1px dashed var(--line);cursor:pointer}#scenes li:hover{background:rgba(255,194,51,.18)}
.bubble{position:absolute;transform:translate(-50%,-100%);max-width:220px;font-size:13px;line-height:1.35;padding:4px 9px;border-radius:12px;background:#fff;color:#1d1d24;border:1px solid #bbb;box-shadow:0 2px 6px rgba(0,0,0,.18);pointer-events:none;white-space:normal;text-align:center}
.bubble.hot{background:#ffe3df;border-color:#e0533d;color:#8a1c0e;font-weight:600}.bubble.cool{background:#e6edf5;border-color:#8aa3bf;color:#2d4660}.bubble.warm{background:#e7f6e9;border-color:#6fb67b;color:#1f5a2b}
table td{padding:1px 8px 1px 0;vertical-align:top}
</style></head><body><div id="app">
<div id="view"><div id="labels"></div><div id="flash"></div></div>
<div id="bar"><span id="clock"></span><button id="play">▶/⏸</button><button id="back">⏪ 10 分</button><span id="speeds"></span>
<label><input id="skip" type="checkbox" checked> 跳過沒事的時間</label>
<select id="mode"><option value="god">上帝視角</option><option value="follow">跟著他</option><option value="eyes">他的眼睛</option></select>
<select id="place"></select><label><input id="walls" type="checkbox" checked> 牆</label><label><input id="top" type="checkbox"> 俯視</label>
<button id="live">▶ LIVE：再走一天</button><span class="dim">唯讀：這一頁不能改變世界</span></div>
<div id="panels">
<section><div id="ltabs"><button data-l="scenes" class="on">好戲</button><button data-l="threads">故事線</button></div>
<div id="scenePane"><div class="row"><button id="bestRun">▶ 只看好戲</button> <label><input id="bestOnly" type="checkbox" checked> 只列最好看的</label></div><ul id="scenes"></ul></div>
<div id="threadPane" style="display:none"><ul id="threads"></ul></div></section>
<section id="thread"></section>
<section><div id="tabs"><button data-tab="overview">總覽</button><button data-tab="who">他是誰</button><button data-tab="now">現在</button><button data-tab="life">人生</button><button data-tab="psyche">心理</button>
<button data-tab="rel">關係</button><button data-tab="know">知道什麼</button><button data-tab="bio">傳記</button></div><div id="who"></div></section>
</div></div>
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
