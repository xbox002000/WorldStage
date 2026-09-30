"""Cinematic grammar, attention and pacing: how a scene's shots are arranged in time for what the audience learns.

A grammar is not a style. A StylePack says how the whole channel looks and sounds (cool, warm, comic). A cinematic
grammar says how one kind of information is usually released: conceal -> reaction -> reveal for a mystery that
pays off, show the truth -> follow the one who does not know it -> payoff for irony, and so on. Grammars are data
(GRAMMARS); the director picks one from the scene's knowledge plan and focalization, and every shot is labelled with
its step and its information function.

Pacing follows information and feeling, not shot count: the shots that establish run long, the ones before the turn
get shorter, there is a held breath before the reveal, the reveal lands, and the reaction is allowed to stay.
The attention plan says, shot by shot, what the audience should look at, what is there for those who look, and what
is kept out of sight until the scene lets it in (controlled information release).
"""
from __future__ import annotations

import dataclasses

from contracts.director import AttentionMark, AttentionPlan, AudienceKnowledgePlan, CameraShot, FocalizationPlan
from contracts.scene_spec import SceneSpec

GRAMMARS = {
    # a mystery that pays off in the scene: we see that something happened, then who it hurts, then what it was
    "conceal_reaction_reveal": {
        "steps": [("conceal", ("hide", "foreshadow")), ("reaction", ("isolate", "misdirect", "reaction", "escalate")),
                  ("reveal", ("reveal", "payoff"))],
        "use": "mystery"},
    # irony: the audience sees the truth first, then follows the one who does not know it
    "show_follow_payoff": {
        "steps": [("show", ("reveal", "hide", "foreshadow")), ("follow", ("isolate", "misdirect", "escalate", "reaction",
                                                                          "observe")), ("payoff", ("payoff",))],
        "use": "irony"},
    # through a witness's (or an animal's) eyes: its view, the thing, the faces around it, silence, the answer
    "pov_insert_reaction_silence_reveal": {
        "steps": [("pov", ("observe", "reveal")), ("insert", ("foreshadow", "hide")), ("reaction", ("reaction", "isolate",
                                                                                                  "misdirect")),
                  ("silence", ("observe",)), ("reveal", ("reveal", "payoff"))],
        "use": "witness"},
    # plain: where, what happens, who is alone with it, how it ends
    "establish_observe_isolate_payoff": {
        "steps": [("establish", ("orient",)), ("observe", ("observe", "connect", "foreshadow", "escalate")),
                  ("isolate", ("isolate", "misdirect")), ("payoff", ("payoff", "reveal"))],
        "use": "plain"},
}


def choose_grammar(knowledge: AudienceKnowledgePlan, focal: FocalizationPlan) -> str:
    if focal.kind == "animal" or focal.mode == "witness":
        return "pov_insert_reaction_silence_reveal"
    if knowledge.strategy == "mystery":
        return "conceal_reaction_reveal"
    if knowledge.strategy == "irony":
        return "show_follow_payoff"
    return "establish_observe_isolate_payoff"


def label(shots: list[CameraShot], grammar: str) -> list[CameraShot]:
    """Walk the grammar's steps in order: a shot takes the current step if its function fits it, or moves the scene
    on to the first later step that fits. Shots that fit no step (an orienting wide, say) keep an empty step."""
    steps = GRAMMARS[grammar]["steps"]
    k, out = 0, []
    for s in shots:
        step = ""
        for j in range(k, len(steps)):
            if s.function in steps[j][1]:
                k, step = j, f"{grammar}:{steps[j][0]}"
                break
        out.append(dataclasses.replace(s, grammar_step=step))
    return out


def information_function(s: CameraShot, knowledge: AudienceKnowledgePlan) -> str:
    if s.function == "hide":
        return "withholds"
    if s.function == "misdirect":
        return "misleads"
    if s.function in ("reveal",) and knowledge.strategy != "mystery":
        return "shows_truth"
    if s.function == "payoff":
        return "confirms"
    if s.function == "orient":
        return "orients"
    if s.function == "foreshadow":
        return "hints"
    return "none"


