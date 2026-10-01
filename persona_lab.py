"""Persona x world counterfactual lab: the same genomes in different branches. What stays, what drifts?

    python persona_lab.py --days 20 --seeds 3,55,260934 --out out/persona_lab
    python persona_lab.py --days 20 --target mei            # shape one person only; the rest live as they were

A branch is one run (contracts/persona.py SimulationBranch). The lab runs, for each seed:

  control    the town (town_life_v1) as written
  placebo    a formative event that leaves no mark (a house move): the noise floor, how far a world drifts from a bare
             extra event alone. Read every other branch against it.
  jianghu    the same genomes in another world (town_in_jianghu_v1)           -> "change the world"
  betrayed   in the town, but early in life they were betrayed by someone they trusted
  kindness   ... they were encouraged and helped
  hostile    ... they grew up among hostility
  success    ... they succeeded early, in front of others
  failed     ... they failed early and nobody reached out                     -> "change what made them"

`--target` shapes only that person (the others keep their own past); without it, everyone is shaped the same way.
Each person is probed in the same standard circumstances (persona_probe.py: exact probabilities, no sampling) when the
world starts and again after N days, and their life is summarised. Against the control branch it reports:

  retention    does each probe still rank the people alike (Spearman across people)? A shaping that keeps the order of
               who gossips more or apologises more kept the personalities; a world that scrambles it did not.
  drift        how far each person moved on each probe (mean absolute change in probability), and on what they hold:
               traits and values (mean absolute change), self-models, the kinds of goals they pursue
  relations    how much trust and affection between people differ, and how many clashes (hostile words, accusations,
               confrontations, losses of control) each branch had
  divergence   per person, where they ended up furthest from their control self
  group drift  one person in two crowds: how far the same genome is moved in the town and in the jianghu from its start

A bare extra event already moves a 20-day world (the placebo branch): who gossips more, who defends more is reshuffled by
chance alone. So every branch is also reported beyond the placebo (`beyond_placebo`), and a claim about a shaping rests on
that, over several seeds, not on the raw difference from the control.

Numbers only describe; nothing here is written back to any world.
"""
from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PRESETS = {  # name -> (kind, text, age, weight, experience)
    "betrayed": ("turning_point", "很小的時候，被最信任的人出賣", 10, 0.9, "betrayal"),
    "kindness": ("childhood", "小時候，總有人願意幫他、鼓勵他", 8, 0.9, "kindness"),
    "hostile": ("childhood", "成長的環境裡，身邊的人常常對他懷有敵意", 9, 0.9, "hostility"),
    "success": ("success", "年輕時就在一件大事上成功，被許多人看見", 18, 0.9, "success"),
    "failed": ("loss", "年輕時一次重要的失敗，沒有人伸手", 17, 0.9, "failure"),
    "placebo": ("childhood", "小時候搬過一次家", 7, 0.9, ""),  # history that leaves no mark: how much does a bare event move a world?
}
BRANCHES = ("control", "placebo", "jianghu") + tuple(p for p in PRESETS if p != "placebo")
PROBES = ("gossip", "apology", "defend", "accuse")
TRAITS = ("vigilance", "trust_default", "cynicism", "aggression", "withdrawal")
VALUES = ("security", "truth", "belonging", "revenge")
CLASH_TYPES = ("accuse", "confront", "shove", "strike")


def shaping(name: str, people: list[str]) -> dict:
    kind, text, age, weight, experience = PRESETS[name]
    return {p: {"formative": [{"kind": kind, "text": text, "age": age, "weight": weight, "experience": experience}]}
            for p in people}


