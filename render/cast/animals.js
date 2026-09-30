/* Cast: animals, drawn like the people (flat, round, seekable). A dog seen from the side, facing right, origin at its
   feet, about 170 units tall where a person is 520. Parts by class: .tail (wags), .ear, .tongue, .eyes-*, .mouthslot
   (where a carried thing is attached), .body (breathing). */
(function () {
  const FUR = { dog: ["#d9a066", "#b9793f", "#f3d7b0"] };

  function makeAnimal(id, species) {
    const [fur, dark, light] = FUR[species] || FUR.dog;
    const g = document.createElementNS("http://www.w3.org/2000/svg", "g");
    g.setAttribute("class", "animal"); g.setAttribute("data-id", id);
    g.innerHTML = `
      <ellipse class="shadow" cx="0" cy="2" rx="96" ry="13" fill="rgba(20,16,30,.22)"/>
      <g class="body">
        <g class="tail" transform="translate(-78 -104)"><path d="M0 0 C-30 -10 -44 -46 -30 -76" stroke="${fur}" stroke-width="20" stroke-linecap="round" fill="none"/></g>
        <rect x="-70" y="-78" width="24" height="76" rx="11" fill="${dark}"/><rect x="30" y="-78" width="24" height="76" rx="11" fill="${dark}"/>
        <ellipse cx="-4" cy="-98" rx="86" ry="44" fill="${fur}"/>
        <ellipse cx="40" cy="-84" rx="36" ry="24" fill="${light}"/>
        <rect x="-48" y="-78" width="24" height="78" rx="11" fill="${fur}"/><rect x="52" y="-78" width="24" height="78" rx="11" fill="${fur}"/>
        <ellipse cx="-36" cy="-2" rx="16" ry="7" fill="${dark}"/><ellipse cx="64" cy="-2" rx="16" ry="7" fill="${dark}"/>
        <path d="M58 -126 q16 12 34 2" stroke="#c8453a" stroke-width="10" stroke-linecap="round" fill="none"/>
        <circle cx="78" cy="-116" r="7" fill="#f2c14a"/>
        <g class="head">
          <circle cx="92" cy="-150" r="44" fill="${fur}"/>
          <ellipse cx="128" cy="-134" rx="30" ry="21" fill="${light}"/>
          <ellipse cx="152" cy="-142" rx="10" ry="8" fill="#2a2226"/>
          <path d="M126 -122 q12 8 26 0" stroke="#5a3a2a" stroke-width="4" stroke-linecap="round" fill="none"/>
          <g class="tongue" opacity="0"><path d="M132 -120 q6 22 16 0 Z" fill="#ff8a95"/></g>
          <g class="eyes eyes-normal"><circle cx="104" cy="-160" r="7" fill="#2a2226"/><circle cx="106" cy="-162" r="2.4" fill="#fff"/></g>
          <g class="eyes eyes-happy" opacity="0"><path d="M97 -160 q7 -8 14 0" stroke="#2a2226" stroke-width="5" stroke-linecap="round" fill="none"/></g>
          <g class="eyes eyes-alert" opacity="0"><circle cx="104" cy="-160" r="8.5" fill="#2a2226"/><circle cx="106" cy="-163" r="3" fill="#fff"/></g>
          <g class="ear ear-down"><path d="M66 -186 C44 -178 40 -140 54 -120 C66 -130 74 -160 80 -180 Z" fill="${dark}"/></g>
          <g class="ear ear-up" opacity="0"><path d="M64 -180 C58 -210 66 -226 80 -230 C86 -214 86 -196 82 -182 Z" fill="${dark}"/></g>
          <g class="mouthslot" transform="translate(146 -118)"></g>
        </g>
      </g>`;
    return g;
  }

  // feelings the dog can show: calm, happy, tense, scared
  function feel(tl, g, t, feeling) {
    const happy = feeling === "happy" || feeling === "relieved" || feeling === "warm";
    const alert = feeling === "tense" || feeling === "shocked" || feeling === "curious";
    tl.set(g.querySelectorAll(".eyes"), { opacity: 0 }, t);
    tl.set(g.querySelector(happy ? ".eyes-happy" : alert ? ".eyes-alert" : ".eyes-normal"), { opacity: 1 }, t);
    tl.set(g.querySelector(".tongue"), { opacity: happy ? 1 : 0 }, t);
    tl.set(g.querySelector(".ear-up"), { opacity: alert ? 1 : 0 }, t);
    tl.set(g.querySelector(".ear-down"), { opacity: alert ? 0 : 1 }, t);
  }

  // the tail: fast and wide when happy, a slow sway otherwise
  function wag(tl, g, t0, t1, feeling) {
    const happy = feeling === "happy" || feeling === "relieved" || feeling === "warm";
    const period = happy ? 0.16 : 0.6, amp = happy ? 26 : 10;
    const n = Math.max(2, Math.floor((t1 - t0) / period));
    const tail = g.querySelector(".tail path");
    tl.set(tail, { svgOrigin: "0 0", rotation: -amp }, t0);
    for (let i = 0; i < n; i++) tl.to(tail, { svgOrigin: "0 0", rotation: i % 2 ? -amp : amp, duration: period, ease: "sine.inOut" }, t0 + i * period);
  }

  window.ANIMALS = { makeAnimal, feel, wag, HEIGHT: 190, EYE: 160, MOUTH: [146, -118] };
})();
