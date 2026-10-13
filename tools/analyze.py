"""Post-mortem of lost games (development tool).

Plays games of agent A against B, and for every game A loses, replays it and
re-searches A's last moves with a long, fixed thinking time. Prints each
position where the deep search prefers a different move or already sees a
forced loss, to tell "search too shallow" apart from evaluation blind spots.

    python3 tools/analyze.py smart agents/geonwoo2/smartplayerJRM.py --games 8 --openings 4
"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import arena  # noqa: E402
from board import Board  # noqa: E402
import smartplayerJangJinha as sp  # noqa: E402


def replay(opening, history, upto):
    """Board before move index `upto` of history (opening stones first)."""
    ref = Board()
    color = 0
    for r, c in list(opening) + list(history[:upto]):
        ref.PlaceStone(r, c, color)
        ref.TakeStone(r, c, color)
        color = 1 - color
    return ref.GetBoard(), color


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("a")
    ap.add_argument("b")
    ap.add_argument("--games", type=int, default=8)
    ap.add_argument("--openings", type=int, default=4)
    ap.add_argument("--seed", type=int, default=5)
    ap.add_argument("--last", type=int, default=6, help="A's last N moves to re-search")
    ap.add_argument("--think", type=float, default=15.0)
    ap.add_argument("--dump", help="save the games (with move history) to this JSON file")
    args = ap.parse_args()
    s = arena.run_match(args.a, args.b, args.games, 1, jobs=4,
                        opening_stones=args.openings, seed=args.seed)
    if args.dump:
        import json
        with open(args.dump, "w") as f:
            json.dump(s["games"], f)
    for gi, g in enumerate(s["games"]):
        if g["outcome"] != "loss":
            continue
        a_color = 0 if g["a_black"] else 1
        n_open = len(g["opening"])
        idx = [i for i in range(len(g["history"]))
               if (n_open + i) % 2 == a_color][-args.last:]
        print(f"\n=== game {gi}: A as {'black' if a_color == 0 else 'white'}, "
              f"lost in {len(g['history'])} moves ({g['reason']})")
        for i in idx:
            board, color = replay(g["opening"], g["history"], i)
            played = tuple(g["history"][i])
            deep = arena.make_player(args.a, color)
            deep.move_time = args.think
            mv = deep.take_turn(board, -1)
            kind, depth, score, nodes = deep.last_info or ("?", 0, 0, 0)
            flag = ""
            if tuple(mv) != played:
                flag += "  <-- deep search differs"
            if score <= -(sp.WIN - 100):
                flag += "  [deep sees forced loss]"
            print(f"  move {i:3d}: played {played}  deep {tuple(mv)} "
                  f"({kind} d={depth} score={score:.0f}){flag}")


if __name__ == "__main__":
    main()
