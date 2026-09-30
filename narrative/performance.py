"""SceneSpec + DirectorPlan + the world (read-only) -> PerformancePlan. Deterministic rules, no model.

Order, each step feeding the next and each carrying its causes:
1. state     the character as of the event: emotion, trust / affection / fear / rivalry toward whoever is there,
             what they believe about them, their goals, their slow traits (vigilance, aggression, withdrawal), what
             they hold and whether it is theirs, what their body perceives (an animal senses, it does not know)
2. drives    fear, resentment, suspicion, guilt, distress, relief, attachment, curiosity, self-protection (0..1)
3. primary   the emotional state the drives add up to (restrained anger is anger that aggression does not release)
4. intent    what they are trying to do in this beat (search, conceal, confront, defend, watch, avoid ...)
5. channels  gaze, posture, hands, face, micro-actions, movement, speech (or ears, tail, head, pace for a dog)
6. continuity what the body carries into the next shot (what is held, the gesture, the gaze, the emotion)
A counterfactual (a benchmark's "what if") changes the state in step 1 only; everything after is the same rules.
"""
from __future__ import annotations

import json
import sqlite3

from contracts.director import DirectorPlan
from contracts.performance import (AnimalBody, BodyState, Cause, Drive, Face, Gaze, Hands, MicroAction,
                                   PerformanceBeat, PerformancePlan, Posture, Speech, finalize, PERFORMANCE_VERSION)
from contracts.scene_spec import Beat, SceneSpec
from world.psyche import ADAPTIVE

# which channels a kind of body has (PerformanceProfile)
PROFILES = {
    "human": {"channels": ("gaze", "posture", "hands", "face", "micro", "movement", "speech"),
              "micro": ("glance_away", "swallow", "jaw_clench", "pat_pockets", "look_around", "exhale",
                        "touch_object", "lingering_look", "smile_break", "breath_fast", "delay")},
    "dog": {"channels": ("gaze", "posture", "animal", "micro", "movement"),
            "micro": ("sniff", "head_tilt", "ear_flick", "tail_wag", "freeze", "paw", "look_back")},
}
HOLDS = {"take": "actor", "find": "actor", "steal": "actor"}
LEAVES = {"misplace": "actor"}


# -- 1. state as of the event (from the deltas: the world's own history) ------------------------------------------
def _value_at(conn: sqlite3.Connection, etype: str, eid: str, fld: str, event_id: int, default):
    row = conn.execute("SELECT new_value FROM event_deltas WHERE entity_type = ? AND entity_id = ? AND field = ? "
                       "AND event_id <= ? ORDER BY delta_id DESC LIMIT 1", (etype, eid, fld, event_id)).fetchone()
    if row is not None:
        return row[0]
    first = conn.execute("SELECT old_value FROM event_deltas WHERE entity_type = ? AND entity_id = ? AND field = ? "
                         "ORDER BY delta_id LIMIT 1", (etype, eid, fld)).fetchone()
    if first is not None:
        return first[0]
    if etype == "relationship":
        a, b = eid.split(":")
        r = conn.execute(f"SELECT {fld} FROM relationships WHERE actor_id = ? AND target_id = ?", (a, b)).fetchone()
        return r[0] if r else default
    if etype == "person":
        r = conn.execute(f"SELECT {fld} FROM people WHERE id = ?", (eid,)).fetchone()
        return r[0] if r else default
    if etype == "var":
        r = conn.execute("SELECT value FROM world_vars WHERE key = ?", (eid,)).fetchone()
        return r[0] if r else default
    return default


