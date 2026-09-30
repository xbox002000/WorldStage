"""Director Reality Test: one world truth, several DirectorPlans, several viewing experiences.

    python director_reality.py                       # plan, compile and render every variant of the benchmark
    python director_reality.py --no-render           # plans, packets and measures only
    python director_reality.py --only dog_irony_subjective

The world is built once from the benchmark's seed (no model, $0). The story is one stretch of one thread. Each variant
forces some of the director's choices (whose eyes, what the audience knows, the camera grammar) and leaves the rest to
the director. Nothing about the scene changes: every variant must have the same scene hash. Writes, per variant,
out/reality/<id>/{director_plan,packet,script}.json, episode.mp4 and sheet.png, then comparison.mp4 (the main three
side by side), comparison.png and results.json.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import asdict
from pathlib import Path

from agent.volition import VolitionDecider
from narrative.arcs import Arc, load_events
from narrative.compiler import compile_packet
from narrative.direction import plan_direction
from narrative.scene_spec import build_scene_specs
from narrative.selector import Candidate
from narrative.threads import derive_threads
from production.viewing import viewing_profile
from world.db import connect, init_db
from world.seed import build_world
from world.simulation import Simulation

ROOT = Path(__file__).resolve().parent
FFMPEG = ROOT / "tools" / "ffmpeg" / "bin" / "ffmpeg"


def world(cfg: dict, path: Path):
    if not path.exists():
        conn = connect(path)
        init_db(conn, cfg["seed"])
        build_world(conn, cfg["seed"], cfg.get("recipe", "town_v1"))
        d = VolitionDecider(cfg["seed"])
        Simulation(conn, d, d, set(), feed=cfg.get("feed")).run(cfg["days"])
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        return conn
    return connect(path)


def story(conn, cfg: dict):
    """The stretch of the thread around the first time an animal took the thing: from the owner losing it to the
    owner finding it again."""
    thread = next(t for t in derive_threads(conn) if t.thread_id == cfg["thread"])
    events = load_events(conn)
    evs = [events[i] for i in thread.event_ids]
    animals = {r[0] for r in conn.execute("SELECT person_id FROM personas WHERE json_extract(traits, '$.species') "
                                          "IS NOT NULL AND json_extract(traits, '$.species') <> 'human'")}
    take = next((k for k, e in enumerate(evs) if e.type == "take" and e.truth.get("actor") in animals), None)
    if take is None:
        raise SystemExit(f"{cfg['thread']}: no animal takes the thing in this world; the benchmark needs another story")
    start = max(k for k in range(take) if evs[k].type == "misplace") if any(e.type == "misplace" for e in evs[:take]) else take
    end = next((k for k in range(take, len(evs)) if evs[k].type == "find"), len(evs) - 1)
    chosen = tuple(evs[start:end + 1])
    spec = build_scene_specs(conn, [Candidate(Arc(chosen, max(chosen, key=lambda e: e.importance), "thread"),
                                              1.0, {}, 1.0)], ["reality"])[0]
    culprits = {e.truth.get("actor") for e in chosen if e.type == "take"}
    payoff = next((e.id for e in chosen if e.type == "find"), None)
    return thread, spec, culprits, payoff


def frames(mp4: Path, packet, out: Path, n: int = 8) -> None:
    """A strip of stills, one from the middle of each of up to n shots."""
    shots = packet.shots
    picks = [shots[round(i * (len(shots) - 1) / max(1, n - 1))] for i in range(min(n, len(shots)))]
    times = [s.start_seconds + s.duration_seconds * 0.6 for s in picks]
    sel = "+".join(f"between(t,{t - 0.02:.2f},{t + 0.02:.2f})" for t in times)
    subprocess.run([str(FFMPEG), "-y", "-loglevel", "error", "-i", str(mp4), "-vf",
                    f"select='{sel}',scale=270:480,tile={len(picks)}x1", "-frames:v", "1", "-fps_mode", "vfr", str(out)],
                   check=True)


def side_by_side(videos: list[Path], out: Path) -> None:
    inputs, chains = [], []
    for k, v in enumerate(videos):
        inputs += ["-i", str(v)]
        chains.append(f"[{k}:v]scale=540:960,tpad=stop_mode=clone:stop_duration=30[v{k}]")
    stack = "".join(f"[v{k}]" for k in range(len(videos)))
    subprocess.run([str(FFMPEG), "-y", "-loglevel", "error", *inputs, "-filter_complex",
                    ";".join(chains) + f";{stack}hstack=inputs={len(videos)},trim=duration="
                    f"{max(_seconds(v) for v in videos):.2f}[out]", "-map", "[out]", "-c:v", "libx264", "-pix_fmt",
                    "yuv420p", "-crf", "22", str(out)], check=True)


def _seconds(v: Path) -> float:
    r = subprocess.run([str(FFMPEG), "-i", str(v)], capture_output=True, text=True, errors="replace")
    import re
    h, m, s = re.search(r"Duration: (\d+):(\d+):([\d.]+)", r.stderr).groups()
    return int(h) * 3600 + int(m) * 60 + float(s)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bench", default="benchmarks/director_reality_v1.json")
    ap.add_argument("--out", default="out/reality")
    ap.add_argument("--only", default="")
    ap.add_argument("--no-render", action="store_true")
    ap.add_argument("--debug", action="store_true", help="print each shot's function and camera at the bottom")
    args = ap.parse_args()
    bench = json.loads((ROOT / args.bench).read_text(encoding="utf-8"))
    out = ROOT / args.out
    out.mkdir(parents=True, exist_ok=True)
    conn = world(bench["world"], out / "world.db")
    thread, spec, culprits, payoff = story(conn, bench["story"])
    results = {"benchmark": bench["id"], "scene_hash": spec.scene_hash, "thread": thread.thread_id,
               "question": thread.central_question, "beats": [f"{b.day}/{b.clock} {b.event_type}" for b in spec.beats],
               "culprits": sorted(culprits), "variants": {}}
    packets = {}
    for v in bench["variants"]:
        if args.only and v["id"] not in args.only.split(","):
            continue
        plan = plan_direction(conn, spec, thread, focalizer=v.get("focalizer"), strategy=v.get("strategy"),
                              grammar=v.get("grammar"))
        packet = compile_packet(spec, direction=plan)
        packets[packet.packet_hash] = packet
        d = out / v["id"]
        d.mkdir(exist_ok=True)
        (d / "director_plan.json").write_text(json.dumps(asdict(plan), ensure_ascii=False, indent=1), encoding="utf-8")
        (d / "packet.json").write_text(json.dumps(asdict(packet), ensure_ascii=False, indent=1), encoding="utf-8")
        profile = viewing_profile(packet, culprits, payoff)
        results["variants"][v["id"]] = {"forced": plan.forced, "strategy": plan.knowledge.strategy,
                                        "focalizer": plan.focalization.focalizer, "goal": plan.dramatic_goal,
                                        "scene_hash": plan.scene_hash, **profile}
        print(f"{v['id']:24} shots {profile['shots']:2}  {profile['seconds']:3}s  height {profile['camera_height_m']}m  "
              f"subjective {profile['subjective_share']:.2f}  words {profile['words_audible_share']:.2f}  "
              f"culprit seen {profile['audience_witnesses_culprit_act']}", flush=True)
        if not args.no_render:
            from render.cast.packet_script import to_script
            from render.cast_backend import CastBackend
            options = {"series": "虛擬小鎮 · 導演實境測試", "tagline": " / ".join(v.get("badge", [])),
                       "badge": v.get("badge", []), "debug": args.debug}
            (d / "script.json").write_text(json.dumps(to_script(packet, **options), ensure_ascii=False, indent=1),
                                           encoding="utf-8")
            backend = CastBackend(packets.__getitem__, workdir=out / "projects", script_options=options)
            take = backend.render(backend.make_request(packet))
            if take.status != "ready":
                raise SystemExit(f"{v['id']}: render failed")
            mp4 = d / "episode.mp4"
            mp4.write_bytes(Path(take.artifact_path).read_bytes())
            frames(mp4, packet, d / "sheet.png")
    assert len({r["scene_hash"] for r in results["variants"].values()}) <= 1, "a variant changed the scene"
    (out / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    main_ids = [m for m in bench.get("main", []) if (out / m / "episode.mp4").exists()]
    if not args.no_render and len(main_ids) > 1:
        side_by_side([out / m / "episode.mp4" for m in main_ids], out / "comparison.mp4")
        subprocess.run([str(FFMPEG), "-y", "-loglevel", "error", *sum((["-i", str(out / m / "sheet.png")] for m in main_ids), []),
                        "-filter_complex", "".join(f"[{k}:v]" for k in range(len(main_ids))) + f"vstack=inputs={len(main_ids)}",
                        str(out / "comparison.png")], check=True)
        print("wrote", out / "comparison.mp4")


if __name__ == "__main__":
    main()
