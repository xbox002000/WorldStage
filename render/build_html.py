"""Scene Spec -> one HyperFrames project per scene. Pure function of the spec: same spec, same HTML.

    python render/build_html.py --spec out/scenes.json --outdir render/projects
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

W, H = 1920, 1080
MAP_X0, MAP_X1, MAP_Y0, MAP_Y1 = 260, 1660, 250, 800
NODE_R = 62
TITLE_SECONDS = 2.0
END_SECONDS = 1.0
MOVE_SECONDS = 0.7

ZOOM = {"wide": 1.0, "two_shot": 1.35, "medium": 1.3, "close_up": 1.7, "insert": 1.6}
PUSH_IN = 0.12  # extra zoom over the shot for slow_push_in
OFFSETS = {"left": (-85, -135), "right": (85, -135)}  # above the place label; captions own the bottom
BACKGROUND_SLOTS = [(0, -240), (-190, -215), (190, -215), (-260, -100), (260, -100)]

EMOTION_ZH = {
    "warm": "溫暖", "happy": "開心", "calm": "平靜", "distant": "疏離", "hurt": "受傷",
    "angry": "憤怒", "tense": "緊張", "shocked": "震驚", "uneasy": "不安",
}
WEATHER_ZH = {"clear": "晴", "cloudy": "多雲", "rain": "雨", "fog": "霧"}
WEATHER_TINT = {"clear": ("#000000", 0.0), "cloudy": ("#8a94a3", 0.10), "rain": ("#2c4a78", 0.20), "fog": ("#d8dde6", 0.16)}
EMOTION_RING = {
    "warm": "#f2b866", "happy": "#f2d066", "calm": "#7fb8c9", "distant": "#8f98a8", "hurt": "#6f8fd6",
    "angry": "#e5534b", "tense": "#e08a3c", "shocked": "#c86bd1", "uneasy": "#b5a36a",
}


def caption(shot: dict) -> str:
    chars = shot["characters"]
    by_role = {c["role"]: c["name"] for c in chars}
    a = by_role.get("actor", "")
    b = by_role.get("target") or by_role.get("victim") or ""
    if shot["event_type"] == "steal":
        prop = shot["props"][0]["name"] if shot["props"] else "東西"
        return f"{a} 拿走了 {b} 的{prop}"
    action = next((c["action"] for c in chars if c["role"] == "actor"), "talk")
    return {
        "chat_warmly": f"{a} 親切地和 {b} 聊天",
        "talk": f"{a} 和 {b} 閒聊",
        "speak_coldly": f"{a} 冷淡地回應 {b}",
        "confront": f"{a} 當面質問 {b}",
    }.get(action, f"{a} 對 {b} 說話")


def avatar_color(person_id: str) -> str:
    hue = int(hashlib.md5(person_id.encode()).hexdigest()[:6], 16) % 360
    return f"hsl({hue}, 55%, 52%)"


def clock_tint(clock: str) -> tuple[str, float]:
    hour = int(clock[:2])
    if hour < 6 or hour >= 20:
        return "#0b1330", 0.45
    if hour >= 17:
        return "#c2703a", 0.16
    return "#000000", 0.0


def build_plan(scene: dict, world_map: dict) -> dict:
    locs = world_map["locations"]
    xs, ys = [l["x"] for l in locs], [l["y"] for l in locs]
    sx = (MAP_X1 - MAP_X0) / ((max(xs) - min(xs)) or 1)
    sy = (MAP_Y1 - MAP_Y0) / ((max(ys) - min(ys)) or 1)
    pos = {l["id"]: (round(MAP_X0 + (l["x"] - min(xs)) * sx), round(MAP_Y0 + (l["y"] - min(ys)) * sy)) for l in locs}

    shots, t = [], TITLE_SECONDS
    for s in scene["shots"]:
        kind, move = s["camera"]["shot_type"], s["camera"]["movement"]
        zoom = ZOOM[kind]
        end_zoom = zoom + (PUSH_IN if move == "slow_push_in" else 0.0)
        px, py = pos[s["location"]["id"]]
        cam = lambda z: {"scale": round(z, 3), "x": round(W / 2 - z * px, 1), "y": round(H / 2 - z * py, 1)}
        tint = clock_tint(s["time"]["clock"])
        people, bg = [], 0
        for c in s["characters"]:
            if c["position"] in OFFSETS:
                dx, dy = OFFSETS[c["position"]]
            else:
                dx, dy = BACKGROUND_SLOTS[bg % len(BACKGROUND_SLOTS)]
                bg += 1
            people.append({"id": c["id"], "x": px + dx, "y": py + dy, "emotion": EMOTION_ZH.get(c["emotion"], c["emotion"]),
                           "ring": EMOTION_RING.get(c["emotion"], "#ffffff")})
        shots.append({
            "start": round(t, 3), "duration": s["duration_seconds"], "cam": cam(zoom), "cam_end": cam(end_zoom),
            "people": people, "caption": caption(s), "thought": s.get("motivation") or "",
            "time": f"第 {s['time']['day']} 天  {s['time']['clock']}", "place": s["location"]["name"],
            "weather": WEATHER_ZH.get(s["weather"], s["weather"]), "weather_tint": WEATHER_TINT[s["weather"]],
            "night_tint": tint, "flip": bool(s["trust_flipped"]),
        })
        t += s["duration_seconds"]
    everyone = scene["assets"]["characters"]
    return {
        "title": scene["title"], "subtitle": f"第 {scene['shots'][0]['time']['day']} 天起",
        "total": round(t + END_SECONDS, 3), "move": MOVE_SECONDS, "title_seconds": TITLE_SECONDS,
        "nodes": [{"id": l["id"], "name": l["name"], "x": pos[l["id"]][0], "y": pos[l["id"]][1]} for l in locs],
        "edges": [[pos[a], pos[b]] for a, b in world_map["edges"]],
        "people": [{"id": pid, "name": info["name"], "initial": info["name"][-1], "color": avatar_color(pid)}
                   for pid, info in everyone.items()],
        "shots": shots,
    }


TEMPLATE = """<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=%(W)d, height=%(H)d" />
<script src="gsap.min.js"></script>
<style>
  @font-face { font-family: "WorldCJK"; src: local("Microsoft JhengHei"), local("微軟正黑體"); font-weight: 400; }
  @font-face { font-family: "WorldCJK"; src: local("Microsoft JhengHei Bold"), local("Microsoft JhengHei"); font-weight: 700; }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  html, body { width: %(W)dpx; height: %(H)dpx; overflow: hidden; background: #0d1117; }
  #root { position: relative; width: %(W)dpx; height: %(H)dpx; overflow: hidden;
    font-family: "WorldCJK", sans-serif; color: #f2f4f8; }
  #world { position: absolute; left: 0; top: 0; width: %(W)dpx; height: %(H)dpx; transform-origin: 0 0; opacity: 0; }
  #edges { position: absolute; left: 0; top: 0; width: %(W)dpx; height: %(H)dpx; }
  .node { position: absolute; width: %(D)dpx; height: %(D)dpx; margin: -%(R)dpx 0 0 -%(R)dpx; border-radius: 50%%;
    background: #1b2330; border: 3px solid #39465a; display: flex; align-items: center; justify-content: center;
    font-size: 26px; color: #9fb0c8; }
  .node.active { border-color: #f2d066; color: #fff; background: #26324a; }
  .avatar { position: absolute; z-index: 5; width: 84px; height: 84px; margin: -42px 0 0 -42px; border-radius: 50%%;
    display: flex; align-items: center; justify-content: center; font-size: 38px; font-weight: 700; color: #fff;
    border: 5px solid #fff; opacity: 0; }
  .avatar .name { position: absolute; top: 88px; font-size: 22px; font-weight: 600; white-space: nowrap; text-shadow: 0 2px 6px #000; }
  .avatar .emo { position: absolute; top: -34px; font-size: 20px; padding: 2px 10px; border-radius: 12px; background: rgba(0,0,0,.6); white-space: nowrap; }
  .tint { position: absolute; inset: 0; pointer-events: none; opacity: 0; }
  #hud-top { position: absolute; left: 60px; top: 44px; font-size: 40px; font-weight: 700; text-shadow: 0 2px 8px #000; opacity: 0; }
  #hud-top small { display: block; font-size: 24px; font-weight: 400; color: #c9d3e3; margin-top: 6px; }
  .cap { position: absolute; left: 0; right: 0; bottom: 120px; text-align: center; opacity: 0; }
  .cap .line { display: inline-block; font-size: 46px; font-weight: 700; padding: 10px 34px; border-radius: 14px; background: rgba(8,10,16,.72); }
  .cap .thought { margin-top: 14px; font-size: 30px; font-style: italic; color: #cfd8e8; text-shadow: 0 2px 8px #000; }
  #title { position: absolute; inset: 0; background: #0d1117; display: flex; flex-direction: column; align-items: center; justify-content: center; }
  #title h1 { font-size: 110px; letter-spacing: .04em; }
  #title p { margin-top: 24px; font-size: 38px; color: #9fb0c8; }
  #fade { position: absolute; inset: 0; background: #000; opacity: 0; }
</style>
</head>
<body>
<div id="root" data-composition-id="main" data-start="0" data-duration="%(total)s" data-width="%(W)d" data-height="%(H)d">
  <div id="stage">
    <div id="world" data-layout-allow-overflow><svg id="edges" viewBox="0 0 %(W)d %(H)d"></svg></div>
    <div id="weather" class="tint"></div>
    <div id="night" class="tint"></div>
    <div id="hud-top"><span id="hud-time"></span><small id="hud-place"></small></div>
    <div id="captions"></div>
    <div id="title"><h1></h1><p></p></div>
    <div id="fade"></div>
  </div>
</div>
<script>
const PLAN = %(plan)s;
window.__timelines = window.__timelines || {};
const world = document.getElementById("world");
const svg = document.getElementById("edges");
const NS = "http://www.w3.org/2000/svg";

for (const [a, b] of PLAN.edges) {
  const l = document.createElementNS(NS, "line");
  l.setAttribute("x1", a[0]); l.setAttribute("y1", a[1]); l.setAttribute("x2", b[0]); l.setAttribute("y2", b[1]);
  l.setAttribute("stroke", "#2c3648"); l.setAttribute("stroke-width", "4");
  svg.appendChild(l);
}
const nodeEl = {};
for (const n of PLAN.nodes) {
  const d = document.createElement("div");
  d.className = "node"; d.textContent = n.name; d.style.left = n.x + "px"; d.style.top = n.y + "px";
  world.appendChild(d); nodeEl[n.id] = d;
}
const avatarEl = {};
for (const p of PLAN.people) {
  const d = document.createElement("div");
  d.className = "avatar"; d.style.background = p.color; d.textContent = p.initial;
  d.innerHTML += '<span class="emo"></span><span class="name">' + p.name + "</span>";
  world.appendChild(d); avatarEl[p.id] = d;
}
const capHost = document.getElementById("captions");
PLAN.shots.forEach((s, i) => {
  const c = document.createElement("div");
  c.className = "cap"; c.id = "cap" + i;
  c.innerHTML = '<div class="line"></div>' + (s.thought ? '<div class="thought"></div>' : "");
  c.querySelector(".line").textContent = s.caption;
  if (s.thought) c.querySelector(".thought").textContent = "「" + s.thought + "」";
  capHost.appendChild(c);
});
document.querySelector("#title h1").textContent = PLAN.title;
document.querySelector("#title p").textContent = PLAN.subtitle;

const tl = gsap.timeline({ paused: true });
const M = PLAN.move;
tl.set("#world", PLAN.shots[0].cam, 0);
tl.to("#world", { opacity: 1, duration: 0.4 }, PLAN.title_seconds - 0.4);
tl.to("#title", { opacity: 0, duration: 0.4 }, PLAN.title_seconds - 0.4);
tl.to("#hud-top", { opacity: 1, duration: 0.4 }, PLAN.title_seconds);

const seen = {};
let activeNode = null;
PLAN.shots.forEach((s, i) => {
  const t = s.start;
  tl.fromTo("#world", i === 0 ? s.cam : {}, { ...s.cam, duration: i === 0 ? 0.01 : M, ease: "power2.inOut", immediateRender: false }, t);
  tl.to("#world", { ...s.cam_end, duration: Math.max(0.1, s.duration - M), ease: "none" }, t + M);
  tl.call(() => { document.getElementById("hud-time").textContent = s.time; document.getElementById("hud-place").textContent = s.place + "  ·  " + s.weather; }, null, t);
  tl.to("#weather", { backgroundColor: s.weather_tint[0], opacity: s.weather_tint[1], duration: M }, t);
  tl.to("#night", { backgroundColor: s.night_tint[0], opacity: s.night_tint[1], duration: M }, t);
  const here = new Set(s.people.map(p => p.id));
  for (const p of PLAN.people) {
    const el = avatarEl[p.id];
    if (here.has(p.id)) {
      const cur = s.people.find(q => q.id === p.id);
      if (!seen[p.id]) { tl.set(el, { x: cur.x, y: cur.y, left: 0, top: 0 }, t); seen[p.id] = true; }
      tl.to(el, { x: cur.x, y: cur.y, opacity: 1, duration: M, ease: "power2.inOut" }, t);
      tl.call(() => { const e = el.querySelector(".emo"); e.textContent = cur.emotion; e.style.border = "2px solid " + cur.ring; el.style.borderColor = cur.ring; }, null, t);
    } else if (seen[p.id]) {
      tl.to(el, { opacity: 0, duration: 0.3 }, t);
    }
  }
  tl.to("#cap" + i, { opacity: 1, duration: 0.3 }, t + 0.3);
  tl.to("#cap" + i, { opacity: 0, duration: 0.3 }, t + s.duration - 0.3);
  if (s.flip) tl.fromTo("#fade", { opacity: 0 }, { opacity: 0.35, duration: 0.15, yoyo: true, repeat: 1 }, t + M);
});
tl.to("#fade", { opacity: 1, duration: 0.8 }, PLAN.total - 0.9);
window.__timelines["main"] = tl;
tl.seek(0);
</script>
</body>
</html>
"""


def render_html(plan: dict) -> str:
    return TEMPLATE % {
        "W": W, "H": H, "D": NODE_R * 2, "R": NODE_R, "total": plan["total"],
        "plan": json.dumps(plan, ensure_ascii=False, sort_keys=True),
    }


def build_projects(spec: dict, outdir: Path, gsap: Path) -> list[Path]:
    made = []
    for scene in spec["scenes"]:
        proj = outdir / scene["scene_id"]
        proj.mkdir(parents=True, exist_ok=True)
        (proj / "index.html").write_text(render_html(build_plan(scene, spec["map"])), encoding="utf-8")
        (proj / "meta.json").write_text(json.dumps({"id": scene["scene_id"], "name": scene["title"]}), encoding="utf-8")
        shutil.copyfile(gsap, proj / "gsap.min.js")
        made.append(proj)
    return made


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", default="out/scenes.json")
    ap.add_argument("--outdir", default="render/projects")
    ap.add_argument("--gsap", default="render/node_modules/gsap/dist/gsap.min.js")
    args = ap.parse_args()
    spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    for p in build_projects(spec, Path(args.outdir), Path(args.gsap)):
        print("built", p)


if __name__ == "__main__":
    main()
