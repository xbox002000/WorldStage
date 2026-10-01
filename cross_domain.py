"""Cross-domain character test: the same people in two worlds. Is each still the same person, living a different life?

    python cross_domain.py --days 20 --seeds 3,55,260934 --out out/cross_domain

The town's ten people (world/content/profiles/town_v1.json) run in the town (recipe town_life_v1) and, with the same
profiles and only a different casting, in the jianghu (recipe town_in_jianghu_v1). For each person a behavioural
signature is measured from what they did:

  hostile     share of their words said with hostility         warm        ... with warmth
  retort      share of their answers that hit back             conciliate  ... that apologise or soothe
  storm_off   share of their answers that walk out            deceit      share of their passing-on that lies, bends or omits
  gossip      things passed on, per chance to pass something on (a decision with something to tell and someone to tell)
  apology     apologies, per answer given while in the wrong
  clash       confrontations and accusations, per chance to confront or accuse

Personality invariant: across the ten people, each signature should rank them alike in both worlds (Spearman rank
correlation per signature, averaged over seeds). Behaviour adapts: what the world offers is used (duels and training
in the jianghu; a job search becomes "打聽別的門派"); goals adapt; the director and the runtime still work.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WORLDS = {"town": "town_life_v1", "jianghu": "town_in_jianghu_v1"}
SIGNATURES = ("hostile", "warm", "retort", "conciliate", "storm_off", "deceit", "gossip", "apology", "clash")


class Chances:
    """Counts each person's chances (wraps the rule agent and the replier; changes nothing they decide)."""

    def __init__(self) -> None:
        self.n: dict[str, Counter] = defaultdict(Counter)

    def watch(self, decider, replier) -> None:
        options, reply = decider.options, replier.reply

        def counted_options(conn, actor, now):
            out = options(conn, actor, now)
            kinds = {it.action for _, it in out if it is not None}
            for k in ("tell", "confront", "accuse"):
                self.n[actor][k] += k in kinds
            self.n[actor]["clash"] += bool(kinds & {"confront", "accuse"})
            return out

        def counted_reply(conn, row, turn, now):
            from agent.reply import stimulus
            s = stimulus(row)
            if s is not None and s[3]:
                self.n[s[0]]["wrong"] += 1
            return reply(conn, row, turn, now)
        decider.options, replier.reply = counted_options, counted_reply


def signatures(conn, days: int, chances: "Chances | None" = None) -> dict[str, dict[str, float]]:
    talk, tone, replies, stance, tells, lies, clash = (Counter() for _ in range(7))
    tone = defaultdict(Counter)
    stance = defaultdict(Counter)
    for etype, truth in conn.execute("SELECT type, truth FROM events"):
        t = json.loads(truth)
        a = t.get("actor")
        reason = t.get("reason") or ""
        if etype == "talk":
            talk[a] += 1
            tone[a][t.get("tone")] += 1
        if reason.startswith("reply:"):
            replies[a] += 1
            stance[a][reason.split(":", 1)[1]] += 1
        if etype == "tell":
            tells[a] += 1
            lies[a] += t.get("mode") in ("lie", "distortion", "omission")
        if etype in ("confront", "accuse"):
            clash[a] += 1
    people = [r[0] for r in conn.execute("SELECT person_id FROM character_profiles ORDER BY person_id")]
    out = {}
    for p in people:
        n, r = max(1, talk[p]), max(1, replies[p])
        ch = chances.n[p] if chances is not None else Counter()
        out[p] = {"hostile": tone[p]["hostile"] / n, "warm": tone[p]["warm"] / n,
                  "retort": stance[p]["retort"] / r, "conciliate": (stance[p]["apologize"] + stance[p]["soothe"]) / r,
                  "storm_off": stance[p]["storm_off"] / r, "deceit": lies[p] / max(1, tells[p]),
                  "gossip": tells[p] / max(1, ch["tell"]) if chances is not None else tells[p] / days,
                  "apology": stance[p]["apologize"] / max(1, ch["wrong"]),
                  "clash": clash[p] / max(1, ch["clash"]) if chances is not None else clash[p] / days}
    return out


