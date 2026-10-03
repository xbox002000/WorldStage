"""A cast from the character forge, living in the jianghu drama's places.

Locations, the sect (青雲門), the chief disciple's seat, the day plans, and the growth and martial
settings are the drama world's (world/content/jianghu_drama.py). The people come from a folder the
generator wrote: profiles.json, genomes.json, relations.json. Nemeses, secrets and crushes become
the world's starting state (a rivalry at init, and backstory events through apply_event).
"""
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import replace
from pathlib import Path

from contracts.base import content_hash, from_dict
from contracts.character import CharacterRoster
from contracts.claim import Claim
from contracts.persona import TEMPERAMENT_KEYS
from contracts.recipe import WorldRecipe
from world.claims import describe_claim
from world.events import Change, ClaimSpec, EventSpec, MemorySpec, apply_event
from world.recipes import load_recipe, register_recipe

_NAME = re.compile(r"^[A-Za-z0-9_-]+$")
# Archetypes who train in the sect when they are old enough to. Younger people stay at the inn.
_DISCIPLE_ARCHETYPES = frozenset({"被看輕的天才", "野心家", "毒舌"})
_GENIUS = "被看輕的天才"
_AMBITION = "野心家"
_RIVALRY = 0.62
_RESENTMENT = 0.55
_ATTRACTION = 0.48


def show_path(folder: Path) -> str:
    """A path the next build in this working directory can open again: relative when it lives under it."""
    folder = Path(folder).resolve()
    try:
        return folder.relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return folder.as_posix()


def cast_hash(folder: Path) -> str:
    """Hash of the three cast files (parsed, so key order and whitespace do not matter)."""
    folder = Path(folder)
    blob = {
        "profiles": json.loads((folder / "profiles.json").read_text(encoding="utf-8")),
        "genomes": json.loads((folder / "genomes.json").read_text(encoding="utf-8")),
        "relations": json.loads((folder / "relations.json").read_text(encoding="utf-8")),
    }
    return content_hash(blob)


def _clip(value: float) -> float:
    return round(min(1.0, max(-1.0, value)), 2)


def _jianghu():
    from world.content import jianghu_drama as drama
    return drama