def character_state(conn: sqlite3.Connection, pid: str, beat: Beat, others: list[str],
                    counterfactual: dict | None = None) -> dict:
    e = beat.event_id
    cf = (counterfactual or {}).get(pid, {})
    s: dict = {"emotion": cf.get("emotion", _value_at(conn, "person", pid, "emotion", e, "calm")),
               "traits": {k: float(cf.get(f"psy.{k}", _value_at(conn, "var", f"psy.{pid}.{k}", "value", e, v)) or v)
                          for k, v in ADAPTIVE.items()},
               "rel": {}, "suspects": {}, "goals": [], "holding": "", "not_mine": False, "missing": False, "cf": cf}
    for o in others:
        s["rel"][o] = {f: float(cf.get(f"{f}:{o}", _value_at(conn, "relationship", f"{pid}:{o}", f, e, 0.0)) or 0.0)
                       for f in ("trust", "affection", "fear", "rivalry")}
        row = conn.execute(
            "SELECT m.memory_id, m.confidence FROM memories m JOIN claims c USING (claim_id) WHERE m.observer_id = ? "
            "AND c.subject = ? AND c.act IN ('take', 'steal') AND c.polarity = 'affirm' AND m.event_id <= ? "
            "ORDER BY m.memory_id DESC LIMIT 1", (pid, o, e)).fetchone()
        cleared = conn.execute(
            "SELECT 1 FROM memories m JOIN claims c USING (claim_id) WHERE m.observer_id = ? AND c.subject = ? "
            "AND c.act IN ('take', 'steal') AND c.polarity = 'deny' AND m.event_id <= ? AND m.memory_id > ?",
            (pid, o, e, row[0] if row else 0)).fetchone()
        if f"suspects:{o}" in cf:
            s["suspects"][o] = (float(cf[f"suspects:{o}"]), "counterfactual")
        elif row and not cleared:
            s["suspects"][o] = (float(row[1]), f"memory:{row[0]}")
    if beat.event_type == "notice_missing":
        sus = next((p.id for p in beat.participants if p.role == "suspect"), None)
        if sus and sus not in s["suspects"]:
            s["suspects"][sus] = (0.6, f"event:{e}:suspect")
    for (truth,) in conn.execute("SELECT truth FROM events WHERE type = 'goal_change' AND event_id <= ? AND "
                                 "json_extract(truth, '$.actor') = ? ORDER BY event_id", (e, pid)):
        g = json.loads(truth)
        s["goals"] = [x for x in s["goals"] if x["goal"] != g["goal"]]
        if g["to"] in ("formed", "active", "revised", "transformed", "blocked"):
            s["goals"].append({"goal": g["goal"], "kind": g["kind"], "target": g.get("target", ""),
                               "object": g.get("object", "")})
    if beat.prop is not None:
        holder = _value_at(conn, "object", beat.prop.id, "owner_person_id", e - 1, None)
        owner = conn.execute("SELECT rightful_owner_id FROM objects WHERE id = ?", (beat.prop.id,)).fetchone()
        s["holding"] = beat.prop.id if holder == pid else ""
        s["not_mine"] = bool(owner and owner[0] and owner[0] != pid and holder == pid)
        s["missing"] = bool(owner and owner[0] == pid and holder != pid)
    return s


