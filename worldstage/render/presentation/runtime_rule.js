// The rule every presentation engine follows (the same as runtime/export.py:sample in Python), and the two clocks.
// Plain functions of the scene document: no three.js, no DOM, no clock of its own. The browser page uses them to draw
// every frame; node uses them to check the page against the Python runtime (runtime/fidelity.py).

export function entity(doc, id) {
  return doc._byId ? doc._byId[id] : (doc._byId = Object.fromEntries(doc.entities.map(e => [e.id, e])))[id];
}

// the last key at or before t (-1 before the first)
export function indexAt(doc, id, t) {
  const e = entity(doc, id);
  if (!e || !e.keys.length) return -1;
  let lo = 0, hi = e.keys.length;
  while (lo < hi) { const mid = (lo + hi) >> 1; if (e.keys[mid][0] <= t) lo = mid + 1; else hi = mid; }
  return lo - 1;
}

export function keyAt(doc, id, t) {
  const e = entity(doc, id);
  if (!e || !e.keys.length) return null;
  return e.keys[Math.max(0, indexAt(doc, id, t))];
}

const wrap = d => ((((d + 540) % 360) + 360) % 360) - 180;
const lerpYaw = (a, b, f) => (((a + wrap(b - a) * f) % 360) + 360) % 360;

// where an entity is at world time t, as [x, y, yaw] (the same rule as runtime/export.py:sample_full):
// walk moves linearly to the next key heading this key's yaw (eased in at a corner); turn holds and turns;
// rise and settle move and turn to the next key; lift travels from here to the holder; fall travels to the next
// key; carried is wherever the holder is; anything else holds
export function sample(doc, id, t) {
  const e = entity(doc, id);
  if (!e || !e.keys.length) return null;
  const keys = e.keys, i = indexAt(doc, id, t), cur = keys[Math.max(0, i)];
  if (cur[5] === "carried" && cur.length > 6 && cur[6]) return sample(doc, cur[6], t);
  if (i < 0) return [keys[0][2], keys[0][3], keys[0][4]];
  if (i + 1 < keys.length) {
    const a = keys[i], b = keys[i + 1], f = b[0] > a[0] ? (t - a[0]) / (b[0] - a[0]) : 0;
    if (a[5] === "walk") {
      let yaw = a[4];
      // the heading eases in from the yaw the body had (after a corner, or a small turn not worth a turn key)
      if (i > 0 && !["turn", "rise", "settle"].includes(keys[i - 1][5])) {
        const turn = Math.abs(wrap(a[4] - keys[i - 1][4]));
        const ease = Math.min(Math.max(0.25, turn / 450), b[0] - a[0]);
        if (turn > 1e-6 && ease > 0 && t - a[0] < ease) yaw = lerpYaw(keys[i - 1][4], a[4], (t - a[0]) / ease);
      }
      return [a[2] + (b[2] - a[2]) * f, a[3] + (b[3] - a[3]) * f, yaw];
    }
    if (a[5] === "turn") return [a[2], a[3], lerpYaw(a[4], b[4], f)];
    if (a[5] === "rise" || a[5] === "settle") return [a[2] + (b[2] - a[2]) * f, a[3] + (b[3] - a[3]) * f, lerpYaw(a[4], b[4], f)];
    if (a[5] === "lift" && a.length > 6 && a[6]) {
      const h = sample(doc, a[6], t);
      if (h) return [a[2] + (h[0] - a[2]) * f, a[3] + (h[1] - a[3]) * f, h[2]];
    }
    if (a[5] === "fall") return [a[2] + (b[2] - a[2]) * f, a[3] + (b[3] - a[3]) * f, a[4]];
  }
  return [cur[2], cur[3], cur[4]];
}

// how far through its current key a moving pose is (0..1), for the animation of rise, settle, lift and fall
export function progress(doc, id, t) {
  const e = entity(doc, id), i = indexAt(doc, id, t);
  if (!e || i < 0 || i + 1 >= e.keys.length) return 1;
  const a = e.keys[i], b = e.keys[i + 1];
  return b[0] > a[0] ? Math.min(1, Math.max(0, (t - a[0]) / (b[0] - a[0]))) : 1;
}

export function holder(doc, id, t) {
  const k = keyAt(doc, id, t);
  return k && (k[5] === "carried" || k[5] === "lift") && k.length > 6 ? k[6] : "";
}

