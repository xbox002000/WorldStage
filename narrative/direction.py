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

import dataclasses
import json
import sqlite3

from contracts.director import (AudienceKnowledgePlan, CameraShot, Cut, DramaticBeat, DirectorPlan, FocalizationPlan,
                                KnowledgeState, POVTransition, SoundCue, finalize)
from contracts.scene_spec import Beat, SceneSpec
from contracts.thread import StoryThread
from narrative.knowledge import knowledge_of

COMPILER_VERSION = "direction-0.3"
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


def _giveaways(spec: SceneSpec, truth: list[str], truth_beats: list[int]) -> list[int]:
    """Beats that would give the answer away: the truth's own beats, and any beat where its subject handles its object
    (the culprit dropping the thing somewhere is as telling as taking it)."""
    pairs = {(t.split(":")[0], t.split(":")[2]) for t in truth if t.count(":") >= 2}
    out = set(truth_beats)
    for i, b in enumerate(spec.beats):
        actor = _role(b, "actor")
        if b.prop is not None and (actor, b.prop.id) in pairs:
            out.add(i)
    return sorted(out)


def plan_knowledge(conn, spec: SceneSpec, thread: StoryThread | None, shown: set[int],
                   strategy: str | None = None) -> AudienceKnowledgePlan:
    k = knowledge_of(conn, thread, shown) if thread is not None else None
    if strategy is not None:
        return _forced_knowledge(conn, spec, k, strategy)
    if k is None or not (k.wrong or k.unaware):
        return AudienceKnowledgePlan("plain", "no one in the story is in the dark about its question", None, None, [])
    state = KnowledgeState(k.question, k.truth, k.knows, k.wrong, k.unaware, k.audience_knows)
    truth = _truth_beats(conn, spec, k.truth)
    exposure = next((i for i, b in enumerate(spec.beats) if b.variant in EXPOSED), None)
    if truth and exposure is not None and exposure > truth[0] and not k.audience_knows:
        return AudienceKnowledgePlan("mystery", "the truth comes out later in this scene: keep the culprit's face back until then",
                                     state, exposure, [i for i in _giveaways(spec, k.truth, truth) if i < exposure])
    if truth or k.audience_knows:
        return AudienceKnowledgePlan("irony", "show the audience what the person it concerns does not know", state,
                                     truth[0] if truth else None, [])
    return AudienceKnowledgePlan("mystery", "nobody on screen, and not the audience, knows the answer yet", state, None, [])


def _forced_knowledge(conn, spec: SceneSpec, k, strategy: str) -> AudienceKnowledgePlan:
    """The same facts, a different audience: irony shows the truth early, mystery keeps it back (until an exposure in
    the scene, if there is one), plain tells it as it happens."""
    if k is None:
        raise ValueError("this scene has no knowledge question to play with")
    state = KnowledgeState(k.question, k.truth, k.knows, k.wrong, k.unaware, k.audience_knows)
    truth = _truth_beats(conn, spec, k.truth)
    if strategy == "irony":
        return AudienceKnowledgePlan("irony", "forced: the audience sees the truth before the person it concerns",
                                     state, truth[0] if truth else None, [])
    if strategy == "mystery":
        exposure = next((i for i, b in enumerate(spec.beats) if b.variant in EXPOSED), None)
        return AudienceKnowledgePlan("mystery", "forced: the audience does not see who did it", state, exposure,
                                     [i for i in _giveaways(spec, k.truth, truth) if exposure is None or i < exposure])
    return AudienceKnowledgePlan("plain", "forced: told as it happens", state, None, [])


def _animals(spec: SceneSpec) -> set[str]:
    return {pid for pid, p in spec.characters.items() if p.asset_id.startswith("animal_")}


def plan_focal(spec: SceneSpec, knowledge: AudienceKnowledgePlan, forced: str | None = None) -> FocalizationPlan:
    animals = _animals(spec)
    if forced == "omniscient":
        return FocalizationPlan("", "none", "omniscient", "forced: outside everyone", list(range(len(spec.beats))), [])
    if forced is not None:
        return _forced_focal(spec, knowledge, forced, forced in animals)
    if animals and knowledge.state is not None and (knowledge.state.wrong or knowledge.state.unaware):
        # the animal did it or sensed it, while the people it concerns are in the dark: a witness that cannot speak
        for a in sorted(animals):
            seen = [i for i, b in enumerate(spec.beats) if a in [p.id for p in b.participants]]
            knows = a in knowledge.state.knows or any(
                b.event_type in ("take", "misplace", "steal") for i, b in enumerate(spec.beats) if i in seen)
            if seen and knows:
                others = [i for i in range(len(spec.beats)) if i not in seen]
                return FocalizationPlan(a, "animal", "witness", "the only one who saw it cannot say it", seen,
                                        [i for i in others if i not in knowledge.withheld_beats])
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


