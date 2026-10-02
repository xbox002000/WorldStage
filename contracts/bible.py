"""Bible: the standing description of who and where a story is filmed with, written once per world and read by every
provider's compiler.

A video model that draws a face has to be told the same face in every shot, in every scene and by every model. The
packet's CharacterLock holds a few facts (an avatar colour, an initial); the Bible is where a real description lives, and
where a reference picture or a voice sample is kept once a provider has made one.

    CharacterAsset  keyed by genome + casting: one person looks the same wherever they are cast, and is dressed by the
                    world they are cast in (the genome's appearance and voice, the casting's costume). The key moves
                    when the genome changes or the costume does, and not otherwise.
    SceneAsset      keyed by the world's own place id: what the place is, from the white-box layout that stages it.

Everything here is *model-neutral prose and plain data*: no model words ("cinematic", "8k", a sampler or a lens), and no
real person's name. A compiler turns the structured fields into its own prompt; the standard sentence is for people and
for the providers that want a sentence. `check_bible` is the gate for both rules, and the publish gate's ban list
(world/personas.py `scan`) is applied by the same call.

Reference slots (`references`) are reserved: a provider fills them the first time it works on a world (a generated face
sheet, a sample of the voice) and the Bible is cached with them. Nothing here generates anything.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Iterable, Literal

from contracts.base import hash_without, to_dict

BIBLE_VERSION = "bible_v0.1"

ReferenceKind = Literal["face", "full_body", "expression_sheet", "voice_sample", "establishing", "plan_view"]
REFERENCE_KINDS: tuple[str, ...] = ("face", "full_body", "expression_sheet", "voice_sample", "establishing", "plan_view")

# Words that belong to a model's prompt and not to a description of a person or a place. A compiler adds what its model
# wants; upstream never writes them. Latin terms are matched as whole words, case-insensitively.
MODEL_WORDS: tuple[str, ...] = (
    "cinematic", "8k", "4k", "16k", "uhd", "hdr", "masterpiece", "best quality", "photorealistic", "hyperrealistic",
    "ultra detailed", "highly detailed", "unreal engine", "octane render", "trending on artstation", "artstation",
    "bokeh", "depth of field", "lens", "35mm", "85mm", "dslr", "midjourney", "stable diffusion", "comfyui", "sora",
    "kling", "negative prompt", "--ar", "--v")


@dataclass(frozen=True)
class ReferenceAsset:
    """A reference made by one provider for one asset (a picture or a sound), by its content hash. Empty until made."""

    kind: ReferenceKind
    provider_id: str
    path: str = ""
    sha256: str = ""
    request_hash: str = ""   # the RenderRequest that made it, so it can be found again


@dataclass(frozen=True)
class Look:
    """How a person looks, field by field (the genome's Appearance, plus what the profile knows). Empty means not written."""

    gender: str = ""
    apparent_age: int = 0
    face: str = ""
    hair: str = ""
    build: str = ""
    marks: list[str] = field(default_factory=list)
    presence: str = ""


@dataclass(frozen=True)
class VoiceDescription:
    timbre: str = ""
    pace: str = ""
    catchphrases: list[str] = field(default_factory=list)
    standard_description: str = ""


@dataclass(frozen=True)
class CharacterAsset:
    asset_id: str                    # char:<genome hex>:<costume hash>
    genome_id: str
    person_id: str                   # who they are in this world
    lock_asset_id: str               # the id the production packet's CharacterLock uses (char_<person>)
    name: str                        # a display name; never part of the standard description
    costume: str                     # what the casting dresses them in
    role: str                        # what they do in this world (the casting's occupation), for the record
    look: Look
    standard_description: str        # one model-neutral sentence: who they look like and what they wear
    identity_lock: list[str]         # facts of appearance that must not change between shots
    wardrobe_lock: list[str]
    voice: VoiceDescription
    voice_asset_id: str              # voice:<genome hex>
    references: list[ReferenceAsset] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)   # what the genome or casting does not say (reported, never invented)


