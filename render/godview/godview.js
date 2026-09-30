// God View: the world playing on its own clock, watched from above or through anyone's eyes. It reads a world save
// (runtime/godview.py) and draws it with the presentation runtime's world and cast; it cannot change anything.
// LIVE asks channel/live.py to run the simulation on (the only writer) and loads the new save.
import * as THREE from "three";
import { start, toThree } from "./presentation.js";
import { holder, pose, sample } from "./runtime_rule.js";

const $ = s => document.querySelector(s);
const params = new URLSearchParams(location.search);
const doc = await (await fetch("world.json?" + Date.now())).json();
const PANEL = 380;
const W = Math.max(480, innerWidth - PANEL), H = innerHeight - 64;
const rt = await start(doc, { host: $("#view"), width: W, height: H, version: null, pass: "rgb" });
const { camera, figs, things, scene, renderer } = rt;
const people = doc.people, names = Object.fromEntries(doc.entities.map(e => [e.id, e.name || e.id]));
const placeName = Object.fromEntries(doc.places.map(p => [p.id, p.name]));
const MOVING = ["walk", "turn", "rise", "settle", "lift", "fall"];
const busy = doc.actions.map(a => [a.t, Math.max(a.end, a.t + 0.5)]).concat(doc.tracks.map(k => [k.approach, k.complete + 0.5]))
  .sort((a, b) => a[0] - b[0]);
const sight = doc.geometry.filter(g => g.collision.blocks_sight && g.h >= 1.2 && (g.z || 0) < 1.0);

const state = { t: +(params.get("t") || 0) || doc.t0 + 8 * 3600, speed: 60, playing: true, skip: true, mode: "god",
                who: params.get("who") || "", place: doc.places[0].id, orbit: { yaw: -0.8, pitch: 0.9, dist: 22 } };

// -- what a body could see now: the same rule as runtime/perception.py (range, field of view, walls and trees) ---------
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
function placeOf(id, t) { const e = doc.entities.find(x => x.id === id); let k = e.keys[0]; for (const kk of e.keys) if (kk[0] <= t) k = kk; else break; return k[1]; }
function sees(who, id, t) {
  const me = sample(doc, who, t), it = sample(doc, id, t);
  if (!me || !it || placeOf(who, t) !== placeOf(id, t) || pose(doc, who, t) === "offstage") return false;
  const dog = (people[who] || {}).species === "dog";
  const d = Math.hypot(it[0] - me[0], it[1] - me[1]);
  if (dog && doc.entities.find(x => x.id === id).kind === "thing" && d <= 6) return true;  // smelt
  if (d > (dog ? 8 : 14)) return false;
  const off = Math.abs(((Math.atan2(it[1] - me[1], it[0] - me[0]) * 180 / Math.PI - me[2] + 540) % 360) - 180);
  if (d > 0.3 && off > (dog ? 125 : 110)) return false;
  return !sight.some(g => g.place === placeOf(who, t) && seg([me[0], me[1]], [it[0], it[1]], g));
}

