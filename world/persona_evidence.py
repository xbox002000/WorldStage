"""The evidence graph (contracts/persona.py PersonaEvidence): which words of a genome rest on what.

Research and authoring data, not world truth: it is kept next to the genome (a content pack's file, or the Persona
Compiler's output), never in world.db, and no rule reads it. It answers "why do we say this person is like that?" and
lets a checker refuse a genome whose fields nobody can account for.
"""
from __future__ import annotations

import dataclasses

from contracts.persona import IMPRESSION_FIELDS, CharacterGenome, Evidence, EvidenceSource, PersonaClaim, PersonaEvidence

AUTHOR = EvidenceSource(id="author", title="作者設定")
REDACTED = EvidenceSource(id="redacted", title="整理過的公開資料")


def fields(g: CharacterGenome) -> list[str]:
    """Every filled-in statement a genome makes, as a path: temperament.temper, profile.values.truth, profile.habits[0],
    profile.core.fear, beliefs[1] ... (a list item or a mapping entry is one path each)."""
    out: list[str] = []

    def many(prefix: str, items) -> None:
        if isinstance(items, dict):
            out.extend(f"{prefix}.{k}" for k in items)
        else:
            out.extend(f"{prefix}[{i}]" for i in range(len(items)))

    p = g.profile
    if g.persona_text:
        out.append("persona_text")
    many("temperament", g.temperament)
    for attr in ("background", "interests", "dislikes", "values"):
        many(f"profile.{attr}", getattr(p, attr))
    many("profile.habits", p.habits)
    out.extend(f"profile.social.{k}" for k, v in dataclasses.asdict(p.social).items() if v)
    out.extend(f"profile.core.{k}" for k, v in dataclasses.asdict(p.core).items() if v)
    if p.life_goal:
        out.append("profile.life_goal")
    for attr in ("typical_choices", "risk", "conflict", "people"):
        many(f"decisions.{attr}", getattr(g.decisions, attr))
    out.extend(f"expression.{k}" for k in ("tone", "rhythm") if getattr(g.expression, k))
    many("expression.vocabulary", g.expression.vocabulary)
    many("expression.rhetoric", g.expression.rhetoric)
    many("knowledge.knows", g.knowledge.knows)
    many("knowledge.unknown", g.knowledge.unknown)
    many("knowledge.learns_on_day", g.knowledge.learns_on_day)
    many("formative", g.formative)
    many("beliefs", g.beliefs)
    for attr in ("face", "hair", "build", "presence"):
        if getattr(g.appearance, attr):
            out.append(f"appearance.{attr}")
    many("appearance.marks", g.appearance.marks)
    if g.appearance.looks_age:
        out.append("appearance.looks_age")
    out.extend(f"voice.{k}" for k in ("timbre", "pace") if getattr(g.voice, k))
    many("voice.catchphrases", g.voice.catchphrases)
    out.append("charm")
    out.extend(k for k in IMPRESSION_FIELDS if getattr(g, k) is not None)  # looks, warmth, talkativeness: when set
    many("attracted_to", g.attracted_to)
    out.append("attachment")
    return out


def _covers(claim_field: str, path: str) -> bool:
    """A claim speaks for a path if it names it, or a whole group that contains it (temperament covers temperament.temper)."""
    return path == claim_field or path.startswith(claim_field + ".") or path.startswith(claim_field + "[")


def authored(g: CharacterGenome) -> PersonaEvidence:
    """The evidence of an invented character: the author's word, for every field."""
    claims = [PersonaClaim(id=f"a{i}", field=path, statement=path, kind="authored", confidence=1.0,
                           evidence=[Evidence(source=AUTHOR.id, quote="作者設定")]) for i, path in enumerate(fields(g))]
    return PersonaEvidence(genome_id=g.genome_id, sources=[AUTHOR], claims=claims)


def uncovered(g: CharacterGenome, ev: PersonaEvidence) -> list[str]:
    """The fields of the genome that no claim speaks for."""
    return [p for p in fields(g) if not any(_covers(c.field, p) for c in ev.claims)]


