"""python -m narrative --db week1.db --top 3 --out out/scenes.json"""
from __future__ import annotations

import argparse
from pathlib import Path

from world.db import connect
from narrative.scene_spec import build_spec, dumps
from narrative.selector import DEFAULT_PROTAGONISTS, rank_arcs, select_top


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--top", type=int, default=3)
    ap.add_argument("--out", default="out/scenes.json")
    ap.add_argument("--protagonists", default=",".join(sorted(DEFAULT_PROTAGONISTS)))
    args = ap.parse_args()

    conn = connect(args.db)
    prot = set(args.protagonists.split(","))
    ranked, _ = rank_arcs(conn, prot)
    chosen, _ = select_top(conn, args.top, prot)
    print(f"{len(ranked)} candidate arcs, top {len(chosen)} selected")
    for c in chosen:
        print(f"  score={c.score:.3f} peak=#{c.arc.peak.id} events={list(c.arc.ids)} {c.breakdown}")
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(dumps(build_spec(conn, chosen)), encoding="utf-8")
    print("wrote", out)


if __name__ == "__main__":
    main()
