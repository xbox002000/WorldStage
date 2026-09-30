"""Acceptance: does a world simulated in its space still live, and what does space change? The same seeds are run for
90 days as the town without space (town_v1) and with it (town_spatial_v1), measured at 30, 60 and 90 days, in four
groups:

  world      events, rejected intents, runtime contradictions, ownership contradictions
  space      teleports, walks through walls or furniture, bodies inside each other, pick-ups out of reach or into a
             full mouth, path failures, the closest two bodies ever came (the runtime's invariants and the physics
             audit over every day)
  cost       simulation seconds per day, runtime rebuild seconds per day, spatial and path queries, yields and detours
  story      threads, long threads (7+ days), threads that cross, goal changes, trust reversals, threads with somebody
             in the dark (information asymmetry), quiet days

    python spatial_compare.py --days 90 --seeds 260934,3,55 --out out/spatial_compare
"""
from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path

from agent.volition import VolitionDecider
from world.db import connect, init_db
from world.seed import build_world
from world.simulation import Simulation

RECIPES = ("town_v1", "town_spatial_v1")


def world_measures(conn, sim, lo, hi) -> dict:
    events = conn.execute("SELECT COUNT(*) FROM events WHERE timestamp >= ? AND timestamp < ?",
                          (lo * 1440, hi * 1440)).fetchone()[0]
    rejected = sum(v for k, v in sim.stats.items() if k.startswith("rejected"))
    return {"events": events, "events_per_day": round(events / (hi - lo), 2), "rejected_intents_total": rejected}


def space_measures(conn, rt, lo: int, hi: int) -> dict:
    """The runtime's invariants over the whole history, and the physics audit over the days [lo, hi)."""
    import tempfile
    from runtime import nav
    from runtime.godview import export_world
    from runtime.physics import audit
    inv = rt.invariants()
    check = rt.check()
    tmp = Path(tempfile.mkdtemp()) / "audit.json"  # a save of the new days, only to audit them
    phys = audit(export_world(conn, tmp, lo, hi - 1, rt))
    near = min((ex[3] for ex in phys["body_overlap"]["examples"]), default=None)
    kinds = {}
    for a in rt.actions:
        if a.kind in ("yield", "detour"):
            kinds[a.kind] = kinds.get(a.kind, 0) + 1
    return {
        "audited_days": [lo, hi],
        "runtime_contradictions": len(check),
        "ownership_contradictions": sum("runtime says" in c for c in check),
        "exclusive_violations": len(inv["exclusive"]), "teleports": len(inv["teleport"]) + phys["jump"]["incidents"],
        "speed_violations": len(inv["speed"]), "full_hand_or_mouth": len(inv["sockets"]),
        "through_walls_or_furniture": phys["in_obstacle"]["incidents"] + phys["thing_in_obstacle"]["incidents"],
        "bodies_touching": phys["body_overlap"]["incidents"], "closest_bodies_m": near,
        "pick_ups_out_of_reach": phys["reach_gap"]["incidents"], "snap_turns": phys["snap_turn"]["incidents"],
        "path_failures": nav.STATS["unreachable"], "path_queries": nav.STATS["path_queries"],
        "squeezes": nav.STATS["squeeze"], "past_people": nav.STATS["past_people"],
        "yields": kinds.get("yield", 0), "detours": kinds.get("detour", 0),
    }