class ForgedPack:
    """One cast folder, shaped as the attributes build_content_world already reads."""

    def __init__(self, folder: Path) -> None:
        self.folder = Path(folder)
        roster_raw = json.loads((self.folder / "profiles.json").read_text(encoding="utf-8"))
        genomes_raw = json.loads((self.folder / "genomes.json").read_text(encoding="utf-8"))
        relations = json.loads((self.folder / "relations.json").read_text(encoding="utf-8"))
        genomes = genomes_raw.get("people") if isinstance(genomes_raw, dict) else None
        rows = relations.get("people") if isinstance(relations, dict) else None
        if not isinstance(genomes, dict) or not isinstance(rows, list):
            raise ValueError(f"{self.folder} is missing genomes.people or relations.people")
        self.ROSTER = from_dict(CharacterRoster, roster_raw)
        self.GENOMES = genomes
        self.relations = relations
        self.CAST_DIR = show_path(self.folder)
        self.CAST_HASH = cast_hash(self.folder)
        self._rows = rows
        self._by_profile = {p.id: p for p in self.ROSTER.people}
        self._compile()

    def _compile(self) -> None:
        drama = _jianghu()
        rows = self._rows
        ids = [row["id"] for row in rows]
        unknown = [pid for pid in ids if pid not in self._by_profile]
        extra = [pid for pid in self._by_profile if pid not in ids]
        if unknown or extra or len(ids) != len(set(ids)):
            raise ValueError(f"{self.folder}: profiles and relations do not list the same people")
        ages = {pid: int(self._by_profile[pid].age) for pid in ids}
        self._ages = ages
        index_of = {pid: i for i, pid in enumerate(ids)}
        disciples = [row["id"] for row in rows if ages[row["id"]] >= 16 and row.get("archetype") in _DISCIPLE_ARCHETYPES]
        if not disciples:
            adults = [row for row in rows if ages[row["id"]] >= 16]
            adults.sort(key=lambda row: (-ages[row["id"]], index_of[row["id"]]))
            disciples = [adults[0]["id"]] if adults else []
        self._disciple_list = disciples
        self._disciples = set(disciples)
        archetype = {row["id"]: row.get("archetype", "") for row in rows}
        ambition = [pid for pid in disciples if archetype[pid] == _AMBITION]
        holder = ambition[0] if ambition else (disciples[0] if disciples else None)

        self.LOCATIONS = drama.LOCATIONS
        self.EDGES = drama.EDGES
        self.PROPS = drama.PROPS
        self.WORLD_VARS = drama.WORLD_VARS
        self.PEOPLE = []
        self.PERSONAS = {}
        self.TRAITS = {}
        self.SCHEDULES = {}
        for i, row in enumerate(rows):
            pid = row["id"]
            prof = self._by_profile[pid]
            home = "qingyun" if pid in self._disciples else "inn"
            temper = row.get("temperament") or {}
            traits = {key: float(temper.get(key, 0.5)) for key in TEMPERAMENT_KEYS}
            traits["sect"] = "qingyun" if pid in self._disciples else ""
            traits["home"] = home
            self.TRAITS[pid] = traits
            self.SCHEDULES[pid] = drama.DISCIPLE if pid in self._disciples else (drama.HOME_A if i % 2 == 0 else drama.HOME_B)
            want = prof.core.want or prof.season_goal or prof.name
            self.PERSONAS[pid] = prof.season_goal or want
            self.PEOPLE.append((pid, prof.name, want))

        members = [(pid, "disciple") for pid in disciples]
        self.FACTIONS = [("qingyun", "青雲門", None, "在江湖上保住青雲門的名聲", members)]
        self.SEATS = [("chief_disciple", "首席弟子", holder, 10, "qingyun")] if holder else [("chief_disciple", "首席弟子", None, 10, "qingyun")]

        under = [item.get("id") for item in self.relations.get("underestimated") or []]
        under_ids = set(under)
        skill: dict[str, float] = {}
        underrated: dict[str, float] = {}
        for row in rows:
            pid = row["id"]
            if archetype[pid] == _GENIUS:
                skill[pid] = 0.75
                underrated[pid] = 0.38
            elif pid in under_ids:
                skill[pid] = 0.56
                underrated[pid] = 0.28
            elif pid in self._disciples:
                skill[pid] = 0.42
            else:
                skill[pid] = 0.12
        self.SKILL = skill
        self.UNDERRATED = underrated
        self._nemesis = {frozenset((pair["a"], pair["b"])) for pair in self.relations.get("nemeses") or []}
        self._secrets = _secret_objects(self.relations.get("secrets") or [])
        self.OBJECTS = [(oid, "舊物", secret["kept_from"], 2000, ["keepsake"]) for secret, oid in self._secrets]
        self.INITIAL_GOALS = self._goals(ids, archetype)

    def EXTRA_VARS(self, pid: str) -> dict[str, float]:
        return {f"skill.{pid}": self.SKILL[pid], f"rep.{pid}": 0.4}

    def relation(self, a: str, b: str, rng) -> tuple[float, float, float]:
        """Two draws, always, then a nudge for sect-mates and a hard rivalry for a nemesis pair."""
        trust = round(rng.uniform(-0.3, 0.5), 2)
        affection = round(rng.uniform(-0.2, 0.4), 2)
        rivalry = 0.0
        if a in self._disciples and b in self._disciples:
            trust = _clip(trust + 0.15)
            affection = _clip(affection + 0.08)
        if frozenset((a, b)) in self._nemesis:
            trust = _clip(trust - 0.35)
            affection = _clip(affection - 0.40)
            rivalry = _RIVALRY
        return trust, affection, rivalry

    def _goals(self, ids: list[str], archetype: dict[str, str]) -> dict:
        goals: dict[str, tuple] = {}

        def put(pid: str, kind: str, target: str, obj: str, priority: float) -> None:
            if pid in ids and pid not in goals and (target in ids or target == ""):
                goals[pid] = (kind, target, obj, priority)

        def other(pid: str) -> str:
            if len(ids) < 2:
                return ""
            return ids[(ids.index(pid) + 1) % len(ids)]

        secret_of = {secret["holder"]: oid for secret, oid in self._secrets}
        for secret, oid in self._secrets:
            put(secret["holder"], "keep_secret", "", f"{secret['holder']}:take:{oid}", 0.8)
        nemesis_of: dict[str, str] = {}
        for pair in self.relations.get("nemeses") or []:
            nemesis_of.setdefault(pair["a"], pair["b"])
            nemesis_of.setdefault(pair["b"], pair["a"])
        for pid in ids:
            if archetype.get(pid) == _GENIUS:
                put(pid, "surpass", nemesis_of.get(pid) or other(pid), "", 0.7)
        for pair in self.relations.get("nemeses") or []:
            put(pair["a"], "outshine", pair["b"], "", 0.6)
            put(pair["b"], "outshine", pair["a"], "", 0.6)
        for crush in self.relations.get("crushes") or []:
            admirer, beloved = crush.get("from"), crush.get("to")
            if admirer in self._ages and self._ages[admirer] >= 18 and beloved in self._ages and self._ages[beloved] >= 18:
                put(admirer, "befriend", beloved, "", 0.55)
        for secret, oid in self._secrets:
            put(secret["kept_from"], "recover", "", oid, 0.6)
        for pid in ids:
            if pid in goals:
                continue
            nxt = other(pid)
            if not nxt:
                put(pid, "save", "", "600", 0.4)
            elif archetype.get(pid) in (_AMBITION, "毒舌"):
                put(pid, "outshine", nxt, "", 0.5)
            elif archetype.get(pid) == "高冷美人":
                put(pid, "save", "", "600", 0.5)
            else:
                put(pid, "befriend", nxt, "", 0.45)
        return goals

    def backstory(self, conn: sqlite3.Connection) -> None:
        """Secrets, nemeses and crushes as history. Events go through apply_event; minors get no attraction."""
        names = {row[0]: row[1] for row in conn.execute("SELECT id, name FROM people UNION ALL SELECT id, name FROM objects")}
        homes = {pid: self.TRAITS[pid]["home"] for pid in self.TRAITS}
        for secret, oid in self._secrets:
            holder, victim = secret["holder"], secret["kept_from"]
            if holder not in names or victim not in names or oid not in names:
                continue
            took, lost = Claim(holder, "take", oid), Claim(victim, "lose", oid)
            text = f"很久以前，{names[holder]}拿走了{names[victim]}的舊物。{secret.get('secret', '')}"
            apply_event(conn, EventSpec(
                timestamp=0, type="backstory", trigger_type="rule", location_id=homes.get(holder, "inn"), importance=0.6,
                truth={"kind": "secret", "actor": holder, "object": oid, "rightful_owner": victim, "text": text},
                participants=[(holder, "actor"), (victim, "victim")],
                changes=[Change("object", oid, "owner_person_id", value=holder),
                         Change("var", f"missing.{oid}", "value", delta=1.0)],
                memories=[MemorySpec(holder, describe_claim(took, names), 1.0, claim=took),
                          MemorySpec(victim, describe_claim(lost, names), 1.0, claim=lost)],
                claims=[ClaimSpec(took), ClaimSpec(lost)],
            ))
        seen = set()
        for pair in self.relations.get("nemeses") or []:
            a, b = pair["a"], pair["b"]
            key = (a, b) if a <= b else (b, a)
            if key in seen or a not in names or b not in names or a == b:
                continue
            seen.add(key)
            why = pair.get("why") or ""
            text = f"{names[a]}與{names[b]}結下宿怨。{why}"
            apply_event(conn, EventSpec(
                timestamp=0, type="backstory", trigger_type="rule", location_id=homes.get(a, "inn"), importance=0.5,
                truth={"kind": "nemesis", "actor": a, "target": b, "text": text},
                participants=[(a, "actor"), (b, "target")],
                changes=[Change("relationship", f"{a}:{b}", "resentment", delta=_RESENTMENT),
                         Change("relationship", f"{b}:{a}", "resentment", delta=_RESENTMENT)],
                memories=[MemorySpec(a, f"與{names[b]}結下宿怨", 1.0),
                          MemorySpec(b, f"與{names[a]}結下宿怨", 1.0)],
            ))
        for crush in self.relations.get("crushes") or []:
            admirer, beloved = crush.get("from"), crush.get("to")
            if admirer not in names or beloved not in names or admirer == beloved:
                continue
            if self._ages.get(admirer, 0) < 18 or self._ages.get(beloved, 0) < 18:
                continue
            note = crush.get("note") or f"{names[admirer]}心裡有{names[beloved]}"
            apply_event(conn, EventSpec(
                timestamp=0, type="backstory", trigger_type="rule", location_id=homes.get(admirer, "inn"), importance=0.4,
                truth={"kind": "crush", "actor": admirer, "target": beloved, "text": note},
                participants=[(admirer, "actor"), (beloved, "target")],
                changes=[Change("relationship", f"{admirer}:{beloved}", "attraction", delta=_ATTRACTION)],
                memories=[MemorySpec(admirer, note, 1.0)],
            ))