# -- 2. drives ------------------------------------------------------------------------------------------------------
def _drives(pid: str, beat: Beat, role: str, s: dict, animal: bool) -> list[Drive]:
    t, out = beat.event_type, []
    tag = "counterfactual" if s["cf"] else None

    def add(name: str, value: float, causes: list[Cause]) -> None:
        if value > 0.05 and causes:
            out.append(Drive(name, round(min(1.0, value), 3), causes))

    for o, r in sorted(s["rel"].items()):
        kind = tag or "relationship"
        add("fear", r["fear"] + 0.3 * s["traits"]["vigilance"] * (r["fear"] > 0),
            [Cause(kind, f"fear:{pid}->{o}={r['fear']:.2f}", r["fear"])])
        res = max(0.0, -r["trust"]) * 0.7 + max(0.0, r["rivalry"]) * 0.5 + max(0.0, -r["affection"]) * 0.3
        add("resentment", res, [Cause(kind, f"trust:{pid}->{o}={r['trust']:.2f}", -r["trust"]),
                                Cause(kind, f"rivalry:{pid}->{o}={r['rivalry']:.2f}", r["rivalry"])])
        add("attachment", max(0.0, r["affection"]) * 0.8 + max(0.0, r["trust"]) * 0.2,
            [Cause(kind, f"affection:{pid}->{o}={r['affection']:.2f}", r["affection"])])
    for o, (conf, ref) in sorted(s["suspects"].items()):
        add("suspicion", conf, [Cause("counterfactual" if ref == "counterfactual" else "belief",
                                      f"{ref}:{pid} thinks {o} took it", conf)])
    if s["not_mine"] and not animal:
        add("guilt", 0.6, [Cause("holding", f"{pid} holds {beat.prop.id}, which is not theirs", 0.6)])
    if s["missing"] or t == "notice_missing":
        add("distress", 0.55 + 0.3 * s["traits"]["vigilance"], [Cause("event", f"event:{beat.event_id}:{t}", 0.6)])
    if t == "find" and role == "actor":
        add("relief", 0.8, [Cause("event", f"event:{beat.event_id}:find", 0.8)])
    if animal and t in ("take", "misplace", "find") or (animal and beat.prop is not None):
        add("curiosity", 0.7, [Cause("perception", f"event:{beat.event_id}:a thing with a smell", 0.7)])
    if role in ("target", "suspect") and t in ("accuse", "confront"):
        add("self_protection", 0.5 + 0.4 * s["traits"]["withdrawal"],
            [Cause("event", f"event:{beat.event_id}:{t} against {pid}", 0.5)])
    emo = s["emotion"]
    if emo in ("angry", "hurt", "ashamed", "uneasy", "afraid", "happy"):
        name = {"angry": "resentment", "hurt": "distress", "ashamed": "guilt", "uneasy": "fear", "afraid": "fear",
                "happy": "relief"}[emo]
        add(name, 0.35, [Cause(tag or "emotion", f"emotion:{pid}={emo}", 0.35)])
    merged: dict[str, Drive] = {}
    for d in out:  # one drive per name: the strongest value, all the causes
        m = merged.get(d.name)
        merged[d.name] = d if m is None else Drive(d.name, max(m.value, d.value), m.causes + d.causes)
    return sorted(merged.values(), key=lambda d: (-d.value, d.name))


def _level(drives: list[Drive], name: str) -> float:
    return next((d.value for d in drives if d.name == name), 0.0)


# -- 3. primary and 4. intent ---------------------------------------------------------------------------------------
def _primary(drives: list[Drive], s: dict, animal: bool) -> tuple[str, float]:
    if not drives:
        return "calm", 0.2
    top = drives[0]
    aggression = s["traits"]["aggression"]
    if top.name == "resentment" and aggression < 0.45:
        return "restrained_anger", top.value
    if top.name == "resentment":
        return "angry", top.value
    if top.name == "self_protection" or (top.name == "fear" and _level(drives, "resentment") > 0.3):
        return "defensive", top.value
    return {"fear": "afraid", "suspicion": "suspicious", "guilt": "guilty", "distress": "distressed",
            "relief": "relieved", "attachment": "warm", "curiosity": "curious"}.get(top.name, "calm"), top.value


def _intent(pid: str, beat: Beat, role: str, primary: str, animal: bool, s: dict) -> str:
    t = beat.event_type
    if animal:
        return {"take": "investigate", "misplace": "lose_interest", "find": "watch", "bark": "warn"}.get(t, "follow")
    if role == "actor":
        if t == "misplace":
            return "go_on"  # unaware: the body does nothing special, which is the point
        if t == "notice_missing":
            return "search"
        if t in ("take", "steal"):
            return "conceal" if s["not_mine"] or t == "steal" else "pick_up"
        if t == "find":
            return "recover"
        if t in ("accuse", "confront"):
            return "confront"
        if t == "give":
            return "hand_over"
        if t == "talk" and beat.variant == "warm":
            return "reach_out"
    if role in ("target", "suspect") and t in ("accuse", "confront"):
        return "defend"
    if role == "witness":
        return "avoid" if primary in ("afraid", "guilty", "defensive") else "watch"
    return "listen" if role in ("target", "receiver") else "be_there"


# -- 5. channels ------------------------------------------------------------------------------------------------------
def _look_at(pid: str, beat: Beat, intent: str, s: dict) -> str:
    others = [p.id for p in beat.participants if p.id != pid and p.role in ("actor", "target", "victim", "receiver")]
    if intent in ("search", "recover", "pick_up", "investigate", "conceal", "go_on") and beat.prop is not None:
        return beat.prop.id if intent != "search" else ""
    if intent == "watch":
        return next((p.id for p in beat.participants if p.role == "actor" and p.id != pid), "")
    return others[0] if others else ""


