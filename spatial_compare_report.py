"""Summarise spatial_compare.py's runs: every measure, town without space vs with it, per checkpoint, as the mean of
the seeds (and the per-seed values where they differ a lot).

    python spatial_compare_report.py out/spatial_compare > out/spatial_compare/summary.md
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from statistics import mean

GROUPS = {
    "world": ["events_per_day", "rejected_intents_total"],
    "space": ["runtime_contradictions", "ownership_contradictions", "exclusive_violations", "teleports",
              "speed_violations", "full_hand_or_mouth", "through_walls_or_furniture", "bodies_touching",
              "closest_bodies_m", "pick_ups_out_of_reach", "snap_turns", "path_failures"],
    "cost": ["simulation_s_per_day", "runtime_s_per_day_after", "spatial_queries", "path_queries", "squeezes",
             "past_people", "yields", "detours"],
    "story": ["threads", "threads_per_day", "long_threads_7d", "crossing_threads", "resolved", "information_asymmetry",
              "goal_changes", "trust_reversals", "belief_reversals", "quiet_day_share", "peak_day_share"],
}


def load(root: Path) -> list[dict]:
    rows = []
    for f in sorted(root.glob("*/results_*.json")):
        rows += json.loads(f.read_text(encoding="utf-8"))
    return rows


def main(root: Path) -> None:
    rows = load(root)
    days = sorted({r["days"] for r in rows})
    seeds = sorted({r["seed"] for r in rows})
    print(f"# Space on and off: {len(seeds)} seeds ({', '.join(map(str, seeds))}), checkpoints {days}\n")
    for group, keys in GROUPS.items():
        print(f"## {group}\n")
        print("| measure | " + " | ".join(f"day {d} off | day {d} on" for d in days) + " |")
        print("|---|" + "---|" * (2 * len(days)))
        for k in keys:
            cells = []
            for d in days:
                for recipe in ("town_v1", "town_spatial_v1"):
                    vals = [r[group][k] for r in rows if r["days"] == d and r["recipe"] == recipe and
                            r[group].get(k) is not None]
                    if not vals:
                        cells.append("-")
                    elif k == "closest_bodies_m":
                        cells.append(f"{min(vals):.3f}")
                    else:
                        cells.append(f"{mean(vals):.2f}" if isinstance(vals[0], float) else f"{mean(vals):.1f}")
            print(f"| {k} | " + " | ".join(cells) + " |")
        print()
    print("## per seed, day", days[-1], "\n")
    for r in sorted((r for r in rows if r["days"] == days[-1]), key=lambda r: (r["seed"], r["recipe"])):
        st = r["story"]
        print(f"- seed {r['seed']} {r['recipe']}: {st['threads']} threads, {st['long_threads_7d']} long, "
              f"{st['crossing_threads']} crossing, asymmetry {st['information_asymmetry']}, "
              f"quiet {st['quiet_day_share']}, strip `{st['strip']}`")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
