// Khronos glTF Validator over every asset the presentation runtime loads. Exit 1 on any error.
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import validator from "gltf-validator";

const dir = process.argv[2];
let bad = 0;
for (const f of readdirSync(dir).filter(f => f.endsWith(".glb")).sort()) {
  const r = await validator.validateBytes(new Uint8Array(readFileSync(join(dir, f))));
  const i = r.issues;
  console.log(JSON.stringify({ file: f, errors: i.numErrors, warnings: i.numWarnings, infos: i.numInfos,
    messages: i.messages.filter(m => m.severity <= 1).slice(0, 5).map(m => `${m.code}: ${m.message}`) }));
  bad += i.numErrors;
}
process.exit(bad ? 1 : 0);
