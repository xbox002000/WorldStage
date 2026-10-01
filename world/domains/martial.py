"""Martial arts, reputation, duels and sects, as a domain pack. The rules themselves are in world/jianghu.py; this
module is how the core finds them: the actions (train, challenge), how the rule agent weighs them, what they do to
reputation and sect loyalty, the goals they serve (surpass) and how a duel looks and sounds.
"""
from __future__ import annotations

import sqlite3

from contracts.recipe import MechanicPrimitive as P
from world import jianghu
from world.domains.base import ActionSpec, Domain, EventStyle
from world.events import EventSpec
from world.intent import Intent
from world.state import WorldError


def _validate_train(conn: sqlite3.Connection, it: Intent, actor: sqlite3.Row) -> None:
    from world.intent import tags_of
    jianghu.validate_train(conn, actor, tags_of(conn, actor["location_id"]))


def _validate_challenge(conn: sqlite3.Connection, it: Intent, actor: sqlite3.Row) -> None:
    from world.animals import is_animal
    if is_animal(conn, it.target or ""):
        raise WorldError("nobody duels an animal")
    jianghu.validate_challenge(conn, it, actor)


def _explain_duel(truth: dict, names: dict, who: str, other: str) -> str:
    win, lose = names.get(truth.get("winner"), ""), names.get(truth.get("loser"), "")
    back = f"，{names.get(truth['returned'], '東西')}物歸原主" if truth.get("returned") else ""
    return f"{who}向{other}挑戰，{win}擊敗了{lose}{back}"


def _explain_train(truth: dict, names: dict, who: str, other: str) -> str:
    return f"{who}練功" + ("（照著劍譜）" if truth.get("with_manual") else "")


class Martial(Domain):
    id = "martial"
    title = "武功"
    primitives = (
        P("reputation", "social", "public standing that acts raise or ruin", ["claims"]),
        P("duel", "adventure", "a challenge settled by skill and luck, with stakes", ["reputation", "martial_arts"]),
        P("sect_factions", "social", "membership, rank and loyalty in groups", ["reputation"]),
        P("martial_arts", "power", "skills that training raises; a manual doubles it", ["schedule"], cost=2),
    )
    actions = {
        "train": ActionSpec("train", _validate_train, jianghu.resolve_train, label="練功"),
        "challenge": ActionSpec("challenge", _validate_challenge, jianghu.resolve_challenge, targets_person=True,
                                conflict=True, label="向{t}挑戰比武",
                                stakes=lambda conn, it: {"ambition": 0.6, "security": -0.4, "revenge": 0.3}),
    }
    styles = {
        "duel": EventStyle(caption="和{t}比武", lines=("來吧，一決高下！", "接招！"), social=True, say=3.0, strikes=3,
                           beat=("strike", "parry", "fierce", "fierce", "wide", "slow_push_in", 6),
                           describe="{a} 向 {b} 挑戰比武", functions=("escalate", "payoff"), first_time=True, heat=3,
                           opens_scene=True, explain=_explain_duel),
        "train": EventStyle(caption="練功", beat=("practise", "watch", "focused", "calm", "medium", "static", 3),
                            describe="{a} 獨自練功", explain=_explain_train),
    }
    goal_text = {"surpass": "有一天打贏{t}"}

    # -- the rule agent --------------------------------------------------------------------------------------------
    def options(self, conn: sqlite3.Connection, actor: str, now: int, ctx: dict) -> list:
        from world.recipes import enabled
        out = []
        here, t = ctx["here"], ctx["traits"]
        if enabled(conn, "duel"):
            # injuries and cooldowns are judged as of the world's last event (as they always were)
            latest = conn.execute("SELECT COALESCE(MAX(timestamp), 0) FROM events").fetchone()[0]
            me = conn.execute("SELECT energy FROM people WHERE id = ?", (actor,)).fetchone()[0]
            hurt = jianghu.injured(conn, actor, latest)
            for p in here:
                if hurt or me < jianghu.DUEL_ENERGY or conn.execute(
                        "SELECT energy FROM people WHERE id = ?", (p,)).fetchone()[0] < jianghu.DUEL_ENERGY \
                        or jianghu.recent_duel(conn, actor, p, latest) or jianghu.injured(conn, p, latest):
                    continue
                r = conn.execute("SELECT trust, affection, fear, rivalry FROM relationships WHERE actor_id = ? AND target_id = ?",
                                 (actor, p)).fetchone()
                if jianghu.skill(conn, actor) < 0.2 or jianghu.skill(conn, p) < 0.2:
                    continue  # not fighters
                gap = jianghu.skill(conn, actor) - jianghu.skill(conn, p)
                rival_sect = jianghu.sect(conn, actor) and jianghu.sect(conn, p) and jianghu.sect(conn, actor) != jianghu.sect(conn, p)
                glory = max(0.0, jianghu.rep(conn, p) - jianghu.rep(conn, actor) + 0.2)
                risk, bully = max(0.0, -gap - 0.1), max(0.0, gap - 0.2)
                # a duel is for a grudge or for a name: never to bully the weak, rarely against a master
                score = (0.7 * t["temper"] * max(0.0, r["rivalry"]) + 0.5 * glory * t["temper"] + 0.2 * bool(rival_sect)
                         - 1.5 * bully - 1.2 * risk - 0.5 * max(0.0, r["fear"]) - 0.3 * max(0.0, r["affection"]) - 0.45)
                out.append((score, Intent(actor, "challenge", p, reason="volition")))
        if enabled(conn, "martial_arts"):
            tags = conn.execute("SELECT tags FROM locations WHERE id = ?", (ctx["location"],)).fetchone()[0]
            if '"training"' in tags:
                out.append((0.1, Intent(actor, "train", reason="volition")))
        return out

    def lean(self, conn: sqlite3.Connection, goal: sqlite3.Row, it: Intent) -> float | None:
        k, a = goal["kind"], it.action
        if k == "surpass" and a == "train":
            return 0.8
        if k in ("surpass", "revenge", "outshine") and a == "challenge" and it.target == goal["target"]:
            return 0.6
        return None

    # -- the world -------------------------------------------------------------------------------------------------
    def effects(self, conn: sqlite3.Connection, spec: EventSpec, primitives: set[str]) -> EventSpec:
        if primitives & {"reputation", "sect_factions"}:
            return jianghu.with_jianghu_effects(conn, spec, primitives)
        return spec

    def review_goal(self, conn: sqlite3.Connection, goal: sqlite3.Row, day: int) -> tuple[str, str] | None:
        if goal["kind"] == "surpass" and conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'world_vars'").fetchone():
            if jianghu.skill(conn, goal["person_id"]) > jianghu.skill(conn, goal["target"]) + 0.05:
                return "completed", "已經比他強了"
        return None

    def describe(self, conn: sqlite3.Connection, pid: str) -> dict:
        from world.attention import var
        if var(conn, f"skill.{pid}", None) is None:
            return {}
        return {"武功": round(jianghu.skill(conn, pid), 2), "名聲": round(jianghu.rep(conn, pid), 2),
                "門派": jianghu.sect(conn, pid) or "—"}