def _forced_focal(spec: SceneSpec, knowledge: AudienceKnowledgePlan, who: str, animal: bool) -> FocalizationPlan:
    """Through the eyes of `who`: only what they took part in, noticed or sensed is theirs; the rest is audience-only
    (or withheld, if the knowledge plan keeps it back)."""
    if who not in spec.characters:
        raise ValueError(f"{who} is not in this scene")
    there = [i for i, b in enumerate(spec.beats) if who in _people(b) or (animal and who in [p.id for p in b.participants])]
    outside = [i for i in range(len(spec.beats)) if i not in there]
    audience_only = [i for i in outside if i not in knowledge.withheld_beats]
    transitions = []
    for i in outside:
        carrier = next((p.id for p in spec.beats[i].participants if p.role == "witness" and p.id != who), None)
        if carrier:
            transitions.append(POVTransition(i, who, carrier, "cut", f"{who} was not there; {carrier} saw it"))
            transitions.append(POVTransition(i + 1, carrier, who, "cut", "back to the one the story follows"))
    return FocalizationPlan(who, "animal" if animal else "person", "witness" if animal else "limited",
                            "forced by the benchmark", there, audience_only, transitions)


def beat_functions(i: int, b: Beat, spec: SceneSpec, knowledge: AudienceKnowledgePlan) -> list[str]:
    f = ["orient"] if i == 0 else []
    t, v = b.event_type, b.variant
    if i in knowledge.withheld_beats:  # it would give the answer away: the act, never the face
        return f + ["hide"]
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
    elif t == "duel":
        f += ["escalate", "payoff"]
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
    if focal.kind == "animal" and focal.focalizer in [p.id for p in b.participants]:
        if focal.focalizer == actor:  # its own act: low, following the thing in its mouth
            shots.append(("observe", "MS", "ground", "rear", "tracking", "medium", actor, "object", 2.5, "wide",
                          "low behind the animal, the thing in its mouth"))
        else:
            shots.append(("observe", "MS", "ground", "subjective", "handheld", "slow", actor, "hands", 3.0, "pov",
                          f"from {focal.focalizer}'s height: legs, hands, a thing changing hands, voices without words"))
    out = []
    for j, s in enumerate(shots[:4]):
        out.append(CameraShot(start + j, i, s[0], s[1], s[2], s[3], s[4], s[5], s[6], s[7], s[8], s[9], s[10]))
    return out


CAMERA_STYLES = ("observational", "push_in", "subjective", "reaction")
TIGHTER = {"EWS": "WS", "WS": "MS", "MS": "MCU", "MCU": "CU", "CU": "CU", "ECU": "ECU", "INSERT": "INSERT"}


