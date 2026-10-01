// God View: the world playing on its own clock, and the Observatory around it. The world is the main picture; the
// Story Observatory (how each story grew) and the Character Observatory (who each person is, and why) sit under it.
// It reads a world save (runtime/godview.py, with narrative/observatory.py's read models); it cannot change anything.
// LIVE asks channel/live.py to run the simulation on (the only writer) and loads the new save.
import * as THREE from "three";
import { start, toThree } from "./presentation.js";
import { holder, pose, sample } from "./runtime_rule.js";

const $ = s => document.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const params = new URLSearchParams(location.search);
const doc = await (await fetch("world.json?" + Date.now())).json();
const obs = doc.observatory || { threads: [], characters: {} };
const view = $("#view");
const W = view.clientWidth, H = view.clientHeight;
const rt = await start(doc, { host: view, width: W, height: H, version: null, pass: "rgb" });
const { camera, figs, things, scene, renderer } = rt;
const people = doc.people, names = Object.fromEntries(doc.entities.map(e => [e.id, e.name || e.id]));
for (const p of doc.places) names[p.id] = p.name;
const placeName = Object.fromEntries(doc.places.map(p => [p.id, p.name]));
const busy = doc.actions.map(a => [a.t, Math.max(a.end, a.t + 0.5)]).concat(doc.tracks.map(k => [k.approach, k.complete + 0.5]))
  .sort((a, b) => a[0] - b[0]);
const sight = doc.geometry.filter(g => g.collision.blocks_sight && g.h >= 1.2 && (g.z || 0) < 1.0);

const state = { t: +(params.get("t") || 0) || doc.t0 + 8 * 3600, speed: 60, playing: true, skip: true, mode: "god",
                who: params.get("who") || "", thing: "", place: doc.places[0].id, thread: params.get("thread") || "",
                tab: "now", walls: true, top: false, follow: null,
                orbit: { yaw: -0.8, pitch: 0.9, dist: 22 } };

