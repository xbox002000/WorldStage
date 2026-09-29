"""SceneSpec (+ its thread and what the audience has seen) -> DirectorPlan. Deterministic rules, no model.

Order of decisions, each feeding the next:
1. knowledge   does the audience know more than the characters (irony), less (mystery), or the same (plain)?
2. focal       through whose eyes: the person the question concerns who is most in the dark; beats they did not
               witness are shown as audience-only (irony) or kept back (mystery); a witness can carry the view there
3. beats       what each beat is for (orient, reveal, hide, escalate, misdirect, payoff ...)
4. camera      coverage from the function: a reveal is a slow push-in on the face that learns; a hidden act is hands
               and an object, not a face; a false lead is a steady medium on the wrongly suspected
5. edit, sound why each cut; silence before a reveal, a sting on it, muffled talk in a point-of-view shot
"""
from __future__ import annotations

import json
import sqlite3

from contracts.director import (AudienceKnowledgePlan, CameraShot, Cut, DramaticBeat, DirectorPlan, FocalizationPlan,
                                KnowledgeState, POVTransition, SoundCue, finalize)
from contracts.scene_spec import Beat, SceneSpec
from contracts.thread import StoryThread
from narrative.knowledge import knowledge_of

COMPILER_VERSION = "direction-0.1"
PRINCIPAL = ("actor", "target", "victim", "suspect", "receiver", "addressee")
EXPOSED = ("lie_exposed", "distortion_exposed", "concealment_exposed", "caught")


LONE = ("take", "misplace", "notice_missing", "find", "cash_prize", "feed_pet", "seed")


def _people(beat: Beat, roles=None) -> list[str]:
    """Who is physically there. In a lone act the victim or suspect is only in someone's mind."""
    present = [p for p in beat.participants if beat.event_type not in LONE or p.role in ("actor", "witness")]
    return [p.id for p in present if roles is None or p.role in roles]


def _role(beat: Beat, role: str) -> str | None:
    return next((p.id for p in beat.participants if p.role == role), None)


def _truth_beats(conn: sqlite3.Connection, spec: SceneSpec, truth: list[str]) -> list[int]:
    triples = {tuple(t.split(":")) for t in truth}
    out = []
    for i, b in enumerate(spec.beats):
        rows = conn.execute("SELECT c.subject, c.act, c.object FROM event_claims ec JOIN claims c USING (claim_id) "
                            "WHERE ec.event_id = ? AND ec.role = 'truth'", (b.event_id,)).fetchall()
        if any(tuple(r) in triples for r in rows):
            out.append(i)
    return out


def plan_knowledge(conn, spec: SceneSpec, thread: StoryThread | None, shown: set[int]) -> AudienceKnowledgePlan:
    k = knowledge_of(conn, thread, shown) if thread is not None else None
    if k is None or not (k.wrong or k.unaware):
        return AudienceKnowledgePlan("plain", "no one in the story is in the dark about its question", None, None, [])
    state = KnowledgeState(k.question, k.truth, k.knows, k.wrong, k.unaware, k.audience_knows)
    truth = _truth_beats(conn, spec, k.truth)
    exposure = next((i for i, b in enumerate(spec.beats) if b.variant in EXPOSED), None)
    if truth and exposure is not None and exposure > truth[0] and not k.audience_knows:
        return AudienceKnowledgePlan("mystery", "the truth comes out later in this scene: keep the culprit's face back until then",
                                     state, exposure, truth)
    if truth or k.audience_knows:
        return AudienceKnowledgePlan("irony", "show the audience what the person it concerns does not know", state,
                                     truth[0] if truth else None, [])
    return AudienceKnowledgePlan("mystery", "nobody on screen, and not the audience, knows the answer yet", state, None, [])


