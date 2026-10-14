"""Move-by-move comparison of two agents on the same positions (dev tool).

Plays empty-board games of agent A against B at several clocks, then, for
every move A made as `--side`, asks B what it would play in that same
position (with a comparable clock). Reports where they disagree, so
systematic differences in style (e.g. the white opening) become visible.

    python3 tools/compare_moves.py smart agents/geonwoo3/smartplayerJRM.py --side white
"""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import arena  # noqa: E402
from analyze import replay  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("a")
    ap.add_argument("b")
    ap.add_argument("--side", choices=["black", "white"], default="white")
    ap.add_argument("--clocks", default="0.5,0.75,1,1.5")
    ap.add_argument("--plies", type=int, default=24, help="compare moves up to this ply")
    ap.add_argument("--only-losses", action="store_true")
    ap.add_argument("--dump")
    args = ap.parse_args()
    a_color = 0 if args.side == "black" else 1
    games = []
    for clock in [float(x) for x in args.clocks.split(",")]:
        s = arena.run_match(args.a, args.b, 4, clock, jobs=4, verbose=False)
        for g in s["games"]:
            if (0 if g["a_black"] else 1) == a_color:
                g["clock"] = clock
                games.append(g)
    if args.dump:
        with open(args.dump, "w") as f:
            json.dump(games, f)
    agree = total = 0
    for gi, g in enumerate(games):
        if args.only_losses and g["outcome"] != "loss":
            continue
        print(f"\n=== game {gi} clock {g['clock']} A as {args.side}: {g['outcome']} in {len(g['history'])} plies")
        line = []
        for i, mv in enumerate(g["history"][:args.plies]):
            if i % 2 != a_color:
                line.append(f"{tuple(mv)}")
                continue
            board, color = replay([], g["history"], i)
            pb = arena.make_player(args.b, color)
            if hasattr(pb, "moves_played"):
                pb.moves_played = i // 2
            alt = tuple(pb.take_turn(board, 40000))
            total += 1
            if alt == tuple(mv):
                agree += 1
                line.append(f"[{tuple(mv)}]")
            else:
                line.append(f"[{tuple(mv)} B:{alt}]")
        print("  " + " ".join(line))
    print(f"\nagreement {agree}/{total}")


if __name__ == "__main__":
    main()
