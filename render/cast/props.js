/* Cast: the things people lose, carry and fight over. `draw(kind)` returns SVG markup centred on x = 0 with its bottom
   at y = 0, about 60 units across, so the same drawing can lie on a floor, sit in a hand or hang from a dog's mouth. */
(function () {
  const DRAW = {
    wallet: `<rect x="-38" y="-46" width="76" height="46" rx="9" fill="#6b3f26"/><path d="M-38 -32 H38" stroke="#4a2a18" stroke-width="3"/>
      <rect x="10" y="-40" width="30" height="20" rx="6" fill="#8a5634"/><circle cx="30" cy="-30" r="4" fill="#f2c14a"/>
      <path d="M-32 -6 H32" stroke="#d9b48a" stroke-width="2" stroke-dasharray="5 4"/>`,
    ring: `<circle cx="0" cy="-22" r="18" fill="none" stroke="#f2c14a" stroke-width="7"/><path d="M-9 -44 L0 -56 L9 -44 Z" fill="#9fe3ff" stroke="#fff" stroke-width="2"/>`,
    parcel: `<rect x="-36" y="-56" width="72" height="56" rx="6" fill="#c99968"/><path d="M0 -56 V0 M-36 -30 H36" stroke="#e8d8b0" stroke-width="8"/>`,
    ticket: `<rect x="-40" y="-34" width="80" height="34" rx="5" fill="#ffd76a"/><circle cx="-40" cy="-17" r="7" fill="#fff"/><circle cx="40" cy="-17" r="7" fill="#fff"/>
      <path d="M-22 -17 H22" stroke="#c8553d" stroke-width="5" stroke-dasharray="6 4"/>`,
    book: `<rect x="-34" y="-58" width="68" height="58" rx="5" fill="#2f4a7a"/><rect x="-26" y="-50" width="30" height="42" rx="3" fill="#f3ead2"/>
      <path d="M-20 -42 V-16 M-11 -42 V-16" stroke="#2f4a7a" stroke-width="3"/>`,
    sword: `<rect x="-6" y="-120" width="12" height="96" rx="3" fill="#dfe6ee"/><rect x="-26" y="-26" width="52" height="8" rx="3" fill="#8a6440"/>
      <rect x="-5" y="-20" width="10" height="20" rx="3" fill="#5a3e29"/>`,
    jade: `<circle cx="0" cy="-26" r="24" fill="#6fbf8f"/><circle cx="0" cy="-26" r="9" fill="#e8f5ec"/>`,
    token: `<circle cx="0" cy="-24" r="22" fill="#b98a3e"/><rect x="-7" y="-31" width="14" height="14" fill="#6d4a1e"/>`,
    gourd: `<circle cx="0" cy="-20" r="20" fill="#d8a24a"/><circle cx="0" cy="-50" r="13" fill="#d8a24a"/><rect x="-3" y="-70" width="6" height="10" fill="#6d4a1e"/>`,
    thing: `<rect x="-26" y="-40" width="52" height="40" rx="10" fill="#c9a0ff"/><path d="M-10 -20 h20" stroke="#fff" stroke-width="5"/>`,
  };
  const KINDS = [["wallet", "wallet"], ["ring", "ring"], ["package", "parcel"], ["parcel", "parcel"], ["ticket", "ticket"],
                 ["manual", "book"], ["book", "book"], ["sword", "sword"], ["jade", "jade"], ["token", "token"], ["gourd", "gourd"]];
  function kindOf(id) { const k = KINDS.find(([p]) => id.includes(p)); return k ? k[1] : "thing"; }
  function draw(id) { return DRAW[kindOf(id)]; }
  window.PROPS = { draw, kindOf };
})();
