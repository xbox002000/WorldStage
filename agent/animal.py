"""How an animal decides: no words, no plans about people's secrets. It follows who it likes, carries things off,
drops them somewhere else, and barks at who frightens it. Deterministic (world seed + time + animal)."""
from __future__ import annotations

import json
import math
import sqlite3

from world.intent import Intent
from world.rng import rng as make_rng

TEMPERATURE = 0.35


class AnimalDecider:
    def __init__(self, world_seed: int | str) -> None:
        self.world_seed = world_seed

    def options(self, conn: sqlite3.Connection, me: str, now: int) -> list[tuple[float, Intent | None]]:
        row = conn.execute("SELECT p.location_id, s.traits FROM people p JOIN personas s ON s.person_id = p.id "
                           "WHERE p.id = ?", (me,)).fetchone()
        here, traits = row["location_id"], json.loads(row["traits"])
        curiosity = traits.get("curiosity", 0.6)
        out: list[tuple[float, Intent | None]] = [(0.4, None)]  # sniff around, lie down
        liked = conn.execute(
            "SELECT r.target_id, r.affection, p.location_id FROM relationships r JOIN people p ON p.id = r.target_id "
            "JOIN personas s ON s.person_id = r.target_id WHERE r.actor_id = ? AND r.affection > 0.1 "
            "AND COALESCE(json_extract(s.traits, '$.species'), 'human') = 'human' ORDER BY r.affection DESC, r.target_id LIMIT 2",
            (me,)).fetchall()
        for r in liked:
            if r["location_id"] != here and conn.execute(
                    "SELECT 1 FROM location_edges WHERE from_location_id = ? AND to_location_id = ?", (here, r["location_id"])).fetchone():
                out.append((0.3 + r["affection"], Intent(me, "move", r["location_id"], reason=f"animal: follows {r['target_id']}")))
        for o in conn.execute("SELECT id FROM objects WHERE location_id = ? AND status = 'normal' "
                              "AND tags NOT LIKE '%\"fixed\"%' ORDER BY id", (here,)):
            carried = conn.execute("SELECT COUNT(*) FROM events WHERE type = 'take' AND json_extract(truth, '$.actor') = ? "
                                   "AND json_extract(truth, '$.object') = ?", (me, o["id"])).fetchone()[0]
            # a new thing is interesting; one it has already carried about, less and less
            out.append((0.2 + 0.6 * curiosity - 0.35 * carried, Intent(me, "take", o["id"], reason="animal: picks it up in its mouth")))
        for o in conn.execute("SELECT id FROM objects WHERE owner_person_id = ? AND status = 'normal' ORDER BY id", (me,)):
            out.append((0.5, Intent(me, "drop", o["id"], reason="animal: lets it fall")))
        for r in conn.execute(
                "SELECT r.target_id, r.fear, r.trust FROM relationships r JOIN people p ON p.id = r.target_id "
                "WHERE r.actor_id = ? AND p.location_id = ? AND (r.fear > 0.15 OR r.trust < -0.2) ORDER BY r.target_id",
                (me, here)):
            out.append((0.3 + r["fear"], Intent(me, "bark", r["target_id"], reason="animal: afraid of them")))
        return out

    def decide(self, conn: sqlite3.Connection, me: str, now: int) -> Intent | None:
        scored = self.options(conn, me, now)
        weights = [math.exp(s / TEMPERATURE) for s, _ in scored]
        return make_rng(self.world_seed, now, me, "animal_pick").choices(scored, weights)[0][1]