def _secret_objects(secrets: list) -> list[tuple[dict, str]]:
    seen: dict[str, int] = {}
    out = []
    for secret in secrets:
        holder = secret.get("holder") or ""
        n = seen.get(holder, 0)
        seen[holder] = n + 1
        oid = f"keepsake_{holder}" if n == 0 else f"keepsake_{holder}_{n}"
        out.append((secret, oid))
    return out


def load_pack(folder: Path) -> ForgedPack:
    return ForgedPack(Path(folder))


def apply_roster(conn: sqlite3.Connection, pack: ForgedPack, people: list[str]) -> dict[str, float]:
    """Write this cast's profiles and genomes, then the same domain starting state a named content pack would get."""
    from world.domains import active
    from world.personas import extras_override
    from world.personas import store as store_genomes
    from world.profiles import profile, store

    store(conn, pack.ROSTER, people)
    missing = [pid for pid in people if pid not in pack.GENOMES]
    if missing:
        raise ValueError(f"no genome for {missing}")
    genomes = {pid: pack.GENOMES[pid] for pid in people}
    with extras_override(genomes):
        store_genomes(conn, pack.ROSTER.content or "forged", people)
    out: dict[str, float] = {}
    for dom in active(conn):
        for pid in people:
            out.update(dom.initial_vars(pid, profile(conn, pid)))
    return out