def _life(conn) -> dict:
    """What each person ended up holding and doing, and how the branch went between people."""
    from world.attention import var
    people = [r[0] for r in conn.execute("SELECT person_id FROM character_profiles ORDER BY person_id")]
    out: dict = {"people": {}, "clashes": {}}
    for p in people:
        goals = sorted({r[0] for r in conn.execute("SELECT kind FROM goals WHERE person_id = ? AND status = 'active'", (p,))})
        rel = conn.execute("SELECT AVG(trust), AVG(affection) FROM relationships WHERE actor_id = ? AND target_id != ?", (p, p)).fetchone()
        out["people"][p] = {
            "traits": {k: round(var(conn, f"psy.{p}.{k}", 0.0), 4) for k in TRAITS},
            "values": {k: round(var(conn, f"psy.{p}.value.{k}", 0.0), 4) for k in VALUES},
            "self": sorted(k for k in ("cannot_trust", "always_blamed", "on_my_own", "some_are_kind", "world_is_hostile")
                           if var(conn, f"psy.{p}.self.{k}", 0.0) >= 0.5),
            "goals": goals, "trust": round(rel[0], 4), "affection": round(rel[1], 4)}
    marks = ",".join("?" * len(CLASH_TYPES))
    out["clashes"] = {
        "hostile_words": conn.execute("SELECT COUNT(*) FROM events WHERE type = 'talk' AND json_extract(truth, '$.tone') = 'hostile'").fetchone()[0],
        "clash_events": conn.execute(f"SELECT COUNT(*) FROM events WHERE type IN ({marks})", CLASH_TYPES).fetchone()[0],
        "turning_points": conn.execute("SELECT COUNT(*) FROM events WHERE type = 'reflection' AND "
                                       "json_extract(truth, '$.formed') != '[]'").fetchone()[0]}
    return out


def run_branch(seed: int, branch: str, days: int, target: str | None) -> dict:
    sys.path.insert(0, str(ROOT))
    from agent.volition import VolitionDecider
    from persona_probe import probe
    from world import personas
    from world.db import connect, init_db
    from world.seed import build_world
    from world.simulation import Simulation
    recipe = "town_in_jianghu_v1" if branch == "jianghu" else "town_life_v1"
    conn = connect()
    init_db(conn, seed)
    people = ["ming", "mei", "jun", "lan", "hao", "yun", "kai", "ning", "tao", "rui"]
    extras = shaping(branch, [target] if target else people) if branch in PRESETS else {}
    with personas.extras_override(extras) if extras else personas.extras_override(None):
        build_world(conn, seed, recipe)
    start = probe(conn, seed)
    d = VolitionDecider(seed)
    Simulation(conn, d, d, set(), feed="synthetic_v1").run(days)
    b = personas.branch(conn)
    return {"seed": seed, "branch": branch, "branch_id": b.branch_id if b else "", "recipe": recipe, "start": start,
            "end": probe(conn, seed), "life": _life(conn)}


def _mean(xs) -> float:
    xs = list(xs)
    return round(sum(xs) / len(xs), 4) if xs else 0.0


def compare(ctl: dict, br: dict) -> dict:
    """One branch against its control, same seed."""
    from cross_domain import spearman
    people = sorted(ctl["end"])
    out: dict = {"retention": {}, "probe_drift": {}, "divergence": {}}
    for k in PROBES:
        out["retention"][k] = spearman([ctl["end"][p][k] for p in people], [br["end"][p][k] for p in people])
        out["probe_drift"][k] = _mean(abs(br["end"][p][k] - ctl["end"][p][k]) for p in people)
    a, b = ctl["life"]["people"], br["life"]["people"]
    out["trait_drift"] = _mean(abs(b[p]["traits"][k] - a[p]["traits"][k]) for p in people for k in TRAITS)
    out["value_drift"] = _mean(abs(b[p]["values"][k] - a[p]["values"][k]) for p in people for k in VALUES)
    out["self_models"] = {"control": sum(len(a[p]["self"]) for p in people), "branch": sum(len(b[p]["self"]) for p in people)}
    out["goals_changed"] = sum(a[p]["goals"] != b[p]["goals"] for p in people)
    out["trust_diff"] = _mean(abs(b[p]["trust"] - a[p]["trust"]) for p in people)
    out["affection_diff"] = _mean(abs(b[p]["affection"] - a[p]["affection"]) for p in people)
    out["clashes"] = {k: [ctl["life"]["clashes"][k], br["life"]["clashes"][k]] for k in ctl["life"]["clashes"]}
    for p in people:
        moves = {k: round(br["end"][p][k] - ctl["end"][p][k], 3) for k in PROBES}
        top = max(moves, key=lambda k: abs(moves[k]))
        out["divergence"][p] = {"probe": top, "shift": moves[top], "self": [x for x in b[p]["self"] if x not in a[p]["self"]],
                                "trait": max(TRAITS, key=lambda k: abs(b[p]["traits"][k] - a[p]["traits"][k]))}
    return out


