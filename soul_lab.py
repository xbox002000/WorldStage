"""Give the people a mind and watch what they do — spending as little of the free quota as possible.

    python soul_lab.py --name pilot --days 3 --dry                      # the whole pipeline with a stub mind: no network, no quota
    python soul_lab.py --name pilot --days 3 --daily-limit 20           # for real (needs GEMINI_API_KEY in the environment)
    python soul_lab.py --name pilot --days 7 --daily-limit 20           # the same world, further: what was paid for is not asked again

What keeps the quota from being wasted:
  * Every answer is kept in `llm_cache.db` next to the world and asked for first (mode "cache"). The world is deterministic,
    so a day that is run again asks the same questions and gets the same answers: running again costs only what is new.
  * The quota is counted in `out/soul/ledger.json` by the provider's day (Pacific time), by model, and a known daily limit
    is refused here before the provider has to say no.
  * When the quota (or the key, or the model) gives out, the run STOPS at that decision; the unfinished day is thrown away
    and the world goes back to the end of the last whole day. It does not let the rule agent finish the day: a world that is
    half mind and half rule would answer nothing. Run it again after the quota resets and it goes on from there.
  * Tier A only by default: a value crossed, a clash, a resolve. A bad mood on its own (a third of the wake-ups, and the
    least likely to change what is chosen) is left to the rule agent unless `--tier AB`.
  * One model for the whole world, one try per request (every try is spent quota), no other provider mixed in.

The world is plain `world.db` and is read like any other (control room, episode planner): nothing downstream needs the mind again.
"""
from __future__ import annotations

import argparse
import json
import random
import shutil
import sqlite3
import sys
from collections import Counter
from pathlib import Path

from agent.cognition import CharacterAgent, QuotaPause
from agent.llm_cache import LLMCache
from agent.llm_ledger import Ledger
from agent.volition import VolitionDecider
from world.db import connect, init_db
from world.seed import build_world
from world.simulation import Simulation

OUT = Path("out/soul")
CACHE_DDL = """CREATE TABLE IF NOT EXISTS llm_cache (request_hash TEXT PRIMARY KEY, provider TEXT NOT NULL, model TEXT NOT NULL,
               request_json TEXT NOT NULL, response_json TEXT NOT NULL, created_at INTEGER NOT NULL)"""


def recorded_order(actor: str, now: int, n: int) -> list[int]:
    """The shuffle the first 11 worlds' answers were asked with. It stays, so those answers (the cache) still match and
    those worlds can be gone on with without paying for them again; the engine's own default uses the world's rng."""
    order = list(range(n))
    random.Random(f"{actor}|{now}").shuffle(order)
    return order


class DryMind:
    """A stand-in that asks nobody: always the first option. Proves the plumbing for nothing."""
    model = "dry"

    def generate_json(self, prompt, schema, temperature=0.7):
        return {"option": 0, "reason": "（試跑）", "inner": ""}


def open_cache(path: Path) -> sqlite3.Connection:
    c = sqlite3.connect(path, isolation_level=None)
    c.execute(CACHE_DDL)
    return c