// -- step functions over the save's timelines --------------------------------------------------------------------------
const at = (series, t) => { let v = series && series.length ? series[0][1] : null; for (const s of series || []) if (s[0] <= t) v = s[1]; else break; return v; };
function doing(id, t) {
  const a = doc.actions.filter(x => x.actor === id && x.t <= t && t <= x.end + 0.3).pop();
  const words = { walk_to: "走向", reach: "伸手拿", sniff: "嗅", face: "轉向", enter: "走進", exit: "離開" };
  const why = { "a place to be": "要待的地方", "the way out": "出口", "going on": "別處" };
  if (a) return `${words[a.kind] || a.kind} ${names[a.target] || placeName[a.target] || why[a.target] || a.target}`;
  const ps = pose(doc, id, t);
  return { sit: "坐著", stand: "站著", offstage: "不在任何地方", walk: "走路" }[ps] || ps;
}
function clock(t) {
  const day = Math.floor(t / 86400), s = t - day * 86400;
  const hh = String(Math.floor(s / 3600)).padStart(2, "0"), mm = String(Math.floor(s % 3600 / 60)).padStart(2, "0");
  return `第 ${day} 天 ${hh}:${mm}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
}

// -- cameras: god (orbit a place), follow someone, through someone's eyes, free ----------------------------------------
const NEUTRAL = { performances: [], t_start: 0, t_end: 1, hidden: [], relation: "frontal", focal: "" };
function aimCamera(t) {
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
    const o = state.orbit, c = toThree(place.offset + 6, 4, 0);
    camera.position.set(c.x + o.dist * Math.cos(o.pitch) * Math.cos(o.yaw), o.dist * Math.sin(o.pitch),
                        c.z + o.dist * Math.cos(o.pitch) * Math.sin(o.yaw));
    camera.lookAt(c);
    camera.fov = 45;
  }
  camera.updateProjectionMatrix();
}

// -- the inspector -------------------------------------------------------------------------------------------------------
function inspect(t) {
  const id = state.who, p = people[id];
  if (!p) { $("#who").innerHTML = `<p class="hint">點一個人（或狗）看他現在想什麼。</p>`; return; }
  const tl = p.timeline, place = at(tl.location_id, t);
  const goals = {};
  for (const g of p.goals) if (g[0] <= t) goals[g[1]] = g;
  const goalRows = Object.values(goals).filter(g => ["active", "formed", "blocked"].includes(g[5]))
    .map(g => `<li>${g[2]}${g[3] ? "：" + g[3] : ""}${g[4] ? "（" + g[4] + "）" : ""} <span class="dim">${g[5]}</span></li>`).join("");
  const trust = Object.entries(p.trust).map(([o, s]) => [o, at(s, t)]).filter(([, v]) => v !== null)
    .sort((a, b) => Math.abs(b[1]) - Math.abs(a[1])).slice(0, 4)
    .map(([o, v]) => `<li>${names[o] || o} <b class="${v < 0 ? "neg" : "pos"}">${v.toFixed(2)}</b></li>`).join("");
  const mem = p.memories.filter(m => m[0] <= t).slice(-4).reverse()
    .map(m => `<li>${m[1]} <span class="dim">${Math.round(m[2] * 100)}%${m[3] === "told_by" ? " · 聽" + m[4] + "說" : m[3] === "inference" ? " · 推測" : ""}</span></li>`).join("");
  const holds = Object.keys(things).filter(o => holder(doc, o, t) === id).map(o => names[o] || o).join("、") || "—";
  const seen = doc.entities.filter(e => e.id !== id && pose(doc, e.id, t) !== "offstage" && e.kind !== "thing" && sees(id, e.id, t)).map(e => e.name).join("、") || "—";
  const seenThings = doc.entities.filter(e => e.kind === "thing" && !holder(doc, e.id, t) && pose(doc, e.id, t) === "on_floor" && sees(id, e.id, t)).map(e => e.name).join("、") || "—";
  const last = doc.events.filter(e => e.t <= t && e.who.includes(id)).pop();
  $("#who").innerHTML = `<h2>${p.name}${p.species !== "human" ? "（" + p.species + "）" : ""}</h2>
    <p class="dim">${p.life_goal || ""}</p>
    <table><tr><td>在</td><td>${placeName[place] || "—"}</td></tr><tr><td>正在</td><td>${doing(id, t)}</td></tr>
    <tr><td>情緒</td><td>${at(tl.emotion, t) || "—"}</td></tr>
    <tr><td>飢餓／體力</td><td>${at(tl.hunger, t) ?? "—"} / ${at(tl.energy, t) ?? "—"}</td></tr>
    <tr><td>錢</td><td>${at(tl.money_cents, t) != null ? (at(tl.money_cents, t) / 100).toFixed(0) + " 元" : "—"}</td></tr>
    <tr><td>手上</td><td>${holds}</td></tr><tr><td>看得見</td><td>${seen}</td></tr><tr><td>看見的東西</td><td>${seenThings}</td></tr></table>
    <h3>目標</h3><ul>${goalRows || "<li class=dim>—</li>"}</ul>
    <h3>信任</h3><ul>${trust || "<li class=dim>—</li>"}</ul>
    <h3>記得</h3><ul>${mem || "<li class=dim>—</li>"}</ul>
    <h3>最近一次行動</h3><p>${last ? `${clock(last.t)} ${last.caption}${last.why ? `<br><span class="dim">因為：${last.why}</span>` : ""}` : "—"}</p>`;
}
function log(t) {
  const rows = doc.events.filter(e => e.t <= t && e.importance >= 0.1).slice(-7).reverse();
  $("#log").innerHTML = rows.map(e => `<li data-t="${e.t}"><span class="dim">${clock(e.t).slice(-8)}</span> ${placeName[e.place] || ""} · ${e.caption}</li>`).join("");
}

// -- controls ------------------------------------------------------------------------------------------------------------
for (const s of [1, 10, 60, 600]) {
  const b = document.createElement("button");
  b.textContent = `×${s}`; b.onclick = () => { state.speed = s; }; $("#speeds").appendChild(b);
}
$("#play").onclick = () => { state.playing = !state.playing; };
$("#back").onclick = () => { state.t = Math.max(doc.t0, state.t - 600); };
$("#skip").onchange = e => { state.skip = e.target.checked; };
$("#mode").onchange = e => { state.mode = e.target.value; };
for (const p of doc.places) { const o = document.createElement("option"); o.value = p.id; o.textContent = p.name; $("#place").appendChild(o); }
$("#place").onchange = e => { state.place = e.target.value; state.mode = "god"; $("#mode").value = "god"; };
$("#log").onclick = e => { const li = e.target.closest("li"); if (li) state.t = +li.dataset.t - 2; };
$("#live").onclick = async () => {
  $("#live").textContent = "世界運轉中…"; $("#live").disabled = true;
  try {
    const r = await fetch("advance?days=1", { method: "POST" });
    const j = await r.json();
    location.search = `?t=${state.t}&who=${state.who}&live=${j.last_day}`;
  } catch (err) { $("#live").textContent = "LIVE 需要 channel/live.py"; }
};
let drag = null;
renderer.domElement.addEventListener("mousedown", e => { drag = [e.clientX, e.clientY, false]; });
addEventListener("mouseup", e => {
  if (drag && !drag[2]) {  // a click: who is under the cursor?
    const r = renderer.domElement.getBoundingClientRect();
    const ray = new THREE.Raycaster();
    ray.setFromCamera(new THREE.Vector2((e.clientX - r.left) / r.width * 2 - 1, -(e.clientY - r.top) / r.height * 2 + 1), camera);
    const hits = ray.intersectObjects(Object.values(figs).map(f => f.root), true);
    if (hits.length) {
      let o = hits[0].object;
      const id = Object.keys(figs).find(k => { let x = o; while (x) { if (x === figs[k].root) return true; x = x.parent; } return false; });
      if (id) state.who = id;
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
addEventListener("keydown", e => { if (e.key === " ") state.playing = !state.playing; });

function nextBusy(t) {
  for (const [a, b] of busy) { if (b >= t) return a <= t ? t : a; }
  return doc.t1;
}
let last = performance.now();
function loop(now) {
  const dt = Math.min(0.1, (now - last) / 1000); last = now;
  if (state.playing) {
    state.t += dt * state.speed;
    if (state.skip) { const n = nextBusy(state.t); if (n - state.t > 3) state.t = n - 1; }  // nothing moves: skip ahead
    if (state.t > doc.t1) { state.t = doc.t1; state.playing = false; }
  }
  rt.poseWorld(state.t, NEUTRAL);
  if (state.who && figs[state.who] && state.mode !== "god") state.place = placeOf(state.who, state.t) || state.place;
  aimCamera(state.t);
  renderer.render(scene, camera);
  $("#clock").textContent = `${clock(state.t)}   ${state.playing ? "▶" : "⏸"} ×${state.speed}`;
  if (Math.floor(now / 250) !== Math.floor((now - dt * 1000) / 250)) {
    try { inspect(state.t); log(state.t); } catch (err) { console.error("inspector", err); }
  }
  requestAnimationFrame(loop);
}
window.__god = { state, rt, doc, inspect, log };  // for inspection; it offers no way to change the world
inspect(state.t); log(state.t);
requestAnimationFrame(loop);
