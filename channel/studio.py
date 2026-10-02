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
"""
from __future__ import annotations

import argparse
import json
import threading
from functools import partial
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

from agent.volition import VolitionDecider
from contracts.base import canonical_json, to_dict
from narrative import debt, episode_planner, pacing, payoff
from narrative.dramaturgy import analyse
from narrative.speech import speak
from narrative.state import compile_state
from producer.director import Director
from runtime.godview import _names, caption
from world.db import connect, init_db
from world.seed import build_world
from world.simulation import Simulation

STUDIO_VERSION = 1
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


class Studio:
    def __init__(self, out: Path, seed: int | None = None, days: int = 0, recipe: str = "jianghu_story_spatial_v1", strategy: str = "greedy",
                 title: str = "") -> None:
        self.out = out
        self.title = title or recipe
        out.mkdir(parents=True, exist_ok=True)
        self.json = out / "studio.json"
        self.conn = connect()
        self.seed, self.recipe, self.strategy = seed, recipe, strategy
        if seed is None:
            raise SystemExit("a control-room world is made with --new SEED (it cannot be resumed from the page alone)")
        init_db(self.conn, seed)
        build_world(self.conn, seed, recipe)
        self.decider = VolitionDecider(seed)
        self.director = None if strategy == "off" else Director(strategy, seed)
        self.sim = Simulation(self.conn, self.decider, self.decider, set(), feed="synthetic_v1", producer=self.director)
        self.shown: set[int] = set()
        self.recent: tuple = ()
        self.days: list[dict] = []
        self.tl = {"places": {}, "events": {}, "people": {}}   # the character timeline, filled one day at a time (a read model, never written back)
        self._emo: dict[str, str] = {}                           # a person's emotion at the start of the next day
        self._side: dict[tuple, int] = {}                        # (who feels, about whom, field) -> the side of zero they were last on
        self.advance(days)

    # -- running -------------------------------------------------------------------------------------------------------
    def advance(self, days: int = 1) -> int:
        with LOCK:
            for _ in range(days):
                self._one_day()
            self.write()
            return len(self.days) - 1

    def _one_day(self) -> None:
        day = len(self.days)
        self.sim.run(1)
        names = self._names()
        sit = analyse(self.conn)["situations"]
        plan = episode_planner.plan_day(self.conn, day, self.shown, sit, self.recent, episode_planner.AB)
        episode = None
        if plan is not None:
            for b in plan.beats:
                self.shown |= set(b.event_ids)
            self.recent = (frozenset(plan.people),) + self.recent[:1]
            episode = self._episode(plan, names)
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

    def _episode(self, plan, names: dict) -> dict:
        d = to_dict(plan)
        ev = {}
        for b in d["beats"]:
            for eid in b["event_ids"]:
                if eid not in ev:
                    r = self.conn.execute("SELECT type, timestamp, location_id, truth FROM events WHERE event_id = ?", (eid,)).fetchone()
                    ev[eid] = {"id": eid, "type": r["type"], "clock": f"{(r['timestamp'] % 1440) // 60:02d}:{(r['timestamp'] % 1440) % 60:02d}",
                               "day": r["timestamp"] // 1440, "place": names.get(r["location_id"] or "", ""), "place_id": r["location_id"] or "",
                               "t": r["timestamp"] * 60, "caption": caption(r["type"], json.loads(r["truth"]), r["location_id"] or "", names)}
                    truth = json.loads(r["truth"])
                    spoken = speak(self.conn, eid, r["type"], truth, names, r["timestamp"], r["location_id"] or "")
                    if spoken:
                        ev[eid]["speech"] = {"say": spoken.get("say", ""), "answer": spoken.get("answer", ""), "subtext": spoken.get("subtext", ""),
                                             "speaker": names.get(truth.get("actor", ""), ""), "listener": names.get(truth.get("target") or truth.get("victim") or "", ""),
                                             "reactions": [{"who": names.get(x["who"], x["who"]), "say": x["say"]} for x in spoken.get("reactions", [])]}
            b["events"] = [ev[i] for i in b["event_ids"]]
        for g in d["grammar"]:
            g["events"] = [ev[i] if i in ev else self._event(i, names) for i in g["event_ids"]]
        d["people_names"] = [names.get(p, p) for p in d["people"]]
        return d

    def _event(self, eid: int, names: dict) -> dict:
        r = self.conn.execute("SELECT type, timestamp, location_id, truth FROM events WHERE event_id = ?", (eid,)).fetchone()
        return {"id": eid, "type": r["type"], "day": r["timestamp"] // 1440, "clock": f"{(r['timestamp'] % 1440) // 60:02d}:{(r['timestamp'] % 1440) % 60:02d}",
                "place": names.get(r["location_id"] or "", ""), "place_id": r["location_id"] or "", "t": r["timestamp"] * 60,
                "caption": caption(r["type"], json.loads(r["truth"]), r["location_id"] or "", names)}

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
        if rt is None:
            return None
        from render.godview.build import build as build_world_page
        from runtime.godview import export_world
        last = (self.conn.execute("SELECT MAX(timestamp) FROM events").fetchone()[0] or 0) // 1440
        rt.advance()
        first = max(0, last - 29)
        export_world(self.conn, self.out / "world.json", first, last, rt)
        build_world_page(self.out / "world.json", self.out / "site" / "world")
        return {"first_day": first, "last_day": last}

    def write(self) -> None:
        led = self.director.ledger if self.director is not None else None
        doc = {"version": STUDIO_VERSION, "meta": {"seed": self.seed, "recipe": self.recipe, "strategy": self.strategy, "days": len(self.days), "title": self.title,
                                                     "week_budget": led.week_budget if led else 0},
               "days": self.days, "people": self.people(), "world3d": self._world3d(),
               "totals": payoff.summary(self.conn), "timeline": self.timeline()}
        self.json.write_text(canonical_json(doc), encoding="utf-8")
        from render.studio.build import build
        build(self.json, self.out / "site")


PRESETS = {
    "jianghu": {"title": "江湖故事（有製作人）", "recipe": "jianghu_story_spatial_v1", "strategy": "greedy", "seed": 501},
    "town": {"title": "小鎮日常", "recipe": "town_spatial_v1", "strategy": "off", "seed": 7},
}


class Hub:
    """Several worlds under one root: each is its own run in its own folder (root/<key>/site), switched from the page.
    A world made in this process can go on; one left by an earlier run is shown as it was (its page is a file)."""

    def __init__(self, root: Path) -> None:
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.worlds: dict[str, Studio] = {}

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

    def catalog(self) -> list[dict]:
        rows = []
        for f in sorted(self.root.glob("*/studio.json")):
            try:
                m = json.loads(f.read_text(encoding="utf-8"))["meta"]
            except (OSError, ValueError, KeyError):
                continue
            rows.append({"key": f.parent.name, "title": m.get("title", f.parent.name), "seed": m["seed"], "days": m["days"], "recipe": m["recipe"],
                         "live": f.parent.name in self.worlds})
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
    ap.add_argument("--preset", default="jianghu", choices=sorted(PRESETS), help="the world to open first (others are made from the page)")
    ap.add_argument("--new", type=int, default=None, help="world seed (default: the preset's)")
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--recipe", default=None, help="override the preset's recipe (jianghu_story_v1 is the same world without space: faster, no 3D)")
    ap.add_argument("--strategy", default=None, help="override the producer: greedy | portfolio | matched | off ...")
    ap.add_argument("--port", type=int, default=8795)
    ap.add_argument("--no-serve", action="store_true")
    a = ap.parse_args()
    hub = Hub(Path(a.out))
    key = hub.make(a.preset, a.new, a.days, a.recipe, a.strategy)
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
