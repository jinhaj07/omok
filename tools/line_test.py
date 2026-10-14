"""Compare opening lines by playing them out (dev tool).

Each line is a fixed sequence of opening moves (black first). From the end
of the line, agent A plays `--side` against B at several clocks (the games
are close to deterministic per clock, so clocks give the variety).

    python3 tools/line_test.py smart agents/geonwoo3/smartplayerJRM.py --side white \
        "9,9 7,9 7,7 9,7" "9,9 7,9 7,7 9,11"
"""
import argparse
import multiprocessing as mp
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import arena  # noqa: E402


def parse(line):
    return [tuple(int(x) for x in mv.split(",")) for mv in line.split()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("a")
    ap.add_argument("b")
    ap.add_argument("lines", nargs="+")
    ap.add_argument("--side", choices=["black", "white"], default="white")
    ap.add_argument("--clocks", default="0.4,0.5,0.6,0.75,0.9,1,1.25,1.5")
    args = ap.parse_args()
    clocks = [float(x) for x in args.clocks.split(",")]
    a_black = args.side == "black"
    jobs = []
    for li, line in enumerate(args.lines):
        opening = parse(line)
        for ci, clock in enumerate(clocks):
            black, white = (args.a, args.b) if a_black else (args.b, args.a)
            jobs.append((li, (black, white, clock, opening, None, 1000 * li + ci)))
    with mp.Pool(4) as pool:
        results = pool.map(arena.play_game, [j for _, j in jobs])
    a_color = 0 if a_black else 1
    for li, line in enumerate(args.lines):
        w = l = d = 0
        for (lj, _), res in zip(jobs, results):
            if lj != li:
                continue
            if res["winner"] is None:
                d += 1
            elif res["winner"] == a_color:
                w += 1
            else:
                l += 1
        print(f"{line:40s}  A({args.side}) W/D/L {w}/{d}/{l}")


if __name__ == "__main__":
    main()
