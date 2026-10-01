"""Persona layer: who a person *is* (CharacterGenome), who they are in one world (CharacterInstance), and which run of
the world that is (SimulationBranch).

    source -> Persona Compiler -> Genome -> Instance (in a world) -> life (events) -> a person who has changed

  Genome    what one is born with, written once and never changed: temperament, values, tastes, habits, how they decide,
            how they speak, what they know, what made them, what they believe. It embeds the CharacterProfile
            (contracts/character.py), which stays the one view the rule agents and domain packs read.
  Instance  a genome living as a person in a world (world.db: character_genomes). The genome is not the person: two
            instances of one genome in two worlds start alike and become different people.
  Branch    one run: recipe, rules, cast and seed, plus where it was forked from. Worlds that share a genome and differ
            in branch are the counterfactual lab's raw material (phase 1B.5).

A person made from a real, public figure is a different matter from an invented one. Such a genome (`public_person`) may
only live in a private branch. To appear in anything published it is first `fictionalize`d (world/personas.py): a new
genome with another name and no identifying detail, which remembers what it was derived from but not who.

Nothing here knows a genre. Phrases such as 冒險 or 衝突 are free text that the content author or the Persona Compiler
writes in the world's own words.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from contracts.base import hash_without
from contracts.character import CharacterProfile

PERSONA_VERSION = 1

SourceKind = Literal["public_person", "historical_person", "fictional_character", "original_character", "user_created",
                     "synthetic"]
Visibility = Literal["private", "public"]
FormativeKind = Literal["childhood", "turning_point", "loss", "success", "relationship"]
BeliefKind = Literal["world", "causal", "people"]
Attachment = Literal["secure", "anxious", "avoidant"]  # how they hold on to people: calmly, clingingly, at arm's length
# the traits that make up a temperament (world/seed.py TRAITS): what the rule agents read from personas.traits
TEMPERAMENT_KEYS = ("honesty", "temper", "gossip", "generosity", "absent_minded", "curiosity")


@dataclass(frozen=True)
class Origin:
    """Where a genome came from. `real_names` is filled only on a raw public_person genome (its name and aliases: the
    publish gate's ban list) and is empty in anything that may be published."""

    kind: SourceKind = "original_character"
    label: str = "作者設定"                      # in words: 作者設定, 公開訪談整理 ...
    fictionalized: bool = False
    derived_from: str = ""                       # genome_id this was fictionalized from
    real_names: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DecisionHabits:
    """How they usually choose, in the world's own words. Read by the character agent's prompt and by the author."""

    typical_choices: list[str] = field(default_factory=list)
    risk: list[str] = field(default_factory=list)       # when they gamble, when they hold back
    conflict: list[str] = field(default_factory=list)
    people: list[str] = field(default_factory=list)     # who they open up to, who they keep away from


@dataclass(frozen=True)
class Expression:
    tone: str = ""
    vocabulary: list[str] = field(default_factory=list)  # words and phrases that sound like them
    rhythm: str = ""
    rhetoric: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class KnowledgeBoundary:
    knows: list[str] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)     # things they cannot know in any world
    learns_on_day: dict[str, int] = field(default_factory=dict)  # what they only come to know from that day on


@dataclass(frozen=True)
class Formative:
    """Something that made them. At world start it is written as a background event, so it is world truth: it can be
    remembered, whispered about and traced."""

    kind: FormativeKind
    text: str
    age: int = 0
    people: list[str] = field(default_factory=list)      # person ids who were part of it, if they are in this world
    weight: float = 0.5                                   # 0..1: how much it shaped them
    experience: str = ""                                  # what it was to them (world/psyche.py EXPERIENCES): betrayal,
                                                          # wronged, shame, kindness, hostility, failure, success; it
                                                          # leaves the same marks as living it would (psyche.SHAPING)


@dataclass(frozen=True)
class Belief:
    kind: BeliefKind
    text: str
    confidence: float = 0.5


@dataclass(frozen=True)
class Appearance:
    """How they look, for the whole of their life in any world (the clothes are casting: contracts/character.py costume).
    The renderers' character locks are made from it, so a face never changes between shots, scenes or models."""

    face: str = ""
    hair: str = ""
    build: str = ""
    marks: list[str] = field(default_factory=list)      # what makes them recognisable: a scar, glasses, a limp
    looks_age: int = 0                                   # the age they look, 0 = their own
    presence: str = ""                                   # how their charm shows: 一笑就讓人放鬆, 站著就讓人讓路


