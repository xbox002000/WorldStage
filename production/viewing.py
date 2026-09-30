"""What watching a packet is like, measured from the packet alone (read-only, no pixels): who is on screen and for how
long, from what height, through whose eyes, how much is heard as words, and whether the audience is shown the truth.
Used by the Director Reality Test to show that two DirectorPlans of the same scene are two different experiences.
"""
from __future__ import annotations

from contracts.packet import ProductionPacket

HEIGHT_M = {"ground": 0.47, "low": 0.9, "eye_level": 1.6, "high": 2.4, "overhead": 4.0}
CLOSE = ("MCU", "CU", "ECU", "INSERT")


def on_screen(shot) -> list[str]:
    """Who the audience actually sees in a shot: not the doer of a hidden act, not the one whose eyes we are behind."""
    hidden = set()
    if shot.function == "hide":
        hidden |= {c.id for c in shot.characters if c.role == "actor"}
    if shot.relation == "subjective" and shot.focalizer:
        hidden.add(shot.focalizer)
    return [c.id for c in shot.characters if c.id not in hidden]


def viewing_profile(packet: ProductionPacket, culprits: set[str] | frozenset[str] = frozenset(),
                    payoff_event: int | None = None) -> dict:
    shots = packet.shots
    total = sum(s.duration_seconds for s in shots) or 1
    share = lambda pred: round(sum(s.duration_seconds for s in shots if pred(s)) / total, 3)  # noqa: E731
    screen: dict[str, int] = {}
    for s in shots:
        for who in on_screen(s):
            screen[who] = screen.get(who, 0) + s.duration_seconds
    before = [s for s in shots if payoff_event is None or s.event_id < payoff_event]
    # the audience witnesses the act if the doer is on screen doing it, or if we are behind the doer's own eyes
    culprit_seen = any(s.event_type in ("take", "steal", "misplace") and s.function != "hide" and
                       (set(on_screen(s)) & set(culprits) or (s.relation == "subjective" and s.focalizer in culprits
                                                               and s.focalizer in {c.id for c in s.characters}))
                       for s in before)
    return {
        "shots": len(shots),
        "seconds": total,
        "camera_height_m": round(sum(HEIGHT_M.get(s.angle, 1.6) * s.duration_seconds for s in shots) / total, 2),
        "subjective_share": share(lambda s: s.relation == "subjective"),
        "close_share": share(lambda s: s.scale in CLOSE),
        "moving_share": share(lambda s: s.camera.movement not in ("static", "")),
        "reaction_shots": sum(1 for s in shots if s.function == "reaction"),
        "words_audible_share": share(lambda s: s.dialogue == "full"),
        "hidden_shots": sum(1 for s in shots if s.function == "hide"),
        "audience_witnesses_culprit_act": bool(culprit_seen),
        "screen_seconds": dict(sorted(screen.items(), key=lambda kv: -kv[1])),
        "captions": [s.caption for s in shots if s.caption],
        "inner": [f"{s.thought_by}:{s.thought_kind}:{s.thought}" for s in shots if s.thought],
    }
