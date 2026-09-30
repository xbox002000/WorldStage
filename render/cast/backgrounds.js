/* Cast: the town's places as flat vector rooms and outdoors. `place(id, time, weather)` returns the SVG markup for
   one 1080x1920 background, lighting and weather baked in (each shot gets its own instance), plus where the floor
   is. Characters stand with their feet at FLOOR_Y. Nothing here moves except what a timeline asks for by id. */
(function () {
  const W = 1080, H = 1920;
  const FLOOR_Y = 1390;

  let n = 0;
  const uid = p => `${p}${++n}`;

  // How each time of day tints the picture (multiplied over everything) and how strongly lamps glow.
  const TOD = {
    day:   { tint: "#ffffff", a: 0.0,  lamp: 0.10, sky: ["#bfe4f7", "#f8f3df"] },
    dusk:  { tint: "#e08a4c", a: 0.30, lamp: 0.65, sky: ["#f59a62", "#7d5aa6"] },
    night: { tint: "#1a2650", a: 0.55, lamp: 1.00, sky: ["#0f1838", "#2d3766"] },
  };
  const WEATHER_VEIL = { clear: null, cloudy: ["#8f9bb0", 0.16], rain: ["#5a7398", 0.24], fog: ["#e4e8ee", 0.30] };

  function lampGlow(x, y, r, k, id) {
    return `<circle cx="${x}" cy="${y}" r="${r}" fill="url(#${id})" opacity="${k}" style="mix-blend-mode:screen"/>`;
  }
  function radial(id, c, a0 = 0.9) {
    return `<radialGradient id="${id}"><stop offset="0" stop-color="${c}" stop-opacity="${a0}"/><stop offset="1" stop-color="${c}" stop-opacity="0"/></radialGradient>`;
  }

  // lighting overlay shared by every place: time tint, weather veil, vignette
  function finish(time, weather, extra = "") {
    const t = TOD[time], v = WEATHER_VEIL[weather], g = uid("vg");
    return `${extra}
      ${t.a ? `<rect width="${W}" height="${H}" fill="${t.tint}" opacity="${t.a}" style="mix-blend-mode:multiply"/>` : ""}
      ${v ? `<rect width="${W}" height="${H}" fill="${v[0]}" opacity="${v[1]}"/>` : ""}
      <defs><radialGradient id="${g}" cx=".5" cy=".46" r=".75"><stop offset=".55" stop-color="#000" stop-opacity="0"/><stop offset="1" stop-color="#0a0812" stop-opacity=".42"/></radialGradient></defs>
      <rect width="${W}" height="${H}" fill="url(#${g})"/>`;
  }

  // window view shared by rooms: sky by time, far buildings, weather
  function windowView(x, y, w, h, time, weather) {
    const t = TOD[time], g = uid("sky"), c = uid("clip");
    const lights = time === "night" ? Array.from({ length: 26 }, (_, i) => {
      const bx = x + 20 + (i * 47) % (w - 40), by = y + h * 0.5 + ((i * 89) % (h * 0.42));
      return `<rect x="${bx}" y="${by}" width="7" height="9" fill="#ffd76a" opacity="${0.5 + (i % 4) * 0.12}"/>`; }).join("") : "";
    const bld = [[0, .52, .16], [.14, .4, .14], [.3, .58, .18], [.5, .46, .13], [.64, .36, .17], [.82, .5, .18]].map(([bx, bh, bw], i) =>
      `<rect x="${x + bx * w}" y="${y + h * (1 - bh)}" width="${bw * w}" height="${h * bh}" fill="${time === "night" ? "#1a2244" : "#b7a59a"}" opacity="${0.75 - (i % 2) * 0.15}"/>`).join("");
    const sun = time === "dusk" ? `<circle cx="${x + w * 0.7}" cy="${y + h * 0.62}" r="${w * 0.11}" fill="#ffd9a0" opacity=".9"/>`
      : time === "night" ? `<circle cx="${x + w * 0.72}" cy="${y + h * 0.2}" r="${w * 0.07}" fill="#f6f1d0"/>` : "";
    const cloud = weather === "cloudy" || weather === "rain" || weather === "fog" ? `<g fill="#fff" opacity=".7"><ellipse cx="${x + w * 0.3}" cy="${y + h * 0.25}" rx="${w * 0.24}" ry="${h * 0.05}"/><ellipse cx="${x + w * 0.6}" cy="${y + h * 0.33}" rx="${w * 0.28}" ry="${h * 0.045}"/></g>` : "";
    return `<defs><linearGradient id="${g}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${t.sky[0]}"/><stop offset="1" stop-color="${t.sky[1]}"/></linearGradient>
      <clipPath id="${c}"><rect x="${x}" y="${y}" width="${w}" height="${h}" rx="18"/></clipPath></defs>
      <g clip-path="url(#${c})"><rect x="${x}" y="${y}" width="${w}" height="${h}" fill="url(#${g})"/>${sun}${cloud}${bld}${lights}
      ${weather === "fog" ? `<rect x="${x}" y="${y}" width="${w}" height="${h}" fill="#eef1f5" opacity=".55"/>` : ""}</g>`;
  }

  // -- 咖啡店 --------------------------------------------------------------------------------------------------------
  function cafe(time, weather) {
    const t = TOD[time], wall = uid("wall"), floor = uid("floor"), wood = uid("wood"), glow = uid("glow");
    const lamps = [250, 560, 880].map((x, i) => {
      const drop = [170, 214, 186][i];
      return `<line x1="${x}" y1="70" x2="${x}" y2="${drop - 56}" stroke="#3b2b20" stroke-width="5"/>
        <path d="M${x - 58} ${drop} L${x + 58} ${drop} L${x + 26} ${drop - 56} L${x - 26} ${drop - 56} Z" fill="#e9a24a"/>
        <ellipse cx="${x}" cy="${drop + 2}" rx="30" ry="11" fill="#fff3c4"/>`;
    }).join("");
    const glows = [250, 560, 880].map((x, i) => lampGlow(x, [200, 244, 216][i] + 40, 300, 0.25 + t.lamp * 0.6, glow)).join("");
    const planks = Array.from({ length: 13 }, (_, i) => {
      const y = 1150 + Math.pow(i, 1.55) * 15 + i * 4;
      return `<line x1="0" y1="${y}" x2="${W}" y2="${y}" stroke="#6d4a2f" stroke-width="${2 + i * 0.5}" opacity=".35"/>`;
    }).join("");
    const chalk = [[40, 60, 220], [40, 100, 160], [40, 140, 250], [40, 180, 200], [40, 222, 120]].map(([x, y, w]) =>
      `<path d="M${x + 24} ${y + 30} h${w}" stroke="#f4f1e6" stroke-width="7" stroke-linecap="round" opacity=".8"/>`).join("");
    const jars = [[20, "#e2c48a", 54], [80, "#b9d4b5", 44], [140, "#d9a09a", 58], [200, "#e6d8b8", 48], [260, "#a9c5d8", 52], [320, "#e2c48a", 44]].map(([x, c, h]) =>
      `<rect x="${70 + x}" y="${616 - h}" width="42" height="${h}" rx="9" fill="${c}"/><rect x="${70 + x + 4}" y="${616 - h - 8}" width="34" height="10" rx="4" fill="#7a5636"/>`).join("");
    return {
      floorY: FLOOR_Y, indoor: true, window: { x: 616, y: 186, w: 388, h: 618 },
      svg: `<defs>
        <linearGradient id="${wall}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#f6e6cc"/><stop offset="1" stop-color="#e7cba3"/></linearGradient>
        <linearGradient id="${floor}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#c99968"/><stop offset="1" stop-color="#94683f"/></linearGradient>
        <linearGradient id="${wood}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#d3a676"/><stop offset="1" stop-color="#b78555"/></linearGradient>
        ${radial(glow, "#ffd58a")}</defs>
      <rect width="${W}" height="1160" fill="url(#${wall})"/>
      <rect width="${W}" height="70" fill="#6d4c33"/><rect y="70" width="${W}" height="12" fill="#5a3e29"/>
      <rect y="880" width="${W}" height="280" fill="#c79a6a"/>
      ${Array.from({ length: 10 }, (_, i) => `<rect x="${i * 120 + 8}" y="900" width="104" height="236" rx="6" fill="#b98a5d" opacity=".55"/>`).join("")}
      <rect y="872" width="${W}" height="12" fill="#e0bd8e"/>
      <g transform="translate(600 170)"><rect width="420" height="650" rx="34" fill="#74502f"/><g transform="translate(16 16)">${windowView(0, 0, 388, 618, time, weather)}</g>
        <path d="M210 16 V634 M16 240 H404 M16 430 H404" stroke="#74502f" stroke-width="12"/><rect x="-20" y="640" width="460" height="28" rx="8" fill="#8a6440"/></g>
      <g transform="translate(70 240)"><rect width="400" height="320" rx="16" fill="#6b4a2f"/><rect x="14" y="14" width="372" height="292" rx="8" fill="#2c3a36"/>${chalk}
        <circle cx="330" cy="70" r="26" fill="none" stroke="#f4f1e6" stroke-width="6"/><path d="M356 60 q22 4 4 26" fill="none" stroke="#f4f1e6" stroke-width="6"/></g>
      <rect x="60" y="616" width="420" height="16" rx="6" fill="#8a6440"/>${jars}
      <g transform="translate(120 640)"><rect width="200" height="120" rx="14" fill="#c7ccd4"/><rect x="14" y="-24" width="172" height="30" rx="10" fill="#aab1bb"/>
        <circle cx="44" cy="40" r="14" fill="#4a5060"/><circle cx="90" cy="40" r="14" fill="#4a5060"/><rect x="128" y="24" width="48" height="60" rx="8" fill="#8890a0"/>
        <rect x="70" y="94" width="60" height="22" rx="6" fill="#2b2f3a"/></g>
      <rect x="-10" y="760" width="560" height="40" rx="12" fill="#e6c79a"/><rect y="792" width="540" height="372" fill="url(#${wood})"/>
      ${[0, 1, 2].map(i => `<rect x="${24 + i * 172}" y="828" width="150" height="290" rx="10" fill="#a87a4e" opacity=".55"/>`).join("")}
      <g transform="translate(400 692)"><path d="M-4 66 a70 66 0 0 1 148 0 Z" fill="#dff1f5" opacity=".7" stroke="#b6d3da" stroke-width="4"/><rect x="-14" y="64" width="168" height="14" rx="6" fill="#c9d7db"/>
        <path d="M30 60 l40 -30 l40 30 Z" fill="#f2c9a0"/><path d="M30 60 h80" stroke="#b76a52" stroke-width="8"/></g>
      <rect y="1156" width="${W}" height="14" fill="#7a5636"/>
      <rect y="1168" width="${W}" height="${H - 1168}" fill="url(#${floor})"/>${planks}
      <ellipse cx="540" cy="${FLOOR_Y + 8}" rx="430" ry="70" fill="#b0503f" opacity=".5"/><ellipse cx="540" cy="${FLOOR_Y + 8}" rx="392" ry="54" fill="none" stroke="#f0d9b0" stroke-width="6" opacity=".55"/>
      ${lamps}${glows}
      <path d="M640 840 L1010 840 L1080 1380 L500 1380 Z" fill="#fff6dc" opacity="${time === "day" ? 0.16 : 0.05}"/>`,
      overlay: finish(time, weather),
    };
  }

  // -- 公園 ----------------------------------------------------------------------------------------------------------
  function park(time, weather) {
    const t = TOD[time], sky = uid("sky"), grass = uid("grass"), glow = uid("glow");
    const tree = (x, y, s, dark) => `<g transform="translate(${x} ${y}) scale(${s})"><rect x="-22" y="-20" width="44" height="220" rx="16" fill="#7a5638"/>
      <g fill="${dark ? "#4f9455" : "#66b361"}"><circle cx="0" cy="-90" r="120"/><circle cx="-92" cy="-30" r="84"/><circle cx="92" cy="-30" r="84"/><circle cx="-40" cy="-170" r="70"/><circle cx="52" cy="-160" r="74"/></g>
      <g fill="#fff" opacity=".12"><circle cx="-30" cy="-120" r="62"/></g></g>`;
    return {
      floorY: FLOOR_Y,
      svg: `<defs><linearGradient id="${sky}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${t.sky[0]}"/><stop offset="1" stop-color="${t.sky[1]}"/></linearGradient>
        <linearGradient id="${grass}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#8ec86a"/><stop offset="1" stop-color="#5e9e4f"/></linearGradient>${radial(glow, "#ffe19a")}</defs>
      <rect width="${W}" height="1080" fill="url(#${sky})"/>
      ${time === "night" ? `<circle cx="820" cy="260" r="70" fill="#f6f1d0"/>` : time === "dusk" ? `<circle cx="780" cy="820" r="120" fill="#ffd9a0" opacity=".85"/>` : `<circle cx="820" cy="240" r="78" fill="#fff6c8" opacity=".9"/>`}
      ${weather !== "clear" ? `<g fill="#fff" opacity=".75"><ellipse cx="260" cy="260" rx="200" ry="46"/><ellipse cx="380" cy="300" rx="180" ry="40"/><ellipse cx="800" cy="420" rx="220" ry="44"/></g>` : ""}
      <path d="M0 900 C160 780 320 800 470 880 C600 800 800 790 1080 890 L1080 1140 L0 1140 Z" fill="#8fbf86"/>
      <path d="M0 960 C220 880 420 920 620 960 C800 900 940 910 1080 950 L1080 1160 L0 1160 Z" fill="#79b06f"/>
      ${tree(140, 880, 0.55, true)}${tree(960, 900, 0.6, true)}
      <rect y="1050" width="${W}" height="${H - 1050}" fill="url(#${grass})"/>
      <path d="M470 1050 C520 1150 400 1250 300 1390 C240 1480 200 1600 140 1920 L820 1920 C760 1700 700 1560 690 1420 C680 1300 640 1140 600 1050 Z" fill="#ecdcb4"/>
      ${tree(120, 1090, 1.0, false)}${tree(1000, 1120, 1.05, false)}
      <g transform="translate(790 1230)"><rect x="-150" y="-70" width="300" height="26" rx="8" fill="#a36f47"/><rect x="-150" y="-118" width="300" height="20" rx="8" fill="#b57e50"/><rect x="-150" y="-98" width="16" height="70" fill="#7a5638"/><rect x="134" y="-98" width="16" height="70" fill="#7a5638"/><rect x="-124" y="-44" width="16" height="70" fill="#5a4630"/><rect x="108" y="-44" width="16" height="70" fill="#5a4630"/></g>
      <g transform="translate(250 1250)"><rect x="-9" y="-330" width="18" height="340" rx="8" fill="#3b3f4a"/><path d="M-40 -330 L40 -330 L26 -390 L-26 -390 Z" fill="#3b3f4a"/><ellipse cx="0" cy="-322" rx="30" ry="12" fill="#fff3c4"/>
        ${lampGlow(0, -320, 260, 0.25 + t.lamp * 0.6, glow)}</g>
      ${Array.from({ length: 24 }, (_, i) => `<circle cx="${(i * 197) % 1000 + 40}" cy="${1500 + (i * 131) % 380}" r="${5 + i % 3}" fill="${["#ffd76a", "#ff8fa3", "#fff", "#c9a0ff"][i % 4]}"/>`).join("")}
      <ellipse cx="540" cy="${FLOOR_Y + 6}" rx="330" ry="46" fill="#2f5f3a" opacity=".22"/>`,
      overlay: finish(time, weather),
    };
  }

  // -- 公寓（一個人的房間） -----------------------------------------------------------------------------------------------
  function apartment(time, weather) {
    const t = TOD[time], wall = uid("wall"), floor = uid("floor"), glow = uid("glow");
    const boards = Array.from({ length: 12 }, (_, i) => {
      const y = 1180 + Math.pow(i, 1.5) * 16 + i * 5;
      return `<line x1="0" y1="${y}" x2="${W}" y2="${y}" stroke="#5a4636" stroke-width="${2 + i * 0.4}" opacity=".3"/>`;
    }).join("");
    return {
      floorY: FLOOR_Y, indoor: true, window: { x: 130, y: 250, w: 360, h: 470 },
      svg: `<defs>
        <linearGradient id="${wall}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#d9e0ea"/><stop offset="1" stop-color="#b9c4d4"/></linearGradient>
        <linearGradient id="${floor}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#a88a6c"/><stop offset="1" stop-color="#7a5f47"/></linearGradient>
        ${radial(glow, "#ffe0a0")}</defs>
      <rect width="${W}" height="1180" fill="url(#${wall})"/>
      ${Array.from({ length: 9 }, (_, i) => `<rect x="${i * 128}" y="0" width="64" height="1180" fill="#ffffff" opacity=".06"/>`).join("")}
      <g transform="translate(110 230)"><rect width="400" height="510" rx="20" fill="#f4f1ea"/><g transform="translate(20 20)">${windowView(0, 0, 360, 470, time, weather)}</g>
        <path d="M200 20 V490 M20 250 H380" stroke="#f4f1ea" stroke-width="12"/><rect x="-24" y="506" width="448" height="24" rx="8" fill="#e2ddd2"/></g>
      <g transform="translate(560 300)"><rect width="160" height="210" rx="10" fill="#8a6440"/><rect x="12" y="12" width="136" height="186" rx="6" fill="#f2c9a0"/>
        <circle cx="80" cy="84" r="34" fill="#e08a4c" opacity=".7"/><path d="M12 170 L60 120 L100 150 L148 110 V198 H12 Z" fill="#7fae6a" opacity=".8"/></g>
      <rect y="1170" width="${W}" height="16" fill="#6d5644"/>
      <rect y="1184" width="${W}" height="${H - 1184}" fill="url(#${floor})"/>${boards}
      <g transform="translate(700 1060)"><rect x="0" y="0" width="380" height="120" rx="20" fill="#6f86b0"/><rect x="0" y="-40" width="380" height="60" rx="24" fill="#f4f1ea"/>
        <rect x="20" y="-70" width="120" height="50" rx="20" fill="#ffffff"/><rect x="-10" y="-160" width="30" height="300" rx="10" fill="#5a4636"/></g>
      <g transform="translate(560 1040)"><rect x="-60" y="0" width="120" height="100" rx="10" fill="#8a6440"/><rect x="-66" y="-10" width="132" height="16" rx="6" fill="#a37a52"/>
        <rect x="-8" y="-120" width="16" height="110" fill="#3b3f4a"/><path d="M-50 -120 L50 -120 L30 -180 L-30 -180 Z" fill="#f2d07a"/>
        ${lampGlow(0, -130, 320, 0.3 + t.lamp * 0.7, glow)}</g>
      <ellipse cx="420" cy="${FLOOR_Y + 8}" rx="330" ry="54" fill="#5a6f94" opacity=".35"/>`,
      overlay: finish(time, weather),
    };
  }

  const PLACES = { cafe, park, apartment };
  function place(id, time, weather) { return (PLACES[id] || cafe)(time, weather); }

  window.PLACES = { place, FLOOR_Y, W, H };
})();
