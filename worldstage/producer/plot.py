"""Episodes from the main line (plot engine, phase 1): the beats bound to real events become key scenes, each storyline gets a
supporting scene from the world's own record, and the scenes of an episode are cut together in time order so that the lines
interweave. Reads the world; writes nothing back to it."""
from __future__ import annotations

from worldstage.narrative.ledger import FactLedger, KnowledgeGate
from worldstage.narrative.scene_cards import SceneCard, card_for
from worldstage.producer.spine import EPISODE_DAYS, SpineResult

SUPPORT_TYPES = ("tell", "confront", "accuse", "flirt", "confession", "shove", "duel", "steal", "take", "regret", "talk", "notice_missing")


def episodes(ledger: FactLedger, spine: SpineResult, n_episodes: int = 3, episode_days: int = EPISODE_DAYS, first_day: int = 0) -> list[dict]:
    out = []
    used: set[int] = {b.event_id for b in spine.bindings.values() if b.event_id is not None}
    for n in range(1, n_episodes + 1):
        lo = first_day + (n - 1) * episode_days
        hi = lo + episode_days - 1
        scenes: list[SceneCard] = []
        povs: list[str] = []
        for bid, b in sorted(spine.bindings.items()):
            if b.beat.episode != n or b.event_id is None:
                continue
            f = ledger.facts.get(b.event_id)
            if f is None:
                continue
            cast = spine.casts.get(b.beat.line, set())
            pov = f.actor if f.actor not in povs else (f.target or f.actor)
            card = card_for(ledger, f, f"E{n}-{b.beat.line}1", n, b.beat.line, bid, pov, cast, lo)
            if card is not None:
                scenes.append(card)
                povs.append(pov)
            # a supporting scene for the line: the most important other fact of the episode among its people, from another POV
            for g in sorted(ledger.window(lo, hi), key=lambda g: (-g.importance, g.fact_id)):
                if g.fact_id in used or g.type not in SUPPORT_TYPES or not (set(g.participants) & cast) or not g.actor:
                    continue
                sp = g.actor if g.actor not in povs else (g.target if g.target and g.target not in povs else None)
                if sp is None:
                    continue
                c2 = card_for(ledger, g, f"E{n}-{b.beat.line}2", n, b.beat.line, None, sp, cast, lo)
                if c2 is None:
                    continue
                used.add(g.fact_id)
                scenes.append(c2)
                povs.append(sp)
                break
        scenes.sort(key=lambda c: (c.ts, c.scene_id))
        for i, c in enumerate(scenes, 1):
            c.scene_id = f"E{n}S{i}-{c.line}"
        out.append({"episode": n, "first_day": lo, "last_day": hi, "scenes": scenes})
    return out


def write_all(ledger: FactLedger, eps: list[dict], writer) -> None:
    gate = KnowledgeGate(ledger)
    for ep in eps:
        for c in ep["scenes"]:
            c.lines = writer.write(ledger, c, gate)
