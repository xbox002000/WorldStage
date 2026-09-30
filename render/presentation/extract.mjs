// Previs data, frame by frame, from the page itself (the same three.js scene HyperFrames renders): the camera
// (position, rotation, lens, projection) and every visible person's 2D keypoints (COCO 18), plus page-level QA
// (how far a thing jumps when it is taken). Headless, in HyperFrames' pinned Chrome.
//
//   node extract.mjs <project dir> <chrome.exe> <fps> <out.json>
import { createServer } from "node:http";
import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { extname, join } from "node:path";
import puppeteer from "puppeteer-core";

const [dir, chrome, fpsArg, out] = process.argv.slice(2);
const fps = +fpsArg || 30;
const TYPES = { ".html": "text/html", ".js": "text/javascript", ".mjs": "text/javascript", ".json": "application/json",
                ".glb": "model/gltf-binary" };
const server = createServer((req, res) => {
  const p = join(dir, decodeURIComponent(req.url.split("?")[0]).replace(/^\/+/, "") || "index.html");
  if (!existsSync(p)) { res.writeHead(404); res.end(); return; }
  res.writeHead(200, { "Content-Type": TYPES[extname(p)] || "application/octet-stream" });
  res.end(readFileSync(p));
});
await new Promise(ok => server.listen(0, "127.0.0.1", ok));
const port = server.address().port;
const browser = await puppeteer.launch({ executablePath: chrome, headless: true,
                                         args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--no-sandbox"] });
const page = await browser.newPage();
await page.goto(`http://127.0.0.1:${port}/index.html`, { waitUntil: "load" });
await page.waitForFunction(() => window.__rt, { timeout: 60000 });
const result = await page.evaluate(async fps => {
  const rt = window.__rt, v = rt.state.version, total = rt.duration(v), frames = [];
  const gaps = [];
  for (let i = 0; i * (1 / fps) < total; i++) {
    const film = i / fps, r = rt.frame(film);
    frames.push({ i, film: +film.toFixed(4), world: +r.t.toFixed(4), camera: r.debug.camera, poses: r.debug.poses,
                  things: r.debug.things });
    for (const [id, q] of Object.entries(r.debug.qa || {})) if (q.hand_gap != null) gaps.push([film, id, q.hand_gap]);
  }
  return { version: v, fps, frames, lift_gaps: gaps };
}, fps);
writeFileSync(out, JSON.stringify(result));
await browser.close();
server.close();
console.log(JSON.stringify({ frames: result.frames.length, version: result.version }));
