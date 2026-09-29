"""What the experiment is measured by. Everything is computed from the world and the production record;
nothing here changes either."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from contracts.base import from_dict
from contracts.scene_spec import SceneSpec
from narrative.arcs import EXPOSED, Arc, load_events
from narrative.continuity import connects
from narrative.scorer import unresolved_tension
from production import db as prod
from world.explain import causes
from world.state import audit

FLAT_TENSION = 0.6  # an ending at least this unresolved leaves viewers hanging: the episode is not flat
LATE_FROM_DAY = 5  # 0-based: days 6 and 7 of a week
WARM_LIMIT = 0.6
FLAT_LIMIT = 2 / 7


@dataclass(frozen=True)
class EpisodeRow:
    episode_id: int
    scene_hash: str
    arc_kind: str
    sim_day: int | None
    spec: SceneSpec


def episodes(conn: sqlite3.Connection) -> list[EpisodeRow]:
    """Every episode that was actually produced, in order, one row per spec (a re-render is not a new episode)."""
    seen: set[str] = set()
    out = []
    for r in conn.execute("SELECT episode_id, scene_hash, arc_kind, sim_day FROM episodes WHERE status <> 'rejected' ORDER BY episode_id"):
        if r["scene_hash"] not in seen:
            seen.add(r["scene_hash"])
            out.append(EpisodeRow(r["episode_id"], r["scene_hash"], r["arc_kind"] or "pair", r["sim_day"],
                                  prod.load_scene_spec(conn, r["scene_hash"])))
    return out


# -- tone ------------------------------------------------------------------------------------------------------------
def llm_talk_tones(world: sqlite3.Connection) -> dict[str, int]:
    """How the model chose to speak: tone counts over talk events a model decided (not seeded or scripted ones)."""
    rows = world.execute(
        "SELECT json_extract(truth, '$.tone') AS tone, COUNT(*) AS n FROM events "
        "WHERE type = 'talk' AND COALESCE(json_extract(truth, '$.source'), '') <> '' GROUP BY tone ORDER BY tone")
    return {r["tone"]: r["n"] for r in rows}


def warm_tone_ratio(world: sqlite3.Connection) -> float | None:
    tones = llm_talk_tones(world)
    total = sum(tones.values())
    return tones.get("warm", 0) / total if total else None


# -- episodes --------------------------------------------------------------------------------------------------------
def _arc(events: dict, row: EpisodeRow) -> Arc:
    evs = tuple(events[i] for i in row.spec.source.source_event_ids if i in events)
    return Arc(evs, events[row.spec.peak_event_id], row.arc_kind)


def episode_flags(events: dict, row: EpisodeRow) -> dict:
    beats = row.spec.beats
    flip = any(b.trust_flipped for b in beats)
    exposure = any(b.event_type == "confront" and b.variant in EXPOSED for b in beats)
    unresolved = unresolved_tension(_arc(events, row), events) >= FLAT_TENSION
    goal_change = False  # V0 has no goal-changing mechanic; recorded so the definition stays complete
    return {"flip": flip, "exposure": exposure, "goal_change": goal_change, "unresolved": unresolved,
            "flat": not (flip or exposure or goal_change or unresolved)}


def flat_episode_ratio(world: sqlite3.Connection, rows: list[EpisodeRow]) -> tuple[float | None, list[dict]]:
    events = load_events(world)
    flags = [{"episode_id": r.episode_id, **episode_flags(events, r)} for r in rows]
    flat = sum(f["flat"] for f in flags)
    return (flat / len(flags) if flags else None), flags


def has_lie_chain(spec: SceneSpec) -> bool:
    """Inside one episode: a lie or distortion is told, it is passed on, and someone catches it."""
    beats = spec.beats
    for i, lie in enumerate(beats):
        if lie.event_type != "tell" or lie.variant not in ("lie", "distortion") or lie.incident is None:
            continue
        spread = [j for j in range(i + 1, len(beats)) if beats[j].event_type == "tell" and beats[j].incident == lie.incident]
        for j in spread:
            if any(k > j and beats[k].event_type == "confront" and beats[k].variant in EXPOSED
                   and beats[k].incident == lie.incident for k in range(len(beats))):
                return True
    return False


def continuity_report(world: sqlite3.Connection, rows: list[EpisodeRow]) -> list[dict]:
    """For episode 2 onward: does it build on what viewers have already seen? (causal or state lineage)"""
    events = load_events(world)
    shown: set[int] = set()
    report = []
    for i, r in enumerate(rows):
        if i:
            evidence = connects(world, events, _arc(events, r), shown)
            report.append({"episode_id": r.episode_id, "connected": evidence is not None, "evidence": evidence})
        shown |= set(r.spec.source.source_event_ids)
    return report


def late_trace(world: sqlite3.Connection) -> tuple[int, int]:
    """Social decisions late in the run that can be traced back to the first day: (reached, total)."""
    late = [r[0] for r in world.execute(
        "SELECT event_id FROM events WHERE timestamp >= ? AND type IN ('talk','steal','tell','confront') ORDER BY event_id",
        (LATE_FROM_DAY * 1440,))]
    reached = sum(1 for e in late if (causes(world, e) or [{"day": 0}])[0]["day"] == 1)
    return reached, len(late)


def usage(conn: sqlite3.Connection, experiment_id: str | None = None) -> dict:
    total = {"days": 0, "llm_calls": 0, "llm_failures": 0, "switches": 0, "decider_errors": 0}
    models: set[str] = set()
    sql, args = "SELECT usage_json FROM daily_runs", ()
    if experiment_id:
        sql, args = sql + " WHERE experiment_id = ?", (experiment_id,)
    for r in conn.execute(sql, args):
        u = json.loads(r[0])
        total["days"] += 1
        for k in ("llm_calls", "llm_failures", "switches", "decider_errors"):
            total[k] += int(u.get(k, 0))
        models |= set(u.get("models", []))
    total["models"] = sorted(models)
    return total


# -- the verdict -----------------------------------------------------------------------------------------------------
def _check(value, passed, target) -> dict:
    return {"value": value, "target": target, "passed": passed}


def acceptance(world: sqlite3.Connection, conn: sqlite3.Connection, *, experiment_id: str | None = None, days: int = 7,
               replay_ok: bool | None = None) -> dict:
    rows = episodes(conn)
    warm = warm_tone_ratio(world)
    flat, flags = flat_episode_ratio(world, rows)
    cont = continuity_report(world, rows)
    reached, late_total = late_trace(world)
    qa = conn.execute("SELECT COUNT(*) FROM episodes e JOIN takes t USING (take_id) JOIN qa_results q USING (take_id) "
                      "WHERE q.layer = 'deterministic' AND q.passed = 1 AND e.status <> 'rejected'").fetchone()[0]
    use = usage(conn, experiment_id)
    chains = [r.episode_id for r in rows if has_lie_chain(r.spec)]
    checks = {
        "episodes_produced": _check(len(rows), len(rows) >= days, f">= {days}"),
        "episodes_passed_qa": _check(qa, qa >= len(rows) > 0, "all"),
        "warm_tone_ratio": _check(warm, (warm < WARM_LIMIT) if warm is not None else None, f"< {WARM_LIMIT}"),
        "flat_episode_ratio": _check(flat, (flat <= FLAT_LIMIT + 1e-9) if flat is not None else None, f"<= {FLAT_LIMIT:.3f}"),
        "lie_chain_in_an_episode": _check(chains, bool(chains), ">= 1 episode"),
        "continuity": _check(sum(c["connected"] for c in cont), all(c["connected"] for c in cont) if cont else None,
                             f"{len(cont)} of {len(cont)} follow-ups connected"),
        "late_decisions_traceable_to_day_1": _check([reached, late_total], reached >= 1, ">= 1"),
        "world_audit": _check(len(audit(world)), not audit(world), "0 problems"),
        "llm_failures": _check([use["llm_failures"], use["llm_calls"]],
                               use["llm_failures"] <= max(1, 0.05 * use["llm_calls"]), "<= 5% of calls"),
        "replay_identical": _check(replay_ok, replay_ok, "same world from the recorded answers"),
    }
    return {"checks": checks, "flags": flags, "continuity": cont, "usage": use, "llm_talk_tones": llm_talk_tones(world),
            "passed": all(c["passed"] for c in checks.values() if c["passed"] is not None),
            "not_evaluated": sorted(k for k, c in checks.items() if c["passed"] is None)}


def format_report(result: dict) -> str:
    lines = ["Experiment report", "-----------------"]
    for name, c in result["checks"].items():
        mark = "  n/a" if c["passed"] is None else (" PASS" if c["passed"] else " FAIL")
        lines.append(f"{mark}  {name:36} {c['value']!s:34} target {c['target']}")
    lines += ["", f"LLM talk tones: {result['llm_talk_tones']}", f"Usage: {result['usage']}"]
    lines.append("Episode flags: " + "; ".join(
        f"#{f['episode_id']} flip={int(f['flip'])} exposed={int(f['exposure'])} unresolved={int(f['unresolved'])} flat={int(f['flat'])}"
        for f in result["flags"]))
    lines.append("RESULT: " + ("all evaluated checks passed" if result["passed"] else "some checks failed")
                 + (f" (not evaluated: {', '.join(result['not_evaluated'])})" if result["not_evaluated"] else ""))
    return "\n".join(lines)