def restyle_camera(spec: SceneSpec, shots: list[CameraShot], focal: FocalizationPlan, grammar: str) -> list[CameraShot]:
    """The same beats and functions, filmed in one camera style (not a cinematic grammar: see narrative/grammar.py):
    observational  from a distance: wide and medium, eye level, static, no inserts or reaction cuts
    push_in        the scene closes in on the focalizer: tighter as it goes, every shot a slow push
    subjective     through the focalizer's eyes wherever they are (ground height for an animal); outside them, wide
    reaction       close and reaction-heavy: tighter coverage, and the focalizer's face after everything that lands
    """
    if grammar not in CAMERA_STYLES:
        raise ValueError(f"unknown camera style {grammar}")
    who, animal, out = focal.focalizer, focal.kind == "animal", []
    last = max((s.beat_index for s in shots), default=0) or 1
    by_beat: dict[int, list[CameraShot]] = {}
    for sh in shots:
        by_beat.setdefault(sh.beat_index, []).append(sh)
    for i, group in sorted(by_beat.items()):
        b = spec.beats[i]
        here = _people(b) + ([who] if animal and who in [p.id for p in b.participants] else [])
        actor = _role(b, "actor") or (here[0] if here else "")
        new: list[tuple] = []
        for sh in group:
            f = sh.function
            if grammar == "observational":
                if f == "reaction":
                    continue
                subj = sh.subject if sh.scale != "INSERT" or f == "hide" else actor
                new.append((f, "WS" if f in ("orient", "isolate") or sh.scale == "WS" else "MS", "eye_level",
                            "frontal" if f == "orient" else "profile", "static", "slow", subj,
                            "space" if f in ("orient", "isolate") else "body", sh.seconds,
                            "wide" if f in ("orient", "isolate") else "two_shot",
                            "watched from a distance: no push, no close-up"))
            elif grammar == "push_in":
                steps = ["WS", "MS", "MCU", "CU"]
                scale = steps[min(3, round(3 * i / last))] if sh.scale != "INSERT" else "INSERT"
                subj = who if who in here and f not in ("hide", "foreshadow") and sh.scale != "INSERT" else sh.subject
                new.append((f, scale, sh.angle if sh.angle != "ground" else "eye_level", "frontal", "push_in", "slow",
                            subj, "face" if scale in ("MCU", "CU") else sh.attention, sh.seconds, sh.spatial_camera,
                            f"the scene closes in on {who}" if who else "closing in"))
            elif grammar == "subjective":
                if who in here and f != "hide":
                    look = actor if actor and actor != who else (b.prop.id if b.prop is not None else actor)
                    new.append((f, "MCU" if look != actor else "MS", "ground" if animal else "eye_level", "subjective",
                                "handheld", "slow", look, "object" if look != actor else "body", sh.seconds, "pov",
                                f"through {who}'s eyes" + (": legs, hands, a thing, voices without words" if animal else "")))
                elif f == "hide":
                    new.append(tuple(getattr(sh, k) for k in _FIELDS))
                else:
                    new.append((f, "WS", "eye_level", "frontal", "static", "slow", sh.subject, "space", sh.seconds,
                                "wide", f"outside {who}'s eyes: the audience alone sees it"))
            else:  # reaction
                if f == "reaction":
                    continue
                new.append((f, TIGHTER[sh.scale] if f != "orient" else "MS", sh.angle, sh.relation, sh.motion,
                            sh.speed, sh.subject, sh.attention, sh.seconds, sh.spatial_camera, sh.reason))
                close_on_them = sh.subject == who and TIGHTER[sh.scale] in ("MCU", "CU", "ECU")
                if who in here and not close_on_them and f not in ("hide", "orient"):
                    new.append(("reaction", "CU", "eye_level", "frontal", "static", "medium", who, "eyes", 1.5,
                                "over_shoulder", f"how it lands on {who}"))
        if not new:  # a beat always keeps one shot
            sh = group[0]
            new.append(tuple(getattr(sh, k) for k in _FIELDS))
        dedup = []
        for t in new:
            if t not in dedup:
                dedup.append(t)
        out += [(i, t) for t in dedup[:4]]
    return [CameraShot(n, i, *t) for n, (i, t) in enumerate(out)]  # grammar steps are labelled afterwards


_FIELDS = ("function", "scale", "angle", "relation", "motion", "speed", "subject", "attention", "seconds",
           "spatial_camera", "reason")


