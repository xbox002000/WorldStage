"""Replay fidelity: when a picture is wrong, which layer is wrong? Each layer is checked against the one below it.

    world         the world's own record: who holds what after each event, the snapshot hash
    runtime       WorldRuntime against the world (check()), its state and trace hashes, the order of events and
                  of hand-offs (a pick-up before the carrying, a drop before it lies on the ground)
    physics       runtime/physics.py over the scene: no walking through solids, no jumps, no taking hold out of
                  reach anywhere; bodies brushing or a sharp turn only where nobody is watching
    presentation  the presentation runtime's rule (render/presentation/runtime_rule.js, run in node) against the
                  Python rule: positions (transform error), who holds what, the order of triggers
    camera        every version's edit maps onto the same world clock: changing whose eyes or the camera never
                  changes where anyone is

    report = fidelity(conn, rt, scene_doc, scene_path)   # report["first_broken"] is None when every layer holds
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from runtime.export import holder_at, pose_at, sample_full
from world.snapshot import snapshot_hash

ROOT = Path(__file__).resolve().parent.parent
VERIFY = ROOT / "render" / "presentation" / "verify.mjs"
TOLERANCE = 1e-3  # metres


def _holder(doc: dict, oid: str, t: float) -> str:
    return holder_at(doc, oid, t)


def moments(doc: dict) -> list[float]:
    """Every time anything can change: each key and each hand-off's start (the same as runtime_rule.js)."""
    return sorted({k[0] for e in doc["entities"] for k in e["keys"]} | {h["start"] for h in doc["handoffs"]})


def expected_triggers(doc: dict) -> list:
    """The same trigger rule as runtime_rule.js, written again here so the two can be compared."""
    out, walking, held = [], {}, {}
    starts: dict[float, list] = {}
    for h in doc["handoffs"]:
        starts.setdefault(h["start"], []).append(h)
    for t in moments(doc):
        for e in doc["entities"]:
            if e["kind"] != "thing":
                w = pose_at(doc, e["id"], t) == "walk"
                if w != walking.get(e["id"], False):
                    out.append([round(t, 3), e["id"], "walk_start" if w else "walk_stop"])
                    walking[e["id"]] = w
            else:
                h = _holder(doc, e["id"], t)
                if h != held.get(e["id"], ""):
                    if held.get(e["id"]):
                        out.append([round(t, 3), held[e["id"]], "let_go:" + e["id"]])
                    if h:
                        out.append([round(t, 3), h, "take_hold:" + e["id"]])
                    held[e["id"]] = h
        for h in starts.get(t, []):
            out.append([round(t, 3), h["actor"], "reach:" + h["thing"]])
    return out


def fidelity(conn, rt, doc: dict, scene_path: Path) -> dict:
    report: dict = {"layers": {}}
    # -- world ------------------------------------------------------------------------------------------------------
    report["world_state_hash"] = snapshot_hash(conn)
    # -- runtime ----------------------------------------------------------------------------------------------------
    problems = rt.check()
    ids = sorted({s["event"] for c in doc["cuts"].values() for s in c["shots"]})
    trace = rt.trace(ids)
    order_ok = True
    by_thing: dict[str, list] = {}
    for i in sorted(trace.interactions, key=lambda i: (i.contact, i.event_id)):
        by_thing.setdefault(i.target, []).append(i.action)
    for thing, acts in by_thing.items():  # a thing is picked up before it is dropped, and so on
        holding = None
        for a in acts:
            if a in ("pickup", "receive", "grab"):
                holding = True
            elif a in ("drop", "hand_over"):
                order_ok &= holding is not False
                holding = False
    events_in_order = [i.event_id for i in trace.interactions] == sorted(i.event_id for i in trace.interactions)
    report["runtime_state_hash"] = rt.state_at(max(ids)).state_hash
    report["trace_hash"] = trace.trace_hash
    report["layers"]["runtime"] = {"ok": not problems and order_ok and events_in_order,
                                   "check": problems[:5], "hand_off_order": order_ok, "event_order": events_in_order}
    # -- physics: does anyone go through a wall, a table or somebody else, jump, or take hold out of reach? ------------
    from runtime.physics import audit
    phys = audit(json.loads(Path(scene_path).read_text(encoding="utf-8")))  # the scene as staged for every engine
    hard = sum(phys[k]["incidents"] for k in ("jump", "in_obstacle", "thing_in_obstacle", "reach_gap"))
    soft = sum(phys[k]["on_screen"] for k in ("body_overlap", "snap_turn"))
    report["layers"]["physics"] = {"ok": hard == 0 and soft == 0,
                                   **{k: {"incidents": v["incidents"], "on_screen": v["on_screen"]}
                                      for k, v in phys.items() if isinstance(v, dict)}}
    # -- presentation (the JS rule the page actually runs) ----------------------------------------------------------
    node = shutil.which("node")
    if node is None:
        report["layers"]["presentation"] = {"ok": None, "why": "node is not installed"}
    else:
        got = json.loads(subprocess.run([node, str(VERIFY), str(scene_path)], capture_output=True, text=True,
                                        encoding="utf-8", check=True).stdout)
        worst, worst_yaw, held_bad = 0.0, 0.0, []
        for t, row in got["samples"].items():
            for eid, xy in row.items():
                p = sample_full(doc, eid, float(t))
                worst = max(worst, abs(p[0] - xy[0]), abs(p[1] - xy[1]))
                worst_yaw = max(worst_yaw, abs((p[2] - xy[2] + 540) % 360 - 180))
        for t, row in got["holders"].items():
            for oid, h in row.items():
                if _holder(doc, oid, float(t)) != h:
                    held_bad.append((t, oid, h))
        exp = expected_triggers(doc)
        same_order = [x[1:] for x in exp] == [x[1:] for x in got["triggers"]]  # and the same moments:
        same_order = same_order and all(abs(a[0] - b[0]) < 1e-3 for a, b in zip(exp, got["triggers"]))
        report["layers"]["presentation"] = {"ok": worst < TOLERANCE and worst_yaw < 0.01 and not held_bad and same_order,
                                            "transform_error_m": round(worst, 6), "yaw_error_deg": round(worst_yaw, 5),
                                            "holder_mismatches": held_bad[:5],
                                            "trigger_order_same": same_order, "triggers": len(got["triggers"])}
        # -- camera: every version on the same world clock -------------------------------------------------------
        drift = max((abs(w - expect) for rows in got["clocks"].values() for _a, _b, w, expect in rows), default=0.0)
        report["layers"]["camera"] = {"ok": drift < 1e-6, "world_clock_drift": drift,
                                      "versions": sorted(got["clocks"])}
    order = ["runtime", "physics", "presentation", "camera"]
    report["first_broken"] = next((k for k in order if report["layers"].get(k, {}).get("ok") is False), None)
    return report
