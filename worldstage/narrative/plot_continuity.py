"""Continuity across scenes and episodes, for the plot engine (phase 1). Severe issues block an episode; warnings are notes.

  B1 severe  a must-hit beat has no real event
  B2 severe  a beat's event is not in world.db, or falls outside its episode
  B3 warn    a bound beat is carried by no scene
  S1 severe  a scene lacks a POV, a question or a turn, or its value does not turn
  T1 severe  scenes out of time order within an episode, or an episode reaching back before the one it follows
  P1 severe  somebody speaks in a scene they are not in
  K1-K3      a line stands on, or quotes, a fact its speaker does not know at that time, or one from later (ledger.KnowledgeGate)
  K6 severe  a line names an object that is in none of the facts it stands on (a prop the world never gave the scene)
  K4 severe  a scene's anchor act stood on something its actor did not know
  K5 severe  a line or a thought calls a fact back as known before its speaker came to know it in an earlier scene's time
  X1 warn    an episode after the first calls back nothing from the ones before
  X2 warn    an episode carries fewer than two storylines, or fewer than two POVs
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

from worldstage.narrative.dialogue import NARRATOR
from worldstage.narrative.ledger import FactLedger, KnowledgeGate

DAY = 1440


@dataclass(frozen=True)
class Issue:
    code: str
    severity: str
    where: str
    detail: str


def check(ledger: FactLedger, episodes: list[dict], bindings: dict, episode_days: int, first_day: int = 0) -> list[Issue]:
    """episodes: [{"episode": n, "scenes": [SceneCard]}]; bindings: beat_id -> {"event_id", "episode", "must_hit"}."""
    out: list[Issue] = []
    gate = KnowledgeGate(ledger)
    carried = {c.beat_id for ep in episodes for c in ep["scenes"] if c.beat_id}
    for bid, b in bindings.items():
        if b["event_id"] is None:
            if b["must_hit"]:
                out.append(Issue("B1", "severe", bid, "must-hit beat has no real event"))
            continue
        row = ledger.conn.execute("SELECT timestamp FROM events WHERE event_id = ?", (b["event_id"],)).fetchone()
        lo = (first_day + (b["episode"] - 1) * episode_days) * DAY
        if row is None or not (lo <= row[0] < lo + episode_days * DAY):
            out.append(Issue("B2", "severe", bid, f"event {b['event_id']} is not a real event of episode {b['episode']}"))
        if bid not in carried:
            out.append(Issue("B3", "warn", bid, "no scene carries this beat"))
    prev_last = -1
    for ep in episodes:
        scenes = ep["scenes"]
        n = ep["episode"]
        ts = [c.ts for c in scenes]
        if ts != sorted(ts):
            out.append(Issue("T1", "severe", f"E{n}", "scenes are out of time order"))
        if scenes and scenes[0].ts < prev_last:
            out.append(Issue("T1", "severe", f"E{n}", "episode begins before the previous one ended"))
        prev_last = max(ts) if ts else prev_last
        if len({c.line for c in scenes}) < 2 or len({c.pov for c in scenes}) < 2:
            out.append(Issue("X2", "warn", f"E{n}", "fewer than two storylines or POVs"))
        earlier = {f for f in ledger.facts if ledger.facts[f].day < first_day + (n - 1) * episode_days}
        called = set()
        for c in scenes:
            where = c.scene_id
            if not c.pov or not c.question or not c.turn or c.turn.get("before") == c.turn.get("after"):
                out.append(Issue("S1", "severe", where, "no POV, question or turn"))
            anchor = ledger.facts.get(c.anchor)
            if anchor is None:
                out.append(Issue("B2", "severe", where, f"anchor {c.anchor} is not a fact of the world"))
                continue
            if anchor.actor:
                out += [Issue(v.code, v.severity, where, v.detail) for v in gate.check_act(anchor.actor, anchor)]
            for x in c.lines:
                sp = x["speaker"]
                if sp == NARRATOR:
                    continue
                if sp not in c.cast:
                    out.append(Issue("P1", "severe", where, f"{ledger.name(sp)} speaks but is not in the scene"))
                out += [Issue(v.code, v.severity, where, v.detail) for v in gate.check_line(sp, x["text"], x["uses"], c.ts)]
                for fid in x["uses"]:
                    k = ledger.how(sp, fid)
                    if k is not None and k.since > c.ts:
                        out.append(Issue("K5", "severe", where, f"{ledger.name(sp)} calls back fact {fid} before learning it"))
                called |= set(x["uses"]) & earlier
        if n > 1 and not called:
            out.append(Issue("X1", "warn", f"E{n}", "nothing from earlier episodes is called back"))
    return out


def summary(issues: list[Issue]) -> dict:
    return {"severe": sum(i.severity == "severe" for i in issues), "warn": sum(i.severity == "warn" for i in issues),
            "issues": [asdict(i) for i in issues]}
