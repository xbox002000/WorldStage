"""Triage a smoke gate: every spatial incident, with both bodies' poses and what the runtime was doing, grouped into
causes, so a fix is aimed at a cause and not at a number.

    python spatial_gate_triage.py out/gates/smoke_001
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from runtime.physics import _at, audit  # noqa: E402


def cause(kind: str, a: tuple, b: tuple | None) -> str:
    pa, pb = a[3], (b[3] if b else "")
    if kind == "body_overlap":
        poses = tuple(sorted((pa, pb)))
        if "offstage" in poses:
            return "offstage"
        if poses == ("stand", "stand") or poses == ("sit", "stand") or poses == ("sit", "sit"):
            return f"both still ({'/'.join(poses)})"
        return "moving: " + "/".join(poses)
    if kind == "snap_turn":
        return f"turn while {pa}"
    if kind == "in_obstacle":
        return f"inside a solid while {pa}"
    return kind


def main(root: Path) -> None:
    total = Counter()
    for gate in sorted(root.glob("*/gate.json")):
        run = gate.parent
        doc = json.loads((run / "godview_all_days.json").read_text(encoding="utf-8"))
        by = {e["id"]: e for e in doc["entities"]}
        r = audit(doc)
        for kind in ("body_overlap", "snap_turn", "in_obstacle", "jump", "reach_gap"):
            for ex in r[kind]["examples"] + ([] if r[kind]["incidents"] <= len(r[kind]["examples"]) else []):
                t = ex[0]
                ids = [x for x in ex[1:] if isinstance(x, str) and x in by]
                a = _at(by[ids[0]], t, by, doc)
                b = _at(by[ids[1]], t, by, doc) if len(ids) > 1 and kind == "body_overlap" else None
                c = cause(kind, a, b)
                total[(kind, c)] += 1
                day, sec = int(t // 86400), t % 86400
                print(f"{run.name:22} {kind:12} {c:28} day {day} {int(sec // 3600):02d}:{int(sec % 3600 // 60):02d} "
                      f"{ids} {a[4]} {[round(v, 2) if isinstance(v, float) else v for v in ex[2:]]}")
    print()
    for (kind, c), n in total.most_common():
        print(f"{n:3}  {kind:12} {c}")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
