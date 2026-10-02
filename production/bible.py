"""Build the Bible (contracts/bible.py) of a world: who is filmed and where, in words no model has to share.

    bible = build_bible(conn)                  # a read-only connection to a world (or a path to a world.db)
    bible = build_bible(conn, cache=True)      # the same, kept under out/bible/ and read back while the world's
                                               # cast, costumes and places have not changed

Read-only on the world and deterministic: the same world gives the same Bible, with the same hash. It reads what the world
already holds, and invents nothing:
  - a person's look and voice come from their genome (appearance, voice), their clothes from the casting (the profile's
    costume), so one genome keeps one face in every world and is dressed by each;
  - a place's description comes from the white-box layout that stages it (narrative/layouts.py) and the world's own name
    for it.
What the genome or casting does not say is listed in `gaps`, not filled in.

Production code may not open or build worlds (tests/test_production.py), so a Bible is made from a connection or a path.
Making one straight from a recipe is a helper for tests and scripts: tests/provider_conformance/worlds.py.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import unicodedata
from pathlib import Path

from contracts.base import canonical_json, content_hash, from_dict, to_dict
from contracts.bible import (BIBLE_VERSION, Bible, CharacterAsset, Look, SceneAsset, VoiceDescription, check_bible,
                             finalize, verify)
from contracts.persona import CharacterGenome
from narrative.layouts import LAYOUTS, layout_ref
from narrative.scene_spec import asset_id as packet_asset_id
from narrative.spatial import template_for
from world.personas import problems as persona_problems
from world.personas import genome as load_genome
from world.profiles import profile as load_profile
from world.reader import open_world_reader

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CACHE = ROOT / "out" / "bible"

GENDER_WORDS = {"male": "男性", "female": "女性"}
# kind -> (measure word, noun), in the order a place's features are listed
FEATURE_WORDS = {"table": ("張", "桌子"), "desk": ("張", "書桌"), "chair": ("張", "椅子"), "counter": ("個", "櫃台"),
                 "sofa": ("張", "沙發"), "bed": ("張", "床"), "bench": ("張", "長椅"), "tree": ("棵", "樹"),
                 "platform": ("座", "月台"), "perch": ("個", "棲架"), "door": ("扇", "門"), "window": ("面", "窗")}


class BibleError(ValueError):
    pass


# --- the world ----------------------------------------------------------------------------------------------------------

def _open(source) -> tuple[sqlite3.Connection, bool]:
    if isinstance(source, sqlite3.Connection):
        return source, False
    if isinstance(source, (str, Path)) and Path(source).exists():
        return open_world_reader(source), True
    raise BibleError(f"a Bible is made from a world connection or the path of a world.db, not {source!r} "
                     "(from a recipe: tests/provider_conformance/worlds.py)")


def _rows(conn: sqlite3.Connection, sql: str) -> list[tuple]:
    try:
        return [tuple(r) for r in conn.execute(sql)]
    except sqlite3.OperationalError:  # a world from before that table existed
        return []


def _recipe(conn: sqlite3.Connection) -> str:
    rows = _rows(conn, "SELECT value FROM meta WHERE key = 'recipe'")
    return rows[0][0] if rows else ""


def world_key(conn: sqlite3.Connection) -> str:
    """What the Bible depends on, cheaply: the cast (genomes and profiles), the places and the layouts that stage them.
    Equal keys give equal Bibles, so a cached one can be read back without building."""
    places = _rows(conn, "SELECT id, name, tags FROM locations ORDER BY id")
    return content_hash({
        "version": BIBLE_VERSION,
        "genomes": _rows(conn, "SELECT person_id, genome_id FROM character_genomes ORDER BY person_id"),
        "profiles": _rows(conn, "SELECT person_id, profile_hash FROM character_profiles ORDER BY person_id"),
        "places": places,
        "layouts": [[p[0], layout_ref(template_for(p[0])).layout_hash] for p in places],
        "recipe": _recipe(conn)})


# --- people -------------------------------------------------------------------------------------------------------------

def _hash8(text: str) -> str:
    return hashlib.sha256(unicodedata.normalize("NFC", text).encode("utf-8")).hexdigest()[:8]


def character_asset_id(genome_id: str, costume: str) -> str:
    """genome + casting: the id moves when the genome or the costume does, and when nothing else does."""
    return f"char:{genome_id.split(':', 1)[1]}:{_hash8(costume) if costume else 'none'}"


def _look(g: CharacterGenome, gender: str, age: int) -> tuple[Look, list[str]]:
    a = g.appearance
    gaps = [f"appearance.{f} is not written" for f in ("face", "hair", "build", "presence") if not getattr(a, f)]
    if not a.marks:
        gaps.append("appearance.marks is not written")
    return Look(gender=gender, apparent_age=a.looks_age or age, face=a.face, hair=a.hair, build=a.build,
                marks=list(a.marks), presence=a.presence), gaps


def _locks(look: Look, costume: str) -> tuple[list[str], list[str]]:
    ident = []
    if look.gender:
        ident.append(f"性別：{GENDER_WORDS.get(look.gender, look.gender)}")
    if look.apparent_age:
        ident.append(f"年齡感：約{look.apparent_age}歲")
    for label, value in (("臉", look.face), ("頭髮", look.hair), ("體型", look.build)):
        if value:
            ident.append(f"{label}：{value}")
    ident += [f"特徵：{m}" for m in look.marks]
    return ident, ([costume] if costume else [])


def _sentence(look: Look, costume: str) -> str:
    parts = []
    who = GENDER_WORDS.get(look.gender, look.gender)
    if who:
        parts.append(who)
    if look.apparent_age:
        parts.append(f"看起來約{look.apparent_age}歲")
    for label, value in (("臉", look.face), ("頭髮", look.hair), ("體型", look.build)):
        if value:
            parts.append(f"{label}：{value}")
    if look.marks:
        parts.append("特徵：" + "、".join(look.marks))
    if look.presence:
        parts.append(f"神態：{look.presence}")
    if costume:
        parts.append(f"穿著：{costume}")
    return "；".join(parts) + ("。" if parts else "")


def _voice(g: CharacterGenome) -> tuple[VoiceDescription, list[str]]:
    v = g.voice
    gaps = [f"voice.{f} is not written" for f in ("timbre", "pace") if not getattr(v, f)]
    parts = [f"音色{v.timbre}" if v.timbre else "", f"語速{v.pace}" if v.pace else ""]
    text = "；".join(p for p in parts if p)
    return VoiceDescription(v.timbre, v.pace, list(v.catchphrases), text + "。" if text else ""), gaps


def _characters(conn: sqlite3.Connection) -> dict[str, CharacterAsset]:
    out: dict[str, CharacterAsset] = {}
    for (pid,) in _rows(conn, "SELECT person_id FROM character_genomes ORDER BY person_id"):
        g = load_genome(conn, pid)
        prof = load_profile(conn, pid)
        if g is None or prof is None:
            continue
        costume = prof.costume
        look, gaps = _look(g, prof.gender, prof.age)
        if not costume:
            gaps.append("casting.costume is not written")
        voice, vgaps = _voice(g)
        ident, wardrobe = _locks(look, costume)
        aid = character_asset_id(g.genome_id, costume)
        out[aid] = CharacterAsset(
            asset_id=aid, genome_id=g.genome_id, person_id=pid, lock_asset_id=packet_asset_id(pid), name=g.name,
            costume=costume, role=prof.occupation.role if prof.occupation else "", look=look,
            standard_description=_sentence(look, costume), identity_lock=ident, wardrobe_lock=wardrobe, voice=voice,
            voice_asset_id=f"voice:{g.genome_id.split(':', 1)[1]}", gaps=gaps + vgaps)
    return out


# --- places -------------------------------------------------------------------------------------------------------------

def _extent(template: str) -> list[float]:
    lay = LAYOUTS[template]
    xs, ys = [0.0], [0.0]
    for o in lay["objects"]:
        xs.append(o.position[0] + o.size[0] / 2)
        ys.append(o.position[1] + o.size[1] / 2)
    for x, y, _yaw in lay["anchors"].values():
        xs.append(x)
        ys.append(y)
    return [round(max(xs) * 2) / 2, round(max(ys) * 2) / 2]  # to the half metre: wall thickness is not the room


def _scene(location_id: str, name: str, tags: list[str]) -> SceneAsset:
    template = template_for(location_id)
    ref = layout_ref(template)
    kinds: dict[str, int] = {}
    for o in ref.objects:
        kinds[o.kind] = kinds.get(o.kind, 0) + 1
    enclosed = kinds.get("wall", 0) >= 3
    w, d = _extent(template)
    features = []
    window = next((o for o in ref.objects if o.kind == "window"), None)
    if window is not None:
        features.append(f"前牆有一面寬約{window.size[0]:g}公尺的窗")
    for kind, (measure, noun) in FEATURE_WORDS.items():
        n = kinds.get(kind, 0)
        if n and kind != "window":
            features.append(f"{n}{measure}{noun}")
    text = f"{name}：{'室內' if enclosed else '戶外'}，約{w:g}×{d:g}公尺" + (f"；{'；'.join(features)}" if features else "") + "。"
    gaps = [] if tags else ["the world gives this place no tags"]
    return SceneAsset(asset_id=f"scene:{location_id}", location_id=location_id, name=name, tags=list(tags),
                      layout_id=ref.layout_id, layout_hash=ref.layout_hash, footprint=[w, d], features=features,
                      standard_description=text, gaps=gaps)


def _scenes(conn: sqlite3.Connection) -> dict[str, SceneAsset]:
    out = {}
    for lid, name, tags in _rows(conn, "SELECT id, name, tags FROM locations ORDER BY id"):
        s = _scene(lid, name, json.loads(tags or "[]"))
        out[s.asset_id] = s
    return out


# --- the Bible ----------------------------------------------------------------------------------------------------------

def _banned(conn: sqlite3.Connection, extra) -> list[str]:
    """The publish gate's list: what the caller gives, and the real names any genome of this world still carries."""
    names = set(extra or ())
    for (pid,) in _rows(conn, "SELECT person_id FROM character_genomes"):
        g = load_genome(conn, pid)
        if g is not None:
            names |= set(g.origin.real_names)
    return sorted(n for n in names if n)


