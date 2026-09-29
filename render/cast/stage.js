/* Cast: turns a scene script into one seekable GSAP timeline. Everything that changes is a tl.set / tl.to on a
   named element, so any frame can be rendered on its own and the same script always gives the same video. */
(function () {
  const NS = "http://www.w3.org/2000/svg";
  const CX = 540, CY = 880;   // where the camera focus lands on the canvas: above the dialogue panel
  const SCALE_STAND = 1.0;
  const EASE_CUT = "power3.out";

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

  // The camera never looks past the edge of the picture: the focus is clamped so the view stays inside 1080 x 1920.
const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
const cam = (z, fx, fy) => {
  const x = clamp(fx, 540 / z, 1080 - 540 / z), y = clamp(fy, CY / z, 1920 - (1920 - CY) / z);
  // Driven through CSS variables (see .shot in style.css): the browser applies the transform, so GSAP's own SVG
  // origin handling cannot shift the picture.
  return { "--cs": z, "--cx": CX - z * x, "--cy": CY - z * y };
};

  // -- the establishing shot: a small town map with the place lit ------------------------------------------------------
  const MAP_ICON = {
    cafe: `<rect x="-52" y="-30" width="104" height="70" rx="10" fill="#f2d6a8"/><path d="M-62 -30 H62 L48 -62 H-48 Z" fill="#c8553d"/><path d="M-62 -30 q15.5 16 31 0 q15.5 16 31 0 q15.5 16 31 0 q15.5 16 31 0" fill="#f6f1e6"/><rect x="-14" y="6" width="28" height="34" rx="4" fill="#7a5636"/>`,
    office: `<rect x="-46" y="-92" width="92" height="132" rx="8" fill="#9db4d0"/>${[0, 1, 2, 3].map(r => [0, 1, 2].map(c => `<rect x="${-34 + c * 26}" y="${-78 + r * 28}" width="16" height="16" rx="3" fill="#e9f3ff"/>`).join("")).join("")}<rect x="-12" y="14" width="24" height="26" rx="3" fill="#5d7794"/>`,
    apartment: `<rect x="-58" y="-40" width="116" height="80" rx="8" fill="#e9c9b0"/><path d="M-70 -40 L0 -96 L70 -40 Z" fill="#b5533c"/><rect x="-34" y="-20" width="24" height="24" rx="3" fill="#fff6dc"/><rect x="10" y="-20" width="24" height="24" rx="3" fill="#fff6dc"/><rect x="-11" y="12" width="22" height="28" rx="3" fill="#7a5636"/>`,
    park: `<ellipse cx="0" cy="28" rx="72" ry="30" fill="#7fbf6a"/><rect x="-6" y="-14" width="12" height="44" fill="#7a5638"/><circle cx="0" cy="-34" r="38" fill="#4f9455"/><circle cx="-34" cy="-8" r="26" fill="#66b361"/><circle cx="36" cy="-8" r="26" fill="#66b361"/><ellipse cx="34" cy="34" rx="26" ry="10" fill="#8fd0f0"/>`,
    station: `<rect x="-62" y="-30" width="124" height="66" rx="10" fill="#c9cfda"/><path d="M-70 -30 H70 L56 -52 H-56 Z" fill="#5d6f8c"/><rect x="-44" y="-12" width="30" height="26" rx="4" fill="#e9f3ff"/><rect x="14" y="-12" width="30" height="26" rx="4" fill="#e9f3ff"/><circle cx="-34" cy="40" r="11" fill="#3b3f4a"/><circle cx="34" cy="40" r="11" fill="#3b3f4a"/>`,
  };
  function mapShot(shot, tl, host) {
    const g = el("g", { class: "shot" });
    window.gsap.set(g, { "--cs": 1, "--cx": 0, "--cy": 0, opacity: 0 });
    const nodes = shot.map.nodes, edges = shot.map.edges;
    const xs = nodes.map(n => n.x), ys = nodes.map(n => n.y);
    const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
    const pos = {};
    nodes.forEach(n => { pos[n.id] = [150 + (n.x - x0) / ((x1 - x0) || 1) * 780, 560 + (n.y - y0) / ((y1 - y0) || 1) * 600]; });
    g.innerHTML = `<defs><linearGradient id="mapbg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#cfe6b8"/><stop offset="1" stop-color="#a9d08c"/></linearGradient></defs>
      <rect width="1080" height="1920" fill="url(#mapbg)"/>
      <g opacity=".55" fill="#8fbf7a">${Array.from({ length: 16 }, (_, i) => `<circle cx="${(i * 233) % 1040 + 20}" cy="${(i * 419) % 1800 + 60}" r="${40 + (i % 4) * 16}"/>`).join("")}</g>
      ${edges.map(([a, b]) => `<path d="M${pos[a][0]} ${pos[a][1]} L${pos[b][0]} ${pos[b][1]}" stroke="#f4ecd6" stroke-width="30" stroke-linecap="round"/><path d="M${pos[a][0]} ${pos[a][1]} L${pos[b][0]} ${pos[b][1]}" stroke="#e0d3b0" stroke-width="4" stroke-dasharray="14 16" stroke-linecap="round"/>`).join("")}
      ${nodes.map(n => `<g transform="translate(${pos[n.id][0]} ${pos[n.id][1]})"><ellipse cx="0" cy="46" rx="80" ry="16" fill="rgba(60,80,40,.25)"/>${MAP_ICON[n.id] || MAP_ICON.cafe}
         <text y="86" text-anchor="middle" font-size="34" font-weight="700" fill="#4a5a3a" font-family="WorldCJK">${esc(n.name)}</text></g>`).join("")}
      <g id="ping${shot.i}" transform="translate(${pos[shot.place][0]} ${pos[shot.place][1] - 6})"><circle r="120" fill="none" stroke="#e0443c" stroke-width="10" opacity=".0"/><circle r="120" fill="none" stroke="#e0443c" stroke-width="10" opacity="0" class="ring2"/></g>
      <g transform="translate(${pos[shot.place][0]} ${pos[shot.place][1] - 130})"><g id="pin${shot.i}"><path d="M0 0 C-36 -44 -30 -86 0 -86 C30 -86 36 -44 0 0 Z" fill="#e0443c" stroke="#fff" stroke-width="6"/><circle cy="-56" r="12" fill="#fff"/></g></g>`;
    host.appendChild(g);
    const [px, py] = pos[shot.place];
    tl.set(g, { opacity: 0 }, 0);
    tl.set(g, { ...cam(1.0, 540, 860) }, shot.start);
    tl.to(g, { opacity: 1, duration: 0.25 }, shot.start);
    tl.set(g, { opacity: 0 }, shot.start + shot.dur);
    tl.to(g, { ...cam(2.1, px, py - 40), duration: shot.dur - 0.2, ease: "power2.inOut" }, shot.start + 0.1);
    const ring = g.querySelector("#ping" + shot.i + " circle");
    tl.fromTo(ring, { attr: { r: 30 }, opacity: 0.9 }, { attr: { r: 150 }, opacity: 0, duration: 0.9, ease: "power1.out", repeat: 1, immediateRender: false }, shot.start + 0.5);
    const pin = g.querySelector("#pin" + shot.i);
    tl.set(pin, { opacity: 0 }, 0);
    tl.set(pin, { opacity: 1, y: -70 }, shot.start + 0.3);
    tl.to(pin, { y: 0, duration: 0.5, ease: "bounce.out" }, shot.start + 0.3);
    return g;
  }

  // -- a scene: a place with people in it, cut like a conversation ---------------------------------------------------
  function sceneShot(shot, tl, host, ctx) {
    const P = window.PLACES.place(shot.place, shot.time, shot.weather);
    const g = el("g", { class: "shot" });
    window.gsap.set(g, { "--cs": 1, "--cx": 0, "--cy": 0, opacity: 0 });
    g.innerHTML = P.svg;
    const people = {};
    for (const s of shot.stage) {
      const c = ctx.cast[s.who];
      const pg = CAST.makeCharacter(s.who, c.hue);
      pg.setAttribute("transform", `translate(${s.x} ${P.floorY}) scale(${s.scale || SCALE_STAND})`);
      g.appendChild(pg);
      people[s.who] = pg;
    }
    g.insertAdjacentHTML("beforeend", P.overlay);
    if (shot.weather === "rain") {   // one pattern, one tween: the streaks scroll and wrap. Indoors they fall on the window only
      const pid = "rainpat" + shot.i, cid = "raincl" + shot.i, win = P.window;
      const clip = P.indoor && win ? `<clipPath id="${cid}"><rect x="${win.x}" y="${win.y}" width="${win.w}" height="${win.h}" rx="18"/></clipPath>` : "";
      g.insertAdjacentHTML("beforeend", `<defs><pattern id="${pid}" width="160" height="240" patternUnits="userSpaceOnUse" patternTransform="rotate(12)">
        <path d="M20 10 v70 M90 70 v60 M140 150 v70 M60 170 v50" stroke="#dfeaff" stroke-width="${P.indoor ? 3 : 4}" stroke-linecap="round" opacity="${P.indoor ? 0.7 : 0.5}"/></pattern>${clip}</defs>
        <g ${clip ? `clip-path="url(#${cid})"` : ""}><g class="rain"><rect x="-300" y="-480" width="1700" height="2640" fill="url(#${pid})"/></g></g>`);
      const rain = g.querySelector(".rain");
      tl.fromTo(rain, { y: 0 }, { y: 240, duration: 0.5, ease: "none", repeat: Math.ceil(shot.dur / 0.5) - 1, immediateRender: false }, shot.start);
    }
    host.appendChild(g);
    const t0 = shot.start, t1 = shot.start + shot.dur;
    tl.set(g, { opacity: 0 }, 0);
    tl.to(g, { opacity: 1, duration: 0.18 }, t0);
    tl.set(g, { opacity: 0 }, t1);

    // people: where they stand, how they feel, who they look at, breathing and blinking
    for (const s of shot.stage) {
      const pg = people[s.who];
      CAST.express(tl, pg, t0, s.feel, s.pose || "down");
      tl.set(pg.querySelector(".eyeset"), { x: (s.look || 0) * 9 }, t0);
      tl.set(pg.querySelector(".head"), { svgOrigin: "0 -262", rotation: (s.look || 0) * 3.5 }, t0);
      const cycles = Math.max(1, Math.floor(shot.dur / 2.4));
      tl.fromTo(pg.querySelector(".body"), { y: 0 }, { y: -5, duration: 1.2, ease: "sine.inOut", yoyo: true, repeat: cycles * 2 - 1, immediateRender: false }, t0);
      CAST.blinks(tl, pg, t0, t1, s.who + shot.i);
    }
    // camera: a cut per entry (instant, then a slow push), so a scene reads as wide -> speaker -> reaction
    shot.cuts.forEach((c, k) => {
      const t = t0 + c.t, end = k + 1 < shot.cuts.length ? t0 + shot.cuts[k + 1].t : t1;
      const z = c.zoom;
      tl.set(g, cam(z, c.focus[0], c.focus[1]), t);
      if (c.push) tl.to(g, { ...cam(z + c.push, c.focus[0], c.focus[1] + (c.drift || 0)), duration: Math.max(0.1, end - t), ease: "none" }, t);
      if (k) { tl.set(g, { opacity: 0.6 }, t); tl.to(g, { opacity: 1, duration: 0.12 }, t + 0.001); }   // a soft flash on the cut
    });
    if (!shot.cuts.length) tl.set(g, cam(1, 540, 1090), t0);

    // beats: lines, reactions, effects
    for (const b of shot.beats) {
      const t = t0 + b.t;
      if (b.feel) CAST.express(tl, people[b.who], t, b.feel, b.pose);
      if (b.line && !b.line.thought) {   // a thought is heard, not spoken: the mouth stays shut
        const end = CAST.talk(tl, people[b.who], t, b.line.dur, b.feel || shot.stage.find(s => s.who === b.who).feel, b.line.text);
        const body = people[b.who].querySelector(".head");
        tl.fromTo(body, { scale: 1, svgOrigin: "0 -262" }, { scale: 1.035, svgOrigin: "0 -262", duration: 0.12, yoyo: true, repeat: 1, immediateRender: false }, t);
        tl.set(people[b.who].querySelector(".mouth-" + (CAST.EXPR[b.feel || "neutral"] || CAST.EXPR.neutral).mouth), { opacity: 1 }, end);
      }
      if (b.shake) {
        const amp = b.shake;
        [[0.04, amp, 0], [0.08, -amp, 0], [0.12, amp * 0.7, 0], [0.16, -amp * 0.5, 0], [0.2, 0, 0]].forEach(([dt, dx]) =>
          tl.to(g, { "--cx": "+=" + dx, duration: 0.04, ease: "none" }, t + dt));
      }
    }
    return { g, people };
  }

  // -- dialogue panel -----------------------------------------------------------------------------------------------------
  function dialogue(shot, tl, ui, ctx) {
    for (const b of shot.beats) {
      if (!b.line) continue;
      const c = ctx.cast[b.who], thought = !!b.line.thought;
      const p = div("dlg" + (thought ? " thought" : ""), "", ui);
      const tag = div("tag", esc(thought ? c.name + "（心裡想）" : c.name), p);
      tag.style.background = CAST.hsl(c.hue, 58, thought ? 40 : 44);
      const txt = div("txt", "", p);
      const chars = Array.from(b.line.text);
      const spans = chars.map(ch => { const s = document.createElement("span"); s.textContent = ch; s.style.opacity = 0; txt.appendChild(s); return s; });
      const t = shot.start + b.t, dur = b.line.dur, per = Math.min(0.09, Math.max(0.03, (dur * 0.8) / chars.length));
      tl.set(p, { opacity: 0, y: 24 }, 0);
      tl.to(p, { opacity: 1, y: 0, duration: 0.18, ease: "power2.out" }, t - 0.05);
      spans.forEach((s, i) => tl.set(s, { opacity: 1 }, t + i * per));
      tl.to(p, { opacity: 0, duration: 0.2 }, t + dur + 0.35);
    }
  }

  function hud(shot, tl, ui) {
    const h = div("hud", `<b>第 ${shot.stamp.day} 天 · ${shot.stamp.clock}</b><small>${esc(shot.stamp.placeName)} · ${esc(shot.stamp.weather)}</small>`, ui);
    tl.set(h, { opacity: 0 }, 0);
    tl.to(h, { opacity: 1, duration: 0.25 }, shot.start + 0.1);
    tl.set(h, { opacity: 0 }, shot.start + shot.dur);
  }

  // -- title card: the two leads face to face -------------------------------------------------------------------------------
  function titleCard(S, tl, host, ui, ctx) {
    const g = el("g", { class: "shot" });
    const [a, b] = S.leads;
    g.innerHTML = `<defs><linearGradient id="tbg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#2a2138"/><stop offset="1" stop-color="#4a3350"/></linearGradient></defs>
      <rect width="1080" height="1920" fill="url(#tbg)"/><circle cx="540" cy="1000" r="420" fill="#ffffff" opacity=".05"/><circle cx="540" cy="1000" r="300" fill="#ffffff" opacity=".05"/>`;
    host.appendChild(g);
    const pa = CAST.makeCharacter(a, ctx.cast[a].hue), pb = CAST.makeCharacter(b, ctx.cast[b].hue);
    const wa = el("g", { transform: "translate(300 1560) scale(1.5)" }), wb = el("g", { transform: "translate(780 1560) scale(1.5)" });
    wa.appendChild(pa); wb.appendChild(pb); g.appendChild(wa); g.appendChild(wb);
    CAST.express(tl, pa, 0, "neutral", "crossed"); CAST.express(tl, pb, 0, "neutral", "crossed");
    tl.set(pa.querySelector(".eyeset"), { x: 9 }, 0); tl.set(pb.querySelector(".eyeset"), { x: -9 }, 0);
    tl.set(pa, { opacity: 0 }, 0); tl.set(pb, { opacity: 0 }, 0);
    tl.fromTo(pa, { x: -120, opacity: 0 }, { x: 0, opacity: 1, duration: 0.7, ease: "power3.out", immediateRender: false }, 0.1);
    tl.fromTo(pb, { x: 120, opacity: 0 }, { x: 0, opacity: 1, duration: 0.7, ease: "power3.out", immediateRender: false }, 0.1);
    const t = div("title", `<div class="series">虛擬小鎮</div><h1>${esc(S.title)}</h1><div class="sub">${esc(S.tagline)}</div>${S.recap ? `<div class="recap">前情提要：${esc(S.recap)}</div>` : ""}`, ui);
    tl.set(t, { opacity: 0, y: 30 }, 0);
    tl.to(t, { opacity: 1, y: 0, duration: 0.6, ease: "power2.out" }, 0.25);
    tl.to(t, { opacity: 0, duration: 0.3 }, S.title_seconds - 0.35);
    tl.to(g, { opacity: 0, duration: 0.35 }, S.title_seconds - 0.35);
  }

  window.STAGE = {
    build(S, gsapRef) {
      const tl = gsapRef.timeline({ paused: true });
      const scene = document.getElementById("scene"), world = document.getElementById("world"), ui = document.getElementById("ui");
      const ctx = { cast: S.cast };
      titleCard(S, tl, world, ui, ctx);
      S.shots.forEach((shot, i) => {
        shot.i = i;
        if (shot.kind === "map") mapShot(shot, tl, world);
        else { sceneShot(shot, tl, world, ctx); dialogue(shot, tl, ui, ctx); }
        hud(shot, tl, ui);
      });
      const fade = document.getElementById("fade");
      tl.set(fade, { opacity: 1 }, 0);
      tl.to(fade, { opacity: 0, duration: 0.5 }, 0.01);
      tl.to(fade, { opacity: 1, duration: 0.8 }, S.total - 0.9);
      return tl;
    },
  };
})();
