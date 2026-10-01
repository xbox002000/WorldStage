"""The Persona layer in a world: genomes, the branch, the real-person rule.

Every person in a world is the instance of a CharacterGenome (contracts/persona.py), stored once with the world
(character_genomes) next to their profile. The genome of a content pack's cast is *lifted* from its roster and its
traits, so the existing casts are `original_character` genomes with nothing added; a content pack may add the rest
(decision habits, voice, knowledge, formative events, beliefs) in world/content/genomes/<content>.json.

Worlds made before this layer simply have no genomes: every reader here returns None or empty, and the gate passes.

A raw `public_person` genome is research material. A world that holds one is a private branch and cannot be filmed or
published; `fictionalize` turns it into a genome that can (another name, no identifying detail), and `scan` is the
publish gate's last look at any text for a name that must not appear.
"""
from __future__ import annotations

import dataclasses
import json
import re
import sqlite3
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path

from contracts.base import canonical_json, from_dict, to_dict
from contracts.character import CharacterProfile
from contracts.persona import (TEMPERAMENT_KEYS, Appearance, Belief, BranchOrigin, CharacterGenome, CharacterInstance,
                               DecisionHabits, Expression, Formative, KnowledgeBoundary, Origin, SimulationBranch, Voice)

EXTRAS = Path(__file__).parent / "content" / "genomes"
EXTRA_TYPES = {"origin": Origin, "decisions": DecisionHabits, "expression": Expression, "knowledge": KnowledgeBoundary,
               "appearance": Appearance, "voice": Voice}
EXTRA_PLAIN = ("charm", "attracted_to", "attachment")


class PersonaError(ValueError):
    pass


class NotPublishable(PersonaError):
    """The world holds a person who may not appear in anything published."""


@lru_cache(maxsize=None)
def _file_extras(content: str) -> dict:
    path = EXTRAS / f"{content}.json"
    return json.loads(path.read_text(encoding="utf-8")).get("people", {}) if path.exists() else {}


_override: dict | None = None


def _extras(content: str) -> dict:
    """The genome extras of a content pack; a pack made from another one (a derived roster) has its people's."""
    if _override is not None:
        return _override
    from world.profiles import load_roster
    roster = load_roster(content)
    while roster is not None and roster.based_on and not (EXTRAS / f"{content}.json").exists():
        content, roster = roster.based_on, load_roster(roster.based_on)  # a pack made from a pack has its people's
    return _file_extras(content)


@contextmanager
def extras_override(extras: dict):
    """Build worlds with these genome extras instead of the content pack's file (the counterfactual lab's branches and
    the tests': {person id: {"formative": [...], ...}}). Worlds built inside the block carry them for good."""
    global _override
    before, _override = _override, extras
    try:
        yield
    finally:
        _override = before


def lift(profile: CharacterProfile, traits: dict, persona_text: str, extras: dict | None = None) -> CharacterGenome:
    """A person's genome from what a content pack gives: their profile, temperament and one-line persona, plus the
    optional extras (decisions, expression, knowledge, formative, beliefs, origin). The job and the season's goal are the
    part a person plays in one world (contracts/character.py Casting): they stay in that world's profile and are not
    in the genome, so one person has the same genome in every world."""
    profile = dataclasses.replace(profile, occupation=None, season_goal="", costume="")
    g = CharacterGenome(
        name=profile.name, profile=profile, persona_text=persona_text,
        temperament={k: float(traits[k]) for k in TEMPERAMENT_KEYS if k in traits})
    changes = {}
    for key, value in (extras or {}).items():
        if key in EXTRA_TYPES:
            changes[key] = from_dict(EXTRA_TYPES[key], value)
        elif key == "formative":
            changes[key] = [from_dict(Formative, v) for v in value]
        elif key == "beliefs":
            changes[key] = [from_dict(Belief, v) for v in value]
        elif key in EXTRA_PLAIN:
            changes[key] = value
        else:
            raise PersonaError(f"{profile.id}: unknown genome field {key!r}")
    return dataclasses.replace(g, **changes) if changes else g


