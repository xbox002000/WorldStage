"""Publisher "local": the listing an episode would go out with, written next to the video. No network.

Title, description and tags are composed from the scene spec by fixed templates: the same episode always gets
the same listing, and nothing in it can claim more than the world's own record shows.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from contracts.base import from_dict
from contracts.packet import ProductionPacket
from contracts.scene_spec import Beat, SceneSpec
from narrative.compiler import caption

HINT = {
    ("confront", "lie_exposed"): "謊言被揭穿", ("confront", "distortion_exposed"): "被歪曲的真相",
    ("confront", "concealment_exposed"): "他一直在隱瞞", ("confront", "unfounded"): "一場誤會",
    ("confront", "misinformed"): "傳言與真相", ("confront", "inconclusive"): "說不清的事",
    ("tell", "lie"): "一個謊言", ("tell", "distortion"): "被扭曲的消息", ("tell", "omission"): "沒說出口的事",
    ("tell", "truth"): "傳開的消息", ("steal", None): "失竊", ("talk", "hostile"): "當面衝突",
    ("talk", "cold"): "冷戰", ("talk", "warm"): "難得的溫情", ("talk", "neutral"): "小鎮日常",
}
BASE_TAGS = ["虛擬小鎮", "AI短劇", "AI生成", "自動運轉的世界", "懸疑", "人物關係"]
DISCLOSURE = "本片為 AI 世界模擬自動生成的虛構故事：人物的每個決定與消息來源都有紀錄可查，情節不是人工編寫。"
MAX_TITLE = 100


def _peak(spec: SceneSpec) -> Beat:
    return next((b for b in spec.beats if b.event_id == spec.peak_event_id), spec.beats[-1])


def compose_listing(spec: SceneSpec, packet: ProductionPacket) -> dict:
    peak = _peak(spec)
    names = {pid: p.name for pid, p in spec.characters.items()}
    key = (peak.event_type, peak.variant if peak.event_type != "steal" else None)
    hint = HINT.get(key, "小鎮日常")
    title = f"{spec.title}：{hint}｜第 {peak.day} 天"[:MAX_TITLE]
    lines = []
    if packet.episode.recap:
        lines.append(f"前情提要：{packet.episode.recap}")
        lines.append("")
    lines.append("這一集：")
    lines += [f"・{s.caption}" for s in packet.shots]
    lines += ["", DISCLOSURE]
    people = list(dict.fromkeys(p.name for p in spec.characters.values()))
    tags = BASE_TAGS + people + [f"第{peak.day}天"]
    return {
        "title": title, "description": "\n".join(lines), "tags": tags, "hashtags": " ".join("#" + t for t in tags[:8]),
        "scene_hash": spec.scene_hash, "packet_hash": packet.packet_hash, "disclosure": DISCLOSURE,
        "beats": [caption(b, names) for b in spec.beats],
    }


class LocalPublisher:
    """Writes publish.json and description.txt into the episode folder and records the publication."""

    name = "local"

    def __init__(self, conn: sqlite3.Connection | None = None, episode_id: int | None = None) -> None:
        self.conn = conn
        self.episode_id = episode_id

    def publish(self, episode_dir: Path) -> str:
        spec = from_dict(SceneSpec, json.loads((episode_dir / "scene_spec.json").read_text(encoding="utf-8")))
        packet = from_dict(ProductionPacket, json.loads((episode_dir / "packet.json").read_text(encoding="utf-8")))
        listing = compose_listing(spec, packet)
        (episode_dir / "publish.json").write_text(json.dumps(listing, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        (episode_dir / "description.txt").write_text(f"{listing['title']}\n\n{listing['description']}\n\n{listing['hashtags']}\n", encoding="utf-8")
        ref = str(episode_dir / "publish.json")
        if self.conn is not None and self.episode_id is not None:
            self.conn.execute("INSERT INTO publications(episode_id, publisher, reference, created_at) VALUES (?,?,?,strftime('%s','now'))",
                              (self.episode_id, self.name, ref))
            self.conn.commit()
        return ref
