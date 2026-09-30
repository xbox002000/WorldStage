"""Shot economy: every shot must change what the audience knows, what a character feels, a relation, the state of a
thing, or what is seen being done. A shot that only changes the angle is not a reason to cut.

Measured before this existed, on the 30-second benchmark: the dog's-eyes version ran 47 s with 16 shots, ten of them a
handheld close shot of the same wallet; the mystery version had four identical hands-and-wallet inserts in a row.

Three passes, all deterministic:
1. cancelling beats: two consecutive beats that undo each other (the dog drops the wallet, then picks it up again)
   leave the world as it was, and if everything they would tell is told again later in the scene they are left
   out. The later occurrence is kept, so the thing ends up where the audience last saw it go.
2. value: each shot is scored on five gains against what the audience has already seen, and a redundancy against the
   shot before it: information (a fact not yet shown), emotion (a face in a feeling it has not been seen in),
   relation (a new place, two people in frame together for the first time, a change of whose eyes), state (a thing
   changes hands in view) and action (someone seen doing something not seen before).
3. the rule: a shot with no gain is cut; a shot that looks like the one before it (same subject, framing, side and
   eyes) in the same beat is merged into it. The scene's first shot and the shot it turns on always stay.
"""
from __future__ import annotations

import dataclasses
import sqlite3

from contracts.director import AudienceKnowledgePlan, CameraShot, DroppedShot, FocalizationPlan, ShotValue
from contracts.scene_spec import Beat, SceneSpec

FACE = ("MCU", "CU", "ECU", "MS")
FAMILY = {"take": "take", "find": "take", "steal": "take", "lose": "lose", "misplace": "lose", "give": "give"}


def _facts(conn: sqlite3.Connection, beat: Beat) -> list[tuple[str, str, str]]:
    """What the beat makes true (claim triples, acts folded into families) and what someone comes to believe in it."""
    rows = conn.execute("SELECT c.subject, c.act, c.object FROM event_claims ec JOIN claims c USING (claim_id) "
                        "WHERE ec.event_id = ? AND ec.role = 'truth' ORDER BY c.claim_id", (beat.event_id,)).fetchall()
    out = []
    for s, a, o in rows:
        f = (s, FAMILY.get(a, a), o)
        if f not in out:
            out.append(f)
    suspect = next((p.id for p in beat.participants if p.role == "suspect"), None)
    actor = next((p.id for p in beat.participants if p.role == "actor"), None)
    if suspect and actor:
        out.append((actor, "suspects", suspect))
    return out


def _holders(conn: sqlite3.Connection, beat: Beat) -> dict[str, tuple[str, str]]:
    """object -> (holder before, holder after) for the things that change hands in this beat."""
    out = {}
    for ent, old, new in conn.execute("SELECT entity_id, old_value, new_value FROM event_deltas WHERE event_id = ? AND "
                                      "entity_type = 'object' AND field = 'owner_person_id' ORDER BY delta_id",
                                      (beat.event_id,)):
        before = out.get(ent, (old or "", ""))[0]
        out[ent] = (before, new or "")
    return out


def _emotion(conn: sqlite3.Connection, who: str, event_id: int) -> str:
    row = conn.execute("SELECT d.new_value FROM event_deltas d WHERE d.entity_type = 'person' AND d.entity_id = ? AND "
                       "d.field = 'emotion' AND d.event_id <= ? ORDER BY d.delta_id DESC LIMIT 1", (who, event_id)).fetchone()
    if row:
        return row[0] or ""
    row = conn.execute("SELECT emotion FROM people WHERE id = ?", (who,)).fetchone()
    return row[0] if row else ""


