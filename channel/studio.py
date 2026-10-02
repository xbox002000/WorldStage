"""The control room: one world, one page. The story (episodes, the producer, payoffs, people) and the world itself in 3D.

    python -m channel.studio --new 17 --days 14 --out out/studio          # run 14 days, write the page, serve it
    python -m channel.studio --out out/studio                              # serve what is there
    open http://127.0.0.1:8795/   ->  the season strip, one day's episode, the producer's hand, the people

Each day the world is run one day (the producer, if any, speaks at dawn), then the episode planner shapes that day's episode
(narrative/episode_planner.py) and everything the page needs is written to `studio.json`: the episode with its scenes, the
producer's decisions (including the days it kept still), the payoffs, the people and what ties them. The page
(render/studio/) only reads it. The world runs in its own space (recipe jianghu_story_spatial_v1), so the same page also holds the 3D
God View (render/godview/, in a frame at `world/`): a scene of an episode opens at the very moment and place it happened, and the 3D
view can return to the day's episode. The one thing the page can ask is "go on": this process then runs the world (the only writer)
another day and writes everything again.

A world whose people have a mind (soul_lab.py: out/soul/<name>/world.db with its llm_cache.db) is looked at, not run on:

    python -m channel.studio --mind out/soul/soul503 --out out/studio_mind     # the same page, with what each of them thought

The world is replayed from the answers already paid for (agent/llm.py mode "replay": a request the cache lacks raises CacheMiss, nothing
ever goes out on the network), with exactly soul_lab's settings, and the events must come out the same as the saved world.db, one by one,
or nothing is written. Each event a mind decided carries `mind` (what it said, what it thought and did not say, why it woke, where its
choice stood among the options): a read model of the agent's own log, it changes nothing of the world.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import threading
from functools import partial
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

from agent.volition import VolitionDecider
from contracts.base import canonical_json, to_dict
from narrative import debt, episode_planner, pacing, payoff
from narrative import lint as LINT
from narrative.dramaturgy import analyse
from narrative.speech import in_own_words, speak
from narrative.state import compile_state
from producer.director import Director
from runtime.godview import _names, caption
from world.db import connect, init_db
from world.seed import build_world
from world.simulation import Simulation

STUDIO_VERSION = 1
MINDS_VERSION = 1
# what soul_lab.py runs a world with (its argparse defaults, and `Simulation(c, agent, agent, set())`: no producer, no feed). A mind world
# must be replayed with exactly this or the questions asked differ and the cache has no answer; replay_check() proves it every time.
MIND_SETTINGS = {"tier": "A", "per_person_day": 2, "budget": 20}
IDLE = "什麼都不做"        # what a mind that chose to do nothing is recorded as choosing (agent/cognition.py describe_intent(None))
LOCK = threading.Lock()   # one simulation at a time (SQLite stays on one thread)
TIES = ("trust", "affection", "respect", "resentment", "attraction")

# -- the character timeline (read model, `timeline` in studio.json): which events count as a moment in somebody's life ---------------
TIMELINE_VERSION = 1
TIMELINE_KINDS = ("payoff", "love", "growth", "outburst", "betrayal", "duel", "switch", "goal", "turn")   # the page has a word and a mark for each
LOVE = ("confession", "date", "break_up")                  # confess / date / break up
OUTBURSTS = ("shove", "strike", "smash", "break_down")     # losing control (world/domains/body.py)
GOAL_TO = ("formed", "transformed", "abandoned", "completed")
TURN_FIELDS = ("affection", "respect")                     # whose feeling about somebody flipped sign
TURN_DEAD = 0.15                                           # a feeling must pass +/-0.15 to count as a side (no flip-flopping around zero)
SAYING = {"breakthrough": "的功力有了突破"}                  # events whose caption (runtime/godview.py) is still the bare event type
# how pleasant each emotion is, for the mood curve: the minutes of a day spent in each, weighted by this
VALENCE = {"happy": 1.0, "proud": 0.8, "relieved": 0.6, "curious": 0.4, "calm": 0.15, "tired": -0.2, "uneasy": -0.4, "embarrassed": -0.45,
           "ashamed": -0.7, "scared": -0.7, "sad": -0.75, "angry": -0.8, "hurt": -0.85}


# -- a world whose people have a mind: replayed from the recorded answers, never asked again ------------------------------------------
class MindReplayError(RuntimeError):
    """The replay did not give the saved world back (or needed an answer that was never recorded): nothing is shown rather than a different world."""


def open_readonly(path: Path) -> sqlite3.Connection:
    """A database that cannot be written to. A WAL database left by a closed run opens read-only too; failing that, as a plain snapshot."""
    for suffix in ("?mode=ro", "?immutable=1"):
        c = sqlite3.connect(f"file:{Path(path).resolve().as_posix()}{suffix}", uri=True)
        try:
            c.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchone()
            return c
        except sqlite3.DatabaseError:
            c.close()
    raise MindReplayError(f"cannot open {path} for reading")


def mind_info(root: Path) -> dict:
    """What a soul_lab world folder says about itself: seed, recipe, days, and where its recorded answers are."""
    root = Path(root)
    db, cache = root / "world.db", root.parent / f"{root.name}.llm_cache.db"
    for need in (db, cache):
        if not need.exists():
            raise MindReplayError(f"{need} is missing: a mind world needs its world.db and its llm_cache.db (soul_lab.py writes both)")
    c = open_readonly(db)
    try:
        meta = dict(c.execute("SELECT key, value FROM meta").fetchall())
        last_end = c.execute("SELECT MAX(timestamp) FROM events WHERE type = 'day_end'").fetchone()[0]
    finally:
        c.close()
    cc = open_readonly(cache)
    try:
        models = [r[0] for r in cc.execute("SELECT model FROM llm_cache GROUP BY model ORDER BY COUNT(*) DESC, model")]
        answers = cc.execute("SELECT COUNT(*) FROM llm_cache WHERE response_json NOT LIKE '%\"__failed__\"%'").fetchone()[0]
    finally:
        cc.close()
    if last_end is None or not models:
        raise MindReplayError(f"{root} has no whole day or no recorded answer")
    return {"db": db, "cache": cache, "log": root / "decisions.jsonl", "seed": int(meta["world_seed"]), "recipe": meta["recipe"],
            "days": last_end // 1440 + 1, "models": models, "answers": answers,
            "prompt_version": int(meta.get("prompt_version", 1))}   # a world asked with prompt v2 says so; it must be replayed with the same prompt


class ReplayMind:
    """The minds of a world that already happened. It answers from the recorded answers only: LLMClient in mode "replay" raises CacheMiss
    for a request nobody recorded and has no way to reach a network. The cache is opened read-only, so it cannot even be added to.
    A miss is remembered here as well, because the agent (agent/cognition.py) would swallow it and let the rule agent decide instead."""

    def __init__(self, cache_path: Path, models: list[str]) -> None:
        from agent.llm import FallbackClient, LLMClient
        from agent.llm_cache import LLMCache
        self.cache_conn = open_readonly(cache_path)
        cache = LLMCache(self.cache_conn)
        self.inner = FallbackClient([LLMClient(m, mode="replay", cache=cache) for m in models])   # what soul_lab's build_chain makes, in replay
        self.misses: list[str] = []
        self.asked = 0

    @property
    def model(self) -> str:
        return self.inner.model

    def generate_json(self, prompt: str, schema: dict, temperature: float = 0.8) -> dict:
        from agent.llm import CacheMiss
        self.asked += 1
        try:
            return self.inner.generate_json(prompt, schema, temperature)
        except CacheMiss as e:
            self.misses.append(str(e)[:80])
            raise


def pair_minds(logs: list[dict], events: list[tuple[int, int, dict]]) -> list[tuple[dict, int | None]]:
    """Which event is each woken mind's decision? `logs` are the agent's own log of a day (agent.log), `events` that day's
    (event_id, timestamp, truth). An event the agent decided carries its reason as "agent:<reason>" and its actor in the truth, so a
    decision is the not yet claimed event of the same actor with the same words, at or after the moment it was decided (its timestamp
    can come later than the log's t), the nearest one first. A mind that chose to do nothing, or whose choice the world did not carry
    out, has no event: it is paired with None. Reading only."""
    free = sorted(((ts, eid, truth) for eid, ts, truth in events if str(truth.get("reason", "")).startswith("agent:")), key=lambda x: (x[0], x[1]))
    out: list[tuple[dict, int | None]] = []
    for log in sorted((x for x in logs if "error" not in x), key=lambda x: x["t"]):
        hit = None
        if log["chose"] != IDLE:
            want = f"agent:{log['reason']}"[:300]
            for i, (ts, eid, truth) in enumerate(free):
                if ts >= log["t"] and truth.get("actor") == log["person"] and truth["reason"] == want:
                    hit = i
                    break
        out.append((log, free.pop(hit)[1] if hit is not None else None))
    return out


def replay_check(conn: sqlite3.Connection, ref: Path, days: int, log_path: Path | None = None, agent_log: list[dict] | None = None) -> dict:
    """The replayed world must be the saved one, event for event: id, type, time, place and truth. (And the replayed decisions the
    ones decisions.jsonl recorded, when it is there.) Raises MindReplayError at the first difference."""
    q = "SELECT event_id, type, timestamp, location_id, truth FROM events ORDER BY event_id"
    r = open_readonly(ref)
    try:
        a = [tuple(x) for x in conn.execute(q)]
        b = [tuple(x) for x in r.execute(q)]
    finally:
        r.close()
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            raise MindReplayError(f"the replay differs from {ref.name} at event {i}: {x[:4]} vs {y[:4]}")
    if len(a) != len(b):
        raise MindReplayError(f"the replay has {len(a)} events, {ref.name} has {len(b)}")
    rep = {"events": len(a), "equal": True, "decisions_checked": 0}
    if log_path is not None and log_path.exists() and agent_log is not None:
        saved = [json.loads(x) for x in log_path.read_text(encoding="utf-8").splitlines() if x.strip()]
        keys = ("person", "t", "wake", "chose", "reason", "inner", "option", "of")
        if [tuple(x.get(k) for k in keys) for x in saved if "error" not in x] != [tuple(x.get(k) for k in keys) for x in agent_log if "error" not in x]:
            raise MindReplayError(f"the replayed decisions differ from {log_path.name}")
        rep["decisions_checked"] = len(saved)
    return rep


class Studio:
    def __init__(self, out: Path, seed: int | None = None, days: int = 0, recipe: str = "jianghu_story_spatial_v1", strategy: str = "greedy",
                 title: str = "", mind: Path | None = None) -> None:
        self.out = out
        self.title = title or recipe
        out.mkdir(parents=True, exist_ok=True)
        self.json = out / "studio.json"
        self.conn = connect()
        self.shown: set[int] = set()
        self.recent: tuple = ()
        self.days: list[dict] = []
        self.ledger = episode_planner.Ledger()                   # what the season has asked (narrative/episode_planner.py): a question is not asked again
        self.lint_days: list[dict] = []                          # each day's hard events and what the world had settled about each thing (the lint's input, beside the days)
        self.episodes: list[dict | None] = []                    # each day's episode as the page reads it (None: a quiet day), for the script lint's ledgers
        self.tl = {"places": {}, "events": {}, "people": {}}   # the character timeline, filled one day at a time (a read model, never written back)
        self._emo: dict[str, str] = {}                           # a person's emotion at the start of the next day
        self._side: dict[tuple, int] = {}                        # (who feels, about whom, field) -> the side of zero they were last on
        self.mind = None                                         # a world with minds in it (soul_lab.py): replayed, read only
        self.minds: list[dict] = []                              # every mind that woke, in time order (the `minds` of studio.json)
        self.mind_by_event: dict[int, dict] = {}                 # event id -> what the mind that decided it said and thought
        if mind is not None:
            self._init_mind(Path(mind))
            days = self.mind["info"]["days"]
        else:
            self.seed, self.recipe, self.strategy = seed, recipe, strategy
            if seed is None:
                raise SystemExit("a control-room world is made with --new SEED (it cannot be resumed from the page alone)")
            init_db(self.conn, seed)
            build_world(self.conn, seed, recipe)
            self.decider = VolitionDecider(seed)
            self.director = None if strategy == "off" else Director(strategy, seed)
            self.sim = Simulation(self.conn, self.decider, self.decider, set(), feed="synthetic_v1", producer=self.director)
        self.advance(days)

    def _init_mind(self, root: Path) -> None:
        """The same world as soul_lab.run_world made it: the same recipe and seed, no producer, no feed, the character agent with the same
        settings and the same option shuffle; the only difference is that its mind answers from the cache and nothing else."""
        import soul_lab
        from agent.cognition import CharacterAgent
        info = mind_info(root)
        self.seed, self.recipe, self.strategy = info["seed"], info["recipe"], "off"
        init_db(self.conn, self.seed)
        build_world(self.conn, self.seed, self.recipe)
        self.client = ReplayMind(info["cache"], info["models"])
        self.agent = CharacterAgent(VolitionDecider(self.seed), self.client, budget=MIND_SETTINGS["budget"], tier=MIND_SETTINGS["tier"],
                                    pause_on_quota=True, per_person_day=MIND_SETTINGS["per_person_day"], shuffle=soul_lab.recorded_order,
                                    prompt_version=info["prompt_version"])
        self.director = None
        self.sim = Simulation(self.conn, self.agent, self.agent, set())
        self.mind = {"info": info, "name": root.name, "log": []}

    # -- running -------------------------------------------------------------------------------------------------------
    def advance(self, days: int = 1) -> int:
        with LOCK:
            for _ in range(days):
                self._one_day()
            if self.mind:
                self._mind_check()
            self.write()
            return len(self.days) - 1

    def _one_day(self) -> None:
        day = len(self.days)
        if self.mind:
            if day >= self.mind["info"]["days"]:
                raise MindReplayError(f"this world is looked at, not run on: the recorded answers end with day {self.mind['info']['days']}")
            self.agent.log.clear()
        self.sim.run(1)
        names = self._names()
        if self.mind:
            self._take_minds(day, names)
        sit = analyse(self.conn)["situations"]
        plan = episode_planner.plan_day(self.conn, day, self.shown, sit, self.recent, episode_planner.SHOW, self.ledger)
        episode = None
        lint_facts = LINT.object_facts(self.conn, day)
        if plan is not None:
            for b in plan.beats:
                self.shown |= set(b.event_ids)
            self.recent = (frozenset(plan.people),) + self.recent[:1]
            episode = self._episode(plan, names)
            episode["cold_open"] = episode_planner.cold_open(self.conn, plan, names, LINT.MODERN_WORDS if "jianghu" in str(self.recipe) else ())
            self._lint(episode, lint_facts, names)
        self.episodes.append(episode)
        self.lint_days.append({"day": day, "hard": LINT.hard_events(self.conn, day), "facts": lint_facts})
        if self.mind:
            self._place_minds(day, episode)
        led = self.director.ledger if self.director is not None else None
        today_entries = [e for e in (led.entries if led else []) if e["day"] == day]
        found = [p for p in payoff.payoffs(self.conn) if p["day"] == day]
        state = compile_state(self.conn, day, [sorted(x) for x in self.recent])
        self.days.append({
            "day": day, "state": state, "pacing": {"intensity": pacing.intensity(self.conn, day), "phase": pacing.phase(self.conn, day)},
            "episode": episode,
            "producer": {"decisions": [d for d in (led.decisions if led else []) if d["day"] == day],
                         "entries": [self._entry(e, names) for e in today_entries],
                         "spent_week": led.spent(day) if led else 0},
            "payoffs": [self._payoff(p, names) for p in found],
            "events": self.conn.execute("SELECT COUNT(*) FROM events WHERE timestamp >= ? AND timestamp < ?", (day * 1440, (day + 1) * 1440)).fetchone()[0],
        })
        self._timeline_day(day, episode, found, names)

    # -- the character timeline: one row per person, one cell per day ---------------------------------------------------------------
    def _timeline_day(self, day: int, episode: dict | None, found: list[dict], names: dict) -> None:
        """Add today to everybody's timeline: the mood, the part in the episode, the moments that matter (a payoff, a confession, a
        breakthrough, losing control, a betrayal, a duel, going over to another side, a new goal) and the turns in how others feel
        about them. It only reads the world. Every moment keeps the event it comes from and, when that event is on screen in today's
        episode, the scene (beat), so the page can go straight there."""
        from world.domains import factions as F
        c, lo, hi = self.conn, day * 1440, (day + 1) * 1440
        humans = F.humans(c)
        hs = set(humans)
        tl = self.tl
        for p in humans:
            tl["people"].setdefault(p, {"mood": [], "emo": [], "role": "", "ev": [], "turns": []})
        beat_of: dict[int, int] = {}      # event -> the scene of today's episode that shows it (an event not on screen is reached through its day)
        for b in (episode or {"beats": []})["beats"]:
            if b["shoot"]:
                for eid in b["event_ids"]:
                    beat_of.setdefault(eid, b["index"])
        rows = {r["event_id"]: r for r in c.execute("SELECT event_id, type, timestamp, location_id, truth FROM events WHERE timestamp >= ? AND timestamp < ? ORDER BY event_id", (lo, hi))}
        part: dict[int, list] = {}
        for eid, pid, role in c.execute("SELECT p.event_id, p.person_id, p.role FROM event_participants p JOIN events e USING (event_id) WHERE e.timestamp >= ? AND e.timestamp < ?", (lo, hi)):
            part.setdefault(eid, []).append((pid, role))
        picked: dict[tuple, dict] = {}    # (event id, kind) -> the moment

        def clock(r) -> str:
            return f"{(r['timestamp'] % 1440) // 60:02d}:{(r['timestamp'] % 1440) % 60:02d}"

        def place(r, rec: dict) -> None:
            if r["location_id"]:
                rec["plid"] = r["location_id"]
                tl["places"][r["location_id"]] = names.get(r["location_id"], r["location_id"])
            if beat_of.get(r["event_id"]) is not None:
                rec["b"] = beat_of[r["event_id"]]

        def take(eid: int, kind: str, who: list[str], note: str = "", extra: str = "", hero: str = "") -> None:
            who = [w for w in dict.fromkeys(who) if w in hs]
            if not who:
                return
            r = rows[eid]
            rec = picked.get((eid, kind))
            if rec is None:
                cap = caption(r["type"], json.loads(r["truth"]), r["location_id"] or "", names)
                if r["type"] in SAYING and cap.endswith(r["type"]):
                    cap = cap[:-len(r["type"])] + SAYING[r["type"]]
                rec = picked[(eid, kind)] = {"id": eid, "k": kind, "d": day, "t": r["timestamp"] * 60, "c": clock(r), "w": [], "cap": cap}
                place(r, rec)
            rec["w"] = sorted(set(rec["w"]) | set(who))
            for key, val in (("n", note), ("x", extra), ("h", hero if hero in hs else "")):
                if val:
                    rec[key] = val

        def involved(eid: int, truth: dict) -> list[str]:
            ids = [pid for pid, role in part.get(eid, []) if role in ("actor", "target")]
            return ids or [x for x in (truth.get("actor"), truth.get("target") or truth.get("victim")) if x]

        paid = {p["event_id"]: p for p in found}
        for eid, r in rows.items():
            t, truth = r["type"], json.loads(r["truth"])
            if eid in paid:
                p = paid[eid]
                take(eid, "payoff", [p["protagonist"], p.get("against") or ""], note=p["kind"], hero=p["protagonist"])
            elif t in LOVE:
                take(eid, "love", involved(eid, truth), note=truth.get("outcome", "") if t == "confession" else t, hero=truth.get("actor", "") if t == "confession" else "")
            elif t == "breakthrough":
                take(eid, "growth", [truth.get("actor", "")], hero=truth.get("actor", ""))
            elif t in OUTBURSTS:
                take(eid, "outburst", involved(eid, truth), note=t, hero=truth.get("actor", ""))
            elif (t == "confront" and str(truth.get("outcome", "")).endswith("_exposed")) or (t == "accuse" and truth.get("outcome") in ("caught", "false")) or t == "steal":
                take(eid, "betrayal", involved(eid, truth), note=truth.get("outcome") or t, hero=truth.get("actor", ""))
            elif t == "duel":
                take(eid, "duel", involved(eid, truth), hero=truth.get("winner", ""))
            elif t == "goal_change" and truth.get("to") in GOAL_TO:
                take(eid, "goal", [truth.get("actor", "")], note=truth["to"], extra=truth.get("text", ""), hero=truth.get("actor", ""))
        fname = {r[0]: r[1] for r in c.execute("SELECT faction_id, name FROM factions")}
        for eid, pid, old, new in c.execute("SELECT d.event_id, d.entity_id, d.old_value, d.new_value FROM event_deltas d JOIN events e USING (event_id) "
                                            "WHERE d.entity_type = 'affiliation' AND d.field = 'faction_id' AND e.timestamp >= ? AND e.timestamp < ? ORDER BY d.delta_id", (lo, hi)):
            if old != new:   # founding one, joining, leaving, or going over to another
                code = "found" if rows[eid]["type"] == "found_faction" else "leave" if not new else "join" if not old else "change"
                take(eid, "switch", [pid], note=code, extra="、".join(fname.get(x, str(x)) for x in (old, new) if x), hero=pid)
        # the part each played in today's episode: the lead (the payoff's hero, else who is in most of the scenes that matter), or in it
        ep_people = [x for x in (episode or {"people": []})["people"] if x in hs]
        lead = ""
        if episode:
            lead = next((p["protagonist"] for p in found if p["protagonist"] in ep_people), "")
            if not lead:
                score: dict[str, float] = {}
                for b in episode["beats"]:
                    if b["shoot"] and not b.get("derived") and b.get("story") != "texture":
                        for pid in {x for e in b["event_ids"] for x, _ in part.get(e, []) if x in hs}:
                            score[pid] = score.get(pid, 0.0) + 1.0 + b["tension"]
                lead = min((p for p in ep_people if p in score), key=lambda p: (-score[p], p), default="")
        for pid in humans:
            tl["people"][pid]["role"] += "L" if pid == lead else "S" if pid in ep_people else "."
        # the mood of the day: the minutes spent in each emotion, weighted by how pleasant it is
        changes: dict[str, list] = {}
        for pid, ts, old, new in c.execute("SELECT d.entity_id, e.timestamp, d.old_value, d.new_value FROM event_deltas d JOIN events e USING (event_id) "
                                           "WHERE d.entity_type = 'person' AND d.field = 'emotion' AND e.timestamp >= ? AND e.timestamp < ? ORDER BY e.timestamp, d.delta_id", (lo, hi)):
            changes.setdefault(pid, []).append((ts - lo, old, new))
        for pid in humans:
            ch = changes.get(pid, [])
            cur = self._emo.get(pid) or (ch[0][1] if ch and ch[0][1] else None) or c.execute("SELECT emotion FROM people WHERE id = ?", (pid,)).fetchone()[0]
            total, last, minutes = 0.0, 0, {}
            for at, _old, new in ch + [(1440, None, None)]:
                total += VALENCE.get(cur, 0.0) * (at - last)
                minutes[cur] = minutes.get(cur, 0) + at - last
                cur, last = new or cur, at
            self._emo[pid] = cur
            # the feeling the day is remembered by: the strongest one held for an hour or more (the people settle back to calm overnight)
            held = [e for e, m in minutes.items() if m >= 60]
            main = max(held, key=lambda e: (abs(VALENCE.get(e, 0.0)) * minutes[e], e), default="calm")
            tl["people"][pid]["mood"].append(round(total / 1440, 2))
            tl["people"][pid]["emo"].append(main)
        # turns: somebody's affection or respect for this person crossed zero (and stayed across it, past the dead zone)
        side = lambda v: 1 if v >= TURN_DEAD else -1 if v <= -TURN_DEAD else 0  # noqa: E731
        turns: dict[tuple, dict] = {}
        for ent, fld, old, new, eid in c.execute("SELECT d.entity_id, d.field, d.old_value, d.new_value, d.event_id FROM event_deltas d JOIN events e USING (event_id) "
                                                 f"WHERE d.entity_type = 'relationship' AND d.field IN ({','.join('?' * len(TURN_FIELDS))}) AND e.timestamp >= ? AND e.timestamp < ? "
                                                 "ORDER BY e.timestamp, d.delta_id", (*TURN_FIELDS, lo, hi)):
            who, about = ent.split(":", 1)
            if who == about or who not in hs or about not in hs or old is None or new is None:
                continue
            key = (who, about, fld)
            before, now = self._side.get(key, side(float(old))), side(float(new))
            if now:
                if before and now != before:
                    r = rows[eid]
                    turns[key] = {"e": eid, "d": day, "t": r["timestamp"] * 60, "c": clock(r), "o": who, "f": fld, "y": now, "a": round(float(old), 2), "z": round(float(new), 2)}
                    place(r, turns[key])
                self._side[key] = now
            else:
                self._side.setdefault(key, before)
        for key, turn in sorted(turns.items(), key=lambda kv: (kv[1]["t"], kv[0])):
            tl["people"][key[1]]["turns"].append(turn)
        for rec in sorted(picked.values(), key=lambda r: (r["t"], r["id"], r["k"])):
            tl["events"][f"{rec['id']}:{rec['k']}"] = rec
            for pid in rec["w"]:
                tl["people"][pid]["ev"].append(f"{rec['id']}:{rec['k']}")

    def timeline(self) -> dict:
        t = self.tl
        return {"version": TIMELINE_VERSION, "days": len(self.days), "places": t["places"], "people": t["people"],
                "events": sorted(t["events"].values(), key=lambda r: (r["t"], r["id"], r["k"]))}

    def _names(self) -> dict:
        names = _names(self.conn)
        names.update({r[0]: r[1] for r in self.conn.execute("SELECT seat_id, title FROM seats")})   # a seat is spoken of by its title
        return names

    def _speak(self, eid: int, r, truth: dict, names: dict, said: set) -> dict | None:
        """What is said at an event, in the page's shape; a line already said in this episode is read again (another line of the same pool)."""
        for variant in range(9):
            spoken = speak(self.conn, eid, r["type"], truth, names, r["timestamp"], r["location_id"] or "", variant)
            if not spoken or not ({spoken.get("say", ""), spoken.get("answer", ""), *(x["say"] for x in spoken.get("reactions", []))} - {""}) & said:
                break
        if not spoken:
            return None
        said.update({spoken.get("say", ""), spoken.get("answer", ""), *(x["say"] for x in spoken.get("reactions", []))} - {""})
        return {"say": spoken.get("say", ""), "answer": spoken.get("answer", ""), "subtext": spoken.get("subtext", ""),
                "speaker": names.get(truth.get("actor", ""), ""), "listener": names.get(truth.get("target") or truth.get("victim") or "", ""),
                "reactions": [{"who": names.get(x["who"], x["who"]), "say": x["say"]} for x in spoken.get("reactions", [])]}

    def _episode(self, plan, names: dict) -> dict:
        d = to_dict(plan)
        ev = {}
        said: set[str] = set()
        for b in d["beats"]:
            montage = len(b["event_ids"]) > 1 and b["reason"].startswith("montage")
            for n, eid in enumerate(b["event_ids"]):
                if eid not in ev:
                    r = self.conn.execute("SELECT type, timestamp, location_id, truth FROM events WHERE event_id = ?", (eid,)).fetchone()
                    truth = json.loads(r["truth"])
                    ev[eid] = {"id": eid, "type": r["type"], "clock": f"{(r['timestamp'] % 1440) // 60:02d}:{(r['timestamp'] % 1440) % 60:02d}",
                               "day": r["timestamp"] // 1440, "place": names.get(r["location_id"] or "", ""), "place_id": r["location_id"] or "",
                               "t": r["timestamp"] * 60, "caption": caption(r["type"], truth, r["location_id"] or "", names),
                               "facts": LINT.event_facts(r["type"], truth, names)}
                    if eid in self.mind_by_event:
                        ev[eid]["mind"] = self.mind_by_event[eid]
                    if not b["derived"] and not (montage and n):       # a montage beat shows the first round's words; a reaction beat shows only the reactions
                        speech = self._speak(eid, r, truth, names, said)
                        if eid in self.mind_by_event:   # a mind decided it: heard in its own words (narrative/speech.in_own_words)
                            speech = in_own_words(speech, self.mind_by_event[eid], LINT.MODERN_WORDS if "jianghu" in str(self.recipe) else (), r["type"])
                            if speech is not None:
                                speech.setdefault("speaker", names.get(truth.get("actor", ""), ""))
                                speech.setdefault("listener", names.get(truth.get("target") or "", ""))
                        if speech:
                            ev[eid]["speech"] = speech
            events = [ev[i] for i in b["event_ids"]]
            if b["derived"]:      # the room's reaction to an event already shown: the watchers' words, not the event's own line again
                events = [{**e, "speech": {**(e.get("speech") or {"speaker": "", "listener": ""}), "say": "", "answer": "", "subtext": ""}} for e in events]
                for e in events:
                    e["speech"]["reactions"] = (ev[e["id"]].get("speech") or {}).get("reactions", [])
            b["events"] = events
            if any(e["day"] != d["day"] for e in events) and all(e["day"] != d["day"] for e in events):
                b["recap"] = True        # what came before, told again as the background of today's story
        for g in d["grammar"]:
            g["events"] = [ev[i] if i in ev else self._event(i, names) for i in g["event_ids"]]
        d["people_names"] = [names.get(p, p) for p in d["people"]]
        return d

    def _lint(self, episode: dict, facts: dict, names: dict) -> None:
        """Hang the script lint (narrative/lint.py) on the episode: what is wrong with it as writing, each judged against the season so far."""
        from world.domains import factions as F
        issues = LINT.lint_episode(episode, prior=[e for e in self.episodes if e], names=[names.get(p, p) for p in F.humans(self.conn)], facts=facts,
                                   jianghu="jianghu" in str(self.recipe))
        episode["lint"] = {"version": LINT.LINT_VERSION, "count": len(issues), "items": [i.as_dict() for i in issues], "metrics": LINT.metrics(episode)}

    def _event(self, eid: int, names: dict) -> dict:
        r = self.conn.execute("SELECT type, timestamp, location_id, truth FROM events WHERE event_id = ?", (eid,)).fetchone()
        out = {"id": eid, "type": r["type"], "day": r["timestamp"] // 1440, "clock": f"{(r['timestamp'] % 1440) // 60:02d}:{(r['timestamp'] % 1440) % 60:02d}",
               "place": names.get(r["location_id"] or "", ""), "place_id": r["location_id"] or "", "t": r["timestamp"] * 60,
               "caption": caption(r["type"], json.loads(r["truth"]), r["location_id"] or "", names)}
        if eid in self.mind_by_event:
            out["mind"] = self.mind_by_event[eid]
        return out

    # -- the minds: what each woken character said and thought (a read model of the agent's log; the world never reads it) ----------------
    def _take_minds(self, day: int, names: dict) -> None:
        """Pair today's log of the agent with the events it decided, and keep what each mind said. Run right after the day, before the episode."""
        c = self.conn
        if self.client.misses:
            raise MindReplayError(f"day {day + 1}: the recorded answers lack {len(self.client.misses)} request(s) the replay needs ({self.client.misses[0]}); "
                                  "nothing is shown: a half-replayed world is not that world")
        self.mind["log"] += [{"day": day + 1, **r} for r in self.agent.log]
        rows, when = [], {}
        for eid, ts, loc, truth in c.execute("SELECT event_id, timestamp, location_id, truth FROM events WHERE timestamp >= ? AND timestamp < ? ORDER BY event_id",
                                             (day * 1440, (day + 1) * 1440)):
            rows.append((eid, ts, json.loads(truth)))
            when[eid] = (ts, loc)
        model = str(self.client.model)
        for log, eid in pair_minds(self.agent.log, rows):
            what = {"reason": log["reason"], "inner": log["inner"], "wake": log["wake"], "chose": log["chose"], "rank": log["option"], "of": log["of"],
                    "rule_top": log["rule_top"]}
            ts, loc = when[eid] if eid is not None else (log["t"], "")
            rec = {"n": len(self.minds), "person": log["person"], "name": names.get(log["person"], log["person"]), "day": day, "t": ts * 60,
                   "clock": f"{(ts % 1440) // 60:02d}:{(ts % 1440) % 60:02d}", "event": eid, "place_id": loc or "", "model": model, **what}
            self.minds.append(rec)
            if eid is not None:
                self.mind_by_event[eid] = {**what, "model": model}

    def _place_minds(self, day: int, episode: dict | None) -> None:
        """Say which scene of today's episode shows each mind's event (none: it is only in the day's list)."""
        beat_of: dict[int, int] = {}
        for b in (episode or {"beats": []})["beats"]:
            if b["shoot"]:
                for eid in b["event_ids"]:
                    beat_of.setdefault(eid, b["index"])
        for rec in self.minds:
            if rec["day"] == day and rec["event"] in beat_of:
                rec["beat"] = beat_of[rec["event"]]

    def _mind_check(self) -> None:
        """Before anything is written: the replay is the saved world."""
        info = self.mind["info"]
        if self.client.misses:
            raise MindReplayError(f"the recorded answers lack {len(self.client.misses)} request(s) the replay needs")
        if self.agent.stats["agent_failed"]:
            raise MindReplayError(f"{self.agent.stats['agent_failed']} recorded answers could not be used on replay")
        rep = replay_check(self.conn, info["db"], len(self.days), info["log"], self.mind["log"])
        self.mind["report"] = {**rep, "days": len(self.days), "minds": len(self.minds), "with_event": len(self.mind_by_event),
                               "idle": len(self.minds) - len(self.mind_by_event), "asked": self.client.asked}

    @staticmethod
    def _entry(e: dict, names: dict) -> dict:
        p = e["params"]
        return {"type": e["type"], "target": e["target"], "target_name": names.get(e["target"], e["target"]), "params": p,
                "toward_name": names.get(p.get("toward", ""), ""), "place_name": names.get(p.get("place", ""), ""),
                "object_name": names.get(p.get("object", ""), ""), "cost": e["budget_cost"], "admitted": e["admitted"], "reason": e["reason"],
                "purpose": e["purpose"], "opportunity": e["arc_id"]}

    @staticmethod
    def _payoff(p: dict, names: dict) -> dict:
        return {"kind": p["kind"], "protagonist": p["protagonist"], "protagonist_name": names.get(p["protagonist"], p["protagonist"]),
                "against_name": names.get(p.get("against") or "", ""), "base": p["base"], "agency": p["agency"], "earned": p["earned"], "parts": p["parts"],
                "event_id": p["event_id"]}

    # -- what the page reads ---------------------------------------------------------------------------------------------
    def people(self) -> list[dict]:
        from world.attention import var
        from world.domains import factions as F
        from world.domains import romance as R
        names = self._names()
        all_payoffs = payoff.payoffs(self.conn)
        out = []
        for pid in F.humans(self.conn):
            total, parts = debt.debt(self.conn, pid)
            prof = R.profile(self.conn, pid)
            fid = F.faction_of(self.conn, pid)
            tied = sorted(({"other": o, "other_name": names.get(o, o), **{k: round(r[k], 2) for k in TIES}, "bond": r["bond"], "estimate": round(r["estimate"], 2)}
                           for o, r in ((r["target_id"], r) for r in self.conn.execute("SELECT * FROM relationships WHERE actor_id = ?", (pid,)))),
                          key=lambda x: -(abs(x["trust"]) + abs(x["affection"]) + abs(x["resentment"]) + abs(x["attraction"])))[:5]
            out.append({"id": pid, "name": names.get(pid, pid), "ability": round(var(self.conn, f"skill.{pid}", 0.0), 2),
                        "crowd": round(self.conn.execute("SELECT COALESCE(AVG(estimate), 0.5) FROM relationships WHERE target_id = ? AND actor_id != ?", (pid, pid)).fetchone()[0], 2),
                        "charm": round(R.charm(self.conn, pid), 2), "faction": fid or "", "debt": total, "debt_parts": parts,
                        "payoffs": [self._payoff(p, names) for p in all_payoffs if p["protagonist"] == pid],
                        "emotion": self.conn.execute("SELECT emotion FROM people WHERE id = ?", (pid,)).fetchone()[0], "ties": tied,
                        "age": prof.age if prof else None})
        return out

    def _world3d(self) -> dict | None:
        """The 3D save (runtime/godview.py: the last 30 days, every place, everyone) and its page, when the world has a space."""
        from world.space import oracle
        space = oracle(self.conn)
        rt = getattr(space, "rt", None)
        if rt is None and self.mind:
            # a soul_lab world has no space of its own (jianghu_story_v1): the runtime still stages it from its events, as `runtime.godview` does for any world.db
            from runtime.world_runtime import WorldRuntime
            rt = WorldRuntime(self.conn)
        if rt is None:
            return None
        from render.godview.build import build as build_world_page
        from runtime.godview import export_world
        last = (self.conn.execute("SELECT MAX(timestamp) FROM events").fetchone()[0] or 0) // 1440
        rt.advance()
        first = max(0, last - 29)
        export_world(self.conn, self.out / "world.json", first, last, rt, minds=self.mind_by_event if self.mind else None)
        build_world_page(self.out / "world.json", self.out / "site" / "world")
        return {"first_day": first, "last_day": last}

    def write(self) -> None:
        led = self.director.ledger if self.director is not None else None
        doc = {"version": STUDIO_VERSION, "meta": {"seed": self.seed, "recipe": self.recipe, "strategy": self.strategy, "days": len(self.days), "title": self.title,
                                                     "week_budget": led.week_budget if led else 0},
               "days": self.days, "people": self.people(), "world3d": self._world3d(),
               "totals": payoff.summary(self.conn), "timeline": self.timeline()}
        doc["lint_days"] = self.lint_days
        doc["lint"] = LINT.season_report(doc)
        if self.mind:   # only a world with minds has these keys: the page of any other world has no trace of them
            rp = self.mind["report"]
            doc["meta"]["mind"] = {"model": ", ".join(self.mind["info"]["models"]), "minds": rp["minds"], "with_event": rp["with_event"], "idle": rp["idle"],
                                   "answers": self.mind["info"]["answers"], "replay_events": rp["events"], "world": self.mind["name"],
                                   "settings": MIND_SETTINGS}
            doc["minds"] = {"version": MINDS_VERSION, "items": self.minds}
        self.json.write_text(canonical_json(doc), encoding="utf-8")
        from render.studio.build import build
        build(self.json, self.out / "site")


