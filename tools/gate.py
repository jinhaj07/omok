"""Regression gate for SmartPlayerJangJinha (development tool).

Runs the checks every version must pass before it is accepted:
  1. rule/engine unit tests,
  2. the grading conditions: 8 games (4 black, 4 white) with a 1 minute
     clock against RandomPlayer and SimplePlayer, needing >= 5 wins each,
  3. a slow-machine check: the same against SimplePlayer with only a
     30 second clock,
  4. a stronger proxy opponent (our own engine limited to depth 2), as a
     stand-in for the unreleased TA agents,
with zero crashes, timeouts or illegal moves anywhere.

    python3 tools/gate.py            # full gate
    python3 tools/gate.py --quick    # skip the slow-machine and proxy stages
"""
import argparse
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import arena  # noqa: E402

BAD = ("crash", "timeout", "illegal")


def stage(name, spec_a, spec_b, games, time_limit, need_wins, jobs, openings=0):
    print(f"== {name}")
    s = arena.run_match(spec_a, spec_b, games, time_limit, jobs=jobs, opening_stones=openings)
    bad = {k: v for k, v in s["reasons"].items() if k.startswith("loss:") and k[5:] in BAD}
    ok = s["win"] >= need_wins and not bad
    print(f"   -> {'PASS' if ok else 'FAIL'} (need {need_wins} wins, bad={bad})\n")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent", default="smart")
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--jobs", type=int, default=2,
                    help="parallel games; keep low so timings stay realistic")
    args = ap.parse_args()

    print("== unit tests")
    t = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests"], cwd=ROOT)
    results = [t.returncode == 0]
    print(f"   -> {'PASS' if results[0] else 'FAIL'}\n")

    a = args.agent
    results.append(stage("vs RandomPlayer (1 min)", a, "random", 8, 1, 5, args.jobs))
    results.append(stage("vs SimplePlayer (1 min)", a, "simple", 8, 1, 5, args.jobs))
    if not args.quick:
        results.append(stage("vs SimplePlayer (30 s, slow machine)", a, "simple", 8, 0.5, 5, args.jobs))
        results.append(stage("vs depth-2 proxy (1 min, random openings)", a, "smart:depth=2",
                             8, 1, 5, args.jobs, openings=4))
        # Team rivals: the target to beat and the previous version.
        for name, path in (("Geonwoo2", "agents/geonwoo2/smartplayerJRM.py"),
                           ("v10", "agents/jinha_v10/smartplayerJangJinha.py")):
            results.append(stage(f"vs {name} (1 min, empty board)", a, path, 8, 1, 5, args.jobs))
    print("GATE", "PASS" if all(results) else "FAIL")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