def _has_table(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'character_genomes'").fetchone() is not None


def store(conn: sqlite3.Connection, content: str, people: list[str]) -> int:
    """Write the genomes of the given people into a world that has no events yet (their profiles are already in)."""
    from world.profiles import profile
    if not _has_table(conn) or profile(conn, people[0]) is None:
        return 0
    extras = _extras(content)
    unknown = sorted(set(extras) - set(people))
    if unknown:
        raise PersonaError(f"{content}: genome extras for people not in the world: {unknown}")
    for pid in people:
        prof = profile(conn, pid)
        text, traits = conn.execute("SELECT text, traits FROM personas WHERE person_id = ?", (pid,)).fetchone()
        g = lift(prof, json.loads(traits), text, extras.get(pid))
        conn.execute("INSERT INTO character_genomes(person_id, genome_id, genome, source_kind) VALUES (?,?,?,?)",
                     (pid, g.genome_id, canonical_json(to_dict(g)), g.origin.kind))
    return len(people)


@lru_cache(maxsize=4096)
def _parse(text: str) -> CharacterGenome:
    return from_dict(CharacterGenome, json.loads(text))


def genome(conn: sqlite3.Connection, pid: str) -> CharacterGenome | None:
    if not _has_table(conn):
        return None
    row = conn.execute("SELECT genome FROM character_genomes WHERE person_id = ?", (pid,)).fetchone()
    return _parse(row[0]) if row else None


def instances(conn: sqlite3.Connection) -> list[CharacterInstance]:
    if not _has_table(conn):
        return []
    b = branch(conn)
    return [CharacterInstance(r[1], b.branch_id if b else "", r[0])
            for r in conn.execute("SELECT person_id, genome_id FROM character_genomes ORDER BY person_id")]


def roster_hash(conn: sqlite3.Connection) -> str:
    """The cast a branch starts from: the genome ids in person order."""
    from contracts.base import content_hash
    return content_hash([[r[0], r[1]] for r in conn.execute(
        "SELECT person_id, genome_id FROM character_genomes ORDER BY person_id")]) if _has_table(conn) else ""


def write_branch(conn: sqlite3.Connection, recipe: str, world_seed: int, forked_from: BranchOrigin | None = None,
                 model: str = "rule_agent_v1") -> SimulationBranch | None:
    """Record which run this world is (meta 'branch'). Private as soon as it holds a raw public_person genome."""
    if not _has_table(conn):
        return None
    from world.recipes import compiled
    from world.ruleset import ruleset_hash
    raw = _raw_public(conn)
    b = SimulationBranch(recipe=recipe, recipe_hash=compiled(recipe).recipe_hash, ruleset_hash=ruleset_hash(),
                         roster_hash=roster_hash(conn), seed=world_seed, model=model,
                         forked_from=forked_from or BranchOrigin(), visibility="private" if raw else "public")
    conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('branch', ?)", (canonical_json(to_dict(b)),))
    return b


def branch(conn: sqlite3.Connection) -> SimulationBranch | None:
    try:
        row = conn.execute("SELECT value FROM meta WHERE key = 'branch'").fetchone()
    except sqlite3.OperationalError:
        return None
    return from_dict(SimulationBranch, json.loads(row[0])) if row else None


def write_formative(conn: sqlite3.Connection) -> int:
    """What made each person, as background events at the start of the world: world truth that can be remembered,
    whispered about and traced. Called once, after the world's variables exist."""
    from world.events import EventSpec, MemorySpec, apply_event
    from world.psyche import shaping_changes
    if not _has_table(conn):
        return 0
    n = 0
    for pid, text in conn.execute("SELECT person_id, genome FROM character_genomes ORDER BY person_id").fetchall():
        g = _parse(text)
        home = conn.execute("SELECT location_id FROM people WHERE id = ?", (pid,)).fetchone()[0]
        for f in g.formative:
            others = [p for p in f.people if conn.execute("SELECT 1 FROM people WHERE id = ?", (p,)).fetchone()]
            changes, shaped = shaping_changes(conn, pid, f.experience, f.weight)  # what it left in them
            apply_event(conn, EventSpec(
                timestamp=0, type="backstory", trigger_type="rule", location_id=home, importance=round(0.3 + 0.4 * f.weight, 2),
                truth={"actor": pid, "formative": f.kind, "age": f.age, "text": f"{g.name}：{f.text}",
                       **({"experience": f.experience, "shaped": shaped} if shaped else {})},
                participants=[(pid, "actor")] + [(p, "other") for p in others],
                changes=changes, memories=[MemorySpec(pid, f.text, 1.0)]))
            n += 1
    return n


# --- the real-person rule ---------------------------------------------------------------------------------------------

def _raw_public(conn: sqlite3.Connection) -> list[str]:
    """People whose genome is a public_person that has not been fictionalized."""
    if not _has_table(conn):
        return []
    out = []
    for pid, text in conn.execute("SELECT person_id, genome FROM character_genomes WHERE source_kind = 'public_person' "
                                  "ORDER BY person_id").fetchall():
        if not _parse(text).origin.fictionalized:
            out.append(pid)
    return out


def problems(conn: sqlite3.Connection) -> list[str]:
    """Why this world may not be filmed or published (empty when it may)."""
    return [f"{pid}: a public_person genome that has not been fictionalized" for pid in _raw_public(conn)]


def assert_publishable(conn: sqlite3.Connection) -> None:
    bad = problems(conn)
    if bad:
        raise NotPublishable("this world holds real people and is a private branch: " + "; ".join(bad))


class FictionalizeError(PersonaError):
    pass


def fictionalize(g: CharacterGenome, *, name: str, replacements: dict[str, str] | None = None,
                 remove: list[str] | tuple[str, ...] = ()) -> tuple[CharacterGenome, list[str]]:
    """Turn a public_person genome into one that may be published, and say which names must never be seen with it.

    `name` is the new name. `replacements` swaps real words for invented ones everywhere (a company, a hometown).
    `remove` lists identifying details to drop: a list item that contains one is deleted, a text field that contains
    one is emptied. The result is checked: if the real name, an alias or a removed detail is still anywhere in it,
    nothing is returned. Returns (the new genome, the ban list: real names, aliases and removed details).
    """
    if g.origin.kind != "public_person":
        raise FictionalizeError(f"only a public_person genome is fictionalized, this one is {g.origin.kind}")
    if g.origin.fictionalized:
        raise FictionalizeError("this genome is already fictionalized")
    swaps, drop, banned = _plan(g, name, replacements, remove)
    data, _ = scrub(to_dict(g), swaps, drop)
    data["name"] = name
    data["profile"]["name"] = name
    data["origin"] = to_dict(Origin(kind="public_person", label="虛構化", fictionalized=True, derived_from=g.genome_id))
    out = from_dict(CharacterGenome, data)
    left = scan([canonical_json(to_dict(out))], banned)
    if left:
        raise FictionalizeError(f"still identifiable after fictionalizing: {left}")
    return out, banned


def _plan(g: CharacterGenome, name: str, replacements, remove) -> tuple[dict[str, str], list[str], list[str]]:
    real = [t for t in {g.name, *g.origin.real_names} if t]
    return {t: name for t in real} | dict(replacements or {}), [t for t in remove if t], sorted({*real, *[t for t in remove if t]})


def _swap(v: str, swaps: dict[str, str]) -> str:
    for old in sorted(swaps, key=len, reverse=True):
        v = re.sub(re.escape(old), lambda _m, new=swaps[old]: new, v, flags=re.IGNORECASE)  # any capitalisation
    return v


def scrub(data, swaps: dict[str, str], drop: list[str]):
    """Names swapped, identifying details dropped, in a genome's plain data. A list item or a mapping entry that holds a
    detail anywhere in it goes whole; a bare text that holds one is emptied. Returns (clean data, where each path went:
    {old path: new path, or None when dropped}): list items move up when one before them is dropped."""
    moved: dict[str, str | None] = {}

    def gives_away(v) -> bool:
        if isinstance(v, str):
            return any(t in _swap(v, swaps) for t in drop)
        if isinstance(v, list):
            return any(gives_away(x) for x in v)
        if isinstance(v, dict):
            return any(gives_away(x) for x in v.values())
        return False

    def walk(v, path: str):
        if isinstance(v, str):
            v = _swap(v, swaps)
            return "" if any(t in v for t in drop) else v
        if isinstance(v, list):
            out = []
            for i, x in enumerate(v):
                if gives_away(x):
                    moved[f"{path}[{i}]"] = None
                    continue
                moved[f"{path}[{i}]"] = f"{path}[{len(out)}]"
                out.append(walk(x, f"{path}[{len(out)}]"))
            return out
        if isinstance(v, dict):
            out = {}
            for k, x in v.items():
                key = _swap(str(k), swaps)
                here = f"{path}.{key}" if path else key
                if key == "" or any(t in key for t in drop) or (isinstance(x, str) and gives_away(x)):
                    moved[f"{path}.{k}" if path else str(k)] = None
                    continue
                moved[f"{path}.{k}" if path else str(k)] = here
                out[key] = walk(x, here)
            return out
        return v

    return walk(data, ""), moved


def fictionalize_all(g: CharacterGenome, ev, *, name: str, replacements: dict[str, str] | None = None,
                     remove: list[str] | tuple[str, ...] = ()):
    """`fictionalize` for a genome and its evidence graph together: (the new genome, its evidence, the ban list). The
    evidence follows the genome: claims about dropped items go, those about moved items move with them, and no source
    that could give the person away is kept."""
    from world.persona_evidence import fictionalize_evidence
    fake, banned = fictionalize(g, name=name, replacements=replacements, remove=remove)
    swaps, drop, _ = _plan(g, name, replacements, remove)
    _, moved = scrub(to_dict(g), swaps, drop)
    new_ev = fictionalize_evidence(ev, fake, lambda text: scrub(text, swaps, drop)[0], moved)
    left = scan([canonical_json(to_dict(new_ev))], banned)
    if left:
        raise FictionalizeError(f"the evidence still identifies the person: {left}")
    return fake, new_ev, banned


def scan(texts: list[str], banned: list[str] | tuple[str, ...]) -> list[str]:
    """The banned names and details found in any of the texts (case-insensitive); the publish gate blocks on any."""
    low = [t.casefold() for t in texts]
    return sorted({b for b in banned if b and any(b.casefold() in t for t in low)})