@dataclass(frozen=True)
class Voice:
    timbre: str = ""
    pace: str = ""
    catchphrases: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class CharacterGenome:
    name: str
    profile: CharacterProfile                            # the stable core, without the part they play in a world (casting)
    temperament: dict[str, float] = field(default_factory=dict)  # TEMPERAMENT_KEYS -> 0..1
    persona_text: str = ""
    origin: Origin = field(default_factory=Origin)
    decisions: DecisionHabits = field(default_factory=DecisionHabits)
    expression: Expression = field(default_factory=Expression)
    knowledge: KnowledgeBoundary = field(default_factory=KnowledgeBoundary)
    formative: list[Formative] = field(default_factory=list)
    beliefs: list[Belief] = field(default_factory=list)
    appearance: Appearance = field(default_factory=Appearance)
    voice: Voice = field(default_factory=Voice)
    charm: float = 0.5                                   # 0..1, born with it: how easily they draw others in
    attracted_to: list[str] = field(default_factory=list)  # genders (profile.gender values) they can fall for; empty = nobody
    attachment: Attachment = "secure"
    version: int = PERSONA_VERSION

    def hash(self) -> str:
        return hash_without(self)

    @property
    def genome_id(self) -> str:
        """Identity by content: the same genome has the same id in every world; any change is a different genome."""
        return "genome:" + self.hash().split(":", 1)[1][:16]


@dataclass(frozen=True)
class CharacterInstance:
    """A genome living in a world as a person. `genome_hash` is checked against the stored genome on load."""

    genome_id: str
    branch_id: str
    person_id: str


@dataclass(frozen=True)
class BranchOrigin:
    """Where a branch was forked from: another branch, at the start of a day (a world snapshot), or nowhere."""

    branch_id: str = ""
    day: int = 0
    snapshot_hash: str = ""


@dataclass(frozen=True)
class SimulationBranch:
    recipe: str
    recipe_hash: str
    ruleset_hash: str
    roster_hash: str                                     # the genomes it starts from, in person order
    seed: int
    model: str = "rule_agent_v1"                         # who decides: the rule agents, or a recorded LLM run
    forked_from: BranchOrigin = field(default_factory=BranchOrigin)
    visibility: Visibility = "public"                    # private as soon as a raw public_person genome is in it
    version: int = PERSONA_VERSION

    def hash(self) -> str:
        return hash_without(self)

    @property
    def branch_id(self) -> str:
        return "branch:" + self.hash().split(":", 1)[1][:16]


# --- the evidence graph -----------------------------------------------------------------------------------------------
# Every statement a genome makes about a person (a trait, a value, a habit, a belief, what made them) is a *claim* with its
# evidence. Claims that disagree stay, each with its own evidence: someone can lean on first principles and sometimes go
# on gut feeling. For an invented character the evidence is the author's word.

ClaimKind = Literal["stated", "inferred", "authored"]   # said outright / read between the lines / written by the author


@dataclass(frozen=True)
class EvidenceSource:
    id: str
    title: str
    locator: str = ""            # a page, a chapter, a timestamp, an address
    period: str = ""             # the time range it speaks of, in words: 2008-2012
    reliability: float = 1.0     # 0..1


@dataclass(frozen=True)
class Evidence:
    source: str                  # an EvidenceSource id
    quote: str = ""
    period: str = ""


@dataclass(frozen=True)
class PersonaClaim:
    id: str
    field: str                   # where in the genome it speaks: "temperament.temper", "beliefs[0]", "decisions.risk"
    statement: str
    kind: ClaimKind
    confidence: float = 0.5
    evidence: list[Evidence] = field(default_factory=list)
    contradicts: list[str] = field(default_factory=list)   # ids of claims it disagrees with (both stay)


@dataclass(frozen=True)
class PersonaEvidence:
    genome_id: str
    sources: list[EvidenceSource] = field(default_factory=list)
    claims: list[PersonaClaim] = field(default_factory=list)
    version: int = PERSONA_VERSION

    def hash(self) -> str:
        return hash_without(self)