def plan_edit_and_sound(spec: SceneSpec, beats: list[DramaticBeat], shots: list[CameraShot],
                        knowledge: AudienceKnowledgePlan, focal: FocalizationPlan,
                        values: list | None = None) -> tuple[list[Cut], list[SoundCue]]:
    from narrative.economy import cut_reason
    value = {v.shot_index: v for v in values or []}
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
        else:  # within a beat: cut for what the shot adds, never for the angle
            cut = Cut(n, cut_reason(value[n], s) if n in value else "causal_continuity", "cut")
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
        far = s.relation == "subjective" and focal.focalizer in _people(b, ("witness",))  # watching, out of earshot
        sensing = focal.kind == "animal" and focal.focalizer in [p.id for p in b.participants]  # voices, not words
        dialogue = ("muffled" if far or sensing else
                    "none" if s.function in ("hide", "foreshadow", "isolate") else "full")
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
                   shown: set[int] | frozenset[int] = frozenset(), *, focalizer: str | None = None,
                   strategy: str | None = None, camera: str | None = None, edit: str | None = None) -> DirectorPlan:
    """The director decides everything unless a benchmark forces a choice (focalizer, strategy, camera style, edit).
    A forced choice changes only how the scene is told; the scene, its events and its truth stay the same.
    focalizer="omniscient": no one's eyes, the camera stands outside everyone."""
    from narrative.grammar import (choose_grammar, information_function, label, pace, plan_attention, re_edit,
                                   turn_of)
    knowledge = plan_knowledge(conn, spec, thread, set(shown), strategy)
    focal = plan_focal(spec, knowledge, focalizer)
    beats = []
    for i, b in enumerate(spec.beats):
        fns = beat_functions(i, b, spec, knowledge)
        inner = focal.focalizer if focal.focalizer in _people(b) else (_role(b, "actor") or "")
        beats.append(DramaticBeat(i, b.event_id, fns, inner, _note(fns, knowledge)))
    shots: list[CameraShot] = []
    for i, b in enumerate(spec.beats):
        shots += _shots_for(i, b, beats[i].functions, focal, len(shots))
    if camera is not None:
        shots = restyle_camera(spec, shots, focal, camera)
    grammar = choose_grammar(knowledge, focal)
    shots = label(shots, grammar)
    shots = [dataclasses.replace(x, information_function=information_function(x, knowledge)) for x in shots]
    shots = re_edit(shots, edit) if edit is not None else pace(shots, turn_of(shots, knowledge))
    # shot economy: cut every shot that adds nothing, merge the ones that repeat the picture before them
    from narrative.economy import value_shots
    shots, values, dropped = value_shots(conn, spec, shots, knowledge, focal, turn_of(shots, knowledge))
    attention = plan_attention(spec, shots, knowledge, focal)
    if attention.reveal_shot is not None:  # controlled release: the camera finds the culprit, nothing is said
        at = next(x for x in shots if x.shot_index == attention.reveal_shot)
        culprit = attention.reveal_subject
        extra = CameraShot(0, at.beat_index, "reveal", "MS", "eye_level", "frontal", "push_in", "slow", culprit, "body",
                           3.0, "wide", attention.reveal_how, "hints", f"{grammar}:reveal")
        k = shots.index(at) + 1
        shots = [dataclasses.replace(x, shot_index=n) for n, x in enumerate(shots[:k] + [extra] + shots[k:])]
        attention = plan_attention(spec, shots, knowledge, focal)
        attention = dataclasses.replace(attention, reveal_shot=k)
        from contracts.director import ShotValue
        values = values[:k] + [ShotValue(k, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, "controlled release: what was kept back")] + \
            [dataclasses.replace(v, shot_index=v.shot_index + 1) for v in values[k:]]
    cuts, sound = plan_edit_and_sound(spec, beats, shots, knowledge, focal, values)
    names = {pid: p.name for pid, p in spec.characters.items()}
    who = names.get(focal.focalizer, focal.focalizer)
    if focal.kind == "animal":
        goal = f"透過{who}的眼睛：牠看見了，卻說不出來" + (f"（{knowledge.state.question}）" if knowledge.state else "")
    elif not who and knowledge.state:
        goal = f"站在所有人之外看：{knowledge.state.question}"
    elif knowledge.strategy == "irony" and knowledge.state:
        goal = f"觀眾知道真相（{knowledge.state.question}），{who}卻不知道：看{who}怎麼走下去"
    elif knowledge.strategy == "mystery" and knowledge.state:
        goal = f"跟著{who}追問：{knowledge.state.question}"
    else:
        goal = f"跟著{who}經歷這件事" if who else "看這件事怎麼發生"
    turn = _character_turn(conn, focal.focalizer, spec)
    if turn:
        goal += f"。這幾天，{who}{turn}"
    forced = {k: v for k, v in (("focalizer", focalizer), ("strategy", strategy), ("camera", camera), ("edit", edit))
              if v is not None}
    return finalize(DirectorPlan(1, spec.scene_id, spec.scene_hash, thread.thread_id if thread else "", COMPILER_VERSION,
                                 goal, knowledge, focal, beats, shots, cuts, sound, attention, grammar, forced,
                                 values, dropped))


def _note(fns: list[str], knowledge: AudienceKnowledgePlan) -> str:
    notes = {"orient": "先讓觀眾知道在哪裡、誰在場", "reveal": "讓觀眾看見真相", "hide": "只給手和東西，不給臉",
             "escalate": "壓力升高", "misdirect": "讓觀眾跟著懷疑錯的人", "payoff": "前面埋的東西在這裡兌現",
             "connect": "兩個人之間的溫度", "isolate": "讓他一個人面對", "foreshadow": "東西留下了，沒人發現",
             "contrast": "荒謬的東西說出了真話", "observe": "旁觀", "reaction": "看它怎麼落在對方身上"}
    return "；".join(notes[f] for f in fns if f in notes)
