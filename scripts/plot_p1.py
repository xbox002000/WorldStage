"""Plot engine, phase 1: three episodes from one world, pulled along a main line and checked for continuity.

    python -m scripts.plot_p1 --dry                         # offline writer: no network, no key, deterministic
    python -m scripts.plot_p1 --estimate                    # what the LLM writer would cost, then stop
    python -m scripts.plot_p1 --llm --max-usd 2             # LLM dialogue (GEMINI_API_KEY), cached; refuses above the cap

Writes <out>/world.db, <out>/episodes.json and <out>/episodes.md (the full script, for scoring).
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from dataclasses import asdict
from pathlib import Path

from worldstage.agent.llm import DEFAULT_MODEL, build_chain, has_api_key
from worldstage.agent.llm_cache import LLMCache
from worldstage.agent.volition import VolitionDecider
from worldstage.narrative import plot_continuity
from worldstage.narrative.dialogue import NARRATOR, LLMWriter, OfflineWriter, estimate_cost
from worldstage.narrative.ledger import FactLedger
from worldstage.producer.plot import episodes, write_all
from worldstage.producer.spine import BEATS, EPISODE_DAYS, LINES, SpineDirector, fulfil
from worldstage.world.db import connect, init_db
from worldstage.world.seed import build_world
from worldstage.world.simulation import Simulation


def make_world(path: Path, seed: int, recipe: str, days: int) -> SpineDirector:
    for ext in ("", "-wal", "-shm"):
        Path(str(path) + ext).unlink(missing_ok=True)
    conn = connect(str(path))
    init_db(conn, seed)
    build_world(conn, seed, recipe)
    decider = VolitionDecider(seed)
    director = SpineDirector("greedy", seed)
    Simulation(conn, decider, decider, set(), feed="synthetic_v1", producer=director).run(days)
    conn.close()
    return director


def to_markdown(ledger: FactLedger, eps: list[dict], spine, report: dict, meta: dict) -> str:
    n = ledger.name
    out = [f"# WorldStage 劇情引擎 Phase 1：三集劇本", "",
           f"世界：seed {meta['seed']}、recipe `{meta['recipe']}`、{meta['days']} 天；台詞：{meta['writer']}。"
           "每一場都站在 world.db 裡真的發生過的事件上（事件編號寫在場景標頭）。", "",
           "## 主線節拍", "", "| 節拍 | 集 | 線 | 作用 | 必中 | 對應世界事件 | 人物 |", "|---|---|---|---|---|---|---|"]
    for bid, b in sorted(spine.bindings.items()):
        ev = f"#{b.event_id}（第{b.day + 1}天）{ledger.facts[b.event_id].summary}" if b.event_id is not None and b.event_id in ledger.facts \
            else (f"#{b.event_id}" if b.event_id is not None else f"未達成：{b.reason}")
        out.append(f"| {bid} | {b.beat.episode} | {b.beat.line} {LINES[b.beat.line]} | {b.beat.role} | {'是' if b.beat.must_hit else '否'} | {ev} | "
                   f"{'、'.join(n(p) for p in b.cast)} |")
    out += ["", f"連戲檢查：嚴重 {report['severe']}、提醒 {report['warn']}。", ""]
    for ep in eps:
        povs = sorted({c.pov for c in ep["scenes"]})
        out += [f"## 第 {ep['episode']} 集（第 {ep['first_day'] + 1}–{ep['last_day'] + 1} 天）", "",
                f"視角：{'、'.join(n(p) for p in povs)}；故事線：{'、'.join(sorted({c.line for c in ep['scenes']}))}", ""]
        for c in ep["scenes"]:
            beat = f"｜節拍 {c.beat_id}" if c.beat_id else ""
            out += [f"### {c.scene_id}　{c.location}　（{LINES[c.line].split('：')[0]}{beat}｜事件 #{c.anchor}）", "",
                    f"- **視角**：{n(c.pov)}", f"- **懸念**：{c.question}", f"- **轉折**：{c.turn['before']} → {c.turn['after']}",
                    f"- **在場**：{'、'.join(n(p) for p in c.cast)}"]
            if c.irony:
                out.append("- **觀眾知道、" + n(c.pov) + "不知道**：" + "；".join(f"#{x} {ledger.facts[x].summary}" for x in c.irony))
            out.append("")
            for x in c.lines:
                uses = f" <sub>[{', '.join('#' + str(u) for u in x['uses'])}]</sub>" if x["uses"] else ""
                if x["speaker"] == NARRATOR:
                    out.append(f"> {x['text']}{uses}")
                elif x.get("kind") == "inner":
                    out.append(f"**{n(x['speaker'])}**：*{x['text']}*{uses}")
                else:
                    out.append(f"**{n(x['speaker'])}**：{x['text']}{uses}")
                out.append("")
    out += ["## 評分表（Rock 填）", "", "| 集 | 鉤子 | 因果可信 | 角色動機 | 懸念 | 想看下一集 | 備註 |", "|---|---|---|---|---|---|---|"]
    out += [f"| {ep['episode']} |  |  |  |  |  |  |" for ep in eps]
    if report["issues"]:
        out += ["", "## 連戲檢查明細", ""] + [f"- {i['severity']} {i['code']} {i['where']}：{i['detail']}" for i in report["issues"]]
    return "\n".join(out) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=701)
    ap.add_argument("--recipe", default="jianghu_drama_v1")
    ap.add_argument("--days", type=int, default=3 * EPISODE_DAYS)
    ap.add_argument("--out", default="out/plot_p1")
    ap.add_argument("--reuse", action="store_true", help="use <out>/world.db as it is")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--dry", action="store_true", help="offline writer (the default)")
    g.add_argument("--llm", action="store_true", help="LLM writer (needs GEMINI_API_KEY)")
    g.add_argument("--estimate", action="store_true", help="print the LLM writer's estimated cost and stop")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--max-usd", type=float, default=2.0)
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    db = out / "world.db"
    pulls = []
    if not (a.reuse and db.exists()):
        pulls = make_world(db, a.seed, a.recipe, a.days).pulls
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    ledger = FactLedger(conn)
    spine = fulfil(conn, BEATS, EPISODE_DAYS)
    eps = episodes(ledger, spine, 3, EPISODE_DAYS)
    cards = [c for ep in eps for c in ep["scenes"]]
    est = estimate_cost(ledger, cards, a.model)
    print("estimate", json.dumps(est))
    if a.estimate:
        return 0
    writer_name = "離線（決定性）寫手"
    if a.llm:
        if not has_api_key():
            print("GEMINI_API_KEY is not set: stopping before any LLM call", file=sys.stderr)
            return 2
        if est["usd"] > a.max_usd:
            print(f"estimate US${est['usd']} is above the cap US${a.max_usd}: stopping", file=sys.stderr)
            return 3
        cache = LLMCache(sqlite3.connect(out / "llm_cache.db", isolation_level=None))
        writer = LLMWriter(build_chain(a.model, mode="cache", cache=cache, max_calls=4 * len(cards)))
        writer_name = f"LLM（{a.model}）"
    else:
        writer = OfflineWriter()
    write_all(ledger, eps, writer)
    binds = {bid: {"event_id": b.event_id, "episode": b.beat.episode, "must_hit": b.beat.must_hit} for bid, b in spine.bindings.items()}
    report = plot_continuity.summary(plot_continuity.check(ledger, eps, binds, EPISODE_DAYS))
    meta = {"seed": a.seed, "recipe": a.recipe, "days": a.days, "writer": writer_name}
    (out / "episodes.md").write_text(to_markdown(ledger, eps, spine, report, meta), encoding="utf-8")
    (out / "episodes.json").write_text(json.dumps({"meta": meta, "estimate": est, "pulls": pulls, "beats": binds,
                                                   "episodes": [{**ep, "scenes": [asdict(c) for c in ep["scenes"]]} for ep in eps],
                                                   "continuity": report,
                                                   "rejected": getattr(writer, "rejected", [])}, ensure_ascii=False, indent=1), encoding="utf-8")
    stats = [{"episode": ep["episode"], "scenes": len(ep["scenes"]), "lines": len({c.line for c in ep["scenes"]}),
              "povs": len({c.pov for c in ep["scenes"]})} for ep in eps]
    print("episodes", json.dumps(stats), "severe", report["severe"], "warn", report["warn"], "missed", spine.missed())
    print("wrote", out / "episodes.md")
    return 0 if report["severe"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
