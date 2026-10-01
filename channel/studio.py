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
from producer.director import Director
from runtime.godview import _names, caption
from world.db import connect, init_db
from world.seed import build_world
from world.simulation import Simulation

STUDIO_VERSION = 1
LOCK = threading.Lock()   # one simulation at a time (SQLite stays on one thread)
TIES = ("trust", "affection", "respect", "resentment", "attraction")


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
        plan = episode_planner.plan_day(self.conn, day, self.shown, sit, self.recent)
        episode = None
        if plan is not None:
            for b in plan.beats:
                self.shown |= set(b.event_ids)
            self.recent = (frozenset(plan.people),) + self.recent[:1]
            episode = self._episode(plan, names)
        led = self.director.ledger if self.director is not None else None
        today_entries = [e for e in (led.entries if led else []) if e["day"] == day]
        found = [p for p in payoff.payoffs(self.conn) if p["day"] == day]
        self.days.append({
            "day": day, "pacing": {"intensity": pacing.intensity(self.conn, day), "phase": pacing.phase(self.conn, day)},
            "episode": episode,
            "producer": {"decisions": [d for d in (led.decisions if led else []) if d["day"] == day],
                         "entries": [self._entry(e, names) for e in today_entries],
                         "spent_week": led.spent(day) if led else 0},
            "payoffs": [self._payoff(p, names) for p in found],
            "events": self.conn.execute("SELECT COUNT(*) FROM events WHERE timestamp >= ? AND timestamp < ?", (day * 1440, (day + 1) * 1440)).fetchone()[0],
        })

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
               "totals": payoff.summary(self.conn)}
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