// -- what a body could see now: the same rule as runtime/perception.py --------------------------------------------------
function seg(a, b, g) {
  const box = [g.x - g.w / 2, g.x + g.w / 2, g.y - g.d / 2, g.y + g.d / 2];
  let t0 = 0, t1 = 1;
  for (let i = 0; i < 2; i++) {
    const d = b[i] - a[i], lo = box[2 * i], hi = box[2 * i + 1];
    if (Math.abs(d) < 1e-9) { if (a[i] < lo || a[i] > hi) return false; continue; }
    let ta = (lo - a[i]) / d, tb = (hi - a[i]) / d;
    if (ta > tb) [ta, tb] = [tb, ta];
    t0 = Math.max(t0, ta); t1 = Math.min(t1, tb);
    if (t0 > t1) return false;
  }
  return t1 > 0.02 && t0 < 0.98;
}
const byId = Object.fromEntries(doc.entities.map(e => [e.id, e]));
function placeOf(id, t) { const e = byId[id]; if (!e) return ""; let k = e.keys[0]; for (const kk of e.keys) if (kk[0] <= t) k = kk; else break; return k[1]; }
function sees(who, id, t) {
  const me = sample(doc, who, t), it = sample(doc, id, t);
  if (!me || !it || placeOf(who, t) !== placeOf(id, t) || pose(doc, who, t) === "offstage") return false;
  const dog = (people[who] || {}).species === "dog";
  const d = Math.hypot(it[0] - me[0], it[1] - me[1]);
  if (dog && byId[id].kind === "thing" && d <= 6) return true;
  if (d > (dog ? 8 : 14)) return false;
  const off = Math.abs(((Math.atan2(it[1] - me[1], it[0] - me[0]) * 180 / Math.PI - me[2] + 540) % 360) - 180);
  if (d > 0.3 && off > (dog ? 125 : 110)) return false;
  return !sight.some(g => g.place === placeOf(who, t) && seg([me[0], me[1]], [it[0], it[1]], g));
}
const at = (series, t) => { let v = series && series.length ? series[0][1] : null; for (const s of series || []) if (s[0] <= t) v = s[1]; else break; return v; };
function doing(id, t) {
  const a = doc.actions.filter(x => x.actor === id && x.t <= t && t <= x.end + 0.3).pop();
  const words = { walk_to: "走向", reach: "伸手拿", sniff: "嗅", face: "轉向", enter: "走進", exit: "離開" };
  const why = { "a place to be": "要待的地方", "the way out": "出口", "going on": "別處", "to bed": "床位" };
  if (a) return `${words[a.kind] || a.kind} ${names[a.target] || why[a.target] || a.target}`;
  return { sit: "坐著", stand: "站著", offstage: "不在任何地方", walk: "走路" }[pose(doc, id, t)] || pose(doc, id, t);
}
function clock(t) {
  const day = Math.floor(t / 86400), s = t - day * 86400;
  return `第 ${day} 天 ${String(Math.floor(s / 3600)).padStart(2, "0")}:${String(Math.floor(s % 3600 / 60)).padStart(2, "0")}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
}
const inSave = t => t >= doc.t0 - 1 && t <= doc.t1;
function jump(t, place) {  // go to a moment (only inside the save: earlier days are in the Observatory, not on stage)
  if (!inSave(t)) { flash(`第 ${Math.floor(t / 86400)} 天不在這份存檔的回放範圍內（第 ${doc.first_day}–${doc.last_day} 天）`); return; }
  state.t = t - 2; if (place) state.place = place; state.playing = false;
}
function flash(msg) { const f = $("#flash"); f.textContent = msg; f.style.opacity = 1; setTimeout(() => { f.style.opacity = 0; }, 2600); }

// -- overlays on the world: names, the selected person's trail, event pulses, the selected story's people -------------
const labels = {};
for (const e of doc.entities) {
  if (e.kind === "thing") continue;
  const d = document.createElement("div");
  d.className = "label"; d.textContent = (e.kind === "animal" ? "🐕 " : "") + (e.name || e.id);
  d.onclick = () => select(e.id);
  $("#labels").appendChild(d);
  labels[e.id] = d;
}
const trail = new THREE.Line(new THREE.BufferGeometry(), new THREE.LineBasicMaterial({ color: 0xff5a36 }));
trail.frustumCulled = false;
scene.add(trail);
const rings = [];
function ring(color) {
  const m = new THREE.Mesh(new THREE.RingGeometry(0.35, 0.48, 32), new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.85, side: THREE.DoubleSide }));
  m.rotation.x = -Math.PI / 2; scene.add(m); return m;
}
const pulses = [];
// how people feel, next to their names (people.emotion on the world's clock)
const FEEL = { angry: "😠", hurt: "😢", ashamed: "😞", uneasy: "😟", scared: "😨", embarrassed: "😳", happy: "😊", relieved: "😌" };
// what is being said now: a bubble over the speaker (lines are a read model, narrative/lines.py), the other's answer after
const TONE_CLASS = { hostile: "hot", retort: "hot", side: "hot", accuse: "hot", confront: "hot", storm_off: "hot",
                     cold: "cool", rebuff: "cool", deny: "cool", warm: "warm", chat: "warm", soothe: "warm",
                     apologize: "warm", comfort: "warm" };
const spoken = doc.events.filter(e => e.line && e.say).sort((a, b) => a.say[0] - b.say[0]);
const bubbles = [];
function bubble() { const d = document.createElement("div"); d.className = "bubble"; $("#labels").appendChild(d); bubbles.push(d); return d; }
function headAt(id, lift) {
  const f = figs[id];
  if (!f || !f.root.visible) return null;
  const v = f.root.position.clone().add(new THREE.Vector3(0, (f.kind === "animal" ? 0.8 : 2.05) + lift, 0)).project(camera);
  return v.z > 1 || Math.abs(v.x) > 1.1 || Math.abs(v.y) > 1.1 ? null : [(v.x + 1) / 2 * W, (1 - v.y) / 2 * H];
}
function speech(t) {
  const now = [];
  for (const e of spoken) {
    if (e.say[0] > t) break;
    const hold = Math.max(e.say[1], e.say[0] + 2.2) + 0.8;  // linger a little so a line can be read at 1x
    if (t > hold) continue;
    now.push([e.actor, e.line.say, e.line.stance]);
    if (e.line.answer && t > (e.say[0] + e.say[1]) / 2) now.push([e.target, e.line.answer, "answer"]);
  }
  const last = {};
  for (const n of now) last[n[0]] = n;  // one bubble a head: the latest line
  let k = 0;
  for (const [who, text, stance] of Object.values(last)) {
    const xy = headAt(who, 0.55);
    if (!xy) continue;
    const d = bubbles[k] || bubble(); k++;
    d.style.display = "block"; d.style.left = `${xy[0]}px`; d.style.top = `${xy[1]}px`;
    d.className = "bubble " + (TONE_CLASS[stance] || "");
    d.textContent = text;
  }
  for (; k < bubbles.length; k++) bubbles[k].style.display = "none";
}
function overlays(t) {
  const pos = new THREE.Vector3();
  for (const [id, d] of Object.entries(labels)) {
    const f = figs[id];
    if (!f || !f.root.visible) { d.style.display = "none"; continue; }
    pos.copy(f.root.position).add(new THREE.Vector3(0, f.kind === "animal" ? 0.8 : 2.05, 0));
    const dist = pos.distanceTo(camera.position), v = pos.clone().project(camera);
    if (v.z > 1 || Math.abs(v.x) > 1.1 || Math.abs(v.y) > 1.1) { d.style.display = "none"; continue; }
    d.style.display = "block";
    d.style.left = `${(v.x + 1) / 2 * W}px`; d.style.top = `${(1 - v.y) / 2 * H}px`;
    const e = byId[id];
    const mood = at(((people[id] || {}).timeline || {}).emotion, t) || "", feel = FEEL[mood] || "";
    d.dataset.feel = mood;
    d.textContent = dist > 30 ? (e.name || id).slice(0, 1) + feel : (e.kind === "animal" ? "🐕 " : "") + (e.name || id) + (feel ? " " + feel : "");  // semantic level of detail
    d.classList.toggle("sel", id === state.who);
    d.classList.toggle("story", storyPeople().includes(id));
  }
  // the selected person's last 90 seconds of world time
  if (state.who && figs[state.who]) {
    const pts = [];
    for (let k = 90; k >= 0; k -= 1.5) {
      const s = sample(doc, state.who, t - k);
      if (s && placeOf(state.who, t - k) === placeOf(state.who, t)) pts.push(toThree(s[0], s[1], 0.05));
    }
    trail.geometry.setFromPoints(pts); trail.visible = pts.length > 1;
  } else trail.visible = false;
  // who the selected story is about
  const sp = storyPeople();
  while (rings.length < sp.length) rings.push(ring(0xffc233));
  rings.forEach((r, i) => {
    const f = figs[sp[i]];
    r.visible = !!(i < sp.length && f && f.root.visible);
    if (r.visible) r.position.copy(f.root.position).setY(0.03);
  });
  // events of the last 20 seconds of world time: a pulse where they happened
  for (const p of pulses) scene.remove(p);
  pulses.length = 0;
  for (const e of doc.events) {
    if (e.t > t || e.t < t - 20 || e.importance < 0.2) continue;
    const who = e.who.find(w => figs[w] && figs[w].root.visible);
    if (!who) continue;
    const k = (t - e.t) / 20, m = ring(0x36b8ff);
    m.scale.setScalar(1 + 2.5 * k); m.material.opacity = 0.8 * (1 - k);
    m.position.copy(figs[who].root.position).setY(0.04);
    pulses.push(m);
  }
  speech(t);
}

// -- cameras ----------------------------------------------------------------------------------------------------------
const NEUTRAL = { performances: [], t_start: 0, t_end: 1, hidden: [], relation: "frontal", focal: "" };
function aimCamera() {
  const place = doc.places.find(p => p.id === state.place);
  const who = state.who && figs[state.who] ? figs[state.who] : null;
  if (state.mode === "follow" && who) {
    const f = new THREE.Vector3(1, 0, 0).applyQuaternion(who.root.quaternion);
    camera.position.copy(who.root.position).addScaledVector(f, -3.2).add(new THREE.Vector3(0, who.kind === "animal" ? 1.2 : 2.2, 0));
    camera.lookAt(who.root.position.clone().add(new THREE.Vector3(0, who.kind === "animal" ? 0.4 : 1.2, 0)));
    camera.fov = 55;
  } else if (state.mode === "eyes" && who) {
    const f = new THREE.Vector3(1, 0, 0).applyQuaternion(who.root.quaternion);
    camera.position.copy(who.root.position).add(new THREE.Vector3(0, who.eye, 0)).addScaledVector(f, 0.15);
    camera.lookAt(camera.position.clone().addScaledVector(f, 3).add(new THREE.Vector3(0, -0.15, 0)));
    camera.fov = who.kind === "animal" ? 75 : 62;
    who.root.visible = false;
  } else {
    const o = state.orbit, fc = state.follow && state.follow.centre && state.follow.centre.length ? state.follow.centre : null;
    let c = toThree(place.offset + 8, 5, 0);
    if (fc) { c = new THREE.Vector3(); fc.forEach(x => c.add(x.root.position)); c.multiplyScalar(1 / fc.length); c.y = 0.8; }
    const pitch = state.top ? 1.52 : o.pitch, dist = state.top ? o.dist * 3.2 : fc ? Math.min(o.dist, 9) : o.dist;  // top: nearly orthographic
    camera.position.set(c.x + dist * Math.cos(pitch) * Math.cos(o.yaw), dist * Math.sin(pitch), c.z + dist * Math.cos(pitch) * Math.sin(o.yaw));
    camera.lookAt(c);
    camera.fov = state.top ? 16 : 45;
  }
  camera.updateProjectionMatrix();
}
function setWalls(on) {
  scene.traverse(o => { if (o.userData && o.userData.geometry && ["wall", "window"].includes(o.userData.kind)) o.visible = on; });
}

// -- scenes: moments worth watching (narrative/scenes.py), best first or in order; each one plays at 1x -----------------
const scenes = (doc.scenes || []).filter(s => s.start != null);
const HEAT = ["💬", "💬", "❄️", "🔥"];
function hhmm(m) { return `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`; }
function sceneList() {
  const best = $("#bestOnly").checked;
  const list = best ? [...scenes].sort((a, b) => b.score - a.score).slice(0, 30) : scenes;
  $("#scenes").innerHTML = list.map(s => `<li data-id="${s.id}"><span>${HEAT[s.heat] || "💬"}</span> <b>${esc(s.title)}</b><br>
    <span class="dim">第 ${s.day} 天 ${hhmm(s.minute)} · ${esc(placeName[s.place] || "")} · ${s.turns} 句 · 戲分 ${s.score}</span></li>`).join("")
    || `<li class="dim">這份存檔裡沒有值得看的場面。</li>`;
}
function playScenes(list) { state.follow = { scenes: list, i: 0, until: 0 }; }
$("#scenes").onclick = e => { const li = e.target.closest("li[data-id]"); if (li) playScenes([scenes.find(s => s.id === +li.dataset.id)]); };
$("#bestOnly").onchange = sceneList;
$("#bestRun").onclick = () => playScenes([...scenes].sort((a, b) => b.score - a.score).slice(0, 12).sort((a, b) => a.start - b.start));
$("#ltabs").onclick = e => {
  const b = e.target.closest("button"); if (!b) return;
  document.querySelectorAll("#ltabs button").forEach(x => x.classList.toggle("on", x === b));
  $("#scenePane").style.display = b.dataset.l === "scenes" ? "" : "none";
  $("#threadPane").style.display = b.dataset.l === "threads" ? "" : "none";
};

// -- the Story Observatory ---------------------------------------------------------------------------------------------
const STATUS = { seeded: ["🌱", "萌芽"], forming: ["🟢", "成形中"], active: ["🟢", "進行中"], escalating: ["🟠", "升溫"],
                 climax: ["🔥", "高潮"], dormant: ["🟡", "休眠"], resolved: ["⚪", "已解決"], revived: ["🔵", "復甦"] };
const threadById = Object.fromEntries(obs.threads.map(t => [t.id, t]));
function storyPeople() { const th = threadById[state.thread]; return th ? th.primary : []; }
function threadList() {
  $("#threads").innerHTML = obs.threads.map(th => {
    const [dot, word] = STATUS[th.status] || ["·", th.status];
    return `<li data-id="${esc(th.id)}" class="${th.id === state.thread ? "on" : ""}"><span>${dot}</span>
      <b>${esc(th.question)}</b><br><span class="dim">${word} · 第 ${th.first_day}–${th.last_day} 天 · ${th.events.length} 事件 ·
      張力 ${th.tension} · 誤會 ${th.asymmetry}${th.cross.length ? " · 交叉 " + th.cross.length : ""}</span>
      <i class="bar"><i style="width:${Math.round(th.tension * 100)}%"></i></i></li>`;
  }).join("");
}
function consequence(e) {
  const bits = [];
  for (const x of e.trust) bits.push(`${esc(names[x.from] || x.from)}→${esc(names[x.to] || x.to)} 信任 ${x.before} → <b class="${x.after < x.before ? "neg" : "pos"}">${x.after}</b>`);
  for (const x of e.feelings) bits.push(`${esc(names[x.who] || x.who)} ${esc(x.before)} → ${esc(x.after)}`);
  for (const x of e.goals) bits.push(`${esc(names[x.who] || x.who)} 目標 ${esc(x.before)} → ${esc(x.after)}`);
  for (const x of e.hands) bits.push(`${esc(names[x.thing] || x.thing)}：${esc(names[x.from] || "地上")} → ${esc(names[x.to] || "地上")}`);
  const know = e.knowledge.map(k => `<li>${esc(names[k.who] || k.who)} 認為「${esc(k.believes)}」<span class="dim">${Math.round(k.confidence * 100)}%${k.source === "told_by" ? " · 聽" + esc(names[k.source_id] || k.source_id) + "說" : k.source === "inference" ? " · 推測" : ""}</span></li>`).join("");
  return (bits.length ? `<div class="cons">${bits.join("<br>")}</div>` : "") + (know ? `<ul class="know">${know}</ul>` : "");
}
function threadDetail() {
  const th = threadById[state.thread];
  if (!th) { $("#thread").innerHTML = `<p class="dim">點一條故事線，看它怎麼長出來。</p>`; return; }
  const [dot, word] = STATUS[th.status] || ["·", th.status];
  const days = {};
  for (const e of th.events) (days[e.day] = days[e.day] || []).push(e);
  const timeline = Object.entries(days).map(([d, es]) => `<div class="day"><div class="dlabel">第 ${d} 天</div>${es.map(e => `
      <div class="node" data-t="${e.t}" data-place="${esc(e.place)}"><b>${esc(e.caption)}</b> <span class="dim">${esc(placeName[e.place] || "")} · #${e.id}${e.cause ? " ← #" + e.cause : ""}</span>
      ${e.why ? `<div class="dim">因為：${esc(e.why)}</div>` : ""}${consequence(e)}</div>`).join("")}</div>`).join("");
  const w = th.why;
  $("#thread").innerHTML = `<h3>${dot} ${esc(th.question)}</h3>
    <div class="why"><b>為什麼有這個故事</b><br>起點：第 ${th.first_day} 天（#${w.origin}）· 狀態：${word}<br>
    主要驅動：${esc(w.drivers.join("、") || "—")}<br>主角：${th.primary.map(p => esc(names[p] || p)).join("、")}${w.affected.length ? " · 受波及：" + w.affected.map(p => esc(names[p] || p)).join("、") : ""}<br>
    張力 ${th.tension} · 資訊不對等 ${th.asymmetry} · 最近一次有意義的事件 #${w.last}<br>
    潛在壓力：${esc(w.pressure.join("；") || "—")}${th.cross.length ? "<br>交叉：" + th.cross.map(c => `<a data-thread="${esc(c)}">${esc((threadById[c] || {}).question || c)}</a>`).join("、") : ""}</div>
    <button id="followStory">▶ 跟隨故事</button> <span class="dim">只在存檔的回放範圍內（第 ${doc.first_day}–${doc.last_day} 天）跳轉</span>
    <div class="timeline">${timeline}</div>`;
  $("#followStory").onclick = () => { state.follow = { list: th.events.filter(e => inSave(e.t)), i: 0, until: 0 }; if (!state.follow.list.length) flash("這條故事線的事件都不在回放範圍內"); };
}
$("#threads").onclick = e => { const li = e.target.closest("li"); if (li) { state.thread = li.dataset.id; threadList(); threadDetail(); } };
$("#thread").onclick = e => {
  const a = e.target.closest("a[data-thread]"); if (a) { state.thread = a.dataset.thread; threadList(); threadDetail(); return; }
  const n = e.target.closest(".node"); if (n) jump(+n.dataset.t, n.dataset.place);
};

// -- the Character Observatory ---------------------------------------------------------------------------------------
const TRUTH = { "TRUE": ["✓", "pos", "屬實"], "FALSE": ["✗", "neg", "錯的"], "PARTIAL": ["≈", "dim", "部分"], "UNKNOWN": ["?", "dim", "無從得知"] };
function spark(hist, lo = -1, hi = 1) {
  const pts = (hist || []).filter(h => h[1] != null);
  if (pts.length < 2) return "";
  const t0 = pts[1][0] || 0, t1 = pts[pts.length - 1][0] || 1;
  const xy = pts.map((h, i) => `${i === 0 ? 0 : ((h[0] - t0) / Math.max(1, t1 - t0) * 118 + 1).toFixed(1)},${(22 - (h[1] - lo) / (hi - lo) * 20).toFixed(1)}`);
  return `<svg width="120" height="24" class="spark"><polyline points="${xy.join(" ")}" fill="none" stroke="currentColor" stroke-width="1.5"/></svg>`;
}
const bar = (v, lo = 0, hi = 1, mark = null) => `<i class="bar"><i style="width:${Math.round((v - lo) / (hi - lo) * 100)}%"></i>${mark != null ? `<u style="left:${Math.round((mark - lo) / (hi - lo) * 100)}%"></u>` : ""}</i>`;
function select(id) { state.who = id; state.thing = ""; renderCharacter(); }
function renderCharacter() {
  const t = state.t, id = state.who, life = obs.characters[id], p = people[id];
  document.querySelectorAll("#tabs button").forEach(b => b.classList.toggle("on", b.dataset.tab === state.tab));
  if (state.thing) { renderThing(); return; }
  if (!life || !p) { $("#who").innerHTML = `<p class="dim">點一個人（或狗）：他是誰，為什麼變成現在這樣。點地上的東西：誰知道它的真相。</p>`; return; }
  const tl = p.timeline, name = esc(life.identity.name);
  let html = `<h2>${name}${life.identity.species !== "human" ? "（" + esc(life.identity.species) + "）" : ""}</h2>`;
  if (state.tab === "overview") {
    const o = life.overview || {};
    const VW = { truth: "真相", loyalty: "忠誠", security: "安穩", belonging: "歸屬", ambition: "野心", freedom: "自由", family: "家人", fairness: "公平", revenge: "報復" };
    const FW = { trust: "信任", affection: "好感" };
    const relLine = r => `${esc(r.name)} <span class="${r.since_start < 0 ? "neg" : "pos"}">${r.since_start > 0 ? "↑" : "↓"}${Math.abs(r.since_start)}</span>`;
    html += `<table><tr><td>現在</td><td>${esc(FEEL[o.emotion] || "")} ${esc(o.emotion || "—")}${Object.entries(o.life || {}).map(([d, v]) => ` · ${esc(d)}：${Object.entries(v).filter(([k]) => k !== "喜歡" && k !== "討厭").map(([k, x]) => `${esc(k)} ${esc(x)}`).join(" ")}`).join("")}</td></tr>
      <tr><td>正在想</td><td>${(o.thinking || []).map(esc).join("<br>") || "—"}</td></tr>
      <tr><td>在乎</td><td>${(o.cares || []).map(k => esc(VW[k] || k)).join(" ＞ ") || "—"}</td></tr>
      <tr><td>害怕</td><td>${(o.fears || []).map(esc).join("；") || "—"}</td></tr>
      <tr><td>最近改變</td><td>${(o.recent || []).map(r => `對${esc(r.name)}的${FW[r.field] || r.field} <span class="${r.delta < 0 ? "neg" : "pos"}">${r.delta > 0 ? "↑" : "↓"}${Math.abs(r.delta)}</span>`).join("<br>") || "—"}</td></tr>
      <tr><td>重要記憶</td><td>${(o.memories || []).map(m => `<span class="dim">第 ${m.day} 天</span> ${esc(m.belief)}`).join("<br>") || "—"}</td></tr>
      <tr><td>關係</td><td>${(o.closer || []).map(relLine).join("、") || ""}${o.apart && o.apart.length ? "<br>" + o.apart.map(relLine).join("、") : ""}</td></tr>
      <tr><td>人生弧</td><td><b>${esc(o.arc_text || "—")}</b><br><span class="dim">${(o.arc || []).map(s => `第 ${s.from_day} 天起 ${esc(s.word)}`).join(" · ")}</span></td></tr></table>`;
  } else if (state.tab === "who") {
    const pf = life.identity.profile;
    if (!pf) html += `<p class="dim">這個世界沒有他的角色設定。</p>`;
    else {
      const kv = o => Object.entries(o || {}).filter(([, v]) => v !== "" && v != null).map(([k, v]) => `<tr><td>${esc(k)}</td><td>${esc(typeof v === "number" ? v : v)}</td></tr>`).join("");
      html += `<p>${pf.age} 歲${pf.occupation ? " · " + esc(pf.occupation.role) : ""} · ${esc(Object.values(pf.background || {}).join("，"))}</p>
        <h3>人生的問題</h3><p><b>${esc(pf.core["人生的問題"] || "—")}</b></p><table>${kv(pf.core)}</table>
        <h3>喜歡 / 討厭</h3><p>${esc(pf.interests.join("、") || "—")}<br><span class="neg">${esc(pf.dislikes.join("、") || "—")}</span></p>
        <h3>看重</h3><p>${Object.entries(pf.values).map(([k, v]) => `${esc(k)} ${v}`).join(" · ")}</p>
        <h3>習慣</h3><ul>${pf.habits.map(h => `<li>${esc(h)}</li>`).join("")}</ul>
        <h3>待人</h3><table>${kv(pf.social)}</table>
        <h3>目標</h3><p>一生：${esc(pf.life_goal)}<br>這一陣子：${esc(pf.season_goal)}</p>
        ${Object.entries(pf.life || {}).map(([d, o]) => `<h3>${esc(d)}</h3><table>${kv(o)}</table>`).join("")}`;
    }
  } else if (state.tab === "now") {
    const holds = Object.keys(things).filter(o => holder(doc, o, t) === id).map(o => names[o] || o).join("、") || "—";
    const seen = doc.entities.filter(e => e.id !== id && e.kind !== "thing" && pose(doc, e.id, t) !== "offstage" && sees(id, e.id, t)).map(e => e.name).join("、") || "—";
    const goals = {};
    for (const g of p.goals) if (g[0] <= t) goals[g[1]] = g;
    html += `<table><tr><td>在</td><td>${esc(placeName[at(tl.location_id, t)] || "—")}</td></tr><tr><td>正在</td><td>${esc(doing(id, t))}</td></tr>
      <tr><td>情緒</td><td>${esc(at(tl.emotion, t) || "—")}</td></tr><tr><td>手上</td><td>${esc(holds)}</td></tr><tr><td>看得見</td><td>${esc(seen)}</td></tr>
      <tr><td>目標</td><td>${Object.values(goals).filter(g => ["active", "formed", "blocked"].includes(g[5])).map(g => esc(g[2] + (g[3] ? "：" + g[3] : "") + (g[4] ? "（" + g[4] + "）" : ""))).join("<br>") || "—"}</td></tr></table>`;
  } else if (state.tab === "life") {
    const ms = life.milestones, d0 = 0, d1 = Math.max(1, doc.last_day);
    html += `<p class="dim">${esc(life.identity.life_goal || "")} · 住在${esc(life.identity.home)}</p>
      <div class="lifeline">${ms.map(m => `<a class="dot k-${m.kind}" style="left:${(m.day - d0) / (d1 - d0) * 96 + 2}%" data-t="${m.t}" data-place="${esc(m.place)}" title="第 ${m.day} 天 ${esc(m.label)}：${esc(m.caption)}"></a>`).join("")}</div>
      <ul class="ms">${ms.map(m => `<li data-t="${m.t}" data-place="${esc(m.place)}"><span class="dim">第 ${m.day} 天</span> <b>${esc(m.label)}</b> ${esc(m.caption)}${m.note && !m.caption.includes(m.note) ? `<span class="dim">（${esc(m.note)}）</span>` : ""}</li>`).join("")}</ul>`;
  } else if (state.tab === "psyche") {
    html += `<h3>特質（慢）</h3>${Object.values(life.traits).map(x => `<div class="row">${esc(x.name)} ${bar(x.now, 0, 1, x.rest)} ${x.now}</div>`).join("")}
      <h3>價值（很慢）</h3>${Object.values(life.values).map(x => `<div class="row">${esc(x.name)} ${bar(x.now, 0, 1, x.start)} ${x.now}</div>`).join("")}
      <h3>自我認知</h3><ul>${life.self_model.filter(s => s.held).map(s => `<li>「${esc(s.text)}」</li>`).join("") || "<li class=dim>還沒有形成</li>"}</ul>
      <h3>疤痕</h3><ul>${life.scars.map(s => `<li>${esc(s.domain)} 強度 ${s.intensity} · 癒合下限 ${s.floor}${s.origin_event ? " · 始於 #" + s.origin_event : ""}</li>`).join("") || "<li class=dim>沒有</li>"}</ul>
      <h3>先天氣質（幾乎不變）</h3><p class="dim">${Object.entries(life.identity.temperament).map(([k, v]) => `${esc(k)} ${v}`).join(" · ")}</p>`;
  } else if (state.tab === "rel") {
    html += life.relationships.map(r => `<div class="row"><a data-who="${esc(r.to)}">${esc(r.name)}</a> 信任 <b class="${r.trust < 0 ? "neg" : "pos"}">${r.trust}</b> 好感 ${r.affection} 畏懼 ${r.fear} ${spark(r.history)}</div>`).join("");
  } else if (state.tab === "know") {
    html += `<ul class="know">${life.knowledge.map(k => { const [m, c, w] = TRUTH[k.truth] || ["", "dim", ""]; return `<li><b class="${c}">${m}</b> 「${esc(k.believes)}」<span class="dim">${Math.round(k.confidence * 100)}%${k.source === "told_by" ? " · 聽" + esc(k.source_id) + "說" : k.source === "inference" ? " · 推測" : ""}${w ? " · 世界真相：" + w : ""}</span></li>`; }).join("")}</ul>`;
  } else if (state.tab === "bio") {
    html += `<p class="dim">傳記是從事件編譯出來的讀取模型，不是真相；每一段都能點回它所根據的事件。</p>` +
      life.biography.map(b => `<p class="bio" data-event="${b.events[0] || ""}">${esc(b.text)} <span class="dim">${b.events.map(e => "#" + e).join(" ")}</span></p>`).join("");
  }
  $("#who").innerHTML = html;
}
function renderThing() {
  const id = state.thing, t = state.t, h = holder(doc, id, t);
  const beliefs = [];
  for (const [pid, life] of Object.entries(obs.characters))
    for (const k of life.knowledge) if (k.object === id) beliefs.push([pid, k]);
  $("#who").innerHTML = `<h2>💼 ${esc(names[id] || id)}</h2><h3>世界真相</h3><p>${h ? "現在在 " + esc(names[h] || h) + " 手上" : pose(doc, id, t) === "on_floor" ? "躺在" + esc(placeName[placeOf(id, t)] || "") + "的地上" : "不在任何地方"}</p>
    <h3>誰知道什麼</h3><ul class="know">${beliefs.map(([pid, k]) => { const [m, c] = TRUTH[k.truth] || ["", "dim"]; return `<li><b class="${c}">${m}</b> ${esc(names[pid] || pid)}：「${esc(k.believes)}」<span class="dim">${Math.round(k.confidence * 100)}%</span></li>`; }).join("") || "<li class=dim>沒有人對它有任何看法</li>"}</ul>`;
}
$("#tabs").onclick = e => { const b = e.target.closest("button"); if (b) { state.tab = b.dataset.tab; state.thing = ""; renderCharacter(); } };
$("#who").onclick = e => {
  const a = e.target.closest("a[data-who]"); if (a) { select(a.dataset.who); return; }
  const n = e.target.closest("[data-t]"); if (n) { jump(+n.dataset.t, n.dataset.place); return; }
  const b = e.target.closest(".bio"); if (b && b.dataset.event) {
    const ev = doc.events.find(x => x.id === +b.dataset.event) || obs.threads.flatMap(th => th.events).find(x => x.id === +b.dataset.event);
    if (ev) jump(ev.t, ev.place); else flash(`事件 #${b.dataset.event} 不在這份存檔的回放範圍內`);
  }
};

