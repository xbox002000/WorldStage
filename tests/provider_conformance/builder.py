"""Make the conformance samples from a real world, deterministically.

    python -m tests.provider_conformance.builder --write     # rewrite samples.json and bible.json
    python -m tests.provider_conformance.builder --check     # rebuild and compare with the files (exit 1 on a difference)

The world is jianghu_story_v1, seed 17, eight days of rule agents. Each sample is one shot of a real event, compiled the way
the pipeline does (SceneSpec -> DirectorPlan -> PerformancePlan -> ProductionPacket) and turned into a ShotRequest the way
production/shots.py does. The hand-over is the one event the eight days do not contain: it is made through the world's own
rules (a take, then a give) on this throwaway copy, so it has witnesses, memories and a thread like any other.

The fixtures are committed so that the suite does not depend on the simulation staying the same; --check says when they have
drifted from what the engine would make today.
"""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import sys
from pathlib import Path

from contracts.backends import ShotRequest
from contracts.base import canonical_json, to_dict
from production.bible import build_bible
from production.shots import describe
from tests.provider_conformance.worlds import played_world

HERE = Path(__file__).resolve().parent
SAMPLES = HERE / "samples.json"
BIBLE = HERE / "bible.json"
RECIPE, SEED, DAYS = "jianghu_story_v1", 17, 8
FIXTURE_VERSION = 1

# kind -> (what it stands for, the closed-vocabulary intent the episode plan gives the beat, the director's function of the
# shot that is taken from it: the intent adds to the director's functions, it does not replace them)
KINDS = {
    "two_person_dialogue": ("two people talking, as one shot", "connect", "connect"),
    "duel": ("a bout between two, with others watching", "escalate", "escalate"),
    "hand_over": ("a thing passes from one hand to another", "payoff", "payoff"),
    "public_face_slap": ("somebody shown to be more than they were taken for, in front of others", "face_slap", "escalate"),
    "ambiguous_closeup": ("a look held a moment too long", "longing_glance", "longing_glance"),
    "crowd_reaction": ("the bystanders as the thing lands", "bystander_shock", "reaction"),
    "confrontation": ("somebody says to a face what the room already half knows", "reveal", "reveal"),
}


def _events(conn):
    from narrative.arcs import load_events
    return load_events(conn)


def _pick_events(conn) -> dict[str, int]:
    """One real event per kind, found by what it is (not by a number that a different engine would shift)."""
    from tests.test_world_c import put
    from world.events import apply_event
    from world.intent import Intent
    from world.rules import resolve
    evs = _events(conn)
    ordered = sorted(evs.values(), key=lambda e: e.id)

    def first(pred):
        return next(e.id for e in ordered if pred(e))

    out = {
        "two_person_dialogue": first(lambda e: e.type == "talk" and len([p for p, _r in e.participants]) == 2
                                     and e.truth.get("tone") in ("warm", "neutral")),
        "duel": first(lambda e: e.type == "duel" and not e.truth.get("slap")),
        "public_face_slap": first(lambda e: e.type == "duel" and e.truth.get("slap")),
        "ambiguous_closeup": first(lambda e: e.type == "flirt"),
        "confrontation": first(lambda e: e.type == "confront" and e.truth.get("outcome") != "false"
                               and len(e.participants) >= 4),
    }
    out["crowd_reaction"] = out["public_face_slap"]
    # the hand-over: made through the world's rules, at the inn, on this throwaway copy
    now = max(e.ts for e in ordered) + 60
    put(conn, now, jun="inn", ming="inn")
    for step, action in enumerate(("take", "give")):
        apply_event(conn, resolve(conn, Intent("jun", action, "wallet_ming"), now + 5 * (step + 1), "decision"))
    out["hand_over"] = max(_events(conn))
    return out