@dataclass(frozen=True)
class SceneAsset:
    asset_id: str                    # scene:<place id>
    location_id: str
    name: str
    tags: list[str]
    layout_id: str                   # the white-box layout that stages it (narrative/layouts.py)
    layout_hash: str
    footprint: list[float]           # width and depth in metres, from the layout's extent
    features: list[str]              # the fixed things in it, in words: 大窗, 櫃台, 5 張桌子
    standard_description: str
    references: list[ReferenceAsset] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Bible:
    version: str
    world: str                       # the recipe the world was made from ("" when unknown)
    characters: dict[str, CharacterAsset] = field(default_factory=dict)   # by asset_id
    scenes: dict[str, SceneAsset] = field(default_factory=dict)           # by asset_id
    gaps: list[str] = field(default_factory=list)
    bible_hash: str = ""

    def hash(self) -> str:
        return hash_without(self, "bible_hash")

    def character_for(self, person_id: str) -> CharacterAsset | None:
        return next((c for c in self.characters.values() if c.person_id == person_id), None)

    def scene_for(self, location_id: str) -> SceneAsset | None:
        return self.scenes.get(f"scene:{location_id}")


def finalize(bible: Bible) -> Bible:
    import dataclasses
    return dataclasses.replace(bible, bible_hash=bible.hash())


def verify(bible: Bible) -> bool:
    return bible.bible_hash == bible.hash()


# --- the two rules: no model words, no real names ---------------------------------------------------------------------

def _strings(obj) -> Iterable[str]:
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from _strings(k)
            yield from _strings(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _strings(v)


def _model_word_pattern(word: str) -> re.Pattern:
    return re.compile(r"(?<![A-Za-z0-9])" + re.escape(word) + r"(?![A-Za-z0-9])", re.IGNORECASE)


_PATTERNS = {w: _model_word_pattern(w) for w in MODEL_WORDS}


def model_words_in(texts: Iterable[str]) -> list[str]:
    """The model-specific words found in the texts (sorted, each once)."""
    joined = "\n".join(texts)
    return sorted(w for w, p in _PATTERNS.items() if p.search(joined))


def check_bible(bible: Bible, banned: Iterable[str] = ()) -> list[str]:
    """What is wrong with a Bible (empty when it is fine): a model word anywhere in it, a banned name (the publish gate's
    list: a real person's name and aliases, from the evidence graph) anywhere in it, a hash that does not match, an
    asset filed under the wrong key, a reference of an unknown kind."""
    bad: list[str] = []
    data = to_dict(bible)
    texts = list(_strings(data))
    for w in model_words_in(texts):
        bad.append(f"model word {w!r} in a description")
    low = [t.casefold() for t in texts]
    for b in sorted({b for b in banned if b}):
        if any(b.casefold() in t for t in low):
            bad.append(f"banned name {b!r} appears in the bible")
    if bible.bible_hash and not verify(bible):
        bad.append("bible_hash does not match its content")
    for key, c in bible.characters.items():
        if key != c.asset_id:
            bad.append(f"character filed under {key!r} has asset_id {c.asset_id!r}")
        bad += _check_references(c.asset_id, c.references)
    for key, s in bible.scenes.items():
        if key != s.asset_id:
            bad.append(f"scene filed under {key!r} has asset_id {s.asset_id!r}")
        bad += _check_references(s.asset_id, s.references)
    return bad


def _check_references(owner: str, refs: list[ReferenceAsset]) -> list[str]:
    return [f"{owner}: reference of unknown kind {r.kind!r}" for r in refs if r.kind not in REFERENCE_KINDS]


# --- the schema (written next to the other contracts' schemas) ---------------------------------------------------------

def schema_text() -> str:
    from contracts.base import schema_for
    return json.dumps(schema_for(Bible), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main() -> None:
    """python -m contracts.bible   writes contracts/schemas/bible.schema.json"""
    from pathlib import Path
    out = Path(__file__).with_name("schemas") / "bible.schema.json"
    out.write_text(schema_text(), encoding="utf-8", newline="\n")
    print("wrote", out)


if __name__ == "__main__":
    main()