def _human(pid, beat, role, intent, primary, intensity, drives, s, seconds):
    fear, res, sus = _level(drives, "fear"), _level(drives, "resentment"), _level(drives, "suspicion")
    guilt, dist, rel = _level(drives, "guilt"), _level(drives, "distress"), _level(drives, "relief")
    prot = _level(drives, "self_protection")
    target = _look_at(pid, beat, intent, s)
    if guilt > 0.4 or prot > 0.5 or (fear > 0.5 and intent != "confront"):
        gaze = Gaze(target, "avoid", round(seconds * 0.25, 2))
    elif intent == "search" or dist > 0.5:
        gaze = Gaze(target, "scan", round(seconds * 0.8, 2))
    elif res > 0.4 or sus > 0.5 or intent == "confront":
        gaze = Gaze(target, "hold", round(seconds * 0.8, 2))
    elif primary in ("distressed",) or s["traits"]["withdrawal"] > 0.5:
        gaze = Gaze(target, "down", round(seconds * 0.5, 2))
    else:
        gaze = Gaze(target, "follow" if target else "glance", round(seconds * 0.5, 2))
    tension = round(max(fear, res, guilt, dist, prot, 0.1), 3)
    openness = round(max(0.05, 1.0 - max(fear, res, prot, guilt) - 0.3 * s["traits"]["withdrawal"]), 3)
    lean = round((0.5 if intent in ("confront", "search", "reach_out") else 0.0) - 0.5 * max(fear, guilt, prot), 3)
    holding = _holding_after(pid, beat, s)
    if intent == "search":
        hands = Hands("search", round(dist, 3), holding)
    elif intent == "confront":
        hands = Hands("point", round(max(res, 0.4), 3), holding)
    elif holding and (guilt > 0.3 or res > 0.5):
        hands = Hands("grip", round(max(guilt, res), 3), holding)
    elif holding:
        hands = Hands("hold", 0.3, holding)
    elif guilt > 0.3 or fear > 0.5:
        hands = Hands("fidget", round(max(guilt, fear), 3), holding)
    elif primary == "restrained_anger":
        hands = Hands("grip", round(res, 3), holding)
    else:
        hands = Hands("idle", 0.1, holding)
    face = Face(
        brows="narrow" if res > 0.35 or sus > 0.5 else "raised" if fear > 0.5 else "knit" if dist > 0.4 else "neutral",
        jaw="tight" if primary in ("restrained_anger", "defensive") or res > 0.5 else "loose",
        mouth="pressed" if primary in ("restrained_anger", "guilty", "defensive") else "smile" if rel > 0.5
        else "open" if intent == "search" and dist > 0.5 else "down" if dist > 0.4 else "neutral",
        eyes="wide" if fear > 0.5 or (intent == "search" and dist > 0.6) else "narrow" if sus > 0.5 or res > 0.5
        else "soft" if rel > 0.5 or _level(drives, "attachment") > 0.5 else "lowered" if guilt > 0.4 else "neutral")
    micro: list[MicroAction] = []
    if guilt > 0.3:
        micro += [MicroAction("glance_away", 0.3), MicroAction("touch_object", 0.6)]
    if primary == "restrained_anger":
        micro += [MicroAction("jaw_clench", 0.35), MicroAction("swallow", 0.7)]
    if fear > 0.5:
        micro += [MicroAction("breath_fast", 0.2), MicroAction("look_around", 0.55)]
    if intent == "search":
        micro += [MicroAction("pat_pockets", 0.25), MicroAction("look_around", 0.6)]
    if sus > 0.5 and intent != "search":
        micro.append(MicroAction("lingering_look", 0.5))
    if rel > 0.5:
        micro += [MicroAction("exhale", 0.4), MicroAction("smile_break", 0.7)]
    if prot > 0.5:
        micro.append(MicroAction("delay", 0.15))
    movement = ("walk_away" if intent == "go_on" and beat.event_type == "misplace" else "approach"
                if intent in ("confront", "reach_out", "recover") else "retreat" if prot > 0.5 or fear > 0.6 else "still")
    delivery = ("restrained" if primary in ("restrained_anger", "defensive") else "short" if guilt > 0.3 or prot > 0.4
                else "sharp" if primary == "angry" else "soft" if dist > 0.4 else "warm" if rel > 0.5 else "none"
                if beat.event_type in ("misplace", "take", "find", "notice_missing") else "soft")
    speech = Speech(delivery, "slow" if primary in ("restrained_anger", "distressed") else "fast" if fear > 0.6 else
                    "normal", round(0.2 + 0.8 * max(prot, guilt, 0.6 * res), 2))
    return gaze, Posture(tension, openness, lean), hands, face, None, micro, movement, speech


