"""How big is the difference a mind makes?  Paired by seed: the world with a model in it against the same seed with rules only.

    python soul_stats.py                      # every seed in out/soul/ whose 7 days are complete (both versions)
    python soul_stats.py --seeds 501,502      # only these

For each metric the difference (soul - rules) is taken per seed, then a paired bootstrap over the seeds (resample seeds with
replacement, 10000 times, a fixed random seed) gives the mean difference and a 90% percentile interval. "A difference" is only
claimed when the interval does not contain 0. With a handful of seeds the interval is wide; that is said, not hidden.

Reads only world.db and decisions.jsonl already on disk. Calls nothing, runs no world.
"""
from __future__ import annotations

import argparse
import json
import random
import re
from collections import Counter
from pathlib import Path

OUT = Path("out/soul")
DAYS = 7
BOOT_N = 10000
BOOT_SEED = 20261002
LEVEL = 0.90
OUTBURSTS = ("shove", "strike", "smash", "break_down")

# (key, label, kind). kind "paired": measured in both worlds. kind "mind": only the world with a mind has decisions.
PAIRED = [
    ("hostile_talk", "不客氣對話數"),
    ("cold_talk", "冷淡對話數"),
    ("warm_talk", "親切對話數"),
    ("outbursts", "失控次數 (shove/strike/smash/break_down)"),
    ("goals_formed", "新形成的目標數"),
    ("tension_v1", "v1 戲劇張力 7 天平均"),
    ("tension_all", "含套件情境的張力平均"),
    ("confront_accuse", "confront + accuse 次數"),
]
MIND = [
    ("differs_rate", "被喚醒的決定中與規則最想做的不同的比例"),
    ("first_line_rate", "被喚醒的決定中選第一行的比例"),
    ("first_line_vs_chance", "選第一行的比例 減 隨機期望值"),
]


# --------------------------------------------------------------------------------------------------------------------
# the statistics (pure: no files, no world)
# --------------------------------------------------------------------------------------------------------------------

def bootstrap_mean(values: list[float], n: int = BOOT_N, seed: int = BOOT_SEED, level: float = LEVEL) -> dict:
    """Percentile bootstrap of the mean of `values` (here: one difference per seed). Deterministic for a given seed."""
    k = len(values)
    if k == 0:
        return {"n": 0, "mean": None, "lo": None, "hi": None, "excludes_zero": False}
    mean = sum(values) / k
    if k == 1:   # nothing to resample: no interval can be given
        return {"n": 1, "mean": mean, "lo": None, "hi": None, "excludes_zero": False}
    rng = random.Random(seed)
    means = sorted(sum(values[rng.randrange(k)] for _ in range(k)) / k for _ in range(n))
    a = (1 - level) / 2
    lo = means[int(a * n)]
    hi = means[min(n - 1, int((1 - a) * n))]
    return {"n": k, "mean": mean, "lo": lo, "hi": hi, "excludes_zero": bool(lo > 0 or hi < 0)}


def paired_differences(soul: dict[int, dict], rules: dict[int, dict], key: str) -> dict[int, float]:
    """soul - rules per seed, only for seeds where both have the metric (a seed in one world only is never used)."""
    out = {}
    for seed in sorted(set(soul) & set(rules)):
        a, b = soul[seed].get(key), rules[seed].get(key)
        if a is not None and b is not None:
            out[seed] = a - b
    return out


def summarise(soul: dict[int, dict], rules: dict[int, dict]) -> dict:
    """Every paired metric: per-seed values and differences, and the bootstrap over the differences."""
    res = {}
    for key, label in PAIRED:
        diffs = paired_differences(soul, rules, key)
        res[key] = {"label": label, "soul": {s: soul[s].get(key) for s in diffs}, "rules": {s: rules[s].get(key) for s in diffs},
                    "diff": diffs, **bootstrap_mean(list(diffs.values()))}
    return res


def summarise_mind(soul: dict[int, dict]) -> dict:
    """The decision metrics only exist for the world with a mind: per seed, and the bootstrap of their mean over seeds."""
    res = {}
    for key, label in MIND:
        vals = {s: m[key] for s, m in sorted(soul.items()) if m.get(key) is not None}
        res[key] = {"label": label, "by_seed": vals, **bootstrap_mean(list(vals.values()))}
    return res


# --------------------------------------------------------------------------------------------------------------------
# reading what is on disk
# --------------------------------------------------------------------------------------------------------------------

def world_metrics(db: Path) -> dict:
    from narrative.dramaturgy import analyse
    from world.db import connect
    c = connect(db)
    try:
        days = c.execute("SELECT COUNT(DISTINCT timestamp / 1440) FROM events WHERE type = 'day_end'").fetchone()[0]
        rep = analyse(c)
        curve, allc = rep["curve"], rep["curve_all"]
        ev = Counter(r[0] for r in c.execute("SELECT type FROM events"))
        tone = Counter(json.loads(r[0] or "{}").get("tone") for r in c.execute("SELECT truth FROM events WHERE type = 'talk'"))
        goals = c.execute("SELECT COUNT(*) FROM events WHERE type = 'goal_change' AND "
                          "json_extract(truth, '$.to') IN ('formed', 'transformed')").fetchone()[0]
        return {"days": days, "hostile_talk": tone["hostile"], "cold_talk": tone["cold"], "warm_talk": tone["warm"],
                "outbursts": sum(ev[t] for t in OUTBURSTS), "goals_formed": goals,
                "tension_v1": sum(curve) / len(curve) if curve else 0.0, "tension_all": sum(allc) / len(allc) if allc else 0.0,
                "confront_accuse": ev["confront"] + ev["accuse"]}
    finally:
        c.close()