def make_client(a, cache_conn, ledger):
    if a.dry:
        return DryMind()
    from agent.llm import build_chain, has_api_key
    if not has_api_key("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        raise SystemExit("GEMINI_API_KEY is not set in the environment: nothing was asked, nothing was spent.")
    return build_chain(a.model, max_calls=a.max_calls, min_interval=a.min_interval, use_openrouter=False, mode="cache",
                       cache=LLMCache(cache_conn), retries=1, ledger=ledger, daily_limit=a.daily_limit)


def run_world(a, root: Path, client, days: int, *, mind: bool = True, announce=print) -> dict:
    """Run (or go on with) the world at `root` until `days` whole days exist. Returns what happened."""
    root.mkdir(parents=True, exist_ok=True)
    db = root / "world.db"
    fresh = not db.exists()
    conn = connect(db)
    version = int(getattr(a, "prompt_version", 1))
    if fresh:
        init_db(conn, a.seed)
        build_world(conn, a.seed, a.recipe)
        if version != 1:  # a world made with a later prompt says so (the control room replays it with the same one); a v1 world says nothing, as before
            conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('prompt_version', ?)", (str(version),))
    else:
        row = conn.execute("SELECT value FROM meta WHERE key = 'prompt_version'").fetchone()
        if int(row[0] if row else 1) != version:
            raise SystemExit(f"this world was made with prompt v{row[0] if row else 1}: its answers are cached by that prompt, so it goes on with it "
                             f"(--prompt-version {row[0] if row else 1}); a new world is made with v{version}")
    agent = CharacterAgent(VolitionDecider(a.seed), client if mind else None, budget=a.budget, tier=a.tier, pause_on_quota=True,
                           per_person_day=getattr(a, "per_person_day", None), shuffle=recorded_order if getattr(a, "shuffle", False) else False,
                           prompt_version=version)
    sim = Simulation(conn, agent, agent, set())
    log = root / "decisions.jsonl"
    paused = None
    done = sim.next_day()
    while done < days:
        prev = root / "world.prev"
        bak = sqlite3.connect(prev)
        conn.backup(bak)
        bak.close()
        agent.log.clear()
        try:
            sim.run(1)
        except QuotaPause as e:
            paused = str(e)
            conn.close()
            for ext in ("", "-wal", "-shm"):
                (root / f"world.db{ext}").unlink(missing_ok=True)
            shutil.copyfile(prev, db)
            announce(f"  day {done + 1}: stopped at a decision ({paused[:140]}); the day is thrown away, the world is back at the end of day {done}")
            break
        entries = list(agent.log)
        with log.open("a", encoding="utf-8") as f:
            for r in entries:
                f.write(json.dumps({"day": done + 1, **r}, ensure_ascii=False) + "\n")
        announce(f"  day {done + 1}: {len(entries)} minds woke ({sum(1 for r in entries if 'error' in r)} failed)")
        done = sim.next_day()
    if paused is None:
        conn.close()
    return {"days": done, "paused": paused, "stats": dict(agent.stats)}


def report(root: Path) -> dict:
    rows = [json.loads(x) for x in (root / "decisions.jsonl").read_text(encoding="utf-8").splitlines()] if (root / "decisions.jsonl").exists() else []
    ok = [r for r in rows if "error" not in r]
    tone = Counter()
    for r in ok:
        for w in ("親切地", "冷淡地", "不客氣地"):
            if r["chose"].startswith(w):
                tone[w] += 1
    kinds = Counter(r["chose"].split("，")[0][:6] for r in ok)
    shown = [r for r in ok if "shown_at" in r]
    return {"woke": len(rows), "answered": len(ok), "failed": len(rows) - len(ok),
            "who_woke": dict(Counter(r["person"] for r in rows).most_common()),
            "differs_from_rules_most_wanted": f"{sum(1 for r in ok if r['differs'])}/{len(ok)}" if ok else "-",
            "chose_the_line_shown_first": f"{sum(1 for r in shown if r['shown_at'] == 0)}/{len(shown)}" if shown else "-",
            "chose_the_rules_favourite": f"{sum(1 for r in shown if r['option'] == 0)}/{len(shown)}" if shown else "-",
            "chose_a_tone": dict(tone), "options_offered_mean": round(sum(r["of"] for r in ok) / len(ok), 1) if ok else 0,
            "samples": [{"day": r["day"], "person": r["person"], "wake": r["wake"], "chose": r["chose"], "reason": r["reason"], "inner": r["inner"]}
                        for r in ok[:6]]}


def event_mix(db: Path) -> dict:
    c = connect(db)
    mix = Counter()
    for r in c.execute("SELECT type, truth FROM events"):
        t = json.loads(r["truth"] or "{}")
        if r["type"] == "talk":
            mix[f"talk:{t.get('tone', '?')}"] += 1
        elif r["type"] in ("confront", "accuse", "goal_change", "tell", "lend", "steal", "take", "give"):
            mix[r["type"]] += 1
    c.close()
    return dict(sorted(mix.items()))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="pilot")
    ap.add_argument("--recipe", default="jianghu_story_v1")
    ap.add_argument("--seed", type=int, default=501)
    ap.add_argument("--days", type=int, default=3)
    ap.add_argument("--model", default="gemini-3.5-flash-lite", help="one model; a comma-separated list hands over when one's quota is gone")
    ap.add_argument("--tier", default="A", choices=("A", "AB"))
    ap.add_argument("--budget", type=int, default=20, help="most wake-ups a world day may have")
    ap.add_argument("--per-person-day", type=int, default=2, help="most wake-ups one person may have in a day (0 = no cap)")
    ap.add_argument("--no-shuffle", action="store_true", help="show the options best-first (the first line is then the rules' favourite)")
    ap.add_argument("--daily-limit", type=int, default=None, help="the free calls a day this model has (the ledger refuses past it)")
    ap.add_argument("--max-calls", type=int, default=None, help="a hard cap on the calls of this run")
    ap.add_argument("--min-interval", type=float, default=4.0)
    ap.add_argument("--dry", action="store_true", help="a stub mind: no network, no quota")
    ap.add_argument("--prompt-version", type=int, default=1, choices=(1, 2, 3),
                    help="1: the prompt the recorded worlds were asked (the default, so they can be gone on with); 2: era, who is he or she, a reason "
                         "about the option chosen, and a checked answer (agent/cognition.py): for a new world, e.g. jianghu_drama_v1")
    ap.add_argument("--baseline", action="store_true", help="also run the same world with rules only, for a comparison of what is chosen")
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args()
    a.shuffle = not a.no_shuffle
    a.per_person_day = a.per_person_day or None
    out = Path(a.out)
    root = out / a.name
    ledger = Ledger(out / "ledger.json")
    root.parent.mkdir(parents=True, exist_ok=True)
    cache_conn = open_cache(root.parent / f"{a.name}.llm_cache.db")
    client = make_client(a, cache_conn, ledger)
    model = a.model.split(",")[0]
    print(f"world {a.recipe} seed {a.seed}, prompt v{a.prompt_version}, to day {a.days}, {'DRY (no network)' if a.dry else a.model}, tier {a.tier}, "
          f"ledger today: {ledger.used(model)} used" + (f" of {a.daily_limit}" if a.daily_limit else ""))
    before = getattr(client, "calls", 0)
    res = run_world(a, root, client, a.days)
    calls = getattr(client, "calls", 0) - before
    print(f"asked the provider {calls} times this run; ledger today: {ledger.used(model)}"
          + (f" of {a.daily_limit}" if a.daily_limit else ""))
    print(f"world is at day {res['days']} of {a.days}" + (" (STOPPED early)" if res["paused"] else ""))
    print(json.dumps(report(root), ensure_ascii=False, indent=1))
    if a.baseline and res["days"]:
        base = out / f"{a.name}.baseline"
        shutil.rmtree(base, ignore_errors=True)
        run_world(a, base, None, res["days"], mind=False, announce=lambda *_: None)
        print("what happened (soul vs rules only, same seed, same days):")
        print(" soul ", json.dumps(event_mix(root / "world.db"), ensure_ascii=False))
        print(" rules", json.dumps(event_mix(base / "world.db"), ensure_ascii=False))
    sys.exit(2 if res["paused"] else 0)


if __name__ == "__main__":
    main()