def _dog(pid, beat, role, intent, primary, intensity, drives, s, seconds):
    fear, att, cur = _level(drives, "fear"), _level(drives, "attachment"), _level(drives, "curiosity")
    target = _look_at(pid, beat, intent, s)
    gaze = Gaze(target, "follow" if intent in ("follow", "watch") else "hold" if cur > 0.5 else "glance",
                round(seconds * 0.6, 2))
    animal = AnimalBody(ears="back" if fear > 0.5 else "up" if cur > 0.5 or intent == "warn" else "neutral",
                        tail="low" if fear > 0.5 else "wag" if att > 0.3 or intent == "lose_interest" else
                        "high" if cur > 0.5 else "neutral",
                        head_tilt=12.0 if cur > 0.5 and intent in ("investigate", "watch") else 0.0,
                        pace="slow" if intent == "investigate" else "trot" if intent in ("follow", "lose_interest")
                        else "dart" if fear > 0.6 else "still")
    micro = []
    if cur > 0.4 and beat.prop is not None:
        micro += [MicroAction("sniff", 0.2), MicroAction("head_tilt", 0.35)]
    if intent == "lose_interest":
        micro += [MicroAction("look_back", 0.7)]
    if fear > 0.5:
        micro.append(MicroAction("freeze", 0.3))
    posture = Posture(round(max(fear, cur * 0.5, 0.1), 3), round(1 - fear, 3), 0.4 if cur > 0.5 else -0.5 * fear)
    movement = "approach" if intent == "investigate" else "walk_away" if intent == "lose_interest" else "still"
    return gaze, posture, None, None, animal, micro, movement, None


def _holding_after(pid: str, beat: Beat, s: dict) -> str:
    if beat.prop is None:
        return s["holding"]
    role = {p.id: p.role for p in beat.participants}.get(pid)
    if HOLDS.get(beat.event_type) == role:
        return beat.prop.id
    if LEAVES.get(beat.event_type) == role:
        return ""
    return s["holding"]


# -- the plan ---------------------------------------------------------------------------------------------------------
def _profile(spec: SceneSpec, pid: str) -> str:
    return "dog" if spec.characters[pid].asset_id.startswith("animal_") else "human"


