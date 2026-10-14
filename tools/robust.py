"""Empty-board robustness check across clock speeds (development tool).

Empty-board games between deterministic engines repeat almost the same line,
so 8 games at one clock are really ~2 distinct games, and the grader's
machine (different speed) will produce different lines anyway. This plays
empty-board games at several clocks to emulate machine speeds and reports
the total.

    python3 tools/robust.py smart agents/geonwoo2/smartplayerJRM.py
"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import arena  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("a")
    ap.add_argument("b")
    ap.add_argument("--clocks", default="0.5,0.75,1,1.5", help="minutes, comma separated")
    ap.add_argument("--games", type=int, default=8, help="games per clock")
    ap.add_argument("--jobs", type=int, default=4)
    args = ap.parse_args()
    tot = [0, 0, 0]
    black = [0, 0, 0]
    white = [0, 0, 0]
    rows = []
    for clock in [float(x) for x in args.clocks.split(",")]:
        s = arena.run_match(args.a, args.b, args.games, clock, jobs=args.jobs, verbose=False)
        for i, k in enumerate(("win", "draw", "loss")):
            tot[i] += s[k]
        for i in range(3):
            black[i] += s["a_black"][i]
            white[i] += s["a_white"][i]
        bad = {k: v for k, v in s["reasons"].items() if k.split(":")[1] in ("crash", "timeout", "illegal")}
        rows.append(f"  clock {clock:>4} min: W/D/L {s['win']}/{s['draw']}/{s['loss']}  {bad or ''}")
    n = sum(tot)
    print(f"{args.a} vs {args.b}")
    print("\n".join(rows))
    print(f"  total W/D/L {tot[0]}/{tot[1]}/{tot[2]}  score={(tot[0] + 0.5 * tot[1]) / n:.3f}"
          f"   black {black}  white {white}")


if __name__ == "__main__":
    main()