def life(conn) -> dict:
    kinds = Counter(r[0] for r in conn.execute("SELECT type FROM events"))
    goals = Counter(json.loads(r[0])["kind"] for r in conn.execute(
        "SELECT truth FROM events WHERE type = 'goal_change' AND json_extract(truth, '$.to') IN ('formed', 'transformed')"))
    words = [json.loads(r[0]).get("text") for r in conn.execute(
        "SELECT truth FROM events WHERE type IN ('job_search', 'overtime', 'job_offer', 'resign', 'decline_offer') LIMIT 3")]
    return {"events": {k: kinds[k] for k in ("duel", "train", "work", "overtime", "praise", "job_search", "job_offer",
                                              "resign", "decline_offer") if kinds[k]},
            "goals": dict(goals.most_common()), "words": words}


def one(world: str, seed: int, days: int, out: str) -> dict:
    sys.path.insert(0, str(ROOT))
    from agent.volition import VolitionDecider
    from world.db import connect, init_db
    from world.seed import build_world
    from world.simulation import Simulation
    from world.db import save_to
    db = Path(out) / f"{world}_{seed}.db"
    conn = connect()  # simulated in memory; kept as a file at the end
    init_db(conn, seed)
    build_world(conn, seed, WORLDS[world])
    d = VolitionDecider(seed)
    sim = Simulation(conn, d, d, set(), feed="synthetic_v1" if world == "town" else None)
    chances = Chances()
    chances.watch(d, sim.replier)
    sim.run(days)
    save_to(conn, db)
    return {"world": world, "seed": seed, "signatures": signatures(conn, days, chances), "life": life(conn),
            "seconds": round(sim.profile.ms["day"] / 1000, 1)}


def spearman(xs: list[float], ys: list[float]) -> float:
    def ranks(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(order):  # ties share their mean rank
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            for k in range(i, j + 1):
                r[order[k]] = (i + j) / 2
            i = j + 1
        return r
    rx, ry = ranks(xs), ranks(ys)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    sx = sum((a - mx) ** 2 for a in rx) ** 0.5
    sy = sum((b - my) ** 2 for b in ry) ** 0.5
    return round(cov / (sx * sy), 3) if sx and sy else 0.0


def compare(runs: list[dict]) -> dict:
    by = {(r["world"], r["seed"]): r for r in runs}
    seeds = sorted({r["seed"] for r in runs})
    rho: dict[str, list[float]] = defaultdict(list)
    for s in seeds:
        a, b = by[("town", s)]["signatures"], by[("jianghu", s)]["signatures"]
        people = sorted(set(a) & set(b))
        for sig in SIGNATURES:
            rho[sig].append(spearman([a[p][sig] for p in people], [b[p][sig] for p in people]))
    return {sig: round(sum(v) / len(v), 3) for sig, v in rho.items()}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=20)
    ap.add_argument("--seeds", default="3,55,260934")
    ap.add_argument("--out", default="out/cross_domain")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    seeds = [int(s) for s in a.seeds.split(",")]
    jobs = [(w, s) for s in seeds for w in WORLDS]
    with ProcessPoolExecutor(min(8, len(jobs))) as ex:
        runs = list(ex.map(one, [w for w, _ in jobs], [s for _, s in jobs], [a.days] * len(jobs), [str(out)] * len(jobs)))
    rho = compare(runs)
    report = {"days": a.days, "seeds": seeds, "rank_correlation": rho, "runs": runs}
    (out / "cross_domain.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    print("personality across worlds (Spearman, mean over seeds):", rho)
    for r in runs:
        print(r["world"], r["seed"], r["seconds"], "s", r["life"])


if __name__ == "__main__":
    main()
