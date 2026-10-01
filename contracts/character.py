"""CharacterProfile: who a person is before the world starts — identity, what they like and hate, what they value,
their habits, how they deal with people, the question their life is about. Content, in JSON, one roster per content
pack (world/content/profiles/<content>.json), validated against this contract and stored in the world itself.

Change speeds (the brief's four layers):
  immutable  id, name, age at the start, background, temperament (in personas.traits)
  stable     interests, dislikes, values, habits, social style, core   -> the profile, never rewritten
  adaptive   trust, fears, tastes that fade, goals, self-model          -> world_vars / goals, moved by events
  dynamic    emotion, energy, hunger, stress                             -> people row / world_vars
A profile never changes after the world starts. What life changes is kept as adaptive state that overlays it.

Nothing here is genre-specific: topics are the content pack's own vocabulary, an occupation names the domain pack
that runs it and the words that domain should use ("work" is 練功 in a sect, 上班 in a town).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from contracts.base import hash_without

CHARACTER_VERSION = 1

# when a habit shows (the rule agent and the stage read these)
HabitWhen = Literal["morning", "after_work", "evening", "at_meal", "alone", "stressed", "anxious", "angry", "hurt",
                    "happy", "lonely", "bored"]
ConflictStyle = Literal["avoid", "bottle_up", "confront", "sulk", "appease"]
# values a person holds (0..1); the psyche's own values (security, truth, belonging, revenge) start from these
VALUE_KEYS = ("truth", "loyalty", "security", "belonging", "ambition", "freedom", "family", "fairness", "revenge")


@dataclass(frozen=True)
class Habit:
    when: HabitWhen
    do: str      # a behaviour id the stage can play: iced_coffee, check_phone, tidy_desk, go_quiet, talk_a_lot ...
    label: str   # how it reads: 下班喝一杯冰咖啡


@dataclass(frozen=True)
class Occupation:
    domain: str = "work"                 # the domain pack that runs it (world/domains)
    role: str = ""                       # 業務, 大師兄, 客棧老闆娘
    place: str = ""                      # location id where it is done
    superior: str = ""                   # a person id, or an offstage name (主管)
    duty: str = "work"                   # the routine action that is this job (work; train, in a sect)
    words: dict[str, str] = field(default_factory=dict)  # the domain's words in this world: {"quit": "離開師門", ...}


@dataclass(frozen=True)
class SocialStyle:
    strangers: str = ""                  # 保守, 熱情
    friends: str = ""                    # 話多
    intimate: str = ""                   # 敏感
    conflict: ConflictStyle = "bottle_up"


@dataclass(frozen=True)
class InnerCore:
    """The question a life is about. A writer's tool: read by the Dramaturgy analysis and a character's own prompt."""

    want: str = ""
    fear: str = ""
    wound: str = ""
    false_belief: str = ""
    need: str = ""
    life_question: str = ""


@dataclass(frozen=True)
class CharacterProfile:
    id: str
    name: str
    age: int
    gender: str = ""
    background: dict[str, str] = field(default_factory=dict)  # birthplace, family, education ... (labels)
    occupation: Occupation | None = None
    interests: dict[str, float] = field(default_factory=dict)  # topic id -> 0..1
    dislikes: dict[str, float] = field(default_factory=dict)   # topic id -> 0..1
    values: dict[str, float] = field(default_factory=dict)     # VALUE_KEYS -> 0..1
    habits: list[Habit] = field(default_factory=list)
    social: SocialStyle = field(default_factory=SocialStyle)
    core: InnerCore = field(default_factory=InnerCore)
    life_goal: str = ""
    season_goal: str = ""
    version: int = CHARACTER_VERSION

    def hash(self) -> str:
        return hash_without(self)


@dataclass(frozen=True)
class Casting:
    """The part a person plays in one world, which is not who they are: their job there (or none) and what they are
    after this season. A cast moved to another world keeps everything else of their profile."""

    occupation: Occupation | None = None
    season_goal: str = ""


@dataclass(frozen=True)
class CharacterRoster:
    """A content pack's cast: the topics people can like or hate (id -> label), and everyone's profile.

    A roster can be based on another one (`based_on`): the same people, with only their casting in this world
    (`casting`) and the world's words for the same topics (`topic_words`: 咖啡 -> 茶). Who they are does not change.
    """

    content: str
    topics: dict[str, str]
    people: list[CharacterProfile] = field(default_factory=list)
    based_on: str = ""
    casting: dict[str, Casting] = field(default_factory=dict)
    topic_words: dict[str, str] = field(default_factory=dict)
    version: int = CHARACTER_VERSION

    def hash(self) -> str:
        return hash_without(self)


def check_roster(r: CharacterRoster) -> list[str]:
    """What is wrong with a roster (empty when it is fine): unknown topics or values, bad weights, duplicates."""
    bad = []
    seen = set()
    for p in r.people:
        if p.id in seen:
            bad.append(f"{p.id}: listed twice")
        seen.add(p.id)
        for kind, table in (("interest", p.interests), ("dislike", p.dislikes)):
            for t, w in table.items():
                if t not in r.topics:
                    bad.append(f"{p.id}: {kind} {t!r} is not a topic of {r.content}")
                if not 0.0 <= w <= 1.0:
                    bad.append(f"{p.id}: {kind} {t} weight {w} is outside 0..1")
        for k, v in p.values.items():
            if k not in VALUE_KEYS:
                bad.append(f"{p.id}: unknown value {k!r}")
            if not 0.0 <= v <= 1.0:
                bad.append(f"{p.id}: value {k} {v} is outside 0..1")
        both = set(p.interests) & set(p.dislikes)
        if both:
            bad.append(f"{p.id}: likes and dislikes {sorted(both)}")
    return bad