def plan_focal(spec: SceneSpec, knowledge: AudienceKnowledgePlan) -> FocalizationPlan:
    counts: dict[str, int] = {}
    for b in spec.beats:
        for pid in _people(b):
            counts[pid] = counts.get(pid, 0) + 1
    if knowledge.state is not None:
        dark = [p for p in knowledge.state.wrong + knowledge.state.unaware if p in counts]
        pool, why = (dark, "the one in the dark") if dark else ([], "")
    else:
        pool, why = [], ""
    if not pool:
        peak = next((b for b in spec.beats if b.event_id == spec.peak_event_id), spec.beats[0])
        pool, why = _people(peak, PRINCIPAL)[:1], "the one who acts at the peak"
    if not pool:
        return FocalizationPlan("", "none", "omniscient", "nobody to follow", list(range(len(spec.beats))), [])
    focal = max(pool, key=lambda p: (counts.get(p, 0), p))
    in_scope = [i for i, b in enumerate(spec.beats) if focal in _people(b)]
    outside = [i for i in range(len(spec.beats)) if i not in in_scope]
    audience_only = [i for i in outside if i not in knowledge.withheld_beats]
    transitions = []
    for i in outside:
        carrier = next((p.id for p in spec.beats[i].participants if p.role == "witness"), None)
        if carrier:
            transitions.append(POVTransition(i, focal, carrier, "cut", f"{focal} was not there; {carrier} saw it"))
            transitions.append(POVTransition(i + 1, carrier, focal, "cut", "back to the one the story follows"))
    return FocalizationPlan(focal, "person", "limited", why, in_scope, audience_only, transitions)


def beat_functions(i: int, b: Beat, spec: SceneSpec, knowledge: AudienceKnowledgePlan) -> list[str]:
    f = ["orient"] if i == 0 else []
    t, v = b.event_type, b.variant
    if t in ("take", "steal", "backstory"):
        # irony: let the audience see who did it; mystery: the act without the face
        f += ["hide"] if i in knowledge.withheld_beats else ["reveal"] if knowledge.strategy == "irony" else ["observe"]
    elif t == "misplace":
        f += ["foreshadow"]
    elif t == "notice_missing":
        f += ["isolate", "misdirect"]
    elif t == "tell":
        f += ["hide"] if v in ("lie", "distortion", "omission") else ["connect"]
    elif t in ("accuse", "confront"):
        f += ["reveal", "payoff"] if v in EXPOSED else ["misdirect", "escalate"] if v in ("false", "unfounded") else ["escalate"]
    elif t == "talk":
        f += ["escalate"] if v in ("cold", "hostile") else ["connect"]
    elif t in ("give", "find"):
        f += ["payoff"]
    elif t in ("lend", "repay"):
        f += ["connect"]
    elif t == "parrot_speaks":
        f += ["contrast", "reveal"]
    elif t == "seed":
        f += ["orient"] if i else []
    return f or ["observe"]


