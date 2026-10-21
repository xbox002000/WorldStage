// Presentation Runtime (three.js): plays a scene written by runtime/stage.py. It is a view, never a second world:
// bodies go where runtime_rule.js says (the Python runtime's rule), feet land on the runtime's footfalls, hands reach
// the runtime's contact points, things are held by whoever the trace says, and the camera flies the trajectory
// runtime/camera.py solved. Nothing here can move a body, hand over a thing or change a shot.
//
// Coordinates: the runtime's (x right, y into the room, z up) are three.js (x, z up, -y), a proper rotation (0.1 was
// a mirror image). Yaw a (degrees, from +x towards +y) is rotation.y = a.
//
// One page, several ways to run it:
//   render   HyperFrames seeks a GSAP timeline; every frame is a pure function of the film time
//   sandbox  ?sandbox=1 in a browser: Space pause · ←/→ seek · 1/2/3 version · F free camera · L lens · R replay
//   passes   opts.pass: rgb | depth | normal | id | pose — the previs control signals for a video model
import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import * as SkeletonUtils from "three/addons/utils/SkeletonUtils.js";
import { attachment, cutAt, foot, holder, pose, progress, reachAt, sample, worldTime } from "./runtime_rule.js";

const UP = new THREE.Vector3(0, 1, 0);
const DEPTH = [0.3, 25];  // metres mapped to white .. black in the depth pass
const sanitize = n => n.replace(/[\[\]\.:\/]/g, "").replace(/\s/g, "_");
const V = (x, y, z) => new THREE.Vector3(x, y, z);
export const toThree = (x, y, z = 0) => V(x, z, -y);  // runtime -> three.js

