"""Domain packs: the one place the core asks what actions, motives, life state and event styles exist.

The core (intent, rules, simulation, the rule agent, the runtime, the read models) names no genre and no area of life:
it asks this registry. A new genre or area of life is a module under world/domains/ listed in BUILTIN (or, for a
test or an experiment, a class passed to `register`), and its content (world/content/). Nothing else changes.
"""
from __future__ import annotations

import importlib
import sqlite3
from functools import lru_cache

from world.domains.base import ActionSpec, Domain, EventStyle

BUILTIN = {
    "martial": "world.domains.martial:Martial",
    "topics": "world.domains.topics:Topics",
    "work": "world.domains.work:Work",
    "body": "world.domains.body:Body",
}
_EXTRA: dict[str, type[Domain]] = {}


def register(cls: type[Domain]) -> type[Domain]:
    """Add a domain at run time (tests, experiments). Built-in domains are listed in BUILTIN instead, so their
    code is part of the ruleset hash."""
    _EXTRA[cls.id] = cls
    _reset()
    return cls


def unregister(domain_id: str) -> None:
    _EXTRA.pop(domain_id, None)
    _reset()


def _reset() -> None:
    all_domains.cache_clear()
    _active.cache_clear()
    from world import recipes
    recipes.reset_library()


@lru_cache(maxsize=None)
def all_domains() -> tuple[Domain, ...]:
    out = []
    for did, path in sorted(BUILTIN.items()):
        mod, _, name = path.partition(":")
        out.append(getattr(importlib.import_module(mod), name)())
    out += [cls() for _, cls in sorted(_EXTRA.items())]
    _register_acts(out)
    return tuple(out)


def _register_acts(domains: list[Domain]) -> None:
    from contracts.claim import register_act
    from world.claims import register_phrase
    from world.social import register_belief_effect
    for d in domains:
        for act, a in d.acts.items():
            register_act(act, a.family, a.object_kind, a.distortion)
            register_phrase(act, a.affirm, a.deny)
            if a.belief_effect:
                register_belief_effect(act, a.belief_effect)


def load_acts() -> None:
    """Make every domain's claim acts known (contracts/claim.py calls this the first time it meets an unknown act)."""
    all_domains()


@lru_cache(maxsize=None)
def _active(order: tuple[str, ...]) -> tuple[Domain, ...]:
    on = set(order)
    return tuple(d for d in all_domains() if d.enabled_by() & on)


def active(conn: sqlite3.Connection) -> tuple[Domain, ...]:
    """The domains this world's recipe switches on, in a fixed order."""
    from world.recipes import compiled, recipe_of
    return _active(tuple(compiled(recipe_of(conn)).order))


def action_spec(name: str) -> tuple[Domain, ActionSpec] | None:
    for d in all_domains():
        if name in d.actions:
            return d, d.actions[name]
    return None


def action_names() -> tuple[str, ...]:
    return tuple(a for d in all_domains() for a in d.actions)


def style(event_type: str) -> EventStyle | None:
    for d in all_domains():
        if event_type in d.styles:
            return d.styles[event_type]
    return None


def styles() -> dict[str, EventStyle]:
    return {k: v for d in all_domains() for k, v in d.styles.items()}


def primitives() -> list:
    return [p for d in all_domains() for p in d.primitives]


def goal_text() -> dict[str, str]:
    return {k: v for d in all_domains() for k, v in d.goal_text.items()}


def conflict_actions() -> tuple[str, ...]:
    return tuple(a.name for d in all_domains() for a in d.actions.values() if a.conflict)


__all__ = ["ActionSpec", "Domain", "EventStyle", "register", "unregister", "all_domains", "active", "action_spec",
           "action_names", "style", "styles", "primitives", "goal_text", "conflict_actions"]