PRESETS = {
    "jianghu": {"title": "江湖故事（有製作人）", "recipe": "jianghu_story_spatial_v1", "strategy": "greedy", "seed": 501},
    "town": {"title": "小鎮日常", "recipe": "town_spatial_v1", "strategy": "off", "seed": 7},
    "drama": {"title": "江湖劇情（有名有姓）", "recipe": "jianghu_drama_spatial_v1", "strategy": "greedy", "seed": 701},
}


class Hub:
    """Several worlds under one root: each is its own run in its own folder (root/<key>/site), switched from the page.
    A world made in this process can go on; one left by an earlier run is shown as it was (its page is a file)."""

    def __init__(self, root: Path) -> None:
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.worlds: dict[str, Studio] = {}
        self.readonly: set[str] = set()      # worlds with minds, made in this process: shown, but there is no going on (the answers end)

    def make(self, preset: str, seed: int | None = None, days: int = 14, recipe: str | None = None, strategy: str | None = None) -> str:
        if preset not in PRESETS:
            raise ValueError(f"no preset {preset!r} (one of {sorted(PRESETS)})")
        p = PRESETS[preset]
        seed = p["seed"] if seed is None else int(seed)
        key = f"{preset}-{seed}"
        if key not in self.worlds:
            self.worlds[key] = Studio(self.root / key, seed, max(1, min(30, int(days))), recipe or p["recipe"], strategy or p["strategy"], p["title"])
        self.catalog()
        return key

    def make_mind(self, root: Path) -> str:
        """Open a soul_lab world (out/soul/<name>) to be looked at: replayed from its recorded answers, never asked anything, never run on."""
        info = mind_info(root)
        key = f"soul-{info['seed']}"
        Studio(self.root / key, mind=root, title="江湖（角色有 LLM）")
        self.readonly.add(key)
        self.catalog()
        return key

    def catalog(self) -> list[dict]:
        rows = []
        for f in sorted(self.root.glob("*/studio.json")):
            try:
                m = json.loads(f.read_text(encoding="utf-8"))["meta"]
            except (OSError, ValueError, KeyError):
                continue
            rows.append({"key": f.parent.name, "title": m.get("title", f.parent.name), "seed": m["seed"], "days": m["days"], "recipe": m["recipe"],
                         "live": f.parent.name in self.worlds, **({"mind": True} if m.get("mind") else {})})
        (self.root / "worlds.json").write_text(json.dumps({"worlds": rows, "presets": {k: v["title"] for k, v in PRESETS.items()}}, ensure_ascii=False),
                                               encoding="utf-8")
        return rows

    def front_door(self, key: str) -> None:
        """The root page sends you to a world."""
        (self.root / "index.html").write_text(f'<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="0;url={key}/site/index.html">'
                                              f'<a href="{key}/site/index.html">導播室</a>', encoding="utf-8")