def _shots_for(i: int, b: Beat, functions: list[str], focal: FocalizationPlan, start: int) -> list[CameraShot]:
    here = _people(b)
    actor = "parrot" if b.event_type == "parrot_speaks" else (_role(b, "actor") or (here[0] if here else ""))
    other = next((p for p in (_role(b, "target"), _role(b, "victim"), _role(b, "suspect")) if p and p in here), "")
    # the face that learns: the focalizer if they are there, else whoever the act lands on, else the one who acts
    reacting = focal.focalizer if focal.focalizer in here and focal.focalizer != actor else (other or actor)
    shots: list[tuple] = []
    for fn in functions:
        if fn == "orient":
            shots.append((fn, "WS", "eye_level", "frontal", "static", "slow", actor or "place", "space", 2.5, "wide",
                          "where we are and who is here"))
        elif fn == "reveal":
            if b.prop is not None:
                shots.append((fn, "INSERT", "high", "frontal", "static", "slow", b.prop.id, "object", 2.0, "insert",
                              "the thing itself"))
            shots.append((fn, "CU", "eye_level", "frontal", "push_in", "slow", reacting, "eyes", 3.5, "over_shoulder",
                          "who did it" if reacting == actor else "the face of the one who learns"))
        elif fn == "hide":
            shots.append((fn, "INSERT" if b.prop is not None else "MS", "high", "rear", "static", "slow",
                          b.prop.id if b.prop is not None else actor, "hands", 2.5, "insert" if b.prop is not None else "over_shoulder",
                          "the act, not the face"))
        elif fn == "escalate":
            shots.append((fn, "MCU", "eye_level", "over_shoulder", "push_in", "medium", actor, "face", 2.5, "over_shoulder",
                          "pressure closing in"))
            if other:
                shots.append(("reaction", "CU", "eye_level", "frontal", "static", "medium", other, "eyes", 2.0,
                              "over_shoulder", "how it lands"))
        elif fn == "misdirect":
            shots.append((fn, "MS", "eye_level", "frontal", "static", "slow", other or actor, "body", 3.0, "two_shot",
                          "hold on the one we are led to suspect" if other else "sure of the wrong person"))
        elif fn == "connect":
            shots.append((fn, "MS", "eye_level", "two_shot", "static", "slow", actor, "body", 3.0, "two_shot",
                          "the two of them together"))
        elif fn == "isolate":
            shots.append((fn, "WS", "high", "profile", "static", "slow", actor, "space", 3.0, "wide", "alone with it"))
        elif fn == "foreshadow":
            shots.append((fn, "INSERT", "high", "frontal", "static", "slow", b.prop.id if b.prop is not None else actor,
                          "object", 2.0, "insert", "left behind, and nobody sees"))
        elif fn == "payoff":
            shots.append((fn, "CU", "eye_level", "frontal", "pull_out", "slow", reacting, "face", 3.5, "over_shoulder",
                          "it lands, then we step back"))
        elif fn == "contrast":
            shots.append((fn, "MS", "low", "frontal", "static", "medium", actor or "parrot", "body", 2.0, "wide",
                          "the absurd thing that says it"))
        elif fn == "observe":
            shots.append((fn, "MS", "eye_level", "profile", "static", "slow", actor, "body", 2.5, "two_shot", "watch"))
    if focal.mode == "limited" and focal.focalizer in _people(b, ("witness",)):
        shots.append(("observe", "MS", "eye_level", "subjective", "handheld", "slow", actor, "body", 2.5, "pov",
                      f"through {focal.focalizer}'s eyes: they only watched"))
    out = []
    for j, s in enumerate(shots[:4]):
        out.append(CameraShot(start + j, i, s[0], s[1], s[2], s[3], s[4], s[5], s[6], s[7], s[8], s[9], s[10]))
    return out


def plan_edit_and_sound(spec: SceneSpec, beats: list[DramaticBeat], shots: list[CameraShot],
                        knowledge: AudienceKnowledgePlan, focal: FocalizationPlan) -> tuple[list[Cut], list[SoundCue]]:
    cuts, sound = [], []
    for n, s in enumerate(shots):
        b = spec.beats[s.beat_index]
        prev = shots[n - 1] if n else None
        if prev is None:
            cut = Cut(n, "open", "cut")
        elif prev.beat_index != s.beat_index:
            pb = spec.beats[prev.beat_index]
            if pb.day != b.day:
                cut = Cut(n, "time_jump", "dissolve")
            elif pb.location.id != b.location.id:
                cut = Cut(n, "location_change", "cut")
            elif "reveal" in beats[s.beat_index].functions or "payoff" in beats[s.beat_index].functions:
                cut = Cut(n, "information_reveal", "smash_cut" if knowledge.strategy == "mystery" else "cut")
            else:
                cut = Cut(n, "causal_continuity", "cut")
        elif s.function == "reaction":
            cut = Cut(n, "reaction", "cut")
        else:
            cut = Cut(n, "attention_shift", "cut")
        cuts.append(cut)
        nxt = shots[n + 1] if n + 1 < len(shots) else None
        if s.function in ("reveal", "payoff"):
            music, why = "sting", "the truth lands"
        elif nxt is not None and nxt.function in ("reveal", "payoff") and nxt.beat_index != s.beat_index:
            music, why = "silence", "hold the breath before it comes out"
        elif s.function in ("hide", "misdirect") and knowledge.strategy == "irony":
            music, why = "tension", "we know, they do not"
        elif s.function in ("connect", "payoff"):
            music, why = "release", "a moment of warmth"
        elif s.function in ("escalate", "reaction"):
            music, why = "tension", "pressure"
        else:
            music, why = "none", "let the place speak"
        dialogue = "muffled" if s.relation == "subjective" else "none" if s.function in ("hide", "foreshadow", "isolate") else "full"
        sound.append(SoundCue(n, music, dialogue, b.location.name, why))
    if cuts:
        cuts.append(Cut(len(shots), "hold", "hold"))  # end on the last image, the question still open
    return cuts, sound


