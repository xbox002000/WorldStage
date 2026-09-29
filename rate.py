"""Rate an episode after watching it.   python rate.py --episode 3 --score 4 [--dramatic] [--boring] [--note "..."]

1 = boring .. 5 = gripping. Ratings are only ever added; the latest one for an episode counts.
"""
from __future__ import annotations

import argparse
import sys

from production import db as prod


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prod", default="out/production.db")
    ap.add_argument("--episode", type=int)
    ap.add_argument("--score", type=int, choices=range(1, 6))
    ap.add_argument("--dramatic", action="store_true", help="the most gripping episode of the run")
    ap.add_argument("--boring", action="store_true", help="the least interesting episode of the run")
    ap.add_argument("--note", default="")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()
    conn = prod.open_production_db(args.prod)
    if args.list or args.episode is None:
        for r in conn.execute(
            "SELECT e.episode_id, e.sim_day, e.title, (SELECT rating FROM episode_ratings r WHERE r.episode_id = e.episode_id "
            "ORDER BY rating_id DESC LIMIT 1) AS rating FROM episodes e WHERE e.status <> 'rejected' ORDER BY e.episode_id"):
            print(f"#{r['episode_id']}  day {(r['sim_day'] or 0) + 1}  {r['title']}  rating={r['rating']}")
        return 0
    if args.score is None:
        ap.error("--score is required")
    conn.execute("INSERT INTO episode_ratings(episode_id, rating, most_dramatic, most_boring, note, created_at) "
                 "VALUES (?,?,?,?,?,strftime('%s','now'))", (args.episode, args.score, int(args.dramatic), int(args.boring), args.note))
    conn.commit()
    print(f"episode {args.episode}: rated {args.score}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
