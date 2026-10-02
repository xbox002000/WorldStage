"""The domain pack interface. A domain is one area of life or one genre's machinery (martial arts, work, magic, ...),
packaged so the core never names it: its actions, how the rule agent weighs them, what its events do to the rest of
the world, the life state it keeps, the goals it can give people, and how its events look and sound.

Every hook is optional and deterministic, and none may change the world except by returning events or changes that
the core applies. A domain is switched on by its recipe primitives, so a world only runs what its recipe asks for.

    class Magic(Domain):
        id = "magic"
        primitives = (P("magic", "power", "spells with costs", ["schedule"]),)
        actions = {"cast": ActionSpec("cast", validate=..., resolve=...)}
        styles = {"spell": EventStyle(caption="{who}對{t}施法", lines=("看招！",), social=True)}

See docs/architecture/domain_packs.md.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Callable

from contracts.recipe import MechanicPrimitive
from world.events import Change, EventSpec
from world.intent import Intent

Scored = list[tuple[float, "Intent | None"]]


@dataclass(frozen=True)
class ActionSpec:
    """An action a domain adds. `validate` raises WorldError when it is not allowed now; `resolve` returns its event."""

    name: str
    validate: Callable[[sqlite3.Connection, Intent, sqlite3.Row], None]
    resolve: Callable[[sqlite3.Connection, Intent, int, str], EventSpec]
    targets_person: bool = False  # the target is a person (never an animal)
    conflict: bool = False        # a clash: counts for strain and for escalation
    label: str = ""               # how the option reads to a character agent: "向{t}挑戰比武" ({t} = the target's name)
    stakes: Callable[[sqlite3.Connection, Intent], dict[str, float]] | None = None  # values it serves (+) or betrays (-)


@dataclass(frozen=True)
class ClaimAct:
    """A proposition a domain adds to the claim vocabulary (contracts/claim.py), so it can be told, believed,
    lied about and judged against world truth like any other."""

    family: str                # acts in one family are "roughly the same thing" (a PARTIAL match)
    object_kind: str           # item | person | topic | ...
    affirm: str                # "喜歡{o}"
    deny: str                  # "不喜歡{o}"
    belief_effect: float = 0.0  # trust change toward the subject for someone who comes to believe it (per confidence)
    distortion: str | None = None  # the act a distorted retelling turns it into


@dataclass(frozen=True)
class EventStyle:
    """How an event type looks and sounds, for every read model and stage. Nothing here decides anything."""

    caption: str = ""                 # God View: "{who}和{t}比武" ({who}, {t}, {o}, {p})
    lines: tuple[str, ...] = ()       # what it would sound like (narrative/lines.py)
    social: bool = False              # the actor walks up to the target and faces them (runtime)
    say: float = 0.0                  # seconds of voice (runtime); 0 = silent
    strikes: int = 0                  # blows exchanged on stage (runtime), a second each
    beat: tuple | None = None         # (actor act, target act, actor emotion, target emotion, shot, move, seconds)
    describe: str = ""                # a beat's line in a packet: "{a} 向 {b} 挑戰比武"
    functions: tuple[str, ...] = ()   # what it does in a story (narrative/direction.py): escalate, payoff, ...
    first_time: bool = False          # a first time doing it is a life milestone (narrative/observatory.py)
    heat: int = 1                     # 0 warm .. 3 a clash (narrative/scenes.py)
    opens_scene: bool = False         # starts a scene others may answer (narrative/scenes.py)
    explain: Callable[[dict, dict, str, str], str] | None = None  # (truth, names, who, other) -> why-text (world/explain.py)


def situation(kind: str, weight: float, day: int, people: list[str], why: str, question: str, events: list[int],
              build: float = 0.0, stakes: float = 0.0, until: int | None = None, lasts: int = 1) -> dict:
    """A dramatic situation found in what really happened (narrative/dramaturgy.py): its kind, when it starts and
    how long it keeps pressing (until a day, or `lasts` days), who is in it, why it is drama, the question it poses,
    the events it stands on, and a potential 0..1 from the kind's weight, how long it has been building and what is at
    stake. Domain packs return these from `situations` so the analysis sees their drama too."""
    pot = min(1.0, weight + 0.25 * min(1.0, build) + 0.2 * min(1.0, stakes))
    return {"kind": kind, "day": day, "until": until, "lasts": lasts, "people": people, "why": why, "question": question,
            "events": sorted(set(e for e in events if e)), "potential": round(pot, 2)}


def add_changes(conn: sqlite3.Connection, spec: EventSpec, extra: list[Change], memories: list | None = None,
                claims: list | None = None, truth: dict | None = None) -> EventSpec:
    """Fold a domain's consequences into an event. A field the event already changes gets one summed change
    (event_deltas holds one row per event and field): relationship deltas are summed and clamped to [-1, 1], other
    deltas summed; a set value the event already sets is kept."""
    from dataclasses import replace
    from world.helpers import clamp_delta, rel
    out = list(spec.changes)
    index = {(c.entity_type, c.entity_id, c.field): i for i, c in enumerate(out)}
    for c in extra:
        key = (c.entity_type, c.entity_id, c.field)
        if key not in index:
            index[key] = len(out)
            out.append(c)
            continue
        old = out[index[key]]
        if old.delta is None or c.delta is None:
            continue
        total = old.delta + c.delta
        if c.entity_type == "relationship":
            a, b = c.entity_id.split(":", 1)
            total = clamp_delta(rel(conn, a, b, c.field), total, -1.0, 1.0)
        out[index[key]] = replace(old, delta=round(total, 6))
    out = [c for c in out if not (c.delta is not None and c.delta == 0 and c.value is None)]
    return replace(spec, changes=out, memories=list(spec.memories) + list(memories or []),
                   claims=list(spec.claims) + list(claims or []), truth={**spec.truth, **(truth or {})})


class Domain:
    id: str = ""
    title: str = ""                                 # how the pack is named to a viewer: 工作, 話題, 武功
    primitives: tuple[MechanicPrimitive, ...] = ()  # declared here, added to the recipe library
    actions: dict[str, ActionSpec] = {}
    styles: dict[str, EventStyle] = {}              # by event type
    goal_text: dict[str, str] = {}                  # goal kinds this domain adds: "surpass": "有一天打贏{t}"
    acts: dict[str, ClaimAct] = {}                  # claim acts this domain adds: "like": ClaimAct("taste", ...)
    situation_kinds: dict[str, str] = {}            # dramatic situations it finds: "choice": "兩難的選擇"

    def enabled_by(self) -> set[str]:
        return {p.id for p in self.primitives} | set(getattr(self, "also_enabled_by", ()))

    # -- the rule agent --------------------------------------------------------------------------------------------
    def options(self, conn: sqlite3.Connection, actor: str, now: int, ctx: dict) -> Scored:
        """Choices this domain offers someone right now, scored. ctx: the actor's row, traits, need, who is here."""
        return []

    def shape(self, conn: sqlite3.Connection, actor: str, now: int, scored: Scored) -> Scored:
        """Reshape what someone is about to choose among (give a talk its topic, ...). The last word before the pick."""
        return scored

    def seize(self, conn: sqlite3.Connection, me: str, targets: list[str], now: int) -> Intent | None:
        """Something that takes the choice away (losing control): asked before anyone decides or answers. None for
        the person to decide as usual."""
        return None

    def reply_options(self, conn: sqlite3.Connection, me: str, other: str, heat: int, now: int) -> Scored:
        """Answers this domain adds when someone is answering `other` mid-exchange (agent/reply.py)."""
        return []

    def irritability(self, conn: sqlite3.Connection, pid: str, now: int) -> float:
        """How short-fused someone is right now (tired, hungry, worked up): adds to the heat of their words."""
        return 0.0

    def reticence(self, conn: sqlite3.Connection, pid: str, other: str, now: int) -> float:
        """How much `pid` leans to saying nothing when `other` has spoken to them (+: holds back, -: answers readily), as a
        score on the "say nothing" answer (agent/reply.py)."""
        return 0.0

    def solidarity(self, conn: sqlite3.Connection, a: str, b: str) -> float:
        """How much `a` takes `b` for one of their own (the same circle, the same faction): -1..1. It tilts whom a bystander
        takes the side of and how readily one believes what one is told."""
        return 0.0

    def influences(self, conn: sqlite3.Connection, pid: str, now: int) -> list[dict]:
        """What of this domain is leaning someone's choices now, for the record of a decision (agent/trace.py): a list of
        {"kind": <this domain>, ...} with plain numbers. Reads only; empty when nothing is."""
        return []

    def lean(self, conn: sqlite3.Connection, goal: sqlite3.Row, it: Intent) -> float | None:
        """How much an open goal of one of this domain's kinds pushes an option (times the goal's priority)."""
        return None

    # -- the world -------------------------------------------------------------------------------------------------
    def effects(self, conn: sqlite3.Connection, spec: EventSpec, primitives: set[str]) -> EventSpec:
        """What this domain adds to any event the rules resolved (reputation after a public shaming, ...)."""
        return spec

    def after_event(self, conn: sqlite3.Connection, event_id: int) -> list[EventSpec]:
        """Consequences nobody chooses, as further events."""
        return []

    def dawn(self, conn: sqlite3.Connection, day: int, now: int) -> list[EventSpec]:
        """The start of a day (a demand at work, ...)."""
        return []

    def scripted(self, conn: sqlite3.Connection, it: Intent, now: int) -> Intent | None:
        """A routine step about to happen: keep it, replace it, or drop it (None)."""
        return it

    def overnight(self, conn: sqlite3.Connection, pid: str, now: int) -> list[Change]:
        """Life state that moves in one's sleep: folded into the person's nightly upkeep event."""
        return []

    def nightly(self, conn: sqlite3.Connection, day: int, now: int) -> list[EventSpec]:
        """After everyone's upkeep: events of the night (a goal forms from how life is going, an offer lapses)."""
        return []

    def review_goal(self, conn: sqlite3.Connection, goal: sqlite3.Row, day: int) -> tuple[str, str] | None:
        """(new status, why) for an open goal of this domain's kinds, or None."""
        return None

    def appraise(self, conn: sqlite3.Connection, pid: str, kind: str, truth: dict) -> list[tuple[str, float]]:
        """What one of this domain's events meant to `pid` (world/psyche.py): [(experience, weight)]."""
        return []

    def initial_vars(self, pid: str, profile: dict | None) -> dict[str, float]:
        """Life state keys a person starts with."""
        return {}

    # -- read models -----------------------------------------------------------------------------------------------
    def describe(self, conn: sqlite3.Connection, pid: str) -> dict:
        """This person's life state in this domain, for the Observatory and a character's own prompt."""
        return {}

    def situations(self, conn: sqlite3.Connection, names: dict) -> list[dict]:
        """Dramatic situations in this domain's part of what happened (see `situation`). Read only."""
        return []
