"""How one person of a sect addresses another. A read model: it never writes the world.

Only a jianghu recipe (meta key ``recipe`` contains ``jianghu``). Two people share a term only when
``affiliations`` puts them in the same faction. The listener's ``role`` is the sect head (``leader`` when a
faction is founded, ``master`` in the jianghu content) and the term is 掌門; otherwise age and gender from
``world.profiles.profile``: an older listener is 師兄／師姐, a younger or same-aged one is 師弟／師妹.
"""
from __future__ import annotations

import sqlite3

# factions.py writes "leader" when someone founds a group; jianghu_v1's cast stores the head as "master".
HEAD_ROLES = frozenset({"leader", "master"})
_SENIOR = {"male": "師兄", "female": "師姐"}
_JUNIOR = {"male": "師弟", "female": "師妹"}


def address(conn: sqlite3.Connection, speaker_id: str, listener_id: str) -> str | None:
    """師兄、師姐、師弟、師妹 or 掌門, or None when this pair would not use one."""
    if conn is None or not speaker_id or not listener_id or speaker_id == listener_id:
        return None
    row = conn.execute("SELECT value FROM meta WHERE key = 'recipe'").fetchone()
    if row is None or "jianghu" not in str(row[0]):
        return None
    rows = {r["person_id"]: r for r in conn.execute(
        "SELECT person_id, faction_id, role FROM affiliations WHERE person_id IN (?, ?)",
        (speaker_id, listener_id))}
    speaker, listener = rows.get(speaker_id), rows.get(listener_id)
    faction = (speaker["faction_id"] or "") if speaker is not None else ""
    if not faction or listener is None or (listener["faction_id"] or "") != faction:
        return None
    if (listener["role"] or "") in HEAD_ROLES:
        return "掌門"
    from world.profiles import profile
    mine, theirs = profile(conn, speaker_id), profile(conn, listener_id)
    if mine is None or theirs is None:
        return None
    table = _SENIOR if theirs.age > mine.age else _JUNIOR
    return table.get(theirs.gender)