def plan_performance(conn: sqlite3.Connection, spec: SceneSpec, direction: DirectorPlan,
                     counterfactual: dict | None = None) -> PerformancePlan:
    """One PerformanceBeat per character in frame per shot. The same beat gives the same performance in every shot
    (a close-up does not change how someone feels); what the shot shows of it is the camera's business."""
    from narrative.direction import _people
    states: dict[str, BodyState] = {}
    last_beat: dict[str, int] = {}
    beats: list[PerformanceBeat] = []
    cache: dict[tuple[int, str], tuple] = {}
    for cs in direction.shots:
        b = spec.beats[cs.beat_index]
        roles = {p.id: p.role for p in b.participants}
        here = [p for p in _people(b) if p in spec.characters]
        if direction.focalization.kind == "animal" and direction.focalization.focalizer in roles:
            here += [direction.focalization.focalizer] if direction.focalization.focalizer not in here else []
        if cs.subject in roles and cs.subject in spec.characters and cs.subject not in here:
            here.append(cs.subject)  # whoever the camera finds is in frame, and performs
        for pid in here:
            key = (cs.beat_index, pid)
            profile = _profile(spec, pid)
            animal = profile == "dog"
            if key not in cache:
                others = [o for o in roles if o != pid and o in spec.characters]
                s = character_state(conn, pid, b, others, counterfactual)
                drives = _drives(pid, b, roles.get(pid, ""), s, animal)
                primary, intensity = _primary(drives, s, animal)
                intent = _intent(pid, b, roles.get(pid, ""), primary, animal, s)
                seconds = sum(x.seconds for x in direction.shots if x.beat_index == cs.beat_index)
                channels = (_dog if animal else _human)(pid, b, roles.get(pid, ""), intent, primary, intensity,
                                                        drives, s, seconds)
                cache[key] = (s, drives, primary, intensity, intent, channels)
            s, drives, primary, intensity, intent, (gaze, posture, hands, face, body, micro, movement, speech) = cache[key]
            prev, hand = states.get(pid), ("mouth" if animal else "right")
            if prev is not None and last_beat.get(pid) == cs.beat_index:
                before = prev  # another angle on the same moment
            else:  # a new beat starts from the world as it was, so a hand the world contradicts shows up as a break
                before = BodyState(s["holding"], hand if s["holding"] else "none", prev.gesture if prev else "idle",
                                   prev.gaze if prev else "", prev.emotion if prev else primary)
            last_beat[pid] = cs.beat_index
            holding = _holding_after(pid, b, s)
            gesture = hands.action if hands is not None else ("carry" if holding else "idle")
            after = BodyState(holding, ("mouth" if animal else "right") if holding else "none", gesture, gaze.target,
                              primary)
            changes = []
            if before.holding != after.holding:
                changes.append(f"holding: {before.holding or '-'} -> {after.holding or '-'} ({b.event_type})")
            if before.emotion != after.emotion:
                why = drives[0].causes[0].ref if drives else "the drives settled"
                changes.append(f"emotion: {before.emotion} -> {after.emotion} ({why})")
            beats.append(PerformanceBeat(cs.shot_index, pid, profile, intent, primary, round(intensity, 3), drives,
                                         gaze, posture, hands, face, body, micro, movement, speech, before, after,
                                         changes))
            states[pid] = after
    return finalize(PerformancePlan(PERFORMANCE_VERSION, spec.scene_hash, direction.plan_hash, beats,
                                    counterfactual or {}))


# -- checks -----------------------------------------------------------------------------------------------------------
def continuity_breaks(plan: PerformancePlan) -> list[str]:
    """Jumps from one shot to the next that nothing explains: a thing appearing in or leaving a hand without an
    event, an emotion changing without a drive, a body using a channel its profile does not have."""
    out, last = [], {}
    for pb in plan.beats:
        prev = last.get(pb.actor)
        if prev is not None and prev.holding != pb.before.holding:
            out.append(f"shot {pb.shot_index} {pb.actor}: holding {prev.holding!r} became {pb.before.holding!r}")
        if pb.before.holding != pb.after.holding and not any(c.startswith("holding:") for c in pb.changes):
            out.append(f"shot {pb.shot_index} {pb.actor}: holding changed without a cause")
        if pb.before.emotion != pb.after.emotion and not any(c.startswith("emotion:") for c in pb.changes):
            out.append(f"shot {pb.shot_index} {pb.actor}: emotion changed without a cause")
        channels = PROFILES[pb.profile]["channels"]
        for name, value in (("hands", pb.hands), ("face", pb.face), ("speech", pb.speech), ("animal", pb.animal)):
            if value is not None and name not in channels:
                out.append(f"shot {pb.shot_index} {pb.actor}: a {pb.profile} has no {name}")
        for m in pb.micro:
            if m.name not in PROFILES[pb.profile]["micro"]:
                out.append(f"shot {pb.shot_index} {pb.actor}: {m.name} is not something a {pb.profile} does")
        last[pb.actor] = pb.after
    return out


def uncaused(plan: PerformancePlan) -> list[str]:
    """Performances that no state explains: any non-calm primary must have drives, and every drive causes."""
    out = []
    for pb in plan.beats:
        if pb.primary != "calm" and not pb.drives:
            out.append(f"shot {pb.shot_index} {pb.actor}: {pb.primary} with no drive")
        for d in pb.drives:
            if not d.causes:
                out.append(f"shot {pb.shot_index} {pb.actor}: drive {d.name} with no cause")
    return out
