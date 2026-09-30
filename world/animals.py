"""Animals: perceivers without language. A dog lives in the world as a person row whose persona traits say
`species`, but it never holds a claim. It does not know that "Jun took the wallet"; it knows a shiny small thing,
lifted, and Jun's smell. Its senses beat a person's (it notices quiet things, and the dark does not blind its nose).

Animals take part in the world through a few acts of their own (agent/animal.py): follow someone they like, carry
something off in their mouth and drop it elsewhere, bark at someone who frightens them. What they sense is stored as
claimless memories (percepts) and as their feelings toward people, so a story can be told through their eyes
(the director's animal focalization) without the animal ever knowing what the humans know.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import replace

from world.events import EventSpec, MemorySpec
from world.helpers import RelDeltas
from world.rng import rng as make_rng

SENSE_P = {"loud": 1.0, "normal": 0.8, "quiet": 0.6}  # a dog hears and smells more than people notice
LOUD = ("accuse", "confront", "bark", "parrot_speaks")
QUIET = ("take", "tell", "lend", "misplace")
SHINY = ("ring", "watch", "key", "phone", "wallet")
# what an animal can make of each kind of event, in its own terms (no words, no ownership, no lies)
PERCEPT = {
    "take": "有人撿起了{thing}，帶著{actor}的氣味",
    "steal": "{actor}很快地抓走了{thing}",
    "misplace": "{actor}走了，留下了{thing}",
    "find": "{actor}撿起了{thing}，很高興",
    "give": "{thing}從{actor}的手到了{target}的手",
    "talk:warm": "{actor}溫柔的聲音",
    "talk:hostile": "{actor}在大聲吼",
    "talk:cold": "{actor}的聲音很冷",
    "accuse": "大聲的爭吵，{actor}很生氣",
    "confront": "大聲的爭吵，{actor}很生氣",
    "parrot_speaks": "那隻鳥又在叫",
    "eat": "食物的味道",
    "lend": "{actor}把東西塞給了{target}",
}
# its own acts, as it would feel them: no names, no ownership, only the thing and the doing
OWN_PERCEPT = {
    "take": "叼起了{thing}，上面有{owner}的氣味",
    "misplace": "把{thing}放下了",
    "steal": "叼起了{thing}，上面有{owner}的氣味",
}


def species(conn: sqlite3.Connection, pid: str) -> str:
    row = conn.execute("SELECT traits FROM personas WHERE person_id = ?", (pid,)).fetchone()
    return json.loads(row[0]).get("species", "human") if row else "human"


def is_animal(conn: sqlite3.Connection, pid: str) -> bool:
    return species(conn, pid) != "human"


def animal_ids(conn: sqlite3.Connection) -> set[str]:
    return {r[0] for r in conn.execute("SELECT person_id FROM personas WHERE json_extract(traits, '$.species') IS NOT NULL "
                                       "AND json_extract(traits, '$.species') <> 'human'")}


def _thing(conn: sqlite3.Connection, oid: str | None) -> str:
    if not oid:
        return "一樣東西"
    row = conn.execute("SELECT id, tags FROM objects WHERE id = ?", (oid,)).fetchone()
    if row is None:
        return "一樣東西"
    tags = json.loads(row["tags"])
    if any(s in oid for s in SHINY):
        return "亮亮的小東西"
    if "paper" in tags or "diary" in oid:
        return "有墨水味的紙"
    if "parcel" in tags:
        return "一個盒子"
    return "一樣東西"


def _loudness(spec: EventSpec) -> str:
    if spec.type in LOUD or spec.truth.get("tone") == "hostile":
        return "loud"
    return "quiet" if spec.type in QUIET else "normal"


def with_senses(conn: sqlite3.Connection, spec: EventSpec) -> EventSpec:
    """Before an event commits: animals present sense it (percepts, feelings), and never keep a human claim."""
    here = spec.location_id
    animals = animal_ids(conn)
    if not animals:
        return spec
    # an animal in the event never holds a claim about it: strip claim memories meant for animals
    memories = [m for m in spec.memories if not (m.observer_id in animals and m.claim is not None)]
    if here is None:
        return replace(spec, memories=memories)
    names = {r[0]: r[1] for r in conn.execute("SELECT id, name FROM people")}
    principals = {p for p, role in spec.participants if role in ("actor", "target", "victim")}
    t = spec.truth
    key = f"{spec.type}:{t.get('tone')}" if spec.type == "talk" else spec.type
    template = PERCEPT.get(key)
    seed = conn.execute("SELECT value FROM meta WHERE key = 'world_seed'").fetchone()[0]
    participants = list(spec.participants)
    deltas = RelDeltas()
    for a in sorted(animals):
        row = conn.execute("SELECT location_id, status FROM people WHERE id = ?", (a,)).fetchone()
        if row is None or row["status"] == "inactive" or row["location_id"] != here:
            continue
        mine = a == t.get("actor")
        if not mine and make_rng(seed, spec.timestamp, f"sense:{spec.type}:{a}", "sense").random() >= SENSE_P[_loudness(spec)]:
            continue
        own = OWN_PERCEPT.get(spec.type) if mine else None
        if own:
            text = own.format(thing=_thing(conn, t.get("object")),
                              owner=names.get(t.get("rightful_owner") or t.get("victim") or t.get("owner"), "別人"))
            memories.append(MemorySpec(a, text, 1.0))
        elif template:
            text = template.format(thing=_thing(conn, t.get("object")), actor=names.get(t.get("actor"), "有人"),
                                   target=names.get(t.get("target") or t.get("victim"), "另一個人"))
            memories.append(MemorySpec(a, text, 0.9))
        if not mine and a not in principals:
            participants.append((a, "sensed"))
        actor = t.get("actor")
        if actor and actor != a and actor in names:
            if spec.type == "talk" and t.get("tone") == "warm":
                deltas.add(a, actor, "affection", 0.03)
            elif _loudness(spec) == "loud":
                deltas.add(a, actor, "fear", 0.05)
                deltas.add(a, actor, "trust", -0.03)
    return replace(spec, memories=memories, participants=participants, changes=list(spec.changes) + deltas.changes(conn))


def keeper(conn: sqlite3.Connection, animal: str) -> str | None:
    """The person an animal has attached itself to (it follows them, they feed it), if any."""
    row = conn.execute("SELECT r.target_id FROM relationships r JOIN personas p ON p.person_id = r.target_id "
                       "WHERE r.actor_id = ? AND r.affection >= 0.3 AND COALESCE(json_extract(p.traits, '$.species'), 'human') = 'human' "
                       "ORDER BY r.affection DESC, r.target_id LIMIT 1", (animal,)).fetchone()
    return row[0] if row else None