export async function start(doc, opts) {
  const W = opts.width, H = opts.height, pass = opts.pass || "rgb";
  const renderer = new THREE.WebGLRenderer({ antialias: pass !== "id", preserveDrawingBuffer: true });
  renderer.setPixelRatio(1);
  renderer.setSize(W, H);
  renderer.shadowMap.enabled = pass === "rgb";
  // picture and id mask in sRGB (the mask's hex colours come out exactly); depth and normals as raw values
  renderer.outputColorSpace = pass === "rgb" || pass === "id" ? THREE.SRGBColorSpace : THREE.LinearSRGBColorSpace;
  opts.host.appendChild(renderer.domElement);
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(pass === "rgb" ? 0xb8d1e6 : pass === "normal" ? 0x8080ff : 0x000000);
  scene.add(new THREE.HemisphereLight(0xf2f4ff, 0x6a7a55, 1.1));
  const sun = new THREE.DirectionalLight(0xffffff, 2.2);
  sun.position.set(-8, 14, -6);
  sun.castShadow = true;
  sun.shadow.mapSize.set(2048, 2048);
  Object.assign(sun.shadow.camera, { left: -30, right: 70, top: 20, bottom: -20, far: 60 });
  scene.add(sun);
  const camera = new THREE.PerspectiveCamera(45, W / H, 0.05, 200);

  // -- pass materials: one set of meshes, drawn as picture, depth, normals or ids ---------------------------------
  const depthMat = new THREE.ShaderMaterial({
    uniforms: { near: { value: DEPTH[0] }, far: { value: DEPTH[1] } },
    vertexShader: `#include <common>
#include <skinning_pars_vertex>
varying float vz;
void main() {
#include <skinbase_vertex>
#include <begin_vertex>
#include <skinning_vertex>
#include <project_vertex>
  vz = -mvPosition.z;
}`,
    fragmentShader: `uniform float near; uniform float far; varying float vz;
void main() { float d = clamp((vz - near) / (far - near), 0.0, 1.0); gl_FragColor = vec4(vec3(1.0 - d), 1.0); }`,
  });
  const normalMat = new THREE.MeshNormalMaterial();
  const flat = new Map();
  const flatMat = hex => { if (!flat.has(hex)) flat.set(hex, new THREE.MeshBasicMaterial({ color: new THREE.Color(hex) })); return flat.get(hex); };
  function forPass(mesh, mask) {
    if (pass === "depth") mesh.material = depthMat;
    else if (pass === "normal") mesh.material = normalMat;
    else if (pass === "id" || pass === "pose") mesh.material = flatMat(pass === "id" ? mask : "#000000");
  }

  // -- the places, from the white-box layouts --------------------------------------------------------------------------
  const COLORS = { wall: 0xdad6ce, table: 0x8c613f, desk: 0x8c613f, chair: 0x6f5a48, tree: 0x4d8c4d, bench: 0x9a6b47,
                   counter: 0x80675a, bed: 0x7385b3, sofa: 0x8c7399, lamp: 0x4d4d52, window: 0xcfe6f5 };
  const setMask = doc.set_mask || { floor: "#202020" };
  for (const p of doc.places) {
    const ground = new THREE.Mesh(new THREE.BoxGeometry(24, 0.1, 18),
      new THREE.MeshStandardMaterial({ color: p.id === "park" ? 0x9ebd80 : 0xa88f74, roughness: 0.95 }));
    ground.position.copy(toThree(p.offset + 6, 4, -0.05));
    ground.receiveShadow = true;
    forPass(ground, setMask.floor);
    scene.add(ground);
  }
  for (const g of doc.geometry) {
    const h = Math.max(0.05, g.h);
    const m = new THREE.Mesh(new THREE.BoxGeometry(g.w, h, g.d),
      new THREE.MeshStandardMaterial({ color: COLORS[g.kind] ?? 0xb3b3b3, roughness: 0.9,
                                       transparent: g.kind === "window", opacity: g.kind === "window" ? 0.35 : 1 }));
    m.position.copy(toThree(g.x, g.y, (g.z || 0) + h / 2));
    m.rotation.y = THREE.MathUtils.degToRad(g.yaw || 0);
    m.castShadow = m.receiveShadow = true;
    if (g.kind === "door") m.visible = false;
    m.userData = { kind: g.kind, id: g.id, place: g.place, geometry: true };  // a view can hide walls to look in
    forPass(m, g.mask || "#606060");
    scene.add(m);
  }

  // -- the cast, from Blender --------------------------------------------------------------------------------------
  const loader = new GLTFLoader();
  const load = name => new Promise(ok => loader.load(`assets/${name}.glb`, ok, undefined, () => ok(null)));
  const assetNames = [...new Set(doc.entities.filter(e => e.kind === "thing").map(e => e.asset || "thing"))];
  const [personG, dogG, ...propG] = await Promise.all([load("person"), load("dog"), ...assetNames.map(load)]);
  const propOf = Object.fromEntries(assetNames.map((n, i) => [n, propG[i]]));
  const fallback = propOf.wallet || (await load("wallet"));
  const figs = {}, things = {};
  for (const e of doc.entities) {
    if (e.kind === "thing") {
      const t = SkeletonUtils.clone((propOf[e.asset] || fallback).scene);  // a skinned clone needs its own skeleton
      // a skinned mesh keeps the bounds of where it was built: without this it is culled once it is carried off
      t.traverse(o => { if (o.isMesh) { o.castShadow = true; o.frustumCulled = false; forPass(o, e.mask); } });
      scene.add(t);
      things[e.id] = t;
      continue;
    }
    const src = e.kind === "animal" ? dogG : personG;
    const root = SkeletonUtils.clone(src.scene);
    const bones = {};
    root.traverse(o => {
      if (o.isBone) bones[o.name] = o;
      if (o.isMesh) {
        o.castShadow = true;
        o.frustumCulled = false;
        if (o.material && e.kind === "person") {  // clothes in the person's own colour: nobody looks like anybody else
          const mats = Array.isArray(o.material) ? o.material : [o.material];
          o.material = mats.map(m => {
            if (m.name !== "cloth" && m.name !== "trousers") return m;
            const c = m.clone();
            if (m.name === "cloth") c.color.setHSL(e.hue / 360, 0.6, 0.52);
            else c.color.setHSL(((e.hue + 180) % 360) / 360, 0.25, 0.28);
            return c;
          });
          if (o.material.length === 1) o.material = o.material[0];
        }
        forPass(o, e.mask);
      }
    });
    root.updateMatrixWorld(true);
    const rest = {}, rq = new THREE.Quaternion();
    root.getWorldQuaternion(rq);
    for (const [n, b] of Object.entries(bones)) {
      const wq = new THREE.Quaternion();
      b.getWorldQuaternion(wq);
      rest[n] = { q: b.quaternion.clone(), p: b.position.clone(), world: rq.clone().invert().multiply(wq) };
    }
    const fig = { e, root, bones, rest, kind: e.kind, eye: e.kind === "animal" ? 0.47 : 1.6,
                  hand: bones[sanitize(e.kind === "animal" ? "mouth" : "hand.R")] };
    if (e.kind === "person") {  // limb lengths and effector offsets, measured on the rest pose
      const w = n => bones[sanitize(n)].getWorldPosition(V(0, 0, 0));
      const chain = (a, b, c, tip) => {
        const A = w(a), B = w(b), C = w(c);
        return { a: A.distanceTo(B), b: B.distanceTo(tip ? tip : C), tip: tip ? bones[sanitize(b)].worldToLocal(tip.clone()) : null };
      };
      const knee = w("shin.L");
      fig.leg = chain("thigh.L", "shin.L", "shin.L", knee.clone().add(V(0, -0.42, 0)));
      fig.arm = chain("upper_arm.R", "forearm.R", "hand.R", null);
      fig.hipH = w("hips").y;
      const head = bones.head;
      fig.face = { nose: head.worldToLocal(V(0.135, 1.67, 0)), eyeR: head.worldToLocal(V(0.118, 1.71, 0.045)),
                   eyeL: head.worldToLocal(V(0.118, 1.71, -0.045)), earR: head.worldToLocal(V(0, 1.68, 0.12)),
                   earL: head.worldToLocal(V(0, 1.68, -0.12)) };
      fig.handTip = bones[sanitize("hand.R")].worldToLocal(w("hand.R").add(V(0, -0.08, 0)));
    }
    scene.add(root);
    figs[e.id] = fig;
  }

  // -- bones ----------------------------------------------------------------------------------------------------------
  const tmpQ = new THREE.Quaternion(), tmpA = new THREE.Vector3();
  const SIDE = V(0, 0, 1), FWD = V(1, 0, 0);  // the body's own axes (it faces +x): SIDE is its left
  function turn(fig, name, axis, angle) {  // turn about an axis of the body, whatever the bone's own axes are
    const b = fig.bones[sanitize(name)];
    if (!b || !angle) return;
    tmpA.copy(axis).applyQuaternion(fig.rest[sanitize(name)].world.clone().invert());
    tmpQ.setFromAxisAngle(tmpA.normalize(), angle);
    b.quaternion.multiply(tmpQ);
  }
  function resetPose(fig) {
    for (const [n, b] of Object.entries(fig.bones)) { b.quaternion.copy(fig.rest[n].q); b.position.copy(fig.rest[n].p); }
  }
  // rotate a bone (in world space) so that `effector` (a world point it moves) points at `target`
  function aim(bone, effector, target, weight = 1) {
    const bp = bone.getWorldPosition(V(0, 0, 0));
    const from = effector.clone().sub(bp).normalize(), to = target.clone().sub(bp).normalize();
    if (from.lengthSq() < 1e-9 || to.lengthSq() < 1e-9) return;
    const q = new THREE.Quaternion().setFromUnitVectors(from, to);
    if (weight < 1) q.slerp(new THREE.Quaternion(), 1 - weight);
    const pw = bone.parent.getWorldQuaternion(new THREE.Quaternion());
    bone.quaternion.premultiply(pw.clone().invert().multiply(q).multiply(pw));
    bone.updateMatrixWorld(true);
  }
  // two-bone IK: put the end of upper->lower (lower's tip, or `tipOf` in lower's frame) on target, bending toward pole
  function ik(fig, upper, lower, tipOf, lens, target, pole) {
    const u = fig.bones[sanitize(upper)], l = fig.bones[sanitize(lower)];
    const H = u.getWorldPosition(V(0, 0, 0));
    const a = lens.a, b = lens.b;
    let d = target.clone().sub(H);
    const dist = THREE.MathUtils.clamp(d.length(), Math.abs(a - b) + 1e-3, a + b - 1e-3);
    d.normalize();
    const x = (a * a - b * b + dist * dist) / (2 * dist), h = Math.sqrt(Math.max(0, a * a - x * x));
    const perp = pole.clone().sub(d.clone().multiplyScalar(pole.dot(d))).normalize();
    const knee = H.clone().add(d.clone().multiplyScalar(x)).add(perp.multiplyScalar(h));
    aim(u, l.getWorldPosition(V(0, 0, 0)), knee);
    const tip = tipOf ? l.localToWorld(tipOf.clone()) : fig.bones[sanitize(lower.replace("forearm", "hand"))].getWorldPosition(V(0, 0, 0));
    aim(l, tip, H.clone().add(d.multiplyScalar(dist)));
  }
  function perfFor(id, cut) { return cut.performances.find(p => p.actor === id) || {}; }
  const trackOf = (id, t) => (doc.tracks || []).find(k => k.actor === id && k.action !== "drop" && t >= k.reach - 0.1 && t <= k.complete + 0.4);

  function animate(fig, id, t, cut, target) {
    resetPose(fig);
    const ps = pose(doc, id, t), walking = ps === "walk", k = progress(doc, id, t);
    const sit = ps === "sit" ? 1 : ps === "settle" ? k : ps === "rise" ? 1 - k : 0;
    const p = perfFor(id, cut), reach = reachAt(doc, id, t);
    const span = Math.max(0.01, cut.t_end - cut.t_start), local = Math.min(1, Math.max(0, (t - cut.t_start) / span));
    const micro = name => (p.micro || []).some(([m, at]) => m === name && local >= at && local - at < 0.12);
    const fwdW = FWD.clone().applyQuaternion(fig.root.quaternion), leftW = SIDE.clone().applyQuaternion(fig.root.quaternion);
    if (fig.kind === "person") {
      const crouch = reach * 0.6;  // a pick-up from the floor: a deep crouch and a bend, so the hand really gets there
      fig.bones.hips.position.y -= sit * 0.42 + crouch * 0.9;
      turn(fig, "spine", SIDE, -(p.lean || 0) * 0.25 - reach * 1.3);
      const swing = walking ? Math.sin(t * 7) : 0;
      let armR = -swing * 0.5, foreR = 0, armL = swing * 0.5, foreL = 0;
      switch (p.hands) {
        case "grip": armR = armL = 0.3; foreR = foreL = 1.3; break;
        case "hold": armR = 0.5; foreR = 1.1; break;
        case "point": armR = 1.5; break;
        case "search": armR = 0.4 + 0.3 * Math.sin(t * 9); armL = 0.4 + 0.3 * Math.sin(t * 9 + 1.5); foreR = foreL = 1.6; break;
        case "fidget": armR = 0.4; foreR = 1.3 + 0.25 * Math.sin(t * 11); break;
      }
      if (sit > 0.5 && !p.hands) { armR = armL = 0.5; foreR = foreL = 0.9; }
      turn(fig, "upper_arm.R", SIDE, armR); turn(fig, "forearm.R", SIDE, foreR);
      turn(fig, "upper_arm.L", SIDE, armL); turn(fig, "forearm.L", SIDE, foreL);
      const tension = p.tension || 0.2;  // shoulders drawn in under strain
      turn(fig, "upper_arm.L", FWD, -tension * 0.12); turn(fig, "upper_arm.R", FWD, tension * 0.12);
      let yaw = 0, pitch = -reach * 0.4;
      if (target) {
        const loc = fig.root.worldToLocal(target.clone());
        const to = Math.atan2(-loc.z, loc.x);
        if (p.gaze === "hold" || p.gaze === "follow" || sit > 0.5) yaw = THREE.MathUtils.clamp(to, -1.3, 1.3);
        if (p.gaze === "avoid") { yaw = -THREE.MathUtils.clamp(to, -1.2, 1.2) * 0.8; pitch -= 0.25; }
      }
      if (p.gaze === "down") pitch -= 0.45;
      if (p.gaze === "scan") yaw = Math.sin(t * 2.4) * 0.9;
      if (micro("glance_away")) yaw = -yaw - 0.6;
      if (micro("swallow")) pitch -= 0.15;
      if (micro("jaw_clench")) pitch += 0.08;
      if (micro("look_around")) yaw = Math.sin(local * 60) * 1.0;
      turn(fig, "neck", UP, yaw * 0.5); turn(fig, "head", UP, yaw * 0.5);
      turn(fig, "head", SIDE, pitch);
      fig.root.updateMatrixWorld(true);
      // feet: on the runtime's footfalls while walking, planted in front of the seat, else under the hips
      for (const side of ["L", "R"]) {
        const sgn = side === "L" ? 1 : -1;
        let tgt;
        const f = walking || ps === "stand" || ps === "turn" ? foot(doc, id, side, t) : null;
        if (f) tgt = toThree(f[0], f[1], 0.06 + f[2]);
        else {
          const base = fig.root.position.clone().add(leftW.clone().multiplyScalar(0.1 * sgn));
          tgt = base.add(fwdW.clone().multiplyScalar(sit * 0.45 + crouch * 0.15)).setY(0.06);
        }
        ik(fig, `thigh.${side}`, `shin.${side}`, fig.leg.tip, fig.leg, tgt, fwdW.clone().add(V(0, 0.3, 0)));
      }
      // the hand goes to the runtime's contact point, and brings the thing up with it
      const tr = trackOf(id, t);
      if (tr && reach > 0.02) {
        const pt = toThree(tr.point[0], tr.point[1], tr.point[2] + 0.04);
        const hand = fig.bones[sanitize("hand.R")].getWorldPosition(V(0, 0, 0));
        const goal = hand.clone().lerp(pt, reach);
        ik(fig, "upper_arm.R", "forearm.R", null, fig.arm, goal, fwdW.clone().negate().add(V(0, -0.5, 0)).add(leftW.clone().multiplyScalar(-0.5)));
      }
    } else {
      const stride = walking ? Math.sin(t * 9.5) : 0;
      for (const [n, ph] of [["leg.FL", 0], ["leg.FR", 1], ["leg.BL", 1], ["leg.BR", 0]])
        turn(fig, n, SIDE, walking ? Math.sin(t * 9.5 + ph * Math.PI) * 0.5 : 0);
      fig.bones.body.position.y += walking ? Math.abs(stride) * 0.015 : 0;
      const tr = (doc.tracks || []).find(k2 => k2.actor === id && k2.sniff != null && t >= k2.sniff && t < k2.reach);
      let pitch = -reach * 0.9, roll = 0, yaw = 0;
      if (micro("sniff") || tr) pitch -= 0.45 + 0.1 * Math.sin(t * 60);
      if (micro("head_tilt")) roll = THREE.MathUtils.degToRad(p.tilt || 12);
      if (micro("look_back")) yaw = 2.2;
      turn(fig, "neck", SIDE, pitch * 0.5); turn(fig, "head", SIDE, pitch * 0.5);
      turn(fig, "head", FWD, roll); turn(fig, "neck", UP, yaw);
      const tail = p.tail || "neutral";
      if (tail === "wag") { turn(fig, "tail", UP, Math.sin(t * 18) * 0.7); turn(fig, "tail", SIDE, 0.3); }
      else if (tail === "high") { turn(fig, "tail", UP, Math.sin(t * 6) * 0.3); turn(fig, "tail", SIDE, 0.6); }
      else if (tail === "low") turn(fig, "tail", SIDE, -0.9);
      else turn(fig, "tail", UP, Math.sin(t * 4) * 0.2);
      const ears = p.ears === "up" ? 0.6 : p.ears === "back" ? -0.8 : 0;
      turn(fig, "ear.L", SIDE, ears); turn(fig, "ear.R", SIDE, ears);
      fig.root.updateMatrixWorld(true);
      const pick = trackOf(id, t);  // the front goes down and the mouth reaches the contact point
      if (pick && reach > 0.02) {
        const pt = toThree(pick.point[0], pick.point[1], pick.point[2] + 0.02);
        turn(fig, "body", SIDE, -reach * 0.3);
        fig.bones.body.position.y -= reach * 0.06;
        fig.root.updateMatrixWorld(true);
        for (const b of ["neck", "head"]) aim(fig.bones[b], fig.hand.getWorldPosition(V(0, 0, 0)), pt, reach);
      }
    }
  }

  // -- the camera: the trajectory runtime/camera.py solved; the sandbox may add a free camera -------------------------
  function cameraAt(cut, film) {
    const keys = cut.camera ? cut.camera.keys : null;
    if (!keys || !keys.length) return null;
    let i = 0;
    while (i + 1 < keys.length && keys[i + 1][0] <= film) i++;
    const a = keys[i], b = keys[Math.min(i + 1, keys.length - 1)];
    const f = b[0] > a[0] ? THREE.MathUtils.clamp((film - a[0]) / (b[0] - a[0]), 0, 1) : 0;
    const L = j => a[j] + (b[j] - a[j]) * f;
    return [toThree(L(1), L(2), L(3)), toThree(L(4), L(5), L(6)), cut.camera.fov];
  }

  // -- the pose pass: OpenPose-style skeletons (COCO 18 keypoints) on black -------------------------------------------
  const overlay = document.createElement("canvas");
  overlay.width = W; overlay.height = H;
  Object.assign(overlay.style, { position: "absolute", left: "0", top: "0" });
  if (pass === "pose") opts.host.appendChild(overlay);
  const LIMBS = [[1, 2], [1, 5], [2, 3], [3, 4], [5, 6], [6, 7], [1, 8], [8, 9], [9, 10], [1, 11], [11, 12], [12, 13],
                 [1, 0], [0, 14], [14, 16], [0, 15], [15, 17]];
  const LIMB_RGB = ["#ff0000", "#ff5500", "#ffaa00", "#ffff00", "#aaff00", "#55ff00", "#00ff00", "#00ff55", "#00ffaa",
                    "#00ffff", "#00aaff", "#0055ff", "#0000ff", "#5500ff", "#aa00ff", "#ff00ff", "#ff00aa"];
  function keypoints(fig) {
    const w = n => fig.bones[sanitize(n)].getWorldPosition(V(0, 0, 0));
    const hl = p => fig.bones.head.localToWorld(p.clone());
    const ankle = s => fig.bones[sanitize(`shin.${s}`)].localToWorld(fig.leg.tip.clone());
    const wrist = s => fig.bones[sanitize(`hand.${s}`)].getWorldPosition(V(0, 0, 0));
    return [hl(fig.face.nose), w("neck"), w("upper_arm.R"), w("forearm.R"), wrist("R"), w("upper_arm.L"), w("forearm.L"),
            wrist("L"), w("thigh.R"), w("shin.R"), ankle("R"), w("thigh.L"), w("shin.L"), ankle("L"),
            hl(fig.face.eyeR), hl(fig.face.eyeL), hl(fig.face.earR), hl(fig.face.earL)];
  }
  function project(p) {
    const v = p.clone().project(camera);
    return [+((v.x + 1) / 2 * W).toFixed(1), +((1 - v.y) / 2 * H).toFixed(1), v.z < 1 && Math.abs(v.x) <= 1.05 && Math.abs(v.y) <= 1.05 ? 1 : 0];
  }

  // -- one frame: a pure function of (version, film time) ----------------------------------------------------------------
  const state = { version: opts.version, lensBoost: 0, free: null };
  function frame(film) {
    const cut = cutAt(doc, state.version, film), t = worldTime(doc, state.version, film);
    const qa = poseWorld(t, cut);
    return shoot(cut, film, t, qa);
  }
  // every body, bone and thing at world time t (the cut says who performs how, and who is kept out of sight)
  function poseWorld(t, cut) {
    for (const [id, f] of Object.entries(figs)) {
      const s = sample(doc, id, t);
      if (!s) continue;
      f.root.position.copy(toThree(s[0], s[1], 0));
      f.root.rotation.set(0, THREE.MathUtils.degToRad(s[2]), 0);
      const hide = (cut.hidden || []).includes(id) || (cut.relation === "subjective" && cut.focal === id && !state.free);
      f.root.visible = pose(doc, id, t) !== "offstage" && !hide;
    }
    scene.updateMatrixWorld(true);
    for (const [id, f] of Object.entries(figs)) {
      const p = perfFor(id, cut);
      let target = null;
      if (p.gaze_target && figs[p.gaze_target]) target = figs[p.gaze_target].root.position.clone().add(V(0, 1.4, 0));
      else if (p.gaze_target && things[p.gaze_target]) target = things[p.gaze_target].getWorldPosition(V(0, 0, 0));
      animate(f, id, t, cut, target);
    }
    scene.updateMatrixWorld(true);
    const qa = {};
    for (const [id, n] of Object.entries(things)) {
      const h = holder(doc, id, t), ps = pose(doc, id, t);
      n.visible = ps !== "offstage";
      if (h && figs[h] && figs[h].hand) {  // lifted or carried: on the hand (or in the mouth)
        const hf = figs[h];
        const at = hf.kind === "person" ? hf.bones[sanitize("hand.R")].localToWorld(hf.handTip.clone()) : hf.hand.getWorldPosition(V(0, 0, 0));
        if (ps === "lift") {  // from where it lay to the socket: never in two places
          const s = sample(doc, id, t), k = progress(doc, id, t);
          const e = doc.entities.find(x => x.id === id), key = e.keys.find(kk => kk[0] <= t && kk[5] === "lift" && kk[0] > t - 2);
          const from = key ? toThree(key[2], key[3], 0.02) : at;
          n.position.copy(from.clone().lerp(at, k));
          qa[id] = { state: "lift", hand_gap: +from.distanceTo(at).toFixed(3) };
          void s;
        } else n.position.copy(at);
        n.quaternion.copy(hf.root.quaternion);
      } else {
        const s = sample(doc, id, t);
        if (s) {
          let z = 0.0;
          if (ps === "fall") { const k = progress(doc, id, t); z = 0.9 * (1 - k * k); }
          n.position.copy(toThree(s[0], s[1], z));
          n.quaternion.identity();
        }
      }
    }
    return qa;
  }
  function shoot(cut, film, t, qa) {
    if (state.free && !state.free.init) { camera.position.copy(state.free.pos); camera.rotation.set(state.free.pitch, state.free.yaw, 0, "YXZ"); camera.fov = 50 + state.lensBoost; }
    else {
      const c = cameraAt(cut, film);
      if (c) { camera.position.copy(c[0]); camera.lookAt(c[1]); camera.fov = c[2] + (state.lensBoost || 0); }
    }
    camera.updateProjectionMatrix();
    renderer.render(scene, camera);
    const poses = {};
    const ctx = pass === "pose" ? overlay.getContext("2d") : null;
    if (ctx) { ctx.fillStyle = "#000"; ctx.fillRect(0, 0, W, H); }
    for (const [id, f] of Object.entries(figs)) {
      if (f.kind !== "person" || !f.root.visible) continue;
      const kp = keypoints(f).map(project);
      poses[id] = kp;
      if (ctx) {
        ctx.lineWidth = Math.max(3, W / 200);
        LIMBS.forEach(([a, b], i) => {
          if (!kp[a][2] || !kp[b][2]) return;
          ctx.strokeStyle = LIMB_RGB[i]; ctx.beginPath(); ctx.moveTo(kp[a][0], kp[a][1]); ctx.lineTo(kp[b][0], kp[b][1]); ctx.stroke();
        });
        kp.forEach(([x, y, v], i) => { if (v) { ctx.fillStyle = LIMB_RGB[i % LIMB_RGB.length]; ctx.beginPath(); ctx.arc(x, y, ctx.lineWidth, 0, 7); ctx.fill(); } });
      }
    }
    const things_ = Object.fromEntries(Object.keys(things).map(id => [id, attachment(doc, id, t)]));
    return { cut, t, debug: {
      camera: { position: camera.position.toArray().map(v => +v.toFixed(4)), quaternion: camera.quaternion.toArray().map(v => +v.toFixed(6)),
                fov: camera.fov, aspect: camera.aspect, near: camera.near, far: camera.far,
                projection: camera.projectionMatrix.elements.map(v => +v.toFixed(6)) },
      poses, things: things_, qa } };
  }
  function filmAt(t) {  // where the same moment of the world falls in the current version's edit
    for (const s of doc.cuts[state.version].shots) if (s.t_start <= t && t < s.t_end) return s.film_start + (t - s.t_start);
    return 0;
  }
  function freeMove(keys, dt) {  // the sandbox's free camera: it moves the lens, never the world
    const f = state.free;
    if (f.init) {
      const e = new THREE.Euler().setFromQuaternion(camera.quaternion, "YXZ");
      Object.assign(f, { init: false, pos: camera.position.clone(), yaw: e.y, pitch: e.x });
    }
    const fwd = V(-Math.sin(f.yaw), 0, -Math.cos(f.yaw)), right = V(Math.cos(f.yaw), 0, -Math.sin(f.yaw));
    const v = 3 * dt;
    if (keys.has("w")) f.pos.addScaledVector(fwd, v);
    if (keys.has("s")) f.pos.addScaledVector(fwd, -v);
    if (keys.has("d")) f.pos.addScaledVector(right, v);
    if (keys.has("a")) f.pos.addScaledVector(right, -v);
    if (keys.has("e")) f.pos.y += v;
    if (keys.has("q")) f.pos.y -= v;
  }
  return { frame, poseWorld, state, filmAt, freeMove, worldAt: film => worldTime(doc, state.version, film),
           versions: Object.keys(doc.cuts || {}).sort(), duration: v => doc.cuts[v].film_duration, figs, things, camera, scene, renderer };
}
