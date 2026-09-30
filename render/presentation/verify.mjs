// Run the presentation runtime's own rule (runtime_rule.js, the file the page uses) over a scene and print what an
// engine would show: positions every 0.5 s, who holds what, the order of triggers, and the world clock of every
// version's edit (so runtime/fidelity.py can check that changing the version never changes the world).
import { readFileSync } from "node:fs";
import { holder, moments, sample, triggers, worldTime } from "./runtime_rule.js";

const doc = JSON.parse(readFileSync(process.argv[2], "utf-8"));
const samples = {}, holders = {};
// at every moment something can change, and a quarter second after it (inside a walk, a turn, a lift or a fall)
const times = [...new Set(moments(doc).flatMap(t => [t, t + 0.25]))].sort((a, b) => a - b);
for (const t of times) {
  const row = {}, held = {};
  for (const e of doc.entities) {
    const p = sample(doc, e.id, t);
    if (p) row[e.id] = [+p[0].toFixed(4), +p[1].toFixed(4), +p[2].toFixed(4)];
    if (e.kind === "thing") held[e.id] = holder(doc, e.id, t);
  }
  samples[t.toFixed(4)] = row;
  holders[t.toFixed(4)] = held;
}
const clocks = {};
for (const v of Object.keys(doc.cuts)) {
  clocks[v] = doc.cuts[v].shots.map(s => [s.film_start, s.film_end, +worldTime(doc, v, s.film_start + 0.25).toFixed(4),
                                          s.t_start + 0.25]);
}
process.stdout.write(JSON.stringify({ samples, holders, triggers: triggers(doc), clocks }));
