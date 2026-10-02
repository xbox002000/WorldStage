"""決定性角色生成器。

生成邏輯在 world/forge.py。這個檔案只負責讀參數、檢查江湖文字、寫出四個檔案。

    python character_forge.py --seed 7 --size 10 --era jianghu --out out/forge/cast_7
    python character_forge.py --seed 7 --size 10 --era jianghu --archetypes 高冷美人,毒舌 --lock locks.json --out out/forge/cast_7
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from narrative.lint import MODERN_WORDS
from world.forge import cast_text, find_modern, forge_cast


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="決定性角色生成器：寫出名冊、基因組、初始關係與中文角色表。")
    parser.add_argument("--seed", type=int, required=True, help="隨機種子")
    parser.add_argument("--size", type=int, required=True, help="人數")
    parser.add_argument("--era", choices=("jianghu", "town"), required=True, help="jianghu 江湖，或 town 現代小鎮")
    parser.add_argument("--out", required=True, help="輸出資料夾")
    parser.add_argument("--archetypes", default="", help="逗號分隔的原型，例如 高冷美人,毒舌")
    parser.add_argument("--lock", default="", help="鎖定檔（JSON）。鍵是人的序號，值是要保留的欄位")
    return parser


def write_cast(cast, out) -> None:
    folder = Path(out)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "profiles.json").write_text(cast.profiles_json, encoding="utf-8")
    (folder / "genomes.json").write_text(cast.genomes_json, encoding="utf-8")
    (folder / "relations.json").write_text(cast.relations_json, encoding="utf-8")
    (folder / "summary.md").write_text(cast.summary, encoding="utf-8")


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    locks = None
    if args.lock:
        locks = json.loads(Path(args.lock).read_text(encoding="utf-8"))
    try:
        cast = forge_cast(args.seed, args.size, args.era, archetypes=args.archetypes or None, locks=locks)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if cast.era == "jianghu":
        hits = find_modern(cast_text(cast), MODERN_WORDS)
        if hits:
            print("江湖文字含現代詞：" + "、".join(hits), file=sys.stderr)
            return 1
    write_cast(cast, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