def forged_recipe(name: str, folder: Path) -> WorldRecipe:
    base = load_recipe("jianghu_drama_v1")
    return replace(base, recipe_id=f"forged_{name}", title=f"角色工坊 {name}", content=show_path(Path(folder)))


def register_forged(name: str, folder: Path) -> str:
    """Register forged_<name> in this process. The base primitives match jianghu_drama_v1; content is the folder."""
    if not _NAME.fullmatch(name):
        raise ValueError(f"install name {name!r} must be ASCII letters, digits, '_' or '-'")
    folder = Path(folder)
    if not (folder / "profiles.json").is_file() or not (folder / "relations.json").is_file():
        raise ValueError(f"{folder} is not a cast folder")
    recipe = forged_recipe(name, folder)
    register_recipe(recipe)
    return recipe.recipe_id


def install_cast(name: str, cast, root: Path | None = None) -> Path:
    """Write the four cast files under root/name (default out/forge/name) and register forged_<name>."""
    if not _NAME.fullmatch(name):
        raise ValueError(f"install name {name!r} must be ASCII letters, digits, '_' or '-'")
    folder = (Path(root) if root is not None else Path("out/forge")) / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "profiles.json").write_text(cast.profiles_json, encoding="utf-8")
    (folder / "genomes.json").write_text(cast.genomes_json, encoding="utf-8")
    (folder / "relations.json").write_text(cast.relations_json, encoding="utf-8")
    (folder / "summary.md").write_text(cast.summary, encoding="utf-8")
    register_forged(name, folder)
    return folder


def identity_name(seed: int, size: int, era: str, locks) -> str:
    """A stable folder name for this seed, size, era and locks. None and {} are the same locks."""
    from world.forge import _normalize_locks
    norm = _normalize_locks(locks, int(size)) if locks else {}
    payload = {
        "era": era,
        "locks": {str(i): norm[i] for i in sorted(norm)},
        "seed": int(seed),
        "size": int(size),
    }
    short = content_hash(payload).split(":", 1)[1][:8]
    return f"{era}_{int(seed)}_{short}"


def cast_payload(cast) -> dict:
    """What the workshop page shows. Blurbs live on the cast, not in profiles.json."""
    rel = cast.relations
    people = []
    for person in cast.people:
        people.append({
            "index": person.index,
            "id": person.id,
            "name": person.name,
            "archetype": person.archetype,
            "blurb": person.blurb,
            "age": person.age,
            "gender": person.gender,
            "looks": person.looks,
            "warmth": person.warmth,
            "talkativeness": person.talkativeness,
            "romance_eligible": person.romance_eligible,
            "charm": person.charm,
            "attachment": person.attachment,
            "conflict": person.conflict,
            "temperament": dict(person.temperament),
            "values": dict(person.values),
            "attracted_to": list(person.attracted_to),
        })
    return {
        "seed": cast.seed,
        "size": cast.size,
        "era": cast.era,
        "people": people,
        "relations": {
            "nemeses": list(rel.get("nemeses") or []),
            "secrets": list(rel.get("secrets") or []),
            "crushes": list(rel.get("crushes") or []),
            "underestimated": list(rel.get("underestimated") or []),
            "not_romance": list(rel.get("not_romance") or []),
        },
    }
