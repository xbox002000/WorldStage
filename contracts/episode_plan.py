"""EpisodePlan: how a stretch of what happened is shaped into one episode (read model, never truth).

The world decides what happened; the director (narrative/direction.py) decides how one scene is filmed. Between them an episode
needs a *shape*: one question it poses, a ladder of beats that climbs and breathes, what each scene changes, where the truth reaches
the audience, and what is left open at the end. This is that shape. Every beat points at events that really happened; nothing here
adds an event, and a beat in which nothing changed is dropped (it is not filmed), not dressed up.

`ShotIntent` is the closed vocabulary the plan speaks to the camera in. It says what a shot is *for* (a face slap, a bystander's
shock, a longing glance), never how to light or lens it: each provider's compiler translates it into its own prompt or controls, and
nothing upstream ever writes model words ("cinematic, 8k").
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from contracts.base import hash_without

EPISODE_PLAN_VERSION = 1

# the rising ladder of an episode (each beat is on one rung)
Stage = Literal["daily", "anomaly", "doubt", "rising", "conflict", "choice", "irreversible", "change"]
STAGES: tuple[str, ...] = ("daily", "anomaly", "doubt", "rising", "conflict", "choice", "irreversible", "change")

# what a shot is for. The first group is the director's existing functions (contracts/director.py); the rest are the moments the
# web-novel and romance structures need.
ShotIntent = Literal["orient", "reveal", "hide", "escalate", "reaction", "payoff", "misdirect", "foreshadow", "isolate", "connect",
                     "contrast", "observe",
                     "setup", "face_slap", "bystander_shock", "longing_glance", "rival_standoff", "confession", "choice",
                     "aftermath", "next_question"]
INTENTS: tuple[str, ...] = ("orient", "reveal", "hide", "escalate", "reaction", "payoff", "misdirect", "foreshadow", "isolate", "connect",
                            "contrast", "observe", "setup", "face_slap", "bystander_shock", "longing_glance", "rival_standoff",
                            "confession", "choice", "aftermath", "next_question")

# the web-novel grammar, in order (docs/episode_planner.md)
GRAMMAR_STEPS: tuple[str, ...] = ("belittled", "hidden_growth", "gathering", "reversal", "bystanders", "next_goal")


@dataclass(frozen=True)
class SceneChecklist:
    """What the scene does, read from the world's own record of what it changed."""

    wants: dict[str, str] = field(default_factory=dict)          # person -> what they were after (their goal), where one is known
    obstructs: str = ""                                          # who stood against them, in a word
    knows: list[str] = field(default_factory=list)               # who was there to know
    audience_only: bool = False                                  # the audience is shown what nobody on screen knows
    emotion: dict[str, list[str]] = field(default_factory=dict)  # person -> [from, to]
    relationship: list[str] = field(default_factory=list)        # "a>b respect +0.35"
    state: list[str] = field(default_factory=list)               # what else changed: a seat, a skill, a goal, a thing
    leaves_question: str = ""
    changed: bool = False


@dataclass(frozen=True)
class EpisodeBeat:
    index: int
    event_ids: list[int]
    stage: Stage
    tension: float                      # 0..1
    intent: ShotIntent
    who: list[str]
    checklist: SceneChecklist
    shoot: bool                         # False: nothing changed, or nobody is on stage; it is not filmed
    reason: str
    derived: bool = False               # a reaction beat added for the same event (bystanders), not a new event


@dataclass(frozen=True)
class GrammarStep:
    step: str
    event_ids: list[int]
    present: bool                       # the world produced it (a missing step is reported, never invented)
    note: str = ""


@dataclass(frozen=True)
class EpisodePlan:
    version: int
    day: int
    kind: str                           # "payoff" (a release the audience waited for) | "inner" (somebody chose against themselves) | "thread" (a story still running)
    thread_id: str
    core_question: str
    beats: list[EpisodeBeat]
    tension_curve: list[float]          # of the beats that are filmed
    has_breath: bool                    # it climbs, drops, and climbs again (or has a quiet opening that the peak is measured from)
    inner_conflict: bool                # somebody chose against something they hold dear
    near_miss: list[int]                # event ids of a near-discovery, if the material has one
    reveal: dict                        # {"strategy": irony|mystery|plain, "beat": index or None}
    ending_question: str                # what is left open (empty: the episode closes everything, which is reported)
    grammar: list[GrammarStep] = field(default_factory=list)
    grammar_complete: bool = False
    dropped: list[int] = field(default_factory=list)   # beat indexes not filmed
    shootable: bool = True
    people: list[str] = field(default_factory=list)    # who it is about (ids), so that the next day can avoid the same pair
    plan_hash: str = ""


def finalize(plan: EpisodePlan) -> EpisodePlan:
    import dataclasses
    return dataclasses.replace(plan, plan_hash=hash_without(plan, "plan_hash"))
