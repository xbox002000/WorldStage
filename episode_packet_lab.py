"""The A/B episode in the packet, measured.   python episode_packet_lab.py --seeds 501,502,503,504,505,506,507,508 --days 14

Each seed is a world run (jianghu_story_v1, 14 days, the greedy producer, no spatial runtime) and every day three arms make their own
episode with their own memory of what they have told:

  off     the thread director's pick (what a daily job does today, `episode_first` off): the packet is one thread's scenes
  first   `episode_first` on, the planner's single-story options: its material and its intents
  ab      `episode_first` on with the A/B options: the A story, the B story and an ordinary moment, composed into one packet
          (production/episode_packet.py), once with no length budget and once within `--budget` seconds

Only packets are compiled (production/episode_packet.compile_arc with the performance plan); nothing is rendered and the video-model
cost is the dry-run planner's (production/dryrun.py), which has no code that sends anything. Reported per arm: episodes, shots and the
shots' seconds per episode, distinct shot intents per episode, episodes with a single intent, B/texture presence, the dry-run cost.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ARMS = ("off", "first", "ab_nobudget", "ab")


def patch_describe() -> list[str]:
    """HEAD bug, worked around here only so that the payoff episodes can be measured: the faction domain's `describe` for `succession`
    and `found_faction` is "{who}...", but a packet's caption fills `{a}`, `{b}` and `{thing}` (narrative/compiler.py caption), so a packet
    with either event raises KeyError('who'). The fix is two words in world/domains/factions.py; it is not made by this work."""
    import dataclasses
    from world.domains import all_domains
    fixed = []
    for d in all_domains():
        for k, v in list(d.styles.items()):
            if "{who}" in (v.describe or ""):
                d.styles[k] = dataclasses.replace(v, describe=v.describe.replace("{who}", "{a}"))
                fixed.append(k)
    return fixed


def run(args) -> dict:
    seed, days, recipe, budget = args
    sys.path.insert(0, str(ROOT))
    patch_describe()
    from agent.volition import VolitionDecider
    from narrative import episode_planner as EP
    from narrative.director import select_thread
    from narrative.dramaturgy import analyse
    from producer.director import Director
    from production import dryrun
    from production import episode_packet as EK
    from world.db import connect, init_db
    from world.seed import build_world
    from world.simulation import Simulation
    conn = connect()
    init_db(conn, seed)
    build_world(conn, seed, recipe)
    d = VolitionDecider(seed)
    sim = Simulation(conn, d, d, set(), feed="synthetic_v1", producer=Director("greedy", seed))
    shown = {a: set() for a in ARMS}
    rows: list[dict] = []

    def measure(arm, day, packet, extra=None):
        kinds = [s.function for s in packet.shots]
        cost = dryrun.plan(packet)
        rows.append({"seed": seed, "day": day, "arm": arm, "shots": len(packet.shots), "body_seconds": EK.body_seconds(packet),
                     "total_seconds": packet.qa.total_seconds, "intents": sorted(set(kinds)), "kinds": len(set(kinds)),
                     "escalate_share": round(kinds.count("escalate") / max(1, len(kinds)), 3),
                     "dryrun_all_wanted": cost["all_wanted_total"], **(extra or {})})

    for day in range(days):
        sim.run(1)
        sit = analyse(conn)["situations"]
        # off: the thread director's pick, films the whole arc, no intents
        cand, thread, _ = select_thread(conn, day, shown["off"])
        if cand is not None:
            shown["off"] |= set(cand.arc.ids)
            measure("off", day, EK.compile_arc(conn, cand.arc, thread, shown["off"] - set(cand.arc.ids), None, performance=True))
        # first: the planner chooses, single story; the daily job's intents (one per event: the last beat's wins)
        arc, thread, kind, payoff, steps = EP.choose_material(conn, day, shown["first"])
        if arc is not None:
            plan = EP.plan_episode(conn, arc, thread, shown["first"], day, kind, payoff, steps, sit)
            intents = {i: [b.intent] for b in plan.beats if b.shoot for i in b.event_ids}
            before = set(shown["first"])
            shown["first"] |= set(arc.ids)
            measure("first", day, EK.compile_arc(conn, arc, thread, before, intents, performance=True),
                    {"kind": kind, "beat_kinds": len({b.intent for b in plan.beats if b.shoot}),
                     "overwritten": sum(1 for e in intents if sum(1 for b in plan.beats if b.shoot and e in b.event_ids) > 1)})
        # ab: composed from the A/B plan, without and with the length budget
        for name, limit in (("ab_nobudget", 1e9), ("ab", budget)):
            m = EP.material(conn, day, shown[name], (), EP.AB)
            if m.arc is None:
                continue
            comp = EK.compose(conn, m, shown[name], day, sit, EP.AB, budget=limit)
            if comp is None:
                continue
            before = set(shown[name])
            shown[name] |= set(comp.arc.ids)
            packet = EK.compile_arc(conn, comp.arc, m.thread, before, comp.intents, performance=True)
            emap = EK.build_map(packet, comp)
            assert not EK.check_map(packet, emap), EK.check_map(packet, emap)
            stories = [r.story for r in emap.shots]
            secs = {k: sum(sh.duration_seconds for r, sh in zip(emap.shots, packet.shots) if r.story == k) for k in ("A", "B", "texture")}
            measure(name, day, packet, {
                "kind": m.kind, "A": stories.count("A"), "B": stories.count("B"), "texture": stories.count("texture"),
                "sec_A": secs["A"], "sec_B": secs["B"], "sec_texture": secs["texture"],
                "beat_kinds": len({b.intent for b in EK.filmed_beats(comp.plan)}),
                "had_b": any(b.story == "B" for b in EK.filmed_beats(comp.source_plan)),
                "had_texture": any(b.story == "texture" for b in EK.filmed_beats(comp.source_plan)),
                "trimmed": [t.story for t in comp.trimmed], "over_budget": comp.over_budget,
                "elided_beats": sum(1 for b in emap.beats if not b.shots), "beats": len(emap.beats)})
    return {"seed": seed, "rows": rows}


def pct(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(q * (len(xs) - 1))))] if xs else 0


def summarize(rows: list[dict], arm: str, budget: float) -> dict:
    r = [x for x in rows if x["arm"] == arm]
    n = len(r)
    f = lambda k: [x[k] for x in r]  # noqa: E731
    out = {
        "episodes": n,
        "shots_mean": round(statistics.mean(f("shots")), 2) if n else 0, "shots_p90": pct(f("shots"), 0.9), "shots_max": max(f("shots"), default=0),
        "body_seconds_mean": round(statistics.mean(f("body_seconds")), 1) if n else 0, "body_seconds_p90": pct(f("body_seconds"), 0.9),
        "body_seconds_max": max(f("body_seconds"), default=0),
        "total_seconds_mean": round(statistics.mean(f("total_seconds")), 1) if n else 0,
        "over_budget_episodes": sum(1 for x in r if x["body_seconds"] > budget),
        "intent_kinds_mean": round(statistics.mean(f("kinds")), 2) if n else 0,
        "single_intent_episodes": sum(1 for x in r if x["kinds"] == 1), "single_intent_rate": round(sum(1 for x in r if x["kinds"] == 1) / max(1, n), 3),
        "kinds_le2_rate": round(sum(1 for x in r if x["kinds"] <= 2) / max(1, n), 3),
        "escalate_share_mean": round(statistics.mean(f("escalate_share")), 3) if n else 0,
        "dryrun_all_wanted_mean_usd": round(statistics.mean(f("dryrun_all_wanted")), 2) if n else 0,
    }
    if arm == "first":
        out["events_whose_first_intent_is_overwritten"] = sum(x["overwritten"] for x in r)
    if arm != "off":
        out.update({"beat_kinds_mean": round(statistics.mean(f("beat_kinds")), 2) if n else 0,
                    "beat_single_intent_rate": round(sum(1 for x in r if x["beat_kinds"] == 1) / max(1, n), 3)})
    if arm.startswith("ab"):
        out.update({
            "sec_A": sum(x["sec_A"] for x in r), "sec_B": sum(x["sec_B"] for x in r), "sec_texture": sum(x["sec_texture"] for x in r),
            "episodes_with_B_shots": sum(1 for x in r if x["B"] > 0), "episodes_with_texture_shots": sum(1 for x in r if x["texture"] > 0),
            "shots_A": sum(x["A"] for x in r), "shots_B": sum(x["B"] for x in r), "shots_texture": sum(x["texture"] for x in r),
            "planned_with_B": sum(1 for x in r if x["had_b"]), "planned_with_texture": sum(1 for x in r if x["had_texture"]),
            "episodes_trimmed": sum(1 for x in r if x["trimmed"]), "texture_trimmed": sum(1 for x in r if "texture" in x["trimmed"]),
            "B_trimmed": sum(1 for x in r if "B" in x["trimmed"]), "A_alone_over_budget": sum(1 for x in r if x["over_budget"]),
            "beats": sum(x["beats"] for x in r), "elided_beats": sum(x["elided_beats"] for x in r)})
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--seeds", default="501,502,503,504,505,506,507,508")
    ap.add_argument("--recipe", default="jianghu_story_v1")
    ap.add_argument("--budget", type=float, default=None)
    ap.add_argument("--out", default="out/episode_packet_lab")
    a = ap.parse_args()
    sys.path.insert(0, str(ROOT))
    from production.episode_packet import BODY_SECONDS_BUDGET
    budget = a.budget if a.budget is not None else BODY_SECONDS_BUDGET
    seeds = [int(s) for s in a.seeds.split(",")]
    with ProcessPoolExecutor(min(8, len(seeds))) as ex:
        res = list(ex.map(run, [(s, a.days, a.recipe, budget) for s in seeds]))
    rows = [x for r in res for x in r["rows"]]
    Path(a.out).mkdir(parents=True, exist_ok=True)
    (Path(a.out) / "rows.json").write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    s = {arm: summarize(rows, arm, budget) for arm in ARMS}
    (Path(a.out) / "summary.json").write_text(json.dumps({"budget": budget, "arms": s}, ensure_ascii=False, indent=1), encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    keys = list(s["ab"])
    print(f"budget {budget}s of shots;  {'':28}" + "".join(f"{v:>14}" for v in ARMS))
    for k in keys:
        print(f"{k:38}" + "".join(f"{s[v].get(k, '-'):>14}" for v in ARMS))


if __name__ == "__main__":
    main()
