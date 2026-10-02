"""Into the packet: an EpisodePlan's A story, B story and ordinary moment become the shots of one ProductionPacket.

The planner (narrative/episode_planner.py, `Options(ab_story=True)`) shapes an episode of three kinds of scene: the A story, a B story of
other people that moved in the same days, and an ordinary moment (texture) to measure the peak from. Until now those were only in
`episode_plan.json` and the control room; a packet was one story's scenes. This module composes the packet from the plan:

    plan beats (filmed ones, in the plan's order) -> one arc -> SceneSpec -> DirectorPlan (the beat's intent is added to its
    functions) -> ProductionPacket                                           + an EpisodePacketMap beside it

* The packet is compiled by the same code as ever (narrative/compiler.py is not touched), so a packet made without a plan is byte for byte
  what it was. What the packet cannot say about a shot (which plan beat, which story line) is in the map (contracts/episode_packet.py),
  named by the packet's hash.
* Every shot's `function` is one word of the closed `ShotIntent` vocabulary (contracts/episode_plan.py); nothing here writes a model's
  words ("cinematic, 8k"): a provider's compiler translates an intent into its own prompt or controls.
* Length: there was no budget for an episode's length (an episode was as long as its scenes). With more scenes there has to be one:
  `BODY_SECONDS_BUDGET`, the seconds of the shots. When the composed episode is over it, **texture is cut first, then the B story's
  earlier scene, then the rest of the B story; the A story is never cut** (if the A story alone is over, the map says `over_budget`).
  A cut is made by planning the episode again without those scenes, so the plan's curve and breath stay true to what is filmed.

The world is read only: nothing here writes it.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass

from contracts.episode_packet import (EPISODE_PACKET_VERSION, BeatCoverage, EpisodePacketMap, ShotBeat, TrimmedScenes, finalize)
from contracts.episode_plan import INTENTS, EpisodePlan
from contracts.packet import ProductionPacket
from contracts.stylepack import SUSPENSE_V1, StylePack
from narrative import episode_planner as EP
from narrative.arcs import Arc, load_events

# The seconds of an episode's shots (the title card, its recap and the ending are the style's and are not counted). There was no length
# budget before (an episode was as long as its scenes), so this one is anchored to what is filmed today and not to what the A/B episode
# turns out to be: the longest single-story packet of 8 seeds x 14 days was 29 s (the thread director's pick) and 30 s (the planner's).
# An A/B episode may be as long as the longest of those, never longer. (docs/episode_planner.md, "Into the packet".)
BODY_SECONDS_BUDGET = 30.0


@dataclass(frozen=True)
class Composition:
    plan: EpisodePlan                 # what is filmed (after trimming)
    source_plan: EpisodePlan          # what the planner made before anything was cut
    arc: Arc                          # the filmed beats' events, in the plan's order (the SceneSpec is built from this)
    intents: dict[int, list[str]]     # event id -> what the plan wants of it (handed to the director)
    trimmed: list[TrimmedScenes]
    body_seconds: float
    budget: float
    over_budget: bool


def filmed_beats(plan: EpisodePlan) -> list:
    return [b for b in plan.beats if b.shoot]


def intents_for(plan: EpisodePlan) -> dict[int, list[str]]:
    """What the plan wants of each event it films: every filmed beat's intent, a reaction beat's after the beat it reacts to (the
    first version of the daily job kept only the last one of an event with two beats)."""
    out: dict[int, list[str]] = {}
    for b in filmed_beats(plan):
        for i in b.event_ids:
            if b.intent not in out.setdefault(i, []):
                out[i].append(b.intent)
    return out


def arc_in_plan_order(events: dict, plan: EpisodePlan, a_arc: Arc) -> Arc | None:
    """The filmed beats' events, each once, in the plan's order; None when the plan films nothing."""
    ids: list[int] = []
    for b in filmed_beats(plan):
        ids += [i for i in b.event_ids if i not in ids]
    if not ids:
        return None
    return Arc(tuple(events[i] for i in ids), a_arc.peak, a_arc.kind)


def body_seconds(packet: ProductionPacket) -> float:
    return round(sum(s.duration_seconds for s in packet.shots), 3)


def compile_arc(world, arc: Arc, thread, shown, intents, style: StylePack = SUSPENSE_V1, scene_id: str = "episode",
                performance: bool = False) -> ProductionPacket:
    """The packet this arc would make: the same steps as production/pipeline.py without the recap and the runtime (neither changes a
    shot's length); `performance` adds the PerformancePlan (what the dry-run cost planner reads)."""
    from narrative.compiler import compile_packet
    from narrative.direction import plan_direction
    from narrative.performance import plan_performance
    from narrative.scene_spec import build_scene_specs
    from narrative.selector import Candidate
    spec = build_scene_specs(world, [Candidate(arc, 0.5, {"episode_planner": 1.0})], [scene_id])[0]
    direction = plan_direction(world, spec, thread, set(shown), intents=intents)
    return compile_packet(spec, style, direction=direction, performance=plan_performance(world, spec, direction) if performance else None)


def _variants(m: EP.Material):
    """The A story with less and less around it: everything, no texture, the B story's last scene only, no B story."""
    sec, tex = m.secondary, m.texture
    seen, out = set(), []
    steps = [(sec, tex), (sec, None), (dataclasses.replace(sec, events=sec.events[-1:], peak=sec.events[-1]) if sec is not None and len(sec.events) > 1 else sec, None),
             (None, None)]
    for s, t in steps:
        key = (tuple(s.ids) if s is not None else (), t.id if t is not None else None)
        if key not in seen:
            seen.add(key)
            out.append((s, t))
    return out


def compose(world, m: EP.Material, shown, day: int, situations: list[dict] | None = None, options: EP.Options = EP.AB,
            style: StylePack = SUSPENSE_V1, budget: float = BODY_SECONDS_BUDGET) -> Composition | None:
    """The episode for a day's material, within the length budget. None when the plan films nothing."""
    if m.arc is None:
        return None
    if situations is None:
        from narrative.dramaturgy import analyse
        situations = analyse(world)["situations"]
    events = load_events(world)
    chosen = first = None
    for sec, tex in _variants(m):
        plan = EP.plan_episode(world, m.arc, m.thread, shown, day, m.kind, m.payoff, m.steps, situations, options, sec, tex)
        arc = arc_in_plan_order(events, plan, m.arc)
        if arc is None:
            continue
        intents = intents_for(plan)
        seconds = body_seconds(compile_arc(world, arc, m.thread, shown, intents, style))
        cand = (plan, arc, intents, seconds)
        first = first or cand
        chosen = cand
        if seconds <= budget:
            break
    if chosen is None:
        return None
    plan, arc, intents, seconds = chosen
    source = first[0]
    kept = {i for b in filmed_beats(plan) for i in b.event_ids}
    trimmed = []
    for story, why in (("texture", "over the length budget: the ordinary moment goes first"),
                       ("B", "over the length budget: then the B story")):
        ids = sorted({i for b in filmed_beats(source) if b.story == story for i in b.event_ids if i not in kept})
        if ids:
            trimmed.append(TrimmedScenes(story, ids, why))
    return Composition(plan, source, arc, intents, trimmed, seconds, budget, seconds > budget)


def build_map(packet: ProductionPacket, comp: Composition) -> EpisodePacketMap:
    """For every shot of the packet: its beat, its story line and its intent."""
    by_event: dict[int, list] = {}
    for b in filmed_beats(comp.plan):
        for i in b.event_ids:
            by_event.setdefault(i, []).append(b)
    rows: list[ShotBeat] = []
    for n, s in enumerate(packet.shots):
        beats = by_event.get(s.event_id)
        if not beats:
            raise ValueError(f"shot {s.shot_id} shows event {s.event_id}, which no filmed beat of the plan owns")
        primary = next((b for b in beats if not b.derived), beats[0])
        derived = next((b for b in beats if b.derived), None)
        b = derived if derived is not None and s.function == derived.intent != primary.intent else primary
        rows.append(ShotBeat(s.shot_id, n, b.index, b.story, s.function, s.event_id, b.derived))
    count = {}
    for r in rows:
        count[r.beat_index] = count.get(r.beat_index, 0) + 1
    beats = [BeatCoverage(b.index, b.story, b.intent, b.event_ids[0], count.get(b.index, 0),
                          "" if count.get(b.index, 0) else "the director's shot economy kept no shot of it")
             for b in filmed_beats(comp.plan)]
    return finalize(EpisodePacketMap(EPISODE_PACKET_VERSION, packet.packet_hash, comp.plan.plan_hash, comp.source_plan.plan_hash, rows,
                                     beats, comp.trimmed, body_seconds(packet), comp.budget, comp.over_budget))


def check_map(packet: ProductionPacket, m: EpisodePacketMap) -> list[str]:
    """What is wrong with a map beside its packet (empty: nothing). Used by QA and the tests."""
    bad = []
    if m.packet_hash != packet.packet_hash:
        bad.append("the map is for another packet")
    if [r.shot_id for r in m.shots] != [s.shot_id for s in packet.shots]:
        bad.append("the map's shots are not the packet's")
    for r, s in zip(m.shots, packet.shots):
        if r.intent != s.function or r.event_id != s.event_id:
            bad.append(f"{r.shot_id}: the map says {r.intent}/{r.event_id}, the packet {s.function}/{s.event_id}")
        if r.intent not in INTENTS:
            bad.append(f"{r.shot_id}: {r.intent} is not a shot intent")
    order = [r.beat_index for r in m.shots]
    if order != sorted(order):
        bad.append("the shots are not in the plan's beat order")
    return bad