def _character_turn(conn, focal: str, spec: SceneSpec) -> str:
    """If the focalizer is changing inside the scene's days, say how (from goal changes and reflections)."""
    if not focal:
        return ""
    days = sorted({b.day for b in spec.beats})
    lo, hi = (days[0] - 1) * 1440, days[-1] * 1440
    turns = []
    for t, truth in conn.execute("SELECT type, truth FROM events WHERE type IN ('goal_change', 'reflection') "
                                 "AND json_extract(truth, '$.actor') = ? AND timestamp >= ? AND timestamp < ? ORDER BY event_id",
                                 (focal, lo, hi)):
        d = json.loads(truth)
        if t == "goal_change" and d.get("to") in ("formed", "transformed", "abandoned"):
            turns.append(f"目標{ {'formed': '變成', 'transformed': '轉為', 'abandoned': '放下了'}[d['to']]}「{d['text']}」")
        elif t == "reflection" and d.get("self_model"):
            turns.append("開始覺得「" + "、".join(d["self_model"]) + "」")
    return "；".join(turns[-2:])


def plan_direction(conn: sqlite3.Connection, spec: SceneSpec, thread: StoryThread | None = None,
                   shown: set[int] | frozenset[int] = frozenset()) -> DirectorPlan:
    knowledge = plan_knowledge(conn, spec, thread, set(shown))
    focal = plan_focal(spec, knowledge)
    beats = []
    for i, b in enumerate(spec.beats):
        fns = beat_functions(i, b, spec, knowledge)
        inner = focal.focalizer if focal.focalizer in _people(b) else (_role(b, "actor") or "")
        beats.append(DramaticBeat(i, b.event_id, fns, inner, _note(fns, knowledge)))
    shots: list[CameraShot] = []
    for i, b in enumerate(spec.beats):
        shots += _shots_for(i, b, beats[i].functions, focal, len(shots))
    cuts, sound = plan_edit_and_sound(spec, beats, shots, knowledge, focal)
    names = {pid: p.name for pid, p in spec.characters.items()}
    who = names.get(focal.focalizer, focal.focalizer)
    if knowledge.strategy == "irony" and knowledge.state:
        goal = f"觀眾知道真相（{knowledge.state.question}），{who}卻不知道：看{who}怎麼走下去"
    elif knowledge.strategy == "mystery" and knowledge.state:
        goal = f"跟著{who}追問：{knowledge.state.question}"
    else:
        goal = f"跟著{who}經歷這件事" if who else "看這件事怎麼發生"
    turn = _character_turn(conn, focal.focalizer, spec)
    if turn:
        goal += f"。這幾天，{who}{turn}"
    return finalize(DirectorPlan(1, spec.scene_id, spec.scene_hash, thread.thread_id if thread else "", COMPILER_VERSION,
                                 goal, knowledge, focal, beats, shots, cuts, sound))


def _note(fns: list[str], knowledge: AudienceKnowledgePlan) -> str:
    notes = {"orient": "先讓觀眾知道在哪裡、誰在場", "reveal": "讓觀眾看見真相", "hide": "只給手和東西，不給臉",
             "escalate": "壓力升高", "misdirect": "讓觀眾跟著懷疑錯的人", "payoff": "前面埋的東西在這裡兌現",
             "connect": "兩個人之間的溫度", "isolate": "讓他一個人面對", "foreshadow": "東西留下了，沒人發現",
             "contrast": "荒謬的東西說出了真話", "observe": "旁觀", "reaction": "看它怎麼落在對方身上"}
    return "；".join(notes[f] for f in fns if f in notes)
