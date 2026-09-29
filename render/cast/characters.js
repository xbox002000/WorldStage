/* Cast: the town's people as flat, round vector characters. Pure functions of (person id, identity hue, pose,
   expression): the same inputs always draw the same picture. Everything that changes over time is a separate element
   switched with tl.set, so any frame can be seeked to. Coordinates: origin at the feet, y grows downwards, a
   standing character is about 520 units tall with the head centred at (0, -360). */
(function () {
  const SKINS = ["#f7dcc6", "#f2cba8", "#e7ba91", "#d6a577", "#c08a60"];

  // The character bible: how each person looks, apart from the colour of their clothes (which is their identity hue).
  const BIBLE = {
    ming: { hair: "side",     hairColor: "#22222a", skin: 1, outfit: "suit",     acc: ["tie"],          pants: "#33394a" },
    mei:  { hair: "long",     hairColor: "#3b2b26", skin: 0, outfit: "coat",     acc: ["scarf"],        pants: "#3a3d4a" },
    jun:  { hair: "messy",    hairColor: "#5a3a26", skin: 2, outfit: "hoodie",   acc: ["bags"],         pants: "#3f4657" },
    lan:  { hair: "bob",      hairColor: "#6b3b2a", skin: 1, outfit: "cardigan", acc: ["glasses_round"], pants: "#4a4238" },
    hao:  { hair: "spiky",    hairColor: "#1f1f26", skin: 2, outfit: "tee",      acc: [],               pants: "#39435a" },
    yun:  { hair: "braid",    hairColor: "#2d2439", skin: 1, outfit: "dress",    acc: ["moon_pin"],     pants: "#3a3550" },
    kai:  { hair: "slick",    hairColor: "#3a2c26", skin: 1, outfit: "suit",     acc: ["glasses_rect"], pants: "#2f3442" },
    ning: { hair: "ponytail", hairColor: "#1e2b38", skin: 0, outfit: "sweater",  acc: [],               pants: "#3d4553" },
    tao:  { hair: "buzz",     hairColor: "#2b2b2b", skin: 3, outfit: "jacket",   acc: ["stubble"],      pants: "#3b3f4a" },
    rui:  { hair: "curly",    hairColor: "#7a4b2a", skin: 1, outfit: "hoodie",   acc: [],               pants: "#40465a" },
  };
  const HAIR_STYLES = ["side", "long", "messy", "bob", "spiky", "braid", "slick", "ponytail", "buzz", "curly"];
  const OUTFITS = ["tee", "hoodie", "suit", "cardigan", "coat", "dress", "sweater", "jacket"];
  const HAIR_COLORS = ["#22222a", "#3b2b26", "#5a3a26", "#7a4b2a", "#2d2439", "#1e2b38"];

  function hash(s) { let h = 2166136261; for (const c of s) { h ^= c.charCodeAt(0); h = Math.imul(h, 16777619); } return h >>> 0; }

  function designFor(id) {
    if (BIBLE[id]) return BIBLE[id];
    const h = hash(id);  // people who are not in the bible still get a stable look
    return { hair: HAIR_STYLES[h % 10], hairColor: HAIR_COLORS[(h >> 4) % 6], skin: (h >> 8) % 5,
             outfit: OUTFITS[(h >> 12) % 8], acc: [], pants: "#3b4252" };
  }

  // -- colour helpers ----------------------------------------------------------------------------------------------
  function hsl(h, s, l, a) { return a === undefined ? `hsl(${h} ${s}% ${l}%)` : `hsl(${h} ${s}% ${l}% / ${a})`; }
  function shade(hex, f) {  // f < 1 darker, > 1 lighter
    const n = parseInt(hex.slice(1), 16), c = k => Math.max(0, Math.min(255, Math.round(((n >> k) & 255) * f)));
    return `rgb(${c(16)},${c(8)},${c(0)})`;
  }

  // -- hair: [behind the body, in front of the head] ---------------------------------------------------------------
  const HAIR = {
    side: c => ["", `<path d="M-126 -358 C-134 -456 -76 -490 -4 -490 C72 -490 130 -454 126 -358 C118 -392 104 -412 84 -422 C40 -404 -30 -404 -84 -424 C-104 -412 -118 -392 -126 -358 Z" fill="${c}"/>
      <path d="M-24 -486 C6 -450 56 -432 96 -424" stroke="${shade(c, 1.9)}" stroke-width="6" stroke-linecap="round" fill="none" opacity=".55"/>`],
    long: c => [`<path d="M-138 -376 C-160 -270 -152 -186 -120 -146 C-70 -126 70 -126 120 -146 C152 -186 160 -270 138 -376 Z" fill="${c}"/>`,
      `<path d="M-128 -364 C-134 -458 -70 -492 0 -492 C70 -492 134 -458 128 -364 C118 -402 96 -424 60 -434 C20 -410 -20 -410 -60 -434 C-96 -424 -118 -402 -128 -364 Z" fill="${c}"/>
       <path d="M-40 -488 C-20 -466 -14 -444 -12 -428" stroke="${shade(c, 1.9)}" stroke-width="6" stroke-linecap="round" fill="none" opacity=".45"/>`],
    messy: c => ["", `<path d="M-126 -360 C-134 -452 -78 -484 -4 -484 C72 -484 130 -452 126 -360 C114 -394 100 -410 84 -418 C40 -400 -30 -402 -84 -420 C-104 -408 -116 -390 -126 -360 Z" fill="${c}"/>
      <path d="M-104 -440 L-138 -486 L-70 -466 Z M-50 -470 L-58 -520 L-8 -482 Z M8 -484 L26 -530 L54 -478 Z M64 -472 L104 -508 L100 -448 Z M104 -440 L146 -450 L120 -410 Z" fill="${c}"/>`],
    bob: c => [`<path d="M-140 -376 C-164 -320 -152 -262 -128 -238 C-90 -224 90 -224 128 -238 C152 -262 164 -320 140 -376 Z" fill="${c}"/>`,
      `<path d="M-128 -364 C-134 -458 -72 -490 0 -490 C72 -490 134 -458 128 -364 C114 -396 90 -410 60 -412 L-60 -412 C-90 -410 -114 -396 -128 -364 Z" fill="${c}"/>
       <path d="M-70 -480 C-40 -460 -30 -440 -28 -416" stroke="${shade(c, 1.9)}" stroke-width="6" stroke-linecap="round" fill="none" opacity=".45"/>`],
    spiky: c => ["", `<path d="M-126 -362 C-130 -428 -112 -450 -92 -454 L-112 -506 L-62 -466 L-52 -526 L-16 -478 L6 -534 L30 -478 L64 -526 L70 -466 L112 -500 L94 -452 C116 -442 130 -420 126 -362 C110 -394 90 -410 70 -418 C30 -402 -30 -402 -70 -418 C-90 -410 -110 -394 -126 -362 Z" fill="${c}"/>`],
    braid: c => [`<path d="M-136 -382 C-156 -290 -150 -196 -122 -150 L122 -150 C150 -196 156 -290 136 -382 Z" fill="${c}"/>
        <g fill="${c}" stroke="${shade(c, 1.7)}" stroke-width="3"><ellipse cx="96" cy="-250" rx="22" ry="26"/><ellipse cx="104" cy="-214" rx="21" ry="25"/><ellipse cx="108" cy="-180" rx="20" ry="24"/><ellipse cx="108" cy="-148" rx="18" ry="22"/></g>
        <circle cx="108" cy="-124" r="10" fill="#e8b84a"/>`,
      `<path d="M-128 -362 C-134 -458 -70 -490 0 -490 C70 -490 134 -458 128 -362 C118 -396 100 -414 80 -424 C60 -404 10 -398 -30 -404 C-70 -410 -104 -394 -128 -362 Z" fill="${c}"/>`],
    slick: c => ["", `<path d="M-122 -364 C-126 -450 -70 -484 0 -486 C72 -484 126 -450 122 -364 C112 -398 96 -416 80 -422 C30 -438 -30 -438 -80 -422 C-96 -416 -112 -398 -122 -364 Z" fill="${c}"/>
      <path d="M-70 -474 C-30 -486 30 -486 76 -466" stroke="${shade(c, 2.4)}" stroke-width="7" stroke-linecap="round" fill="none" opacity=".55"/>`],
    ponytail: c => [`<path d="M92 -450 C196 -440 224 -330 178 -232 C170 -282 138 -326 100 -352 Z" fill="${c}"/><ellipse cx="102" cy="-420" rx="14" ry="20" fill="#e06a7a" transform="rotate(20 102 -420)"/>`,
      `<path d="M-128 -362 C-134 -458 -70 -490 0 -490 C70 -490 134 -458 128 -362 C118 -396 100 -414 80 -424 C60 -404 10 -398 -30 -404 C-70 -410 -104 -394 -128 -362 Z" fill="${c}"/>`],
    buzz: c => ["", `<path d="M-122 -366 C-126 -438 -70 -472 0 -472 C70 -472 126 -438 122 -366 C110 -398 90 -414 60 -418 C20 -428 -20 -428 -60 -418 C-90 -414 -110 -398 -122 -366 Z" fill="${c}" opacity=".78"/>`],
    curly: c => ["", `<path d="M-124 -372 C-128 -436 128 -436 124 -372 Z" fill="${c}"/>
      <g fill="${c}"><circle cx="-98" cy="-424" r="36"/><circle cx="-54" cy="-458" r="38"/><circle cx="0" cy="-470" r="40"/><circle cx="54" cy="-458" r="38"/><circle cx="98" cy="-424" r="36"/><circle cx="-122" cy="-384" r="28"/><circle cx="122" cy="-384" r="28"/></g>`],
  };

  // -- clothes ---------------------------------------------------------------------------------------------------
  function outfitDetail(kind, base, skin) {
    const dk = shade(hexOf(base), 0.78), lt = shade(hexOf(base), 1.18);
    switch (kind) {
      case "suit": return `<path d="M-30 -256 L0 -196 L30 -256 Z" fill="#f4f4f7"/><path d="M-30 -256 L-6 -200 L-56 -150 L-84 -236 Z M30 -256 L6 -200 L56 -150 L84 -236 Z" fill="${dk}"/>`;
      case "hoodie": return `<path d="M-52 -258 C-40 -228 40 -228 52 -258 C30 -246 -30 -246 -52 -258 Z" fill="${dk}"/><rect x="-46" y="-140" width="92" height="40" rx="14" fill="${dk}" opacity=".7"/>`;
      case "cardigan": return `<path d="M-36 -256 L0 -170 L36 -256 Z" fill="#f2ead8"/><path d="M0 -190 L0 -100" stroke="${dk}" stroke-width="4"/><circle cx="-8" cy="-160" r="4" fill="${dk}"/><circle cx="-8" cy="-130" r="4" fill="${dk}"/>`;
      case "coat": return `<path d="M-36 -256 L0 -206 L36 -256 Z" fill="#e9e6ee"/><path d="M0 -206 L0 -96" stroke="${dk}" stroke-width="5"/><path d="M-36 -256 L-6 -206 L-50 -176 Z M36 -256 L6 -206 L50 -176 Z" fill="${lt}"/>`;
      case "dress": return `<path d="M-44 -256 C-20 -226 20 -226 44 -256 Z" fill="#fff4e6"/><path d="M-84 -160 L84 -160" stroke="${dk}" stroke-width="10" opacity=".6"/>`;
      case "sweater": return `<path d="M-46 -258 C-30 -224 30 -224 46 -258 C30 -244 -30 -244 -46 -258 Z" fill="${lt}"/><path d="M-84 -104 L84 -104" stroke="${dk}" stroke-width="8" opacity=".55"/>`;
      case "jacket": return `<path d="M-2 -256 L-2 -100" stroke="${dk}" stroke-width="5"/><path d="M-50 -256 L-2 -206 L-2 -256 Z" fill="${dk}"/><rect x="34" y="-190" width="40" height="34" rx="6" fill="${dk}" opacity=".75"/>`;
      default: return `<path d="M-44 -256 C-24 -232 24 -232 44 -256 Z" fill="${dk}"/>`;  // tee: round collar
    }
  }
  function hexOf(c) {  // "hsl(H S% L%)" -> "#rrggbb"
    if (c[0] === "#") return c;
    const m = c.match(/hsl\((\d+(?:\.\d+)?)[ ,]+(\d+(?:\.\d+)?)%[ ,]+(\d+(?:\.\d+)?)%/);
    const h = +m[1] / 360, s = +m[2] / 100, l = +m[3] / 100;
    const f = n => { const k = (n + h * 12) % 12, a = s * Math.min(l, 1 - l); return l - a * Math.max(-1, Math.min(k - 3, 9 - k, 1)); };
    const x = v => Math.round(v * 255).toString(16).padStart(2, "0");
    return "#" + x(f(0)) + x(f(8)) + x(f(4));
  }

  // -- accessories -------------------------------------------------------------------------------------------------
  const ACC = {
    tie: (o) => `<path d="M-12 -216 L12 -216 L18 -160 L0 -140 L-18 -160 Z" fill="#c0392b"/><path d="M-12 -216 L12 -216 L8 -204 L-8 -204 Z" fill="#96281b"/>`,
    scarf: (o) => `<path d="M-72 -252 C-40 -220 40 -220 72 -252 L76 -226 C40 -196 -40 -196 -76 -226 Z" fill="#e8c46a"/><path d="M44 -214 L74 -150 L48 -142 L30 -204 Z" fill="#d8b050"/>`,
    bags: (o) => `<path d="M-150 -272 C-148 -272 -148 -272 -150 -272" fill="none"/>`,
    glasses_round: (o) => `<g fill="rgba(255,255,255,.18)" stroke="#5b4636" stroke-width="7"><circle cx="-46" cy="-350" r="34"/><circle cx="46" cy="-350" r="34"/></g><path d="M-12 -352 L12 -352" stroke="#5b4636" stroke-width="7"/>`,
    glasses_rect: (o) => `<g fill="rgba(255,255,255,.18)" stroke="#2f3442" stroke-width="7"><rect x="-82" y="-372" width="68" height="46" rx="12"/><rect x="14" y="-372" width="68" height="46" rx="12"/></g><path d="M-14 -352 L14 -352" stroke="#2f3442" stroke-width="7"/>`,
    moon_pin: (o) => `<path d="M-100 -430 a20 20 0 1 0 22 26 a15 15 0 1 1 -22 -26 Z" fill="#f0d06a"/>`,
    stubble: (o) => `<g fill="#6a5040" opacity=".5">${[[-40, -270], [-20, -262], [0, -258], [20, -262], [40, -270], [-56, -282], [56, -282], [-8, -272], [10, -274], [-30, -278], [32, -280]].map(p => `<circle cx="${p[0]}" cy="${p[1]}" r="3"/>`).join("")}</g>`,
    circles: (o) => `<g fill="none" stroke="#7a5a6a" stroke-width="5" opacity=".35"><path d="M-64 -334 q18 12 36 0"/><path d="M28 -334 q18 12 36 0"/></g>`,
  };

  // -- faces: every variant exists once, the timeline switches them with opacity -------------------------------------
  const EYES = {
    normal: (c) => `<g fill="#2a2230"><ellipse cx="-46" cy="-352" rx="16" ry="22"/><ellipse cx="46" cy="-352" rx="16" ry="22"/></g><g fill="#fff"><circle cx="-41" cy="-360" r="6"/><circle cx="51" cy="-360" r="6"/><circle cx="-50" cy="-344" r="3"/><circle cx="42" cy="-344" r="3"/></g>`,
    happy: (c) => `<g fill="none" stroke="#2a2230" stroke-width="7" stroke-linecap="round"><path d="M-64 -344 Q-46 -370 -28 -344"/><path d="M28 -344 Q46 -370 64 -344"/></g>`,
    narrow: (c) => `<g fill="#2a2230"><ellipse cx="-46" cy="-346" rx="17" ry="19"/><ellipse cx="46" cy="-346" rx="17" ry="19"/></g><g fill="#fff"><circle cx="-41" cy="-346" r="4.5"/><circle cx="51" cy="-346" r="4.5"/></g>
      <g fill="${c}"><path d="M-70 -376 L-24 -350 L-24 -382 L-70 -382 Z"/><path d="M70 -376 L24 -350 L24 -382 L70 -382 Z"/></g><g stroke="#2a2230" stroke-width="5" stroke-linecap="round"><path d="M-66 -372 L-26 -350"/><path d="M66 -372 L26 -350"/></g>`,
    half: (c) => `<g fill="#2a2230"><ellipse cx="-46" cy="-348" rx="16" ry="20"/><ellipse cx="46" cy="-348" rx="16" ry="20"/></g><g fill="#fff"><circle cx="-42" cy="-354" r="5"/><circle cx="50" cy="-354" r="5"/></g>
      <g fill="${c}"><path d="M-66 -372 L-26 -372 L-26 -350 L-66 -350 Z"/><path d="M26 -372 L66 -372 L66 -350 L26 -350 Z"/></g><g stroke="#2a2230" stroke-width="5" stroke-linecap="round"><path d="M-64 -350 L-28 -350"/><path d="M28 -350 L64 -350"/></g>`,
    wide: (c) => `<g fill="#fff" stroke="#2a2230" stroke-width="4"><circle cx="-46" cy="-352" r="27"/><circle cx="46" cy="-352" r="27"/></g><g fill="#2a2230"><circle cx="-46" cy="-352" r="11"/><circle cx="46" cy="-352" r="11"/></g><g fill="#fff"><circle cx="-42" cy="-357" r="4"/><circle cx="50" cy="-357" r="4"/></g>`,
    down: (c) => `<g fill="#2a2230"><ellipse cx="-46" cy="-342" rx="16" ry="18"/><ellipse cx="46" cy="-342" rx="16" ry="18"/></g><g fill="${c}"><path d="M-66 -366 L-26 -366 L-26 -348 L-66 -348 Z"/><path d="M26 -366 L66 -366 L66 -348 L26 -348 Z"/></g><g stroke="#2a2230" stroke-width="5" stroke-linecap="round"><path d="M-64 -348 Q-46 -340 -28 -348"/><path d="M28 -348 Q46 -340 64 -348"/></g>`,
    sad: (c) => `<g fill="#2a2230"><ellipse cx="-46" cy="-350" rx="17" ry="23"/><ellipse cx="46" cy="-350" rx="17" ry="23"/></g><g fill="#fff"><circle cx="-40" cy="-359" r="8"/><circle cx="52" cy="-359" r="8"/><circle cx="-52" cy="-342" r="4"/><circle cx="40" cy="-342" r="4"/></g>`,
  };
  // brow poses: [left rotation, right rotation, lift]; positive left rotation = inner end down (angry)
  const BROW = {
    neutral: [0, 0, 0], soft: [-4, 4, -2], angry: [22, -22, 4], sad: [-18, 18, -2], up: [-4, 4, -16], cold: [6, -6, 4],
    worried: [-12, 12, -8], smug: [-10, 14, -4],
  };
  const MOUTH = {
    flat: `<path d="M-20 4 L20 4" stroke="#3a2630" stroke-width="7" stroke-linecap="round"/>`,
    smile_small: `<path d="M-22 -2 Q0 18 22 -2" stroke="#3a2630" stroke-width="7" stroke-linecap="round" fill="none"/>`,
    smile: `<path d="M-30 -4 Q0 26 30 -4" stroke="#3a2630" stroke-width="7" stroke-linecap="round" fill="none"/>`,
    smile_open: `<path d="M-32 -6 Q0 40 32 -6 Z" fill="#3a2630"/><path d="M-16 14 Q0 26 16 14 Q0 8 -16 14 Z" fill="#e8737f"/>`,
    frown: `<path d="M-24 14 Q0 -10 24 14" stroke="#3a2630" stroke-width="7" stroke-linecap="round" fill="none"/>`,
    frown_small: `<path d="M-16 12 Q0 -2 16 12" stroke="#3a2630" stroke-width="7" stroke-linecap="round" fill="none"/>`,
    open_s: `<ellipse cx="0" cy="6" rx="16" ry="12" fill="#3a2630"/><ellipse cx="0" cy="14" rx="9" ry="5" fill="#e8737f"/>`,
    open_l: `<path d="M-26 -4 Q0 -8 26 -4 Q28 34 0 36 Q-28 34 -26 -4 Z" fill="#3a2630"/><path d="M-20 -2 Q0 -6 20 -2 L18 8 Q0 5 -18 8 Z" fill="#fff"/><ellipse cx="0" cy="24" rx="12" ry="7" fill="#e8737f"/>`,
    o: `<ellipse cx="0" cy="8" rx="11" ry="14" fill="#3a2630"/>`,
    smirk: `<path d="M-22 8 Q8 10 26 -8" stroke="#3a2630" stroke-width="7" stroke-linecap="round" fill="none"/>`,
    grit: `<rect x="-30" y="-6" width="60" height="26" rx="8" fill="#fff" stroke="#3a2630" stroke-width="6"/><path d="M-10 -6 V20 M10 -6 V20 M0 -6 V20" stroke="#3a2630" stroke-width="3"/>`,
    shout: `<path d="M-32 14 Q0 -20 32 14 Q24 46 0 48 Q-24 46 -32 14 Z" fill="#3a2630"/><path d="M-24 8 Q0 -8 24 8 L20 18 Q0 8 -20 18 Z" fill="#fff"/><ellipse cx="0" cy="36" rx="14" ry="7" fill="#e8737f"/>`,
    wobble: `<path d="M-26 8 Q-13 -6 0 8 T26 8" stroke="#3a2630" stroke-width="6" stroke-linecap="round" fill="none"/>`,
  };
  const FX = {
    sweat: `<path d="M118 -400 C104 -376 102 -356 118 -350 C134 -356 132 -376 118 -400 Z" fill="#8fd0f0" stroke="#5aa8d0" stroke-width="3"/>`,
    vein: `<g stroke="#e0443c" stroke-width="7" stroke-linecap="round" fill="none"><path d="M-104 -448 q10 -8 20 0 M-98 -456 q0 12 -10 20 M-84 -448 q10 8 4 20"/></g>`,
    tear: `<path d="M-64 -318 C-72 -300 -72 -290 -64 -284 C-56 -290 -56 -300 -64 -318 Z" fill="#8fd0f0" stroke="#5aa8d0" stroke-width="3"/>`,
    spark: `<g fill="#ffe27a"><path d="M118 -440 l6 16 16 6 -16 6 -6 16 -6 -16 -16 -6 16 -6 Z"/><path d="M-120 -420 l4 10 10 4 -10 4 -4 10 -4 -10 -10 -4 10 -4 Z"/></g>`,
    bang: `<g fill="#e0443c"><rect x="106" y="-470" width="14" height="34" rx="7"/><circle cx="113" cy="-418" r="8"/></g>`,
    ques: `<text x="110" y="-424" font-size="56" font-weight="700" fill="#5a6fd0" font-family="sans-serif">?</text>`,
  };
  // feeling (the world's word) -> how the face is drawn
  const EXPR = {
    neutral:     { eyes: "normal", brow: "neutral", mouth: "flat",        blush: 0 },
    calm:        { eyes: "normal", brow: "neutral", mouth: "smile_small", blush: 0 },
    warm:        { eyes: "happy",  brow: "soft",    mouth: "smile",       blush: 0.55 },
    happy:       { eyes: "happy",  brow: "up",      mouth: "smile_open",  blush: 0.6, fx: "spark" },
    distant:     { eyes: "half",   brow: "cold",    mouth: "flat",        blush: 0 },
    cold:        { eyes: "half",   brow: "cold",    mouth: "flat",        blush: 0 },
    hurt:        { eyes: "sad",    brow: "sad",     mouth: "frown_small", blush: 0.15, fx: "tear" },
    angry:       { eyes: "narrow", brow: "angry",   mouth: "grit",        blush: 0.2, fx: "vein" },
    tense:       { eyes: "normal", brow: "worried", mouth: "wobble",      blush: 0,    fx: "sweat" },
    shocked:     { eyes: "wide",   brow: "up",      mouth: "o",           blush: 0,    fx: "bang" },
    uneasy:      { eyes: "down",   brow: "worried", mouth: "wobble",      blush: 0.1,  fx: "sweat" },
    curious:     { eyes: "normal", brow: "smug",    mouth: "smile_small", blush: 0,    fx: "ques" },
    ashamed:     { eyes: "down",   brow: "worried", mouth: "flat",        blush: 0.7,  fx: "sweat" },
    embarrassed: { eyes: "down",   brow: "soft",    mouth: "smile_small", blush: 0.8 },
    smug:        { eyes: "half",   brow: "smug",    mouth: "smirk",       blush: 0 },
  };
  // how wide the mouth opens while speaking, by feeling
  const TALK = { angry: "shout", shocked: "open_l", happy: "open_l", tense: "open_s", hurt: "open_s", default: "open_s" };

  // -- arms ----------------------------------------------------------------------------------------------------------
  const POSES = {  // [left arm path (from shoulder to hand), right arm path]
    down:    ["M-70 -232 Q-108 -184 -96 -126", "M70 -232 Q108 -184 96 -126"],
    crossed: ["M-70 -232 Q-92 -160 30 -168", "M70 -232 Q92 -150 -30 -150"],
    point:   ["M-70 -232 Q-108 -184 -96 -126", "M70 -236 Q150 -230 178 -290"],
    shock:   ["M-70 -232 Q-138 -250 -100 -322", "M70 -232 Q138 -250 100 -322"],
    hold:    ["M-70 -232 Q-110 -170 -34 -150", "M70 -232 Q110 -170 34 -150"],
    hips:    ["M-70 -232 Q-128 -190 -78 -150", "M70 -232 Q128 -190 78 -150"],
  };
  const HAND_R = 19;

  function pathEnd(d) { const n = d.match(/-?\d+(?:\.\d+)?/g).map(Number); return [n[n.length - 2], n[n.length - 1]]; }

  let uid = 0;
  /* Returns an <g> for one person. Parts are addressed by class: .pose-<name>, .eyes-<name>, .brow, .mouth-<name>,
     .fx-<name>, .blush, .body (breathing), .head (nodding), .blink. */
  function makeCharacter(id, hue) {
    const d = designFor(id), k = ++uid;
    const skin = SKINS[d.skin], skinDk = shade(skin, 0.86), hair = d.hairColor;
    const outfit = hsl(hue, 58, 56), outfitDk = hsl(hue, 58, 44), sleeve = outfit;
    const [hairBack, hairFront] = HAIR[d.hair](hair);
    const arms = Object.entries(POSES).map(([name, [l, r]]) => {
      const [lx, ly] = pathEnd(l), [rx, ry] = pathEnd(r);
      return `<g class="pose pose-${name}" opacity="${name === "down" ? 1 : 0}">
        <path d="${l}" stroke="${sleeve}" stroke-width="36" stroke-linecap="round" fill="none"/><circle cx="${lx}" cy="${ly}" r="${HAND_R}" fill="${skin}"/>
        <path d="${r}" stroke="${sleeve}" stroke-width="36" stroke-linecap="round" fill="none"/><circle cx="${rx}" cy="${ry}" r="${HAND_R}" fill="${skin}"/></g>`;
    }).join("");
    const eyes = Object.entries(EYES).map(([n, f]) => `<g class="eyes eyes-${n}" opacity="${n === "normal" ? 1 : 0}">${f(skin)}</g>`).join("");
    const mouths = Object.entries(MOUTH).map(([n, s]) => `<g class="mouth mouth-${n}" transform="translate(0 -304)" opacity="${n === "flat" ? 1 : 0}">${s}</g>`).join("");
    const fx = Object.entries(FX).map(([n, s]) => `<g class="fx fx-${n}" opacity="0">${s}</g>`).join("");
    const acc = d.acc.map(a => ACC[a](d)).join("");
    const glasses = d.acc.some(a => a.startsWith("glasses"));
    const svg = `
      <ellipse class="shadow" cx="0" cy="2" rx="104" ry="15" fill="rgba(20,16,30,.22)"/>
      <g class="body">
        ${hairBack}
        <g class="legs"><rect x="-56" y="-108" width="44" height="100" rx="20" fill="${d.pants}"/><rect x="12" y="-108" width="44" height="100" rx="20" fill="${d.pants}"/>
          <ellipse cx="-36" cy="-6" rx="34" ry="15" fill="#2a2630"/><ellipse cx="36" cy="-6" rx="34" ry="15" fill="#2a2630"/></g>
        <rect class="torso" x="-82" y="-260" width="164" height="170" rx="48" fill="${outfit}"/>
        <g class="outfit">${outfitDetail(d.outfit, outfit, skin)}</g>
        ${acc.includes("scarf") || d.outfit === "hoodie" ? "" : ""}
        ${arms}
        <rect x="-19" y="-268" width="38" height="34" rx="12" fill="${skinDk}"/>
        <g class="head">
          <circle cx="-118" cy="-352" r="22" fill="${skinDk}"/><circle cx="118" cy="-352" r="22" fill="${skinDk}"/>
          <ellipse cx="0" cy="-360" rx="122" ry="112" fill="${skin}"/>
          <ellipse cx="0" cy="-262" rx="86" ry="14" fill="${skinDk}" opacity=".35"/>
          <ellipse class="blush" cx="-72" cy="-320" rx="24" ry="13" fill="#ff8f96" opacity="0"/>
          <ellipse class="blush" cx="72" cy="-320" rx="24" ry="13" fill="#ff8f96" opacity="0"/>
          <g class="blink"><g class="eyeset">${eyes}</g></g>
          <g class="brows" stroke="${shade(hair, 1.15)}" stroke-width="9" stroke-linecap="round" fill="none">
            <path class="brow brow-l" d="M-66 -398 L-24 -398"/>
            <path class="brow brow-r" d="M24 -398 L66 -398"/>
          </g>
          <path d="M-5 -326 Q0 -320 5 -326" stroke="${skinDk}" stroke-width="5" stroke-linecap="round" fill="none"/>
          ${mouths}
          ${hairFront}
          ${acc}
          ${fx}
        </g>
      </g>`;
    const g = document.createElementNS("http://www.w3.org/2000/svg", "g");
    g.setAttribute("class", "person"); g.setAttribute("data-id", id);
    g.innerHTML = svg;
    return g;
  }

  // Everything a timeline needs to pose one character at a moment. `tl.set` only, so any frame can be seeked to.
  function express(tl, g, t, feeling, pose) {
    const e = EXPR[feeling] || EXPR.neutral;
    tl.set(g.querySelectorAll(".eyes"), { opacity: 0 }, t);
    tl.set(g.querySelector(".eyes-" + e.eyes), { opacity: 1 }, t);
    tl.set(g.querySelectorAll(".mouth"), { opacity: 0 }, t);
    tl.set(g.querySelector(".mouth-" + e.mouth), { opacity: 1 }, t);
    tl.set(g.querySelectorAll(".fx"), { opacity: 0 }, t);
    if (e.fx) tl.set(g.querySelector(".fx-" + e.fx), { opacity: 1 }, t);
    tl.set(g.querySelectorAll(".blush"), { opacity: e.blush }, t);
    const [lr, rr, lift] = BROW[e.brow];
    // inner ends: the left brow's inner end is its right end, so its rotation pivot is there
    tl.set(g.querySelector(".brow-l"), { svgOrigin: "-24 -398", rotation: lr, y: lift }, t);
    tl.set(g.querySelector(".brow-r"), { svgOrigin: "24 -398", rotation: rr, y: lift }, t);
    if (pose) {
      tl.set(g.querySelectorAll(".pose"), { opacity: 0 }, t);
      tl.set(g.querySelector(".pose-" + pose), { opacity: 1 }, t);
    }
  }

  // Speaking: the mouth flaps between open and closed on a fixed pattern derived from the text, so it is the same
  // every time. Returns the time the last flap ends.
  function talk(tl, g, t0, seconds, feeling, text) {
    const e = EXPR[feeling] || EXPR.neutral, open = TALK[feeling] || TALK.default;
    const h = hash(text), step = 0.14;
    const n = Math.max(2, Math.floor(seconds / step));
    for (let i = 0; i < n; i++) {
      const t = t0 + i * step, isOpen = ((h >> (i % 24)) & 1) === 1 || i % 3 === 0;
      tl.set(g.querySelectorAll(".mouth"), { opacity: 0 }, t);
      tl.set(g.querySelector(".mouth-" + (isOpen ? open : e.mouth)), { opacity: 1 }, t);
    }
    tl.set(g.querySelectorAll(".mouth"), { opacity: 0 }, t0 + n * step);
    tl.set(g.querySelector(".mouth-" + e.mouth), { opacity: 1 }, t0 + n * step);
    return t0 + n * step;
  }

  // Blinks at fixed, person-specific moments across [t0, t1].
  function blinks(tl, g, t0, t1, seed) {
    let t = t0 + 0.8 + (hash(seed) % 100) / 100;
    while (t < t1 - 0.3) {
      tl.set(g.querySelector(".blink"), { svgOrigin: "0 -350", scaleY: 0.08 }, t);
      tl.set(g.querySelector(".blink"), { svgOrigin: "0 -350", scaleY: 1 }, t + 0.11);
      t += 2.2 + ((hash(seed + Math.round(t * 10)) % 140) / 100);
    }
  }

  window.CAST = { makeCharacter, express, talk, blinks, designFor, EXPR, POSES, hexOf, hsl, hash, shade, SKINS };
})();