def build_bible(source, *, banned=(), cache=None) -> Bible:
    """The Bible of a world. `source` is a (read-only) connection or the path of a world.db.

    banned  names that must not appear anywhere in it (a real person's name and aliases); a genome's own `real_names`
            are always added. A world that holds a real person who was not fictionalized is refused.
    cache   True for out/bible/, or a directory: the Bible is kept there under the world's key, and read back (and
            checked against its own hash) while the cast, costumes and places are unchanged.
    """
    conn, opened = _open(source)
    try:
        bad = persona_problems(conn)
        if bad:
            raise BibleError("this world holds real people and is a private branch: " + "; ".join(bad))
        folder = DEFAULT_CACHE if cache is True else Path(cache) if cache else None
        key = world_key(conn)
        path = folder / f"bible_{key.split(':', 1)[1][:16]}.json" if folder else None
        ban = _banned(conn, banned)
        if path is not None and path.exists():
            hit = load_bible(path)
            if hit is not None and not check_bible(hit, ban):
                return hit
        characters, scenes = _characters(conn), _scenes(conn)
        gaps = [] if characters else ["this world has no genomes, so no character is described"]
        bible = finalize(Bible(version=BIBLE_VERSION, world=_recipe(conn), characters=characters, scenes=scenes, gaps=gaps))
        problems = check_bible(bible, ban)
        if problems:
            raise BibleError("the Bible breaks its own rules: " + "; ".join(problems))
        if path is not None:
            save_bible(bible, path)
        return bible
    finally:
        if opened:
            conn.close()


def save_bible(bible: Bible, path: Path | str) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_json(to_dict(bible)), encoding="utf-8", newline="\n")
    return path


def load_bible(path: Path | str) -> Bible | None:
    """A saved Bible, or None when the file is missing, unreadable, of another version or does not match its hash."""
    try:
        b = from_dict(Bible, json.loads(Path(path).read_text(encoding="utf-8")))
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return b if b.version == BIBLE_VERSION and verify(b) else None