def group_drift(branch: dict) -> float:
    """How far the same genomes moved from their start in this branch's crowd (mean absolute change over probes)."""
    return _mean(abs(branch["end"][p][k] - branch["start"][p][k]) for p in branch["start"] for k in PROBES)


def average(per_seed: list[dict]) -> dict:
    """Mean of the numeric leaves over seeds (lists and strings are kept from the first seed)."""
    first = per_seed[0]
    if isinstance(first, dict):
        return {k: average([s[k] for s in per_seed]) for k in first}
    if isinstance(first, (int, float)) and not isinstance(first, bool):
        return round(sum(per_seed) / len(per_seed), 4)
    if isinstance(first, list) and first and all(isinstance(x, (int, float)) for x in first):
        return [round(sum(s[i] for s in per_seed) / len(per_seed), 3) for i in range(len(first))]
    return first


def beyond_placebo(r: dict, noise: dict) -> dict:
    """What a branch moved beyond what a bare extra event moves (both against the same control): positive means more."""
    pick = lambda d, keys: {k: round(d[k] - noise[k], 3) for k in keys}  # noqa: E731
    return {"probe_drift": {k: round(r["probe_drift"][k] - noise["probe_drift"][k], 3) for k in PROBES},
            "retention": {k: round(r["retention"][k] - noise["retention"][k], 3) for k in PROBES},
            **pick(r, ("trait_drift", "value_drift", "trust_diff", "affection_diff", "goals_changed")),
            "self_models": round(r["self_models"]["branch"] - noise["self_models"]["branch"], 2),
            "hostile_words": round(r["clashes"]["hostile_words"][1] - noise["clashes"]["hostile_words"][1], 1),
            "turning_points": round(r["clashes"]["turning_points"][1] - noise["clashes"]["turning_points"][1], 2)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=20)
    ap.add_argument("--seeds", default="3,55,260934")
    ap.add_argument("--branches", default=",".join(BRANCHES))
    ap.add_argument("--target", default=None, help="shape only this person (a person id)")
    ap.add_argument("--out", default="out/persona_lab")
    a = ap.parse_args()
    seeds = [int(s) for s in a.seeds.split(",")]
    branches = [b for b in a.branches.split(",") if b]
    if "control" not in branches:
        branches.insert(0, "control")
    jobs = [(s, b, a.days, a.target) for s in seeds for b in branches]
    with ProcessPoolExecutor(min(8, len(jobs))) as ex:
        runs = list(ex.map(run_branch, *zip(*jobs)))
    by = {(r["seed"], r["branch"]): r for r in runs}
    report: dict = {"days": a.days, "seeds": seeds, "target": a.target, "branches": {}, "group_drift": {}}
    for b in branches:
        report["group_drift"][b] = _mean(group_drift(by[(s, b)]) for s in seeds)
        if b != "control":
            report["branches"][b] = average([compare(by[(s, "control")], by[(s, b)]) for s in seeds])
    if "placebo" in report["branches"]:
        noise = report["branches"]["placebo"]
        report["beyond_placebo"] = {b: beyond_placebo(r, noise) for b, r in report["branches"].items() if b != "placebo"}
    report["branch_ids"] = {f"{r['seed']}:{r['branch']}": r["branch_id"] for r in runs}
    Path(a.out).mkdir(parents=True, exist_ok=True)
    (Path(a.out) / "persona_lab.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    print(f"persona lab: {a.days} days, seeds {seeds}" + (f", only {a.target} shaped" if a.target else ""))
    print("group drift (how far the same genomes move from their own start):", report["group_drift"])
    for b, r in report["branches"].items():
        print(f"\n[{b}] vs control")
        print("  retention (rank correlation across people):", r["retention"])
        print("  probe drift (mean |change| in probability):", r["probe_drift"])
        print(f"  traits {r['trait_drift']}  values {r['value_drift']}  self-models {r['self_models']}  goals changed in {r['goals_changed']} people")
        print(f"  trust diff {r['trust_diff']}  affection diff {r['affection_diff']}  clashes [control, branch] {r['clashes']}")
    for b, r in report.get("beyond_placebo", {}).items():
        print(f"\n[{b}] beyond the placebo (what the shaping moved, not the noise): {r}")


if __name__ == "__main__":
    main()
