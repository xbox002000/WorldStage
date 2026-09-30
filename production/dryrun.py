"""Shot Cost Planner: which shots of a packet are worth a paid video model, what each request would carry, and what
it would cost. A dry run: it compiles requests and prices them, and has no code that sends anything anywhere.

    python -m production.dryrun out/reality_v2/A_ming_pov/packet.json [--budget 1.50]

A shot goes to a model only where the procedural renders cannot carry it: a body's performance seen close
(MCU/CU/ECU on a person or an animal), or the beat's turn (reveal, payoff) on a body. Everything else stays
procedural at $0. Under a budget, the shots that matter most are kept (turns first, then close performance), and
the rest fall back to procedural, so the director trades quality against cost shot by shot.

Each request is provider-neutral first (what the shot needs), then priced per provider from production/prices.json:
  prompt              the shot in words, with the performance (production/shots.py:describe)
  duration            the shot's seconds, raised to the provider's minimum
  references          the character sheets (Blender cast) and the white-box frame of this shot (the layout, the
                      blocking, where everyone is): the model fills in a picture that already exists
  camera              scale, angle, relation (whose eyes), movement: from the DirectorPlan
  motion              the runtime's hand-offs in this shot and when contact falls (0..1): from the World Runtime
  continuity          what each body holds before and after: from the PerformancePlan
"""
from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict
from pathlib import Path

from contracts.base import from_dict
from contracts.migrate import migrate_packet
from contracts.packet import PACKET_VERSION, ProductionPacket, Shot
from production.shots import describe

PRICES = json.loads((Path(__file__).resolve().parent / "prices.json").read_text(encoding="utf-8"))
CLOSE = ("MCU", "CU", "ECU")
TURNS = ("reveal", "payoff")


def needs_model(shot: Shot) -> tuple[bool, str, int]:
    """(whether a video model should make it, why, how much it matters: 2 = a turn on a body, 1 = close performance)."""
    bodies = [pb for pb in shot.performances if pb.actor == shot.subject_id]
    if shot.function == "hide" or not bodies:
        return False, "no body to perform (an insert, a hidden act, a place)", 0
    if shot.function in TURNS:
        return True, f"the turn of the beat ({shot.function}) on {shot.subject_id}", 2
    if shot.scale in CLOSE:
        return True, f"{shot.subject_id}'s performance seen close ({shot.scale})", 1
    return False, "wide or medium: the procedural render carries it", 0


def request(shot: Shot, packet: ProductionPacket, previs: dict | None = None) -> dict:
    """What a video model would be sent for this shot. With a Previs Pack (render/presentation/previs.py) the request
    carries the shot's control signals: depth, pose, id mask, normals, the camera track and the runtime's actions,
    so the model is left the look and not the blocking."""
    controls = {}
    if previs is not None:
        n = int(shot.shot_id.lstrip("s"))
        row = next((r for r in previs["shots"] if r["index"] == n), None)
        if row is not None:
            controls = {k: f"{previs['cut']}/{row['dir']}/{v}" for k, v in row["passes"].items() if k != "rgb"}
            controls.update(reference_video=f"{previs['cut']}/{row['dir']}/{row['passes'].get('rgb', '')}",
                            camera_track=f"{previs['cut']}/{row['dir']}/{row['camera']}",
                            keypoints=f"{previs['cut']}/{row['dir']}/{row['pose']}",
                            runtime=f"{previs['cut']}/{row['dir']}/{row['runtime']}",
                            depth_range_m=previs["depth_range_m"], id_palette="previs.json#id_palette")
    return {
        "shot_id": shot.shot_id,
        "prompt": describe(shot),
        "seconds": shot.duration_seconds,
        "aspect": f"{packet.canvas.width}:{packet.canvas.height}",
        "references": sorted({f"cast3d:{'dog' if pb.profile == 'dog' else 'person'}.glb#{pb.actor}" for pb in shot.performances}
                             | {f"whitebox:{shot.shot_id}"}),
        "camera": {"scale": shot.scale, "angle": shot.angle, "relation": shot.relation, "movement": shot.camera.movement,
                   "focalizer": shot.focalizer},
        "motion": [{"actor": i.actor, "action": i.action, "thing": i.target, "hand": i.hand, "at": shot.moment}
                   for i in shot.interactions],
        "continuity": {pb.actor: {"holding_before": pb.before.holding, "holding_after": pb.after.holding,
                                  "gaze": pb.gaze.mode, "primary": pb.primary} for pb in shot.performances},
        "audio": shot.dialogue == "full" and any(pb.speech and pb.speech.delivery not in ("none",) for pb in shot.performances),
        "controls": controls,
    }


def price(req: dict, provider: str) -> float:
    p = PRICES["providers"][provider]
    secs = max(p["min_seconds"], min(p["max_seconds"], math.ceil(req["seconds"])))
    rate = p.get("per_second_with_audio", p["per_second"]) if req["audio"] else p["per_second"]
    return round(secs * rate, 3)


def plan(packet: ProductionPacket, budget: float | None = None, provider: str = "kling_3_pro",
         previs: dict | None = None) -> dict:
    rows = []
    for s in packet.shots:
        want, why, weight = needs_model(s)
        req = request(s, packet, previs)
        rows.append({"shot": s.shot_id, "function": s.function, "scale": s.scale, "subject": s.subject_id,
                     "want_model": want, "why": why, "weight": weight, "request": req,
                     "cost": {p: price(req, p) for p in PRICES["providers"]} if want else {}})
    wanted = sorted((r for r in rows if r["want_model"]), key=lambda r: (-r["weight"], r["cost"][provider], r["shot"]))
    spent = 0.0
    for r in wanted:
        c = r["cost"][provider]
        if budget is None or spent + c <= budget + 1e-9:
            r["route"], spent = provider, round(spent + c, 3)
        else:
            r["route"] = "procedural"
            r["why"] += f"; over the budget ({budget:.2f})"
    for r in rows:
        r.setdefault("route", "procedural")
    return {"packet_hash": packet.packet_hash, "provider": provider, "budget": budget, "total": spent,
            "all_wanted_total": round(sum(r["cost"][provider] for r in wanted), 3),
            "shots": rows, "sent": False, "prices": PRICES["source"]}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("packet")
    ap.add_argument("--budget", type=float)
    ap.add_argument("--provider", default="kling_3_pro", choices=sorted(PRICES["providers"]))
    ap.add_argument("--previs", help="a Previs Pack's previs.json: the requests carry its control signals")
    args = ap.parse_args()
    data = json.loads(Path(args.packet).read_text(encoding="utf-8"))
    if data.get("version") != PACKET_VERSION:
        data = migrate_packet(data)
    packet = from_dict(ProductionPacket, data)
    previs = json.loads(Path(args.previs).read_text(encoding="utf-8")) if args.previs else None
    out = plan(packet, args.budget, args.provider, previs)
    for r in out["shots"]:
        cost = f"${r['cost'][args.provider]:.2f}" if r["route"] != "procedural" else "$0"
        print(f"{r['shot']}  {r['function']:10} {r['scale']:6} {r['subject']:12} {r['route']:12} {cost:>7}  {r['why']}")
    print(f"total ${out['total']:.2f} (every wanted shot: ${out['all_wanted_total']:.2f}) · {args.provider} · nothing sent")
    Path(args.packet).with_name("cost_plan.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
