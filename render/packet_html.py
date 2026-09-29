"""ProductionPacket -> one HyperFrames project. A pure function of the packet: same packet, same files."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from contracts.packet import ProductionPacket
from narrative.color import ink_for

NODE_R = 62
MOVE_SECONDS = 0.7
MAP_X = (0.14, 0.86)  # map area as a fraction of the canvas
MAP_Y = (0.24, 0.74)

ZOOM = {"wide": 1.0, "two_shot": 1.35, "medium": 1.3, "close_up": 1.7, "insert": 1.6}
PUSH_IN = 0.12  # extra zoom over the shot for slow_push_in
OFFSETS = {"left": (-85, -135), "right": (85, -135)}  # above the place label; captions own the bottom
BG_COLUMNS = (0, -1, 1, -2, 2)  # witnesses fill rows centre outwards, above the principals
BG_SPACING = 150
MAX_BACKGROUND = 6  # anyone beyond this is counted, not drawn
SAFE_WIDTH = 0.86  # share of the canvas width a row of witnesses may use


ROW_GAP = 175
FIRST_ROW = 240  # how far above the place the first row of onlookers stands
TOP_MARGIN = 100  # keep clear of the top of the frame (labels above heads, the HUD)


def per_row(canvas_width: int, zoom: float) -> int:
    """How many witnesses fit in one row at this zoom without leaving the frame."""
    return max(1, min(len(BG_COLUMNS), int(canvas_width * SAFE_WIDTH / zoom // BG_SPACING)))


def rows_available(canvas_height: int, zoom: float, scale: float = 1.0) -> int:
    """How many rows of onlookers fit above the place before they would leave the top of the frame."""
    reach = (canvas_height / 2 - TOP_MARGIN) / zoom / scale  # world units between the place and the safe top edge
    return max(1, 1 + int((reach - FIRST_ROW) // ROW_GAP)) if reach >= FIRST_ROW else 1


def background_slot(k: int, row_size: int = len(BG_COLUMNS)) -> tuple[int, int]:
    return BG_COLUMNS[k % row_size] * BG_SPACING, -FIRST_ROW - (k // row_size) * ROW_GAP

EMOTION_ZH = {
    "warm": "溫暖", "happy": "開心", "calm": "平靜", "distant": "疏離", "hurt": "受傷",
    "angry": "憤怒", "tense": "緊張", "shocked": "震驚", "uneasy": "不安",
    "curious": "好奇", "ashamed": "羞愧", "embarrassed": "尷尬",
}
WEATHER_ZH = {"clear": "晴", "cloudy": "多雲", "rain": "雨", "fog": "霧"}
WEATHER_TINT = {"clear": ("#000000", 0.0), "cloudy": ("#8a94a3", 0.10), "rain": ("#2c4a78", 0.20), "fog": ("#d8dde6", 0.16)}
TIME_TINT = {"night": ("#0b1330", 0.45), "dusk": ("#c2703a", 0.16), "day": ("#000000", 0.0)}
EMOTION_RING = {
    "warm": "#f2b866", "happy": "#f2d066", "calm": "#7fb8c9", "distant": "#8f98a8", "hurt": "#6f8fd6",
    "angry": "#e5534b", "tense": "#e08a3c", "shocked": "#c86bd1", "uneasy": "#b5a36a",
    "curious": "#6fc7a3", "ashamed": "#9a6f86", "embarrassed": "#d98fa0",
}


def _lock_value(lock: list[str], key: str) -> str:
    return next(v.split("=", 1)[1] for v in lock if v.startswith(key + "="))


def build_plan(packet: ProductionPacket) -> dict:
    W, H = packet.canvas.width, packet.canvas.height
    S = min(W, H) / 1080  # world-space distances scale with the canvas
    locs = packet.map.locations
    xs, ys = [l.x for l in locs], [l.y for l in locs]
    x0, x1, y0, y1 = MAP_X[0] * W, MAP_X[1] * W, MAP_Y[0] * H, MAP_Y[1] * H
    sx = (x1 - x0) / ((max(xs) - min(xs)) or 1)
    sy = (y1 - y0) / ((max(ys) - min(ys)) or 1)
    pos = {l.id: (round(x0 + (l.x - min(xs)) * sx), round(y0 + (l.y - min(ys)) * sy)) for l in locs}

    names = {c.id: c.name for s in packet.shots for c in s.characters}
    emotions: dict[str, list[dict]] = {}  # per person, the distinct feelings they show (one label element each)
    shots = []
    for s in packet.shots:
        zoom = ZOOM[s.camera.shot_type]
        end_zoom = zoom + (PUSH_IN if s.camera.movement == "slow_push_in" else 0.0)
        px, py = pos[s.location.id]
        cam = lambda z: {"scale": round(z, 3), "x": round(W / 2 - z * px, 1), "y": round(H / 2 - z * py, 1)}
        row_size = per_row(W, max(zoom, end_zoom))
        room = min(MAX_BACKGROUND, row_size * rows_available(H, max(zoom, end_zoom), S))
        people, bg, hidden = [], 0, 0
        for c in s.characters:
            background = c.position not in OFFSETS
            if background:
                if bg >= room:
                    hidden += 1
                    continue
                dx, dy = background_slot(bg, row_size)
                bg += 1
            else:
                dx, dy = OFFSETS[c.position]
            emotion, ring = EMOTION_ZH.get(c.emotion, c.emotion), EMOTION_RING.get(c.emotion, "#ffffff")
            people.append({"id": c.id, "x": round(px + dx * S), "y": round(py + dy * S), "bg": background,
                           "emotion": emotion, "ring": ring})
            if not background and all(e["text"] != emotion for e in emotions.setdefault(c.id, [])):
                emotions[c.id].append({"text": emotion, "ring": ring})
        shots.append({
            "start": s.start_seconds, "duration": s.duration_seconds, "cam": cam(zoom), "cam_end": cam(end_zoom),
            "people": people, "more": hidden, "caption": s.caption, "thought": s.thought or "",
            "time": f"第 {s.day} 天  {s.clock}", "place": s.location.name,
            "weather": WEATHER_ZH.get(s.lighting.weather, s.lighting.weather),
            "weather_tint": WEATHER_TINT[s.lighting.weather], "night_tint": TIME_TINT[s.lighting.time_of_day],
            "flip": s.trust_flipped,
        })
    return {
        "title": packet.episode.title, "subtitle": f"第 {packet.shots[0].day} 天起", "recap": packet.episode.recap,
        "total": packet.qa.total_seconds, "move": MOVE_SECONDS, "title_seconds": packet.episode.title_seconds,
        "node_r": round(NODE_R * S),
        "nodes": [{"id": l.id, "name": l.name, "x": pos[l.id][0], "y": pos[l.id][1]} for l in locs],
        "edges": [[pos[a], pos[b]] for a, b in packet.map.edges],
        "people": [{"id": pid, "name": names[pid], "initial": _lock_value(lock.identity_lock, "initial"),
                    "color": _lock_value(lock.identity_lock, "avatar_color"),
                    "ink": ink_for(_lock_value(lock.identity_lock, "avatar_color")), "emotions": emotions.get(pid, [])}
                   for pid, lock in sorted(packet.continuity_locks.characters.items()) if pid in names],
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
  #root { position: relative; width: %(W)dpx; height: %(H)dpx; overflow: hidden; font-family: "WorldCJK", sans-serif; color: #f2f4f8; }
  #world { position: absolute; left: 0; top: 0; width: %(W)dpx; height: %(H)dpx; transform-origin: 0 0; opacity: 0; }
  #edges { position: absolute; left: 0; top: 0; width: %(W)dpx; height: %(H)dpx; }
  .node { position: absolute; width: %(D)dpx; height: %(D)dpx; margin: -%(R)dpx 0 0 -%(R)dpx; border-radius: 50%%;
    background: #121924; border: 3px solid #4a5a72; display: flex; align-items: center; justify-content: center;
    font-size: 26px; color: #e2ebf7; }
  .avatar { position: absolute; z-index: 5; width: 84px; height: 84px; margin: -42px 0 0 -42px; border-radius: 50%%;
    display: flex; align-items: center; justify-content: center; font-size: 38px; font-weight: 700; color: #fff;
    border: 5px solid #fff; opacity: 0; }
  .avatar .name { position: absolute; top: 88px; font-size: 22px; font-weight: 600; white-space: nowrap; text-shadow: 0 2px 6px #000; color: #f2f4f8; }
  .avatar .emo { position: absolute; top: -34px; font-size: 20px; padding: 2px 10px; border-radius: 12px; background: rgba(0,0,0,.6); white-space: nowrap; color: #f2f4f8; }
  .tint { position: absolute; inset: 0; pointer-events: none; opacity: 0; }
  #hud-top { position: absolute; left: 48px; top: 44px; width: 60%%; height: 90px; font-size: 40px; font-weight: 700; text-shadow: 0 2px 8px #000; opacity: 0; }
  #hud-top .hud { position: absolute; left: 0; top: 0; opacity: 0; white-space: nowrap; }
  #hud-top small { display: block; font-size: 24px; font-weight: 400; color: #c9d3e3; margin-top: 6px; }
  .more { position: absolute; right: 40px; top: 52px; font-size: 26px; padding: 4px 16px; border-radius: 16px; background: rgba(0,0,0,.55); color: #cfd8e8; opacity: 0; }
  .cap { position: absolute; left: 24px; right: 24px; bottom: %(CAPB)dpx; text-align: center; opacity: 0; }
  .cap .line { display: inline-block; font-size: 46px; font-weight: 700; padding: 10px 34px; border-radius: 14px; background: rgba(8,10,16,.72); }
  .cap .thought { margin-top: 14px; font-size: 30px; font-style: italic; color: #cfd8e8; text-shadow: 0 2px 8px #000; }
  #title { position: absolute; inset: 0; background: #0d1117; display: flex; flex-direction: column; align-items: center; justify-content: center; }
  #title h1 { font-size: %(TITLE)dpx; letter-spacing: .04em; text-align: center; }
  #title p { margin-top: 24px; font-size: 38px; color: #9fb0c8; }
  #title p.recap { margin-top: 44px; max-width: 86%%; font-size: 34px; line-height: 1.5; color: #cfd8e8; text-align: center; }
  #fade { position: absolute; inset: 0; background: #000; opacity: 0; }
</style>
</head>
<body>
<div id="root" data-composition-id="main" data-start="0" data-duration="%(total)s" data-width="%(W)d" data-height="%(H)d">
  <div id="stage">
    <div id="world" data-layout-allow-overflow><svg id="edges" viewBox="0 0 %(W)d %(H)d"></svg></div>
    <div id="weather" class="tint"></div>
    <div id="night" class="tint"></div>
    <div id="hud-top"></div>
    <div id="crowd"></div>
    <div id="captions"></div>
    <div id="title"><h1></h1><p id="sub"></p><p id="recap" class="recap"></p></div>
    <div id="fade"></div>
  </div>
%(AUDIO)s</div>
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
for (const n of PLAN.nodes) {
  const d = document.createElement("div");
  d.className = "node"; d.textContent = n.name; d.style.left = n.x + "px"; d.style.top = n.y + "px";
  world.appendChild(d);
}
const avatarEl = {};
const emoEl = {};  // emoEl[person][feeling] = its label; only one is visible at a time
for (const p of PLAN.people) {
  const d = document.createElement("div");
  d.className = "avatar"; d.style.background = p.color; d.style.color = p.ink; d.textContent = p.initial;
  const name = document.createElement("span");
  name.className = "name"; name.textContent = p.name; d.appendChild(name);
  emoEl[p.id] = {};
  for (const e of p.emotions) {
    const s = document.createElement("span");
    s.className = "emo"; s.textContent = e.text; s.style.border = "2px solid " + e.ring; s.style.opacity = "0";
    d.appendChild(s); emoEl[p.id][e.text] = s;
  }
  world.appendChild(d); avatarEl[p.id] = d;
}
// Everything that changes per shot is its own element switched on and off with tl.set: the timeline can be seeked
// to any frame and always shows the right state (tl.call would not survive a seek).
const hudHost = document.getElementById("hud-top");
const crowdHost = document.getElementById("crowd");
const capHost = document.getElementById("captions");
PLAN.shots.forEach((s, i) => {
  const h = document.createElement("div");
  h.className = "hud"; h.id = "hud" + i; h.innerHTML = "<span></span><small></small>";
  h.children[0].textContent = s.time; h.children[1].textContent = s.place + "  ·  " + s.weather;
  hudHost.appendChild(h);
  const m = document.createElement("div");
  m.className = "more"; m.id = "more" + i; m.textContent = "另有 " + s.more + " 人在場";
  crowdHost.appendChild(m);
  const c = document.createElement("div");
  c.className = "cap"; c.id = "cap" + i;
  c.innerHTML = '<div class="line"></div>' + (s.thought ? '<div class="thought"></div>' : "");
  c.querySelector(".line").textContent = s.caption;
  if (s.thought) c.querySelector(".thought").textContent = "「" + s.thought + "」";
  capHost.appendChild(c);
});
document.querySelector("#title h1").textContent = PLAN.title;
document.getElementById("sub").textContent = PLAN.subtitle;
document.getElementById("recap").textContent = PLAN.recap ? "前情提要：" + PLAN.recap : "";

const tl = gsap.timeline({ paused: true });
const M = PLAN.move;
tl.set("#world", PLAN.shots[0].cam, 0);
tl.to("#world", { opacity: 1, duration: 0.4 }, PLAN.title_seconds - 0.4);
tl.to("#title", { opacity: 0, duration: 0.4 }, PLAN.title_seconds - 0.4);
tl.to("#hud-top", { opacity: 1, duration: 0.4 }, PLAN.title_seconds);

const seen = {};
const feeling = {};  // the label currently shown for each person
PLAN.shots.forEach((s, i) => {
  const t = s.start;
  tl.fromTo("#world", i === 0 ? s.cam : {}, { ...s.cam, duration: i === 0 ? 0.01 : M, ease: "power2.inOut", immediateRender: false }, t);
  tl.to("#world", { ...s.cam_end, duration: Math.max(0.1, s.duration - M), ease: "none" }, t + M);
  if (i) { tl.set("#hud" + (i - 1), { opacity: 0 }, t); tl.set("#more" + (i - 1), { opacity: 0 }, t); }
  tl.set("#hud" + i, { opacity: 1 }, t);
  if (s.more) tl.set("#more" + i, { opacity: 1 }, t);
  tl.to("#weather", { backgroundColor: s.weather_tint[0], opacity: s.weather_tint[1], duration: M }, t);
  tl.to("#night", { backgroundColor: s.night_tint[0], opacity: s.night_tint[1], duration: M }, t);
  const here = new Set(s.people.map(p => p.id));
  for (const p of PLAN.people) {
    const el = avatarEl[p.id];
    if (here.has(p.id)) {
      const cur = s.people.find(q => q.id === p.id);
      if (!seen[p.id]) { tl.set(el, { x: cur.x, y: cur.y, left: 0, top: 0 }, t); seen[p.id] = true; }
      tl.to(el, { x: cur.x, y: cur.y, opacity: 1, duration: M, ease: "power2.inOut" }, t);
      tl.set(el, { borderColor: cur.bg ? "#94a3b8" : cur.ring }, t);
      const want = cur.bg ? null : cur.emotion;  // onlookers carry no feeling label: it would only clutter a crowd
      if (feeling[p.id] !== want) {
        if (feeling[p.id]) tl.set(emoEl[p.id][feeling[p.id]], { opacity: 0 }, t);
        if (want) tl.set(emoEl[p.id][want], { opacity: 1 }, t);
        feeling[p.id] = want;
      }
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


AUDIO_TAG = ('  <audio id="score" src="assets/score.wav" data-start="0" data-duration="%s" data-volume="1" '
             'data-track-index="9"></audio>\n')


def render_html(packet: ProductionPacket, with_score: bool = False) -> str:
    plan = build_plan(packet)
    W, H = packet.canvas.width, packet.canvas.height
    portrait = H > W
    return TEMPLATE % {
        "W": W, "H": H, "D": plan["node_r"] * 2, "R": plan["node_r"], "total": plan["total"],
        "CAPB": 260 if portrait else 120, "TITLE": 96 if portrait else 110,
        "AUDIO": AUDIO_TAG % plan["total"] if with_score else "",
        "plan": json.dumps(plan, ensure_ascii=False, sort_keys=True),
    }


def to_srt(packet: ProductionPacket) -> str:
    def stamp(t: float) -> str:
        ms = round(t * 1000)
        return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"

    return "".join(f"{i}\n{stamp(c.start)} --> {stamp(c.end)}\n{c.text}\n\n" for i, c in enumerate(packet.subtitle_plan, 1))


def build_project(packet: ProductionPacket, outdir: Path, gsap: Path, score: bytes | None = None) -> Path:
    outdir.mkdir(parents=True, exist_ok=True)
    if score is not None:
        (outdir / "assets").mkdir(exist_ok=True)
        (outdir / "assets" / "score.wav").write_bytes(score)
    (outdir / "index.html").write_text(render_html(packet, with_score=score is not None), encoding="utf-8")
    (outdir / "meta.json").write_text(json.dumps({"id": packet.packet_hash[7:19], "name": packet.episode.title}, ensure_ascii=False), encoding="utf-8")
    (outdir / "subtitles.srt").write_text(to_srt(packet), encoding="utf-8")
    shutil.copyfile(gsap, outdir / "gsap.min.js")
    return outdir
