"""The series memory of the channel: which world events viewers have already seen, and what to remind them of."""
from __future__ import annotations

import json
import sqlite3

from contracts.scene_spec import SceneSpec
from narrative.compiler import caption
from production import db as prod

RECAP_LINES = 2


def used_event_ids(conn: sqlite3.Connection) -> set[int]:
    """World events already told in an episode that has not been rejected."""
    rows = conn.execute(
        "SELECT DISTINCT je.value FROM episodes e JOIN scene_specs s USING (scene_hash), "
        "json_each(s.spec_json, '$.source.source_event_ids') je WHERE e.status <> 'rejected'")
    return {int(r[0]) for r in rows}


def prior_specs(conn: sqlite3.Connection) -> list[SceneSpec]:
    """Specs of earlier episodes, oldest first."""
    hashes = [r[0] for r in conn.execute(
        "SELECT scene_hash FROM episodes WHERE status <> 'rejected' ORDER BY episode_id")]
    seen: list[str] = []
    for h in hashes:
        if h not in seen:
            seen.append(h)
    return [prod.load_scene_spec(conn, h) for h in seen]


def principals(spec: SceneSpec) -> set[str]:
    return {p.id for b in spec.beats for p in b.participants[:2]}


def build_recap(conn: sqlite3.Connection, spec: SceneSpec, lines: int = RECAP_LINES) -> str:
    """One line per earlier episode that involved the same people, newest kept, oldest first. No LLM."""
    mine = principals(spec)
    picked: list[str] = []
    for prior in reversed(prior_specs(conn)):
        if prior.scene_hash == spec.scene_hash or not (mine & principals(prior)):
            continue
        peak = next((b for b in prior.beats if b.event_id == prior.peak_event_id), prior.beats[-1])
        picked.append(caption(peak, {pid: p.name for pid, p in prior.characters.items()}))
        if len(picked) == lines:
            break
    return "；".join(reversed(picked))


def record_episode(conn: sqlite3.Connection, *, scene_hash: str, take_id: int | None, title: str, sim_day: int | None,
                   arc_kind: str, score: float, continuity: dict | None, qa_status: str, recap: str) -> int:
    existing = conn.execute("SELECT episode_id FROM episodes WHERE scene_hash = ? AND take_id IS ?", (scene_hash, take_id)).fetchone()
    if existing:
        return int(existing[0])
    cur = conn.execute(
        "INSERT INTO episodes(scene_hash, take_id, title, status, created_at, sim_day, arc_kind, score, continuity_json, "
        "qa_status, recap) VALUES (?,?,?,?,strftime('%s','now'),?,?,?,?,?,?)",
        (scene_hash, take_id, title, "draft", sim_day, arc_kind, score,
         json.dumps(continuity, sort_keys=True) if continuity else None, qa_status, recap))
    conn.commit()
    return int(cur.lastrowid)