def cancelling_beats(conn: sqlite3.Connection, spec: SceneSpec) -> dict[int, str]:
    """Pairs of consecutive beats that undo each other and tell nothing that is not told again elsewhere."""
    facts = [_facts(conn, b) for b in spec.beats]
    held = [_holders(conn, b) for b in spec.beats]
    out: dict[int, str] = {}
    i = 1  # the scene's first and last beats always stay
    while i < len(spec.beats) - 2:
        a, b = spec.beats[i], spec.beats[i + 1]
        pa, pb = a.prop.id if a.prop else None, b.prop.id if b.prop else None
        actor = lambda x: next((p.id for p in x.participants if p.role == "actor"), None)  # noqa: E731
        # a witness only matters if the scene comes back to them; a passer-by who saw it once does not
        elsewhere = {p.id for j, x in enumerate(spec.beats) if j not in (i, i + 1) for p in x.participants}
        witnesses = [p.id for x in (a, b) for p in x.participants if p.role == "witness" and p.id in elsewhere]
        if pa and pa == pb and actor(a) == actor(b) and pa in held[i] and pa in held[i + 1] \
                and held[i][pa][0] == held[i + 1][pa][1] and not witnesses:
            others = {f for j, fs in enumerate(facts) if j not in (i, i + 1) and j not in out for f in fs}
            if all(f in others for f in facts[i] + facts[i + 1]):
                why = f"{a.event_type} then {b.event_type}: {pa} ends where it was, and all of it is shown again later"
                out[i] = out[i + 1] = why
                i += 2
                continue
        i += 1
    return out


def _visible_facts(shot: CameraShot, beat: Beat, facts: list[tuple[str, str, str]]) -> set[tuple[str, str, str]]:
    """The facts a shot lets the audience see: a hidden act or a thing on its own shows what happened to the thing,
    not who did it; a body shows what that body does and comes to believe."""
    if shot.function == "orient":  # where we are and who is here: the place, not yet what happens in it
        return set()
    agentless = {("?", a, o) for _s, a, o in facts if a not in ("suspects",)}
    if shot.information_function == "withholds" or shot.scale == "INSERT" or (beat.prop and shot.subject == beat.prop.id):
        return agentless
    mine = {f for f in facts if f[0] == shot.subject}
    return agentless | mine if mine else agentless


