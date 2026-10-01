"""Character profiles: loading a content pack's roster, writing it into a new world, and reading it back.

A roster lives in world/content/profiles/<content>.json and must satisfy contracts/character.py (check_roster).
It is copied into the world (character_profiles, content_topics) when the world is built, so a world carries who
its people are and replays without the content files. Worlds made before profiles existed simply have none: every
reader here returns None or empty, and the domains that need a profile stay quiet for that person.
"""
from __future__ import annotations

import json
import sqlite3
from functools import lru_cache
from pathlib import Path

from contracts.base import canonical_json, from_dict, to_dict
from contracts.character import CharacterProfile, CharacterRoster, check_roster

HERE = Path(__file__).parent / "content" / "profiles"


class RosterError(ValueError):
    pass


def roster_path(content: str) -> Path:
    return HERE / f"{content}.json"


@lru_cache(maxsize=None)
def load_roster(content: str) -> CharacterRoster | None:
    path = roster_path(content)
    if not path.exists():
        return None
    r = from_dict(CharacterRoster, json.loads(path.read_text(encoding="utf-8")))
    if r.based_on:
        r = _derive(r)
    bad = check_roster(r)
    if bad:
        raise RosterError(f"{path.name}: " + "; ".join(bad))
    return r


def _derive(r: CharacterRoster) -> CharacterRoster:
    """The same people in another world: their profiles unchanged except for their casting here."""
    from dataclasses import replace
    base = load_roster(r.based_on)
    if base is None:
        raise RosterError(f"{r.content}: based on {r.based_on!r}, which has no roster")
    unknown = sorted(set(r.casting) - {p.id for p in base.people})
    if unknown:
        raise RosterError(f"{r.content}: casting for people not in {r.based_on}: {unknown}")
    people = []
    for p in base.people:
        c = r.casting.get(p.id)
        if c is None and base.based_on:  # a world made from a world that was already a casting: they keep that casting
            people.append(p)
        else:
            people.append(replace(p, occupation=c.occupation, season_goal=c.season_goal or p.season_goal, costume=c.costume)
                          if c is not None else replace(p, occupation=None, costume=""))
    topics = {**base.topics, **r.topic_words, **r.topics}
    return replace(r, people=people, topics=topics)


def store(conn: sqlite3.Connection, roster: CharacterRoster | None, people: list[str]) -> int:
    """Write the profiles of the given people (and the roster's topics) into a world that has no events yet."""
    if roster is None or not _has_tables(conn):
        return 0
    by_id = {p.id: p for p in roster.people}
    missing = [p for p in people if p not in by_id]
    if missing:
        raise RosterError(f"{roster.content}: no profile for {missing}")
    for topic, label in sorted(roster.topics.items()):
        conn.execute("INSERT INTO content_topics(topic, label) VALUES (?,?)", (topic, label))
    for pid in people:
        p = by_id[pid]
        conn.execute("INSERT INTO character_profiles(person_id, profile, profile_hash) VALUES (?,?,?)",
                     (pid, canonical_json(to_dict(p)), p.hash()))
    return len(people)


def _has_tables(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'character_profiles'").fetchone() is not None


@lru_cache(maxsize=4096)
def _parse(text: str) -> CharacterProfile:
    return from_dict(CharacterProfile, json.loads(text))


def profile(conn: sqlite3.Connection, pid: str) -> CharacterProfile | None:
    if not _has_tables(conn):
        return None
    row = conn.execute("SELECT profile FROM character_profiles WHERE person_id = ?", (pid,)).fetchone()
    return _parse(row[0]) if row else None


def topics(conn: sqlite3.Connection) -> dict[str, str]:
    if not _has_tables(conn):
        return {}
    return {r[0]: r[1] for r in conn.execute("SELECT topic, label FROM content_topics ORDER BY topic")}