export function pose(doc, id, t) {
  const k = keyAt(doc, id, t);
  return k ? k[5] : "offstage";
}

// a foot of a walking person: planted at a footfall, swinging between two, or (neither) under the hips.
// returns [x, y, lift height], or null for "under the hips"
export function foot(doc, id, side, t) {
  const e = entity(doc, id);
  if (!e || !e.steps) return null;
  let prev = null, next = null;
  for (const s of e.steps) {
    if (s[2] !== side) continue;
    if (s[0] <= t) prev = s; else { next = s; break; }
  }
  if (prev && t <= prev[1]) return [prev[3], prev[4], 0];
  if (prev && next && t < next[0]) {
    const f = (t - prev[1]) / Math.max(1e-6, next[0] - prev[1]);
    return [prev[3] + (next[3] - prev[3]) * f, prev[4] + (next[4] - prev[4]) * f, 0.12 * Math.sin(Math.PI * f)];
  }
  return null;
}

// the film clock (a version's edit) -> the world clock
export function cutAt(doc, version, film) {
  const shots = doc.cuts[version].shots;
  for (const s of shots) if (s.film_start <= film && film < s.film_end) return s;
  return film >= shots[shots.length - 1].film_end ? shots[shots.length - 1] : shots[0];
}

export function worldTime(doc, version, film) {
  const s = cutAt(doc, version, film);
  return s.t_start + Math.max(0, Math.min(film - s.film_start, s.t_end - s.t_start));
}

// how far into a hand-off someone is (0 = not reaching, 1 = at contact)
export function reachAt(doc, id, t) {
  let best = 0;
  for (const h of doc.handoffs) {
    if (h.actor !== id || h.action === "strike") continue;
    const done = h.complete ?? h.t + 0.3;
    if (t >= h.start && t <= done + 0.4) {
      const up = Math.min(1, Math.max(0, (t - h.start) / Math.max(0.05, h.t - h.start)));
      const down = Math.min(1, Math.max(0, (done + 0.4 - t) / 0.4));
      best = Math.max(best, t <= done ? up : down);
    }
  }
  return best;
}

// the state a thing is in at t, as the runtime's action tracks name it:
// ground | targeted | reaching | contact | attached | dropping | offstage (RuntimeActionTrack)
export function attachment(doc, thing, t) {
  let state = holder(doc, thing, t) ? "attached" : pose(doc, thing, t) === "offstage" ? "offstage" : "ground";
  for (const k of doc.tracks || []) {
    if (k.thing !== thing) continue;
    if (k.action === "drop") { if (t >= k.contact && t < k.complete) state = "dropping"; continue; }
    if (t >= k.approach && t < k.reach) state = "targeted";
    else if (t >= k.reach && t < k.contact) state = "reaching";
    else if (t >= k.contact && t < k.complete) state = "contact";
  }
  return state;
}

// what an engine does, in order, when it plays the world clock at `fps`: bodies start and stop walking, reach,
// take hold of things and let go of them (compared with the runtime's own order by runtime/fidelity.py)
// the moments at which anything can change: every key and every hand-off's start (the playback clock is runtime
// time and a scene can span days, so it is walked event by event, not frame by frame)
export function moments(doc) {
  const set = new Set();
  for (const e of doc.entities) for (const k of e.keys) set.add(k[0]);
  for (const h of doc.handoffs) set.add(h.start);
  return [...set].sort((a, b) => a - b);
}

export function triggers(doc) {
  const out = [], walking = {}, held = {};
  const starts = {};
  for (const h of doc.handoffs) (starts[h.start] = starts[h.start] || []).push(h);
  for (const t of moments(doc)) {
    for (const e of doc.entities) {
      if (e.kind !== "thing") {
        const w = pose(doc, e.id, t) === "walk";
        if (w !== !!walking[e.id]) { out.push([+t.toFixed(3), e.id, w ? "walk_start" : "walk_stop"]); walking[e.id] = w; }
      } else {
        const h = holder(doc, e.id, t);
        if (h !== (held[e.id] || "")) {
          if (held[e.id]) out.push([+t.toFixed(3), held[e.id], "let_go:" + e.id]);
          if (h) out.push([+t.toFixed(3), h, "take_hold:" + e.id]);
          held[e.id] = h;
        }
      }
    }
    for (const h of starts[t] || []) out.push([+t.toFixed(3), h.actor, "reach:" + h.thing]);
  }
  return out;
}