// -- controls ----------------------------------------------------------------------------------------------------------
for (const s of [1, 10, 60, 600]) { const b = document.createElement("button"); b.textContent = `×${s}`; b.onclick = () => { state.speed = s; }; $("#speeds").appendChild(b); }
$("#play").onclick = () => { state.playing = !state.playing; };
$("#back").onclick = () => { state.t = Math.max(doc.t0, state.t - 600); };
$("#skip").onchange = e => { state.skip = e.target.checked; };
$("#mode").onchange = e => { state.mode = e.target.value; };
$("#walls").onchange = e => { state.walls = e.target.checked; setWalls(state.walls); };
$("#top").onchange = e => { state.top = e.target.checked; };
for (const p of doc.places) { const o = document.createElement("option"); o.value = p.id; o.textContent = p.name; $("#place").appendChild(o); }
$("#place").onchange = e => { state.place = e.target.value; state.mode = "god"; $("#mode").value = "god"; };
$("#live").onclick = async () => {
  $("#live").textContent = "世界運轉中…"; $("#live").disabled = true;
  try { const j = await (await fetch("advance?days=1", { method: "POST" })).json(); location.search = `?t=${state.t}&who=${state.who}&thread=${encodeURIComponent(state.thread)}&live=${j.last_day}`; }
  catch (err) { $("#live").textContent = "LIVE 需要 channel/live.py"; }
};
let drag = null;
renderer.domElement.addEventListener("mousedown", e => { drag = [e.clientX, e.clientY, false]; });
addEventListener("mouseup", e => {
  if (drag && !drag[2] && e.target === renderer.domElement) {  // a click: who (or what) is under the cursor?
    const r = renderer.domElement.getBoundingClientRect(), ray = new THREE.Raycaster();
    ray.setFromCamera(new THREE.Vector2((e.clientX - r.left) / r.width * 2 - 1, -(e.clientY - r.top) / r.height * 2 + 1), camera);
    const roots = [...Object.entries(figs).map(([k, f]) => [k, f.root, "who"]), ...Object.entries(things).map(([k, n]) => [k, n, "thing"])];
    const hits = ray.intersectObjects(roots.map(x => x[1]), true);
    if (hits.length) {
      const hit = roots.find(([, root]) => { let x = hits[0].object; while (x) { if (x === root) return true; x = x.parent; } return false; });
      if (hit && hit[2] === "who") select(hit[0]);
      else if (hit) { state.thing = hit[0]; renderCharacter(); }
    }
  }
  drag = null;
});
addEventListener("mousemove", e => {
  if (!drag) return;
  const dx = e.clientX - drag[0], dy = e.clientY - drag[1];
  if (Math.abs(dx) + Math.abs(dy) > 3) drag[2] = true;
  state.orbit.yaw += dx * 0.005; state.orbit.pitch = Math.min(1.45, Math.max(0.15, state.orbit.pitch + dy * 0.005));
  drag[0] = e.clientX; drag[1] = e.clientY;
});
renderer.domElement.addEventListener("wheel", e => { state.orbit.dist = Math.min(60, Math.max(4, state.orbit.dist * (1 + e.deltaY * 0.001))); });
addEventListener("keydown", e => { if (e.key === " " && e.target === document.body) { state.playing = !state.playing; e.preventDefault(); } });

