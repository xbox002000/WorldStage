"""Smoke gate: a few seeds, a few days, every place, every check. It must be all green before anything longer runs.

    python spatial_gate.py --days 3 --seeds 260934,3,55 --out out/gates/smoke_001

Each run keeps its world (world_<day>.db, a SQLite backup) and a manifest (seed, recipe and its hash, ruleset hash,
code hashes), so any failure, thread or event can be found again. Failures are classified by layer:

  world         the runtime contradicts the world (who holds what, who is where)
  runtime       the runtime's own laws: exclusive bookings, teleports, speed, full hands or mouths, walls
  spatial       the physics audit over every day: walking through solids, jumps, snap turns, taking hold out of
                reach, bodies inside each other (closer than 0.35 m). Shoulders brushing (0.35 m to 0.9 of the two
                radii) is the recorded known limitation: counted and reported, not a failure
  presentation  the JS rule the page plays (render/presentation/runtime_rule.js, in node) against the Python rule
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PENETRATION = 0.35  # metres centre to centre: closer than this is two bodies inside each other
CODE = ("runtime/world_runtime.py", "runtime/nav.py", "runtime/perception.py", "runtime/scheduler.py",
        "runtime/physics.py", "runtime/export.py", "narrative/layouts.py", "render/presentation/runtime_rule.js")


def _sha(p: Path) -> str:
    return "sha256:" + hashlib.sha256(p.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def presentation_check(doc_path: Path, doc: dict) -> dict:
    from runtime.export import holder_at, sample_full
    node = shutil.which("node")
    if node is None:
        return {"ok": None, "why": "node is not installed"}
    got = json.loads(subprocess.run([node, str(ROOT / "render" / "presentation" / "verify.mjs"), str(doc_path)],
                                    capture_output=True, text=True, encoding="utf-8", check=True).stdout)
    worst = worst_yaw = 0.0
    held_bad = 0
    for t, row in got["samples"].items():
        for eid, xy in row.items():
            p = sample_full(doc, eid, float(t))
            worst = max(worst, abs(p[0] - xy[0]), abs(p[1] - xy[1]))
            worst_yaw = max(worst_yaw, abs((p[2] - xy[2] + 540) % 360 - 180))
    for t, row in got["holders"].items():
        held_bad += sum(holder_at(doc, oid, float(t)) != h for oid, h in row.items())
    return {"ok": worst < 1e-3 and worst_yaw < 0.01 and held_bad == 0, "transform_error_m": round(worst, 6),
            "yaw_error_deg": round(worst_yaw, 5), "holder_mismatches": held_bad}


def one(seed: int, recipe: str, days: int, out: str) -> dict:
    sys.path.insert(0, str(ROOT))
    from agent.volition import VolitionDecider
    from runtime.godview import export_world
    from runtime.physics import audit
    from runtime.world_runtime import WorldRuntime
    from world.db import connect, init_db
    from world.recipes import compiled
    from world.ruleset import ruleset_hash
    from world.seed import build_world
    from world.simulation import Simulation
    from world.space import oracle
    run_dir = Path(out) / f"{seed}_{recipe}"
    run_dir.mkdir(parents=True, exist_ok=True)
    conn = connect()
    init_db(conn, seed)
    build_world(conn, seed, recipe)
    d = VolitionDecider(seed)
    sim = Simulation(conn, d, d, set(), feed="synthetic_v1")
    sim.run(days)
    with connect(run_dir / f"world_{days}.db") as disk:  # the world itself, kept
        conn.backup(disk)
    space = oracle(conn)
    rt = space.rt if space is not None else WorldRuntime(conn)
    rt.advance()
    check, inv = rt.check(), rt.invariants()
    doc_path = run_dir / "godview_all_days.json"
    doc = export_world(conn, doc_path, 0, days - 1, rt)
    phys = audit(doc)
    penetrating = [ex for ex in phys["body_overlap"]["examples"] if ex[3] < PENETRATION]
    brushes = [ex for ex in phys["body_overlap"]["examples"] if ex[3] >= PENETRATION]
    pres = presentation_check(doc_path, doc)
    layers = {
        "world": {"ok": not check, "contradictions": check[:5]},
        "runtime": {"ok": not any(inv.values()), **{k: v[:3] for k, v in inv.items()}},
        # bodies closer than 0.35 m centre to centre (9 cm into each other) fail; shoulders brushing (0.35 m to
        # 0.9 of the two radii) is the recorded known limitation: counted and reported, not a failure
        "spatial": {"ok": all(phys[k]["incidents"] == 0 for k in ("jump", "in_obstacle", "thing_in_obstacle",
                                                                  "reach_gap", "snap_turn")) and not penetrating,
                    "penetrating": penetrating, "brushes": len(brushes),
                    "closest_m": min((ex[3] for ex in phys["body_overlap"]["examples"]), default=None),
                    **{k: {"incidents": v["incidents"], "examples": v["examples"][:4]}
                       for k, v in phys.items() if isinstance(v, dict)}},
        "presentation": pres,
    }
    manifest = {"seed": seed, "recipe": recipe, "recipe_hash": compiled(recipe).compiled_hash, "days": days,
                "ruleset_hash": ruleset_hash(), "code": {c: _sha(ROOT / c) for c in CODE},
                "worlds": [f"world_{days}.db"], "events": conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]}
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    result = {"seed": seed, "recipe": recipe, "layers": layers,
              "first_broken": next((k for k in ("world", "runtime", "spatial", "presentation")
                                    if layers[k]["ok"] is False), None)}
    (run_dir / "gate.json").write_text(json.dumps(result, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=3)
    ap.add_argument("--seeds", default="260934,3,55")
    ap.add_argument("--recipes", default="town_v1,town_spatial_v1")
    ap.add_argument("--out", default="out/gates/smoke")
    a = ap.parse_args()
    jobs = [(int(s), r, a.days, a.out) for s in a.seeds.split(",") for r in a.recipes.split(",")]
    with ProcessPoolExecutor(max_workers=min(6, len(jobs))) as ex:
        results = list(ex.map(one, *zip(*jobs)))
    green = all(r["first_broken"] is None for r in results)
    for r in results:
        sp = r["layers"]["spatial"]
        print(r["seed"], r["recipe"], "PASS" if r["first_broken"] is None else f"FAIL at {r['first_broken']}",
              {k: sp[k]["incidents"] for k in ("jump", "in_obstacle", "thing_in_obstacle", "reach_gap", "snap_turn")},
              f"penetrating {len(sp['penetrating'])} brushes {sp['brushes']} closest {sp['closest_m']}",
              {k: len(v) for k, v in r["layers"]["runtime"].items() if k != "ok"})
    (Path(a.out) / "summary.json").write_text(json.dumps({"green": green, "results": results}, ensure_ascii=False,
                                                         indent=1, default=str), encoding="utf-8")
    print("GATE", "GREEN" if green else "RED")


if __name__ == "__main__":
    main()