def decision_metrics(path: Path) -> dict:
    rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()] if path.exists() else []
    ok = [r for r in rows if "error" not in r]
    shown = [r for r in ok if "shown_at" in r]
    out = {"woke": len(rows), "answered": len(ok), "failed": len(rows) - len(ok)}
    if ok:
        out["differs_rate"] = sum(1 for r in ok if r["differs"]) / len(ok)
    if shown:
        out["first_line_rate"] = sum(1 for r in shown if r["shown_at"] == 0) / len(shown)
        out["first_line_vs_chance"] = out["first_line_rate"] - sum(1 / r["of"] for r in shown) / len(shown)
    return out


def find_seeds(out: Path) -> list[int]:
    return sorted(int(m.group(1)) for p in out.iterdir() if (m := re.fullmatch(r"soul(\d+)", p.name)) and p.is_dir())


def load(out: Path, seeds: list[int] | None = None, days: int = DAYS) -> tuple[dict, dict, dict]:
    """Returns (soul, rules, skipped): metrics by seed for the complete pairs, and why the others were left out."""
    soul, rules, skipped = {}, {}, {}
    for seed in seeds or find_seeds(out):
        a, b = out / f"soul{seed}", out / f"soul{seed}.baseline"
        if not (a / "world.db").exists() or not (b / "world.db").exists():
            skipped[seed] = "a world is missing"
            continue
        ma, mb = world_metrics(a / "world.db"), world_metrics(b / "world.db")
        if ma["days"] < days or mb["days"] < days:
            skipped[seed] = f"incomplete (soul {ma['days']} days, rules {mb['days']} days)"
            continue
        soul[seed] = {**ma, **decision_metrics(a / "decisions.jsonl")}
        rules[seed] = mb
    return soul, rules, skipped


# --------------------------------------------------------------------------------------------------------------------

def fmt(x, nd=2) -> str:
    return "-" if x is None else f"{x:.{nd}f}"


def print_report(paired: dict, mind: dict, soul: dict, skipped: dict) -> None:
    seeds = sorted(soul)
    print(f"seeds used ({len(seeds)}): {seeds}" + (f"; left out: {skipped}" if skipped else ""))
    print(f"\nper seed, soul / rules")
    print(f"{'metric':<44}" + "".join(f"{s:>12}" for s in seeds))
    for key, r in paired.items():
        print(f"{r['label']:<40}" + "".join(f"{fmt(r['soul'].get(s), 1) + '/' + fmt(r['rules'].get(s), 1):>12}" for s in seeds))
    print(f"\npaired difference (soul - rules), paired bootstrap {BOOT_N}x, {int(LEVEL * 100)}% interval")
    print(f"{'metric':<40}{'mean diff':>10}{'lo':>9}{'hi':>9}   verdict")
    for key, r in paired.items():
        verdict = "有差別" if r["excludes_zero"] else ("樣本不足" if r["n"] < 2 else "區間含 0")
        print(f"{r['label']:<36}{fmt(r['mean']):>10}{fmt(r['lo']):>9}{fmt(r['hi']):>9}   {verdict}")
    print(f"\nwoken decisions (soul world only; no rules-only counterpart)")
    print(f"{'metric':<44}" + "".join(f"{s:>9}" for s in seeds) + f"{'mean':>9}{'lo':>8}{'hi':>8}")
    for key, r in mind.items():
        print(f"{r['label']:<30}" + "".join(f"{fmt(r['by_seed'].get(s), 3):>9}" for s in seeds)
              + f"{fmt(r['mean'], 3):>9}{fmt(r['lo'], 3):>8}{fmt(r['hi'], 3):>8}")
    print("minds woke per seed:", {s: soul[s]["woke"] for s in seeds}, "total", sum(soul[s]["woke"] for s in seeds))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--seeds", default="", help="comma-separated; default: every soul<seed> directory")
    ap.add_argument("--days", type=int, default=DAYS)
    a = ap.parse_args()
    out = Path(a.out)
    seeds = [int(x) for x in a.seeds.split(",") if x.strip()] or None
    soul, rules, skipped = load(out, seeds, a.days)
    paired, mind = summarise(soul, rules), summarise_mind(soul)
    print_report(paired, mind, soul, skipped)
    pooled = {"woke": sum(m["woke"] for m in soul.values()), "answered": sum(m["answered"] for m in soul.values()),
              "failed": sum(m["failed"] for m in soul.values())}
    dump = {"seeds": sorted(soul), "skipped": {str(k): v for k, v in skipped.items()}, "days": a.days, "bootstrap": {"n": BOOT_N, "seed": BOOT_SEED, "level": LEVEL},
            "paired": json.loads(json.dumps(paired)), "mind": json.loads(json.dumps(mind)), "pooled": pooled,
            "per_seed": {"soul": {str(s): m for s, m in soul.items()}, "rules": {str(s): m for s, m in rules.items()}}}
    (out / "stats.json").write_text(json.dumps(dump, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nwrote {out / 'stats.json'}")


if __name__ == "__main__":
    main()