def value_shots(conn: sqlite3.Connection, spec: SceneSpec, shots: list[CameraShot], knowledge: AudienceKnowledgePlan,
                focal: FocalizationPlan, turn: int | None) -> tuple[list[CameraShot], list[ShotValue], list[DroppedShot]]:
    elided = cancelling_beats(conn, spec)
    facts = [_facts(conn, b) for b in spec.beats]
    held = [_holders(conn, b) for b in spec.beats]
    seen_facts: set = set()
    seen_face: dict[str, str] = {}
    seen_pairs: set = set()
    seen_places: set = set()
    seen_actions: set = set()
    state_shown: set = set()
    seen_views: set = set()
    kept: list[CameraShot] = []
    values: list[ShotValue] = []
    dropped: list[DroppedShot] = []
    last_pov = None
    for s in shots:
        b = spec.beats[s.beat_index]
        if s.beat_index in elided:
            dropped.append(DroppedShot(s.beat_index, s.function, s.subject, s.scale, s.relation, elided[s.beat_index]))
            continue
        vis = _visible_facts(s, b, facts[s.beat_index])
        info = len(vis - seen_facts) / max(1, len(vis)) if vis else 0.0
        emotion = 0.0
        if s.subject in spec.characters and s.scale in FACE and s.attention in ("face", "eyes", "body"):
            feel = _emotion(conn, s.subject, b.event_id)
            if seen_face.get(s.subject) != feel:
                emotion = 1.0
        here = [p.id for p in b.participants if p.id in spec.characters]
        relation = 0.0
        if b.location.id not in seen_places:
            relation = 1.0
        pov = _viewpoint(s, focal)
        if pov[0] != "outside" and pov not in seen_views:  # the first shot from the focalizer's eyes or height
            relation = 1.0
        elif last_pov is not None and pov != last_pov:
            relation = max(relation, 0.5)
        if s.relation in ("two_shot", "over_shoulder"):
            pair = tuple(sorted({s.subject} | ({focal.focalizer} if focal.focalizer in here else set(here[:2]))))
            if len(pair) == 2 and pair not in seen_pairs:
                relation = max(relation, 1.0)
        state = 0.0
        moved = held[s.beat_index]
        if moved and s.beat_index not in state_shown and (s.subject in moved or s.subject in here or s.scale == "INSERT"):
            state = 1.0
        act = (s.subject, b.event_type)
        action = 0.0 if act in seen_actions or s.subject not in spec.characters else 1.0
        prev = kept[-1] if kept else None
        same = prev is not None and prev.subject == s.subject and prev.scale == s.scale and prev.relation == s.relation
        redundancy = 1.0 if same and prev.beat_index == s.beat_index else 0.5 if same else 0.0
        gain = info + emotion + relation + state + action
        must = not kept or s.shot_index == turn
        if same and prev.beat_index == s.beat_index:  # the same picture again: one shot, a little longer
            merged = dataclasses.replace(prev, seconds=round(prev.seconds + min(1.5, s.seconds * 0.5), 2),
                                         reason=prev.reason if s.reason in prev.reason else f"{prev.reason}; {s.reason}")
            kept[-1] = merged
            dropped.append(DroppedShot(s.beat_index, s.function, s.subject, s.scale, s.relation,
                                       "the same picture as the shot before: merged into it"))
        elif gain <= 0 and not must:
            dropped.append(DroppedShot(s.beat_index, s.function, s.subject, s.scale, s.relation,
                                       "nothing new: no fact, feeling, relation, change of hands or action"))
            continue
        else:
            kept.append(s)
            values.append(ShotValue(len(kept) - 1, round(info, 3), emotion, relation, state, action, redundancy,
                                    round(gain - redundancy, 3), _why(info, emotion, relation, state, action, must)))
        seen_facts |= vis
        if s.subject in spec.characters and s.scale in FACE:
            seen_face[s.subject] = _emotion(conn, s.subject, b.event_id)
        seen_places.add(b.location.id)
        if s.relation in ("two_shot", "over_shoulder"):
            seen_pairs.add(tuple(sorted({s.subject} | ({focal.focalizer} if focal.focalizer in here else set(here[:2])))))
        if state:
            state_shown.add(s.beat_index)
        if s.subject in spec.characters:
            seen_actions.add(act)
        last_pov = pov
        seen_views.add(pov)
    kept = [dataclasses.replace(x, shot_index=n) for n, x in enumerate(kept)]
    return kept, values, dropped


def _viewpoint(s: CameraShot, focal: FocalizationPlan) -> tuple[str, str]:
    """Whose viewpoint a shot takes: through the focalizer's eyes, at an animal focalizer's height, or outside.
    The first shot from a viewpoint tells the audience through whom the scene is told: that is a new relation."""
    if s.relation == "subjective":
        return "eyes", focal.focalizer
    if s.angle == "ground" and focal.kind == "animal":
        return "height", focal.focalizer
    return "outside", ""


def _why(info, emotion, relation, state, action, must) -> str:
    parts = [n for n, v in (("new information", info), ("a feeling not yet seen", emotion),
                            ("a new place or relation", relation), ("a thing changes hands", state),
                            ("an action not yet seen", action)) if v > 0]
    return ", ".join(parts) or ("the shot the scene opens or turns on" if must else "")


def cut_reason(v: ShotValue, shot: CameraShot) -> str:
    """Why cut to this shot, from what it adds. Changing the angle is never a reason."""
    if v.information > 0:
        return "hide" if shot.information_function == "withholds" else "information_reveal"
    if v.emotion > 0:
        return "reaction"
    if v.relation >= 1.0:
        return "new_relation"
    if v.relation > 0:
        return "pov_change"
    if v.state > 0 or v.action > 0:
        return "action"
    return "causal_continuity"