def story_measures(conn, days: int) -> dict:
    from narrative.knowledge import knowledge_of
    from narrative.rhythm import rhythm
    from narrative.threads import derive_threads
    threads = derive_threads(conn)
    r = rhythm(conn, 0, days, threads)
    dark = 0
    for t in threads:
        try:
            k = knowledge_of(conn, t)
        except Exception:  # a thread kind the knowledge model does not cover
            k = None
        dark += bool(k and (k.wrong or k.unaware))
    return {"threads": len(threads), "threads_per_day": round(len(threads) / days, 2),
            "long_threads_7d": sum(t.last_day - t.first_day >= 7 for t in threads),
            "crossing_threads": sum(bool(t.cross_threads) for t in threads),
            "resolved": sum(t.status == "resolved" for t in threads),
            "someone_in_the_dark": dark, "information_asymmetry": round(dark / len(threads), 2) if threads else 0.0,
            "goal_changes": sum(r["people"]["goal_changes"].values()), "trust_reversals": r["people"]["trust_reversals"],
            "belief_reversals": r["people"]["belief_reversals"], "quiet_day_share": r["shape"]["quiet"],
            "peak_day_share": r["shape"]["peak"], "strip": r["strip"]}


def run(seed: int, recipe: str, days: int, checkpoints: list[int], out: Path | None = None) -> list[dict]:
    """One world, measured at each checkpoint. With `out`, the world itself is kept at every checkpoint
    (world_<day>.db) with a manifest, so any story or number can be traced back to the world it came from."""
    from runtime import nav
    from runtime.world_runtime import WorldRuntime
    from world.space import oracle
    nav.STATS.clear()
    conn = connect()
    init_db(conn, seed)
    build_world(conn, seed, recipe)
    d = VolitionDecider(seed)
    sim = Simulation(conn, d, d, set(), feed="synthetic_v1")
    space = oracle(conn)  # a spatial world plays its runtime along; the town without space gets one played after
    rt = space.rt if space is not None else WorldRuntime(conn)
    rows, done, spent, runtime_s = [], 0, 0.0, 0.0
    for cp in checkpoints:
        t = time.perf_counter()
        sim.run(cp - done)
        spent += time.perf_counter() - t
        t = time.perf_counter()
        rt.advance()
        runtime_s += time.perf_counter() - t
        row = {"seed": seed, "recipe": recipe, "days": cp,
               "world": world_measures(conn, sim, 0, cp), "space": space_measures(conn, rt, done, cp),
               "cost": {"simulation_s_per_day": round(spent / cp, 3),
                        # the runtime inside a spatial simulation is part of its simulation time
                        "runtime_s_per_day_after": round(runtime_s / cp, 3),
                        "spatial_queries": getattr(space, "queries", 0)},
               "story": story_measures(conn, cp)}
        for k in ("path_queries", "squeezes", "past_people", "yields", "detours"):
            row["cost"][k] = row["space"].pop(k)
        done = cp
        if out is not None:
            out.mkdir(parents=True, exist_ok=True)
            with connect(out / f"world_{cp}.db") as disk:
                conn.backup(disk)
            row["world"]["kept"] = f"world_{cp}.db"
        rows.append(row)
        print(json.dumps({k: row[k] for k in ("seed", "recipe", "days")}), flush=True)
    if out is not None:
        from spatial_gate import CODE, _sha
        from world.recipes import compiled
        from world.ruleset import ruleset_hash
        manifest = {"seed": seed, "recipe": recipe, "recipe_hash": compiled(recipe).compiled_hash, "days": days,
                    "checkpoints": checkpoints, "worlds": [f"world_{cp}.db" for cp in checkpoints],
                    "ruleset_hash": ruleset_hash(), "code": {c: _sha(Path(__file__).resolve().parent / c) for c in CODE},
                    "metrics": "results_*.json"}
        (out / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--seeds", default="260934,3,55")
    ap.add_argument("--recipes", default=",".join(RECIPES))
    ap.add_argument("--out", default="out/spatial_compare")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    cps = [d for d in (30, 60, 90) if d <= a.days] or [a.days]
    rows = []
    for seed in [int(s) for s in a.seeds.split(",")]:
        for recipe in a.recipes.split(","):
            rows += run(seed, recipe, a.days, cps, out / f"{seed}_{recipe}")
            (out / f"results_{a.seeds.replace(',', '_')}_{a.recipes.replace(',', '_')}.json").write_text(
                json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