# -- pacing ---------------------------------------------------------------------------------------------------------
def pace(shots: list[CameraShot], turn_shot: int | None) -> list[CameraShot]:
    """Staircase towards the turn: establishing shots long, the run-up shorter and shorter, a held breath just
    before it, the turn itself, then a reaction allowed to stay."""
    if turn_shot is None or not shots:
        return shots
    out = []
    for s in shots:
        d = s.shot_index - turn_shot
        if s.function == "orient":
            k = 1.25
        elif -4 <= d <= -2:
            k = 0.7 + 0.1 * (d + 4)  # 0.7, 0.8, 0.9: compressing
        elif d == -1:
            k = 1.4  # the breath before
        elif d == 0:
            k = 1.15
        elif d in (1, 2) and s.function in ("reaction", "payoff", "isolate", "observe"):
            k = 1.35  # let it land
        else:
            k = 1.0
        out.append(dataclasses.replace(s, seconds=round(max(1.0, s.seconds * k), 2)))
    return out


def turn_of(shots: list[CameraShot], knowledge: AudienceKnowledgePlan) -> int | None:
    """The shot the scene turns on: the reveal (irony), the payoff (mystery and plain)."""
    want = ("reveal",) if knowledge.strategy == "irony" else ("payoff", "reveal")
    return next((s.shot_index for s in shots if s.function in want), None)


# -- edit variants (a benchmark can force one) ------------------------------------------------------------------------
EDITS = ("tight", "hold", "reaction_first")


def re_edit(shots: list[CameraShot], edit: str) -> list[CameraShot]:
    """tight: cut as soon as the point is made. hold: stay a second longer where it lands. reaction_first: within a
    beat, the face that learns comes before the thing it learns (the audience reads it on them first)."""
    if edit not in EDITS:
        raise ValueError(f"unknown edit {edit}")
    if edit == "tight":
        shots = [dataclasses.replace(s, seconds=round(max(1.0, s.seconds * 0.7), 2)) for s in shots]
    elif edit == "hold":
        shots = [dataclasses.replace(s, seconds=s.seconds + (1.0 if s.function in ("reaction", "payoff", "reveal",
                                                                                   "isolate") else 0.0)) for s in shots]
    else:
        by_beat: dict[int, list[CameraShot]] = {}
        for s in shots:
            by_beat.setdefault(s.beat_index, []).append(s)
        shots = []
        for _, group in sorted(by_beat.items()):
            faces = [s for s in group if s.function in ("reaction", "isolate", "misdirect")]
            rest = [s for s in group if s not in faces]
            if faces and any(s.function in ("reveal", "payoff") for s in rest):
                first = [s for s in rest if s.function == "orient"]
                shots += first + faces + [s for s in rest if s not in first]
            else:
                shots += group
    return [dataclasses.replace(s, shot_index=n) for n, s in enumerate(shots)]


# -- attention --------------------------------------------------------------------------------------------------------
def plan_attention(spec: SceneSpec, shots: list[CameraShot], knowledge: AudienceKnowledgePlan,
                   focal: FocalizationPlan) -> AttentionPlan:
    """Shot by shot: the subject is the primary; whoever else is there and matters is secondary; a culprit kept back
    by a mystery is hidden. In a mystery the truth is let in once, at the end, by what the camera finds, never said."""
    culprits = {t.split(":")[0] for t in (knowledge.state.truth if knowledge.state else []) if ":" in t}
    marks, reveal_shot, how, subject = [], None, "", ""
    for s in shots:
        b = spec.beats[s.beat_index]
        ids = [p.id for p in b.participants]
        others = [i for i in ids if i != s.subject and i in spec.characters]
        hidden = next((c for c in culprits if c in ids and s.beat_index in knowledge.withheld_beats), "")
        secondary = next((o for o in others if o not in (hidden, focal.focalizer if s.relation == "subjective" else "")),
                         b.prop.id if b.prop is not None and b.prop.id != s.subject else "")
        why = ("kept out of sight: it would give the answer away" if hidden else
               f"{secondary} is there for whoever looks" if secondary else "one thing to look at")
        marks.append(AttentionMark(s.shot_index, s.subject, secondary, hidden, why))
    if knowledge.strategy == "mystery" and culprits:
        # the last shot where a culprit is physically there but not hidden: the camera lingers on them
        for m, s in zip(reversed(marks), reversed(shots)):
            b = spec.beats[s.beat_index]
            there = [p.id for p in b.participants if p.id in culprits]
            if there and not m.hidden and s.beat_index not in knowledge.withheld_beats:
                reveal_shot, subject = s.shot_index, there[0]
                how = f"the camera finds {there[0]} close by, and stays: nothing is said"
                break
    return AttentionPlan(marks, reveal_shot, how, subject)
