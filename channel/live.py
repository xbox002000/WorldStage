"""LIVE: a world that goes on by itself, watched from the God View.

    python -m channel.live --new 260934 --days 12 --out out/live     # make a spatial world, run 12 days, serve it
    python -m channel.live --out out/live                           # serve the world already there
    open http://127.0.0.1:8793/  ->  ▶ LIVE runs the simulation one more day and reloads the save

The page only reads. The one thing it can ask is "go on": this process then runs the Simulation (the world's only
writer) for a day on its own copy of the world, with rule-based decisions (no model, $0), and writes a new save.
The world is simulated in its own space (recipe town_spatial_v1): who witnesses what and who finds what depends on
where everyone really is.
"""
from __future__ import annotations

import argparse
import json
import threading
from functools import partial
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

from agent.volition import VolitionDecider
from render.godview.build import build
from runtime.godview import export_world
from world.db import connect, init_db
from world.seed import build_world
from world.simulation import Simulation

LOCK = threading.Lock()  # one simulation at a time (the server is single-threaded: SQLite stays on one thread)


class World:
    def __init__(self, out: Path, seed: int | None = None, days: int = 0, recipe: str = "town_spatial_v1") -> None:
        self.out, self.db = out, out / "world.db"
        out.mkdir(parents=True, exist_ok=True)
        fresh = seed is not None
        if fresh and self.db.exists():
            raise SystemExit(f"{self.db} exists: serve it without --new, or choose another --out")
        self.conn = connect(self.db)
        if fresh:
            init_db(self.conn, seed)
            build_world(self.conn, seed, recipe)
        self.seed = int(self.conn.execute("SELECT value FROM meta WHERE key = 'world_seed'").fetchone()[0])
        if days:
            self.advance(days)
        else:
            self.save()

    def advance(self, days: int = 1) -> int:
        with LOCK:
            d = VolitionDecider(self.seed)
            Simulation(self.conn, d, d, set(), feed="synthetic_v1").run(days)
            return self.save()

    def save(self) -> int:
        last = (self.conn.execute("SELECT MAX(timestamp) FROM events").fetchone()[0] or 0) // 1440
        from world.space import oracle
        space = oracle(self.conn)  # the runtime the simulation has been playing along: no need to replay the history
        rt = getattr(space, "rt", None)
        if rt is not None:
            rt.advance()
        export_world(self.conn, self.out / "world.json", max(0, last - 1), last, rt)
        build(self.out / "world.json", self.out / "site")
        return last


class Handler(SimpleHTTPRequestHandler):
    world: World

    def do_POST(self) -> None:  # noqa: N802
        if not self.path.startswith("/advance"):
            self.send_error(404)
            return
        last = self.world.advance(1)
        body = json.dumps({"last_day": last}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:
        pass


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="out/live")
    ap.add_argument("--new", type=int, default=None, help="world seed: make a new spatial world")
    ap.add_argument("--days", type=int, default=0)
    ap.add_argument("--port", type=int, default=8793)
    ap.add_argument("--no-serve", action="store_true")
    a = ap.parse_args()
    world = World(Path(a.out), a.new, a.days)
    print("world", world.db, "save", world.out / "world.json")
    if a.no_serve:
        return
    Handler.world = world
    srv = HTTPServer(("127.0.0.1", a.port), partial(Handler, directory=str(world.out / "site")))
    print(f"god view: http://127.0.0.1:{a.port}/")
    srv.serve_forever()


if __name__ == "__main__":
    main()