class Handler(SimpleHTTPRequestHandler):
    hub: Hub

    def _json(self, code: int, obj: dict) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802
        from urllib.parse import parse_qs, urlparse
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        parts = [x for x in u.path.split("/") if x]
        try:
            if parts[-1:] == ["advance"] and parts:
                world = self.hub.worlds.get(parts[0])
                if parts[0] in self.hub.readonly:
                    self._json(409, {"error": "a world with minds is replayed from the answers already paid for: going on would ask new questions (quota). It can be read, not continued"})
                    return
                if world is None:
                    self._json(409, {"error": "this world was left by an earlier run: it can be read, not continued"})
                    return
                self._json(200, {"last_day": world.advance(7 if q.get("n") == "7" else 1)})
            elif parts == ["new"]:
                self._json(200, {"key": self.hub.make(q.get("preset", "jianghu"), int(q["seed"]) if q.get("seed") else None, int(q.get("days", 14)))})
            else:
                self.send_error(404)
        except (ValueError, KeyError) as e:
            self._json(400, {"error": str(e)})

    def end_headers(self) -> None:
        # the page is rebuilt whenever the code changes: a browser that kept an old script next to a new page shows buttons that do nothing
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, *args) -> None:
        pass


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="out/studio", help="the folder all the worlds live under")
    ap.add_argument("--preset", default=None, choices=sorted(PRESETS), help="the world to open first (default jianghu; others are made from the page)")
    ap.add_argument("--new", type=int, default=None, help="world seed (default: the preset's)")
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--recipe", default=None, help="override the preset's recipe (jianghu_story_v1 is the same world without space: faster, no 3D)")
    ap.add_argument("--strategy", default=None, help="override the producer: greedy | portfolio | matched | off ...")
    ap.add_argument("--mind", action="append", default=None, metavar="DIR",
                    help="look at a world whose people have a mind (a soul_lab.py folder, e.g. out/soul/soul503): replayed from its llm_cache.db, no network, no quota; may be repeated")
    ap.add_argument("--port", type=int, default=8795)
    ap.add_argument("--no-serve", action="store_true")
    a = ap.parse_args()
    hub = Hub(Path(a.out))
    keys = [hub.make_mind(Path(m)) for m in a.mind or []]
    if a.preset or not keys:   # --mind alone opens the mind world; with --preset too, both are there and the preset opens first
        keys.insert(0, hub.make(a.preset or "jianghu", a.new, a.days, a.recipe, a.strategy))
    key = keys[0]
    hub.front_door(key)
    print("studio", hub.root / key / "studio.json")
    if a.no_serve:
        return
    Handler.hub = hub
    srv = HTTPServer(("127.0.0.1", a.port), partial(Handler, directory=str(hub.root)))
    print(f"control room: http://127.0.0.1:{a.port}/")
    srv.serve_forever()


if __name__ == "__main__":
    main()