def check(g: CharacterGenome, ev: PersonaEvidence, *, complete: bool = True) -> list[str]:
    """What is wrong with an evidence graph (empty when it is fine): wrong genome, duplicate ids, bad confidence, a
    claim with nothing behind it, an unknown source, a contradiction with a claim that is not there, a claim about a field
    the genome does not have, and (when `complete`) fields nobody accounts for."""
    bad = []
    if ev.genome_id != g.genome_id:
        bad.append(f"evidence is for {ev.genome_id}, not {g.genome_id}")
    paths = fields(g)
    sources = {s.id for s in ev.sources}
    ids: set[str] = set()
    for s in ev.sources:
        if not 0.0 <= s.reliability <= 1.0:
            bad.append(f"source {s.id}: reliability {s.reliability} is outside 0..1")
    for c in ev.claims:
        if c.id in ids:
            bad.append(f"{c.id}: listed twice")
        ids.add(c.id)
        if not 0.0 <= c.confidence <= 1.0:
            bad.append(f"{c.id}: confidence {c.confidence} is outside 0..1")
        if not c.evidence:
            bad.append(f"{c.id}: nothing behind it")
        for e in c.evidence:
            if e.source not in sources:
                bad.append(f"{c.id}: evidence from unknown source {e.source!r}")
        if c.kind == "authored" and any(e.source != AUTHOR.id for e in c.evidence):
            bad.append(f"{c.id}: an authored claim rests on the author's word only")
        if not any(_covers(c.field, p) for p in paths):
            bad.append(f"{c.id}: the genome has nothing at {c.field!r}")
    for c in ev.claims:
        for other in c.contradicts:
            if other not in ids:
                bad.append(f"{c.id}: contradicts {other!r}, which is not there")
    if complete:
        bad.extend(f"no evidence for {p}" for p in uncovered(g, ev))
    return bad


def conflicts(ev: PersonaEvidence) -> list[tuple[str, str]]:
    """The pairs of claims that disagree. Both stay in the graph; they are what makes a person more than one note."""
    pairs = set()
    for c in ev.claims:
        for o in c.contradicts:
            pairs.add(tuple(sorted((c.id, o))))
    return sorted(pairs)


def why(ev: PersonaEvidence, path: str) -> list[PersonaClaim]:
    """Every claim that speaks for a field, strongest first: the answer to 'why do we say this?'"""
    return sorted((c for c in ev.claims if _covers(c.field, path)), key=lambda c: (-c.confidence, c.id))


def fictionalize_evidence(ev: PersonaEvidence, fake: CharacterGenome, clean, moved: dict) -> PersonaEvidence:
    """The evidence of a fictionalized genome: what it said, with no source that gives the person away. `clean` is the
    text cleaning applied to the genome (names swapped; it returns "" for a text that has to go) and `moved` says where
    each path of the genome went (None when dropped; world/personas.py scrub). Titles, locators and quotes of the real
    sources are not kept: every claim points at one redacted source. A claim about something that was dropped, or whose
    own words gave the person away, is left out, and so are the contradictions that pointed at it."""
    claims = []
    for c in ev.claims:
        field_ = _move(c.field, moved)
        statement = clean(c.statement)
        if field_ is None or statement == "":
            continue
        claims.append(dataclasses.replace(c, field=field_, statement=statement, evidence=[Evidence(source=REDACTED.id)]))
    kept = {c.id for c in claims}
    claims = [dataclasses.replace(c, contradicts=[o for o in c.contradicts if o in kept]) for c in claims]
    return PersonaEvidence(genome_id=fake.genome_id, sources=[REDACTED], claims=claims)


def _move(path: str, moved: dict) -> str | None:
    """Where a claim's field went: the field itself, or (for a group such as decisions.risk) the group if anything of it
    is left."""
    if path in moved:
        return moved[path]
    inside = [v for k, v in moved.items() if k.startswith(path + ".") or k.startswith(path + "[")]
    if inside and not any(v is not None for v in inside):
        return None
    return path
