"""Explain one event of a world.   python explain.py --world out/world.db --event 348"""
from __future__ import annotations

import argparse
import sys

from world.explain import explain_event, format_explanation
from world.reader import open_world_reader


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--world", required=True)
    ap.add_argument("--event", type=int, required=True)
    args = ap.parse_args()
    conn = open_world_reader(args.world)
    print(format_explanation(explain_event(conn, args.event)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
