/* Cast, directed: one packet shot -> one screen shot, following the DirectorPlan fields the packet carries.
   scale      WS / MS / MCU / CU / INSERT          -> how close the camera is
   angle      eye_level / high / low / ground      -> where the eye line sits; ground is an animal's height
   relation   subjective                            -> the focalizer is not drawn: we are behind their eyes
              over_shoulder                         -> the focalizer's dark shoulder in the foreground
   motion     static / push_in / pull_out / handheld / tracking
   function   hide                                  -> the act, never the face: the doer is not drawn
   dialogue   muffled                               -> voices, not words
   Everything is a tl.set / tl.to at a fixed time, so any frame can be rendered on its own. */
(function () {
  const NS = "http://www.w3.org/2000/svg";
  const W = 1080, H = 1920;
  const ZOOM = { EWS: 0.9, WS: 1.0, MS: 1.4, MCU: 1.9, CU: 2.5, ECU: 3.0, INSERT: 3.0 };
  const PERSON_AT = { eyes: 352, face: 330, body: 240, hands: 160, object: 140, space: 260 };
  const ANIMAL_AT = { eyes: 160, face: 150, body: 100, hands: 118, object: 118, space: 120 };
  const FEEL = { relieved: "happy", fierce: "angry", focused: "curious" };

  function el(tag, attrs, html) {
    const e = document.createElementNS(NS, tag);
    for (const k in attrs || {}) e.setAttribute(k, attrs[k]);
    if (html) e.innerHTML = html;
    return e;
  }
  function div(cls, html, parent) {
    const d = document.createElement("div"); d.className = cls; if (html !== undefined) d.innerHTML = html;
    if (parent) parent.appendChild(d); return d;
  }
  function esc(s) { return String(s).replace(/[&<>]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c])); }
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  // the camera: focus (fx, fy) lands on canvas point (540, cy); the view never leaves the picture
  function cam(z, fx, fy, cy) {
    const x = clamp(fx, 540 / z, W - 540 / z), y = clamp(fy, cy / z, H - (H - cy) / z);
    return { "--cs": z, "--cx": 540 - z * x, "--cy": cy - z * y };
  }
  function hashf(s) { let h = 2166136261; for (const c of s) { h ^= c.charCodeAt(0); h = Math.imul(h, 16777619); } return (h >>> 0) / 4294967296; }

  function defs(svg) {
    svg.insertAdjacentHTML("afterbegin", `<defs>
      <filter id="dogvision" color-interpolation-filters="sRGB"><feColorMatrix type="matrix"
        values="0.56 0.44 0 0 0  0.56 0.44 0 0 0  0 0.24 0.76 0 0  0 0 0 1 0"/><feGaussianBlur stdDeviation="1.2"/></filter>
      <filter id="silhouette" x="-20%" y="-20%" width="140%" height="140%"><feColorMatrix type="matrix"
        values="0 0 0 0 0.07  0 0 0 0 0.05  0 0 0 0 0.09  0 0 0 0.92 0"/><feGaussianBlur stdDeviation="7"/></filter>
      <filter id="soft"><feGaussianBlur stdDeviation="14"/></filter>
      <radialGradient id="vig" cx="50%" cy="46%" r="70%"><stop offset="55%" stop-color="#000" stop-opacity="0"/><stop offset="100%" stop-color="#000" stop-opacity=".78"/></radialGradient>
      <radialGradient id="vigsoft" cx="50%" cy="46%" r="75%"><stop offset="65%" stop-color="#000" stop-opacity="0"/><stop offset="100%" stop-color="#000" stop-opacity=".45"/></radialGradient>
      </defs>`);
  }

  // -- the people and animals of one shot -----------------------------------------------------------------------------
  function figure(who, c) {
    return c.kind === "animal" ? window.ANIMALS.makeAnimal(who, c.species || "dog") : window.CAST.makeCharacter(who, c.hue);
  }
  function heightOf(c, attention) { return (c.kind === "animal" ? ANIMAL_AT : PERSON_AT)[attention] || 240; }

  function sceneShot(shot, tl, host, fgHost, ui, S) {
    const P = window.PLACES.place(shot.place, shot.time, shot.weather);
    const t0 = shot.start, t1 = shot.start + shot.dur, ts = t0 + shot.dur * 0.45;
    const shake = el("g"), g = el("g", { class: "shot" });
    window.gsap.set(g, { "--cs": 1, "--cx": 0, "--cy": 0 });
    g.innerHTML = P.svg;
    shake.appendChild(g);
    const subjective = shot.relation === "subjective";
    const animalEyes = subjective && shot.focal_kind === "animal";
    if (animalEyes) g.setAttribute("filter", "url(#dogvision)");
    const pos = {}, figs = {};
    const hidden = new Set();
    if (shot.fn === "hide" && shot.actor) hidden.add(shot.actor);          // the act, never the face
    if (subjective && shot.focal) hidden.add(shot.focal);                   // we are behind their eyes
    const order = shot.stage.slice().sort((a, b) => (b.back ? 1 : 0) - (a.back ? 1 : 0));
    for (const s of order) {
      const c = S.cast[s.who];
      const s0 = s.back ? 0.62 : 1.0, y = s.back ? P.floorY - 150 : P.floorY;
      pos[s.who] = { x: s.x, y, s: s0, c };
      if (hidden.has(s.who)) continue;
      const wrap = el("g", { transform: `translate(${s.x} ${y})` }), mover = el("g");
      const inner = el("g", { transform: `scale(${s0 * (s.face || 1)} ${s0})` });
      const f = figure(s.who, c);
      inner.appendChild(f); mover.appendChild(inner); wrap.appendChild(mover); g.appendChild(wrap);
      figs[s.who] = { wrap: mover, f, c };
    }
    // the thing: where it is at the start of the shot and where it ends up
    const propAt = state => {
      if (!state) return null;
      if (state === "ground") {
        const a = pos[shot.actor] || { x: 420, y: P.floorY, s: 1 };
        return { x: clamp(a.x + (a.c && a.c.kind === "animal" ? 200 : 150) * (shot.face_actor || 1), 120, 960), y: P.floorY, s: 1.25, ground: true };
      }
      const who = state.slice(5), p = pos[who];
      if (!p) return null;
      if (p.c.kind === "animal") return { x: p.x + 146 * p.s * (shot.face_of && shot.face_of[who] || 1), y: p.y - 100 * p.s, s: 0.9 * p.s, who };
      return { x: p.x + 96 * p.s, y: p.y - 118 * p.s, s: 1.0 * p.s, who };
    };
    let prop0 = null, prop1 = null;
    if (shot.prop) {
      const a = propAt(shot.prop_from), b = propAt(shot.prop_to);
      const mk = at => {  // placed by the outer group, moved by the inner one
        const e = el("g", { transform: `translate(${at.x} ${at.y})` }), mv = el("g");
        mv.appendChild(el("g", { transform: `scale(${at.s})` }, window.PROPS.draw(shot.prop)));
        e.appendChild(mv); g.appendChild(e); e.mv = mv; return e;
      };
      if (a) prop0 = { e: mk(a), at: a };
      if (b && (!a || b.x !== a.x || b.y !== a.y)) prop1 = { e: mk(b), at: b };
      if (prop0) { tl.set(prop0.e, { opacity: 1 }, 0); if (prop1) tl.set(prop0.e, { opacity: 0 }, ts); }
      if (prop1) {
        tl.set(prop1.e, { opacity: 0 }, 0);
        tl.set(prop1.e, { opacity: 1 }, ts);
        if (prop1.at.ground && prop0 && !prop0.at.ground)          // it falls from the hand or the mouth
          tl.fromTo(prop1.e.mv, { y: prop0.at.y - prop1.at.y, x: prop0.at.x - prop1.at.x },
                    { y: 0, x: 0, duration: 0.45, ease: "bounce.out", immediateRender: false }, ts);
      }
      if (shot.fn === "hide" && prop0 && shot.event !== "misplace") {   // something unseen carries it off
        const shadow = el("ellipse", { cx: prop0.at.x - 260, cy: P.floorY + 6, rx: 110, ry: 20, fill: "rgba(10,8,16,.4)" });
        g.appendChild(shadow);
        tl.set(shadow, { opacity: 0 }, 0);
        tl.fromTo(shadow, { opacity: 0.9, x: 0 }, { x: 520, duration: 0.9, ease: "power1.in", immediateRender: false }, ts - 0.5);
        tl.fromTo(prop0.e.mv, { x: 0, y: 0 }, { y: -520, x: 260, duration: 0.5, ease: "power2.in", immediateRender: false }, ts);
        if (prop1) tl.set(prop1.e, { opacity: 0 }, ts);
      }
    }
    g.insertAdjacentHTML("beforeend", P.overlay);
    host.appendChild(shake);

    // what people feel, how they breathe and blink; what the animal does
    for (const s of shot.stage) {
      const F = figs[s.who];
      if (!F) continue;
      const feel = FEEL[s.feel] || s.feel || "neutral";
      if (F.c.kind === "animal") {
        window.ANIMALS.feel(tl, F.f, t0, feel);
        window.ANIMALS.wag(tl, F.f, t0, t1, feel);
      } else {
        window.CAST.express(tl, F.f, t0, feel, s.pose || "down");
        if (s.pose2) window.CAST.express(tl, F.f, ts, FEEL[s.feel2] || s.feel2 || feel, s.pose2);
        tl.set(F.f.querySelector(".eyeset"), { x: (s.look || 0) * 9 }, t0);
        window.CAST.blinks(tl, F.f, t0, t1, s.who + shot.i);
      }
      const cycles = Math.max(1, Math.floor(shot.dur / 2.4));
      tl.fromTo(F.f.querySelector(".body"), { y: 0 }, { y: -5, duration: 1.2, ease: "sine.inOut", yoyo: true, repeat: cycles * 2 - 1, immediateRender: false }, t0);
      if (s.walk) tl.fromTo(F.wrap, { x: 0 }, { x: s.walk, duration: shot.dur, ease: "none", immediateRender: false }, t0);
      if (s.walk_after) tl.fromTo(F.wrap, { x: 0 }, { x: s.walk_after, duration: t1 - ts, ease: "none", immediateRender: false }, ts);
      if (s.walk_before) tl.fromTo(F.wrap, { x: 0 }, { x: s.walk_before, duration: ts - t0, ease: "power1.out", immediateRender: false }, t0);
    }
    // a belief on screen: the face of the one they suspect, in a thought bubble above them
    if (shot.suspect && pos[shot.thinker] && S.cast[shot.suspect]) {
      const p = pos[shot.thinker], bx = clamp(p.x + 150, 200, 880), by = p.y - 640 * p.s;
      const bub = el("g", { transform: `translate(${bx} ${by})` });
      bub.innerHTML = `<circle cx="-110" cy="150" r="14" fill="#fff" opacity=".92"/><circle cx="-70" cy="104" r="22" fill="#fff" opacity=".92"/>
        <ellipse cx="0" cy="0" rx="120" ry="104" fill="#fff" opacity=".95"/><clipPath id="bub${shot.i}"><ellipse cx="0" cy="0" rx="108" ry="92"/></clipPath>`;
      const face = el("g", { "clip-path": `url(#bub${shot.i})` });
      const head = el("g", { transform: "translate(0 150) scale(0.5)" });
      const who = window.CAST.makeCharacter(shot.suspect, S.cast[shot.suspect].hue);
      head.appendChild(who); face.appendChild(head); bub.appendChild(face);
      bub.insertAdjacentHTML("beforeend", `<text x="78" y="-58" font-size="64" font-weight="700" fill="#c8453a">?</text>`);
      g.appendChild(bub);
      window.CAST.express(tl, who, t0, "smug", "crossed");
      tl.set(bub, { opacity: 0, scale: 0.6, svgOrigin: "0 0" }, 0);
      tl.to(bub, { opacity: 1, scale: 1, svgOrigin: "0 0", duration: 0.35, ease: "back.out(2)" }, t0 + 0.5);
    }

    // -- the camera ------------------------------------------------------------------------------------------------------
    let z = ZOOM[shot.scale] || 1.3, fx = 540, fy = 1080, cy = 880;
    const subj = pos[shot.subject];
    if (shot.subject === shot.prop && (prop0 || prop1)) {
      const at = (prop0 || prop1).at; fx = at.x; fy = at.y - 40 * at.s;
    } else if (subj) {
      fx = subj.x + (subj.c.kind === "animal" ? 60 : 0) * subj.s; fy = subj.y - heightOf(subj.c, shot.attention) * subj.s;
    } else if (shot.attention === "space" || !subj) { z = Math.min(z, 1.1); }
    if (shot.attention === "space") { fx = 540; fy = P.floorY - 300; z = Math.min(z, 1.1); }
    if (shot.angle === "ground") { cy = 1300; fy = P.floorY - 70; z = Math.max(z, 1.45); }
    else if (shot.angle === "high") { cy = 780; fy -= 30; }
    else if (shot.angle === "low") { cy = 1080; fy += 40; }
    const base = cam(z, fx, fy, cy);
    tl.set(g, base, t0);
    if (shot.motion === "push_in" || shot.motion === "slow_push_in") tl.fromTo(g, base, { ...cam(z * 1.22, fx, fy, cy), duration: shot.dur, ease: "none", immediateRender: false }, t0);
    else if (shot.motion === "pull_out") tl.fromTo(g, cam(z * 1.4, fx, fy, cy), { ...base, duration: shot.dur, ease: "power1.out", immediateRender: false }, t0);
    else if (shot.motion === "tracking") tl.fromTo(g, base, { ...cam(z, fx + 170, fy, cy), duration: shot.dur, ease: "none", immediateRender: false }, t0);
    if (shot.motion === "handheld" || shot.motion === "tracking") {
      const n = Math.max(3, Math.floor(shot.dur / 0.42));
      for (let k = 0; k < n; k++) {
        const r = hashf(shot.i + ":" + k), q = hashf(k + ":" + shot.i);
        tl.to(shake, { x: (r - 0.5) * 22, y: (q - 0.5) * 16, rotation: (r - 0.5) * 0.8, svgOrigin: "540 960", duration: 0.42, ease: "sine.inOut" }, t0 + k * 0.42);
      }
    }
    tl.set(shake, { opacity: 0 }, 0);
    tl.set(shake, { opacity: 1 }, t0);
    tl.set(shake, { opacity: 0 }, t1);

    // -- whose eyes: overlays that do not move with the camera ------------------------------------------------------------
    const fg = el("g");
    if (animalEyes) {
      const snout = S.cast[shot.focal] ? "#d9a066" : "#b98a5d";
      fg.innerHTML = `<rect width="${W}" height="${H}" fill="url(#vig)"/>
        <g filter="url(#soft)"><ellipse cx="540" cy="1990" rx="300" ry="190" fill="${snout}"/><ellipse cx="540" cy="1830" rx="70" ry="44" fill="#2a2226"/></g>`;
      // what it carries hangs in front of its own nose
      const mine = "hand:" + shot.focal, held0 = shot.prop_from === mine, held1 = shot.prop_to === mine;
      if (shot.prop && (held0 || held1)) {
        const carried = el("g", { transform: "translate(540 1420) scale(2.4)" }, window.PROPS.draw(shot.prop));
        fg.appendChild(carried);
        tl.set(carried, { opacity: held0 ? 1 : 0 }, 0);
        if (held0 !== held1) tl.set(carried, { opacity: held1 ? 1 : 0 }, ts);
        if (prop0 && held0) tl.set(prop0.e, { opacity: 0 }, 0);
        if (prop1 && held1) tl.set(prop1.e, { opacity: 0 }, ts);
      }
    } else if (subjective) {
      fg.innerHTML = `<rect width="${W}" height="${H}" fill="url(#vigsoft)"/>`;
    } else if (shot.relation === "over_shoulder" && shot.focal && pos[shot.focal] && shot.subject !== shot.focal) {
      const c = S.cast[shot.focal], left = pos[shot.focal].x < 540;
      const sil = el("g", { filter: "url(#silhouette)", transform: `translate(${left ? 60 : 1020} 2350) scale(${left ? 2.3 : -2.3} 2.3)` });
      sil.appendChild(figure(shot.focal, c));
      fg.appendChild(sil);
    }
    if (fg.childNodes.length) {
      fgHost.appendChild(fg);
      tl.set(fg, { opacity: 0 }, 0); tl.set(fg, { opacity: 1 }, t0); tl.set(fg, { opacity: 0 }, t1);
    }

    // -- words: the caption (or what the focalizer senses), a thought, muffled voices ------------------------------------
    if (shot.caption) {
      const sense = shot.caption.kind === "sense";
      const p = div("cap" + (sense ? " sense" : ""), "", ui);
      if (sense) div("tag", esc(shot.caption.label), p);
      div("txt", esc(shot.caption.text), p);
      const people = shot.stage.some(x => x.who !== shot.focal && S.cast[x.who] && S.cast[x.who].kind !== "animal");
      if (shot.dialogue === "muffled" && people) div("muffle", "（聽得見人聲，聽不懂說什麼）", p);
      tl.set(p, { opacity: 0, y: 20 }, 0);
      tl.to(p, { opacity: 1, y: 0, duration: 0.2 }, t0 + 0.15);
      tl.to(p, { opacity: 0, duration: 0.2 }, shot.caption.until - 0.25);
    }
    if (shot.thought) {
      const p = div("dlg thought", "", ui);
      const tag = div("tag", esc(shot.thought.label), p);
      tag.style.background = shot.thought.animal ? "#b9793f" : window.CAST.hsl(S.cast[shot.thought.who].hue, 58, 40);
      div("txt", esc(shot.thought.text), p);
      tl.set(p, { opacity: 0 }, 0);
      tl.to(p, { opacity: 1, duration: 0.25 }, t0 + 0.6);
      tl.to(p, { opacity: 0, duration: 0.2 }, t1 - 0.2);
    }
    const h = div("hud", `<b>第 ${shot.stamp.day} 天 · ${shot.stamp.clock}</b><small>${esc(shot.stamp.placeName)}</small>`, ui);
    tl.set(h, { opacity: 0 }, 0); tl.set(h, { opacity: 1 }, t0); tl.set(h, { opacity: 0 }, t1);
    if (S.debug) {
      const d = div("why", esc(`${shot.fn} · ${shot.scale} · ${shot.angle} · ${shot.relation} · ${shot.motion} — ${shot.note}`), ui);
      tl.set(d, { opacity: 0 }, 0); tl.set(d, { opacity: 1 }, t0); tl.set(d, { opacity: 0 }, t1);
    }
    // the cut into this shot
    if (shot.cut === "dissolve") { const f = document.getElementById("fade"); tl.to(f, { opacity: 0.9, duration: 0.18 }, t0 - 0.18); tl.to(f, { opacity: 0, duration: 0.3 }, t0); }
    if (shot.cut === "smash_cut") { const f = document.getElementById("flash"); tl.set(f, { opacity: 0.85 }, t0); tl.to(f, { opacity: 0, duration: 0.18 }, t0 + 0.02); }
  }

  function titleCard(S, tl, host, ui) {
    const g = el("g");
    g.innerHTML = `<defs><linearGradient id="tbg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#2a2138"/><stop offset="1" stop-color="#4a3350"/></linearGradient></defs>
      <rect width="${W}" height="${H}" fill="url(#tbg)"/><circle cx="540" cy="1100" r="420" fill="#fff" opacity=".05"/><circle cx="540" cy="1100" r="300" fill="#fff" opacity=".05"/>`;
    host.appendChild(g);
    const lead = S.leads.filter(w => S.cast[w]).slice(0, 2);
    lead.forEach((w, k) => {
      const wrap = el("g", { transform: `translate(${lead.length === 1 ? 540 : k ? 760 : 320} 1560) scale(1.4)` });
      const f = figure(w, S.cast[w]); wrap.appendChild(f); g.appendChild(wrap);
      if (S.cast[w].kind === "animal") window.ANIMALS.feel(tl, f, 0, "happy");
      else window.CAST.express(tl, f, 0, "neutral", "crossed");
    });
    const t = div("title", `<div class="series">${esc(S.series)}</div><h1>${esc(S.title)}</h1><div class="sub">${esc(S.tagline || "")}</div>`, ui);
    tl.set(t, { opacity: 0, y: 30 }, 0);
    tl.to(t, { opacity: 1, y: 0, duration: 0.5, ease: "power2.out" }, 0.2);
    tl.to(t, { opacity: 0, duration: 0.3 }, S.title_seconds - 0.35);
    tl.set(g, { opacity: 1 }, 0);
    tl.to(g, { opacity: 0, duration: 0.3 }, S.title_seconds - 0.3);
  }

  window.DIRECTED = {
    build(S, gsapRef) {
      const tl = gsapRef.timeline({ paused: true });
      const scene = document.getElementById("scene"), world = document.getElementById("world"), ui = document.getElementById("ui");
      defs(scene);
      const fgHost = el("g"); scene.appendChild(fgHost);
      titleCard(S, tl, world, ui);
      S.shots.forEach((shot, i) => { shot.i = i; sceneShot(shot, tl, world, fgHost, ui, S); });
      if (S.badge) { const b = div("badge", S.badge.map(esc).join("<br>"), ui); tl.set(b, { opacity: 0 }, 0); tl.set(b, { opacity: 1 }, S.title_seconds); }
      const fade = document.getElementById("fade");
      tl.set(fade, { opacity: 1 }, 0);
      tl.to(fade, { opacity: 0, duration: 0.5 }, 0.01);
      tl.to(fade, { opacity: 1, duration: 0.8 }, S.total - 0.9);
      return tl;
    },
  };
})();