def _packet(conn, event_id: int, intent: str):
    from narrative.arcs import Arc
    from narrative.compiler import compile_packet
    from narrative.direction import plan_direction
    from narrative.performance import plan_performance
    from narrative.scene_spec import build_scene_specs
    from narrative.selector import Candidate
    e = _events(conn)[event_id]
    spec = build_scene_specs(conn, [Candidate(Arc((e,), e, "thread"), 1.0, {}, 1.0)], ["conformance"])[0]
    direction = plan_direction(conn, spec, intents={event_id: [intent]})
    performance = plan_performance(conn, spec, direction)
    return compile_packet(spec, direction=direction, performance=performance)


def fixed_seed(kind: str) -> int:
    """Each sample has its own seed that belongs to the sample, not to the packet: a packet's hash moves whenever any compiler
    file does, and a conformance run has to be the same run next month."""
    return int.from_bytes(hashlib.sha256(f"conformance:{kind}".encode()).digest()[:4], "big") % 2 ** 31


def _shot_request(packet, shot, kind: str) -> ShotRequest:
    """The same fields production/shots.py sends a visual provider (no control images: those are files of one machine)."""
    return ShotRequest(shot.shot_id, describe(shot), float(shot.duration_seconds), packet.canvas.width, packet.canvas.height,
                       packet.canvas.fps, fixed_seed(kind), subject=shot.subject, action=shot.action,
                       environment=shot.environment, camera=f"{shot.camera.shot_type}/{shot.camera.movement}",
                       controls={}, reference_asset_ids=sorted(c.asset_id for c in shot.characters),
                       performance=[dataclasses.asdict(pb) for pb in shot.performances])


def build() -> tuple[dict, dict]:
    conn = played_world(RECIPE, SEED, DAYS)
    bible = build_bible(conn)
    picked = _pick_events(conn)
    samples = []
    for kind, (meaning, intent, function) in KINDS.items():
        event_id = picked[kind]
        packet = _packet(conn, event_id, intent)
        shot = next((s for s in packet.shots if s.function == function), None) or packet.shots[-1]
        who = sorted({c.id for c in shot.characters})
        samples.append({
            "id": kind, "meaning": meaning, "intent": intent, "requires": ["t2v"],
            "source": {"recipe": RECIPE, "seed": SEED, "days": DAYS, "event_id": event_id,
                       "event_type": _events(conn)[event_id].type, "shot_id": shot.shot_id, "function": shot.function,
                       "scale": shot.scale, "packet_hash": packet.packet_hash},
            "bible": {"characters": [a.asset_id for a in (bible.character_for(p) for p in who) if a],
                      "scene": f"scene:{shot.location.id}"},
            "shot": to_dict(_shot_request(packet, shot, kind))})
    conn.close()
    return ({"fixture_version": FIXTURE_VERSION, "recipe": RECIPE, "seed": SEED, "days": DAYS,
             "bible_hash": bible.bible_hash, "samples": samples}, to_dict(bible))


def _steady(samples: dict) -> dict:
    """The fixtures without the packet hashes: they say which packet a shot came from, and move with every compiler change."""
    out = json.loads(canonical_json(samples))
    for sample in out["samples"]:
        sample["source"].pop("packet_hash", None)
    return out


def drift() -> list[str]:
    """What differs between the committed fixtures and what the engine makes today (empty when nothing does)."""
    samples, bible = build()
    old = json.loads(SAMPLES.read_text(encoding="utf-8"))
    out = [f"sample {a['id']}" for a, b in zip(_steady(old)["samples"], _steady(samples)["samples"]) if a != b]
    if len(old["samples"]) != len(samples["samples"]):
        out.append("the number of samples")
    if canonical_json(json.loads(BIBLE.read_text(encoding="utf-8"))) != canonical_json(bible):
        out.append("the bible")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    if args.write:
        samples, bible = build()
        SAMPLES.write_text(json.dumps(samples, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
        BIBLE.write_text(json.dumps(bible, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
        print(f"wrote {SAMPLES.name} ({len(samples['samples'])} samples) and {BIBLE.name}")
        return 0
    if args.check:
        moved = drift()
        print("fixtures match what the engine makes today" if not moved else "fixtures have drifted (" + ", ".join(moved) + "): run with --write")
        return 1 if moved else 0
    print(json.dumps(build()[0], ensure_ascii=False, indent=1)[:3000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