function nextBusy(t) { for (const [a, b] of busy) if (b >= t) return a <= t ? t : a; return doc.t1; }
let last = performance.now(), lastPanel = 0;
function loop(now) {
  const dt = Math.min(0.1, (now - last) / 1000); last = now;
  const f = state.follow;
  if (f && f.scenes) {  // a scene, or the best scenes one after another: each from its first line to its last, at 1x
    const s = f.scenes[f.i];
    if (!f.until) {
      state.t = s.start - 2; state.place = s.place || state.place; state.speed = 1; state.playing = true;
      state.mode = "god"; $("#mode").value = "god"; f.until = 1; flash(`第 ${s.day} 天 ${hhmm(s.minute)} ${s.title}`);
      f.centre = s.people.map(p => figs[p]).filter(Boolean);  // the orbit looks at the people in the scene
    } else if (state.t > s.end + 2.5) { f.i++; f.until = 0; if (f.i >= f.scenes.length) state.follow = null; }
  } else if (f && f.list.length) {  // FOLLOW STORY: to each of the story's events in turn, a few seconds each, at 1x
    const e = f.list[f.i];
    if (!f.until) { state.t = e.t - 3; state.place = e.place || state.place; state.speed = 1; state.playing = true; f.until = now + 6000; flash(`${clock(e.t)} ${e.caption}`); }
    else if (now > f.until) { f.i++; f.until = 0; if (f.i >= f.list.length) state.follow = null; }
  }
  if (state.playing) {
    state.t += dt * state.speed;
    if (state.skip && !state.follow) { const n = nextBusy(state.t); if (n - state.t > 3) state.t = n - 1; }
    if (state.t > doc.t1) { state.t = doc.t1; state.playing = false; }
  }
  rt.poseWorld(state.t, NEUTRAL);
  if (state.who && figs[state.who] && state.mode !== "god") state.place = placeOf(state.who, state.t) || state.place;
  aimCamera();
  overlays(state.t);
  renderer.render(scene, camera);
  $("#clock").textContent = `${clock(state.t)}   ${state.playing ? "▶" : "⏸"} ×${state.speed}${state.follow ? (state.follow.scenes ? "  播放好戲中" : "  跟隨故事中") : ""}`;
  if (now - lastPanel > 400 && state.tab === "now") { lastPanel = now; try { renderCharacter(); } catch (err) { console.error(err); } }
  requestAnimationFrame(loop);
}
window.__god = { state, rt, doc, obs, select, renderCharacter, threadDetail };  // for inspection; no way to change the world
sceneList(); threadList(); threadDetail(); renderCharacter();
requestAnimationFrame(loop);
