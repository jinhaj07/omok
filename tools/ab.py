"""Large A/B comparison of agent variants against a pool (development tool).

A config file names the variants (agent specs, see arena.py, e.g.
"agents/v13/smartplayerJRM.py@tscale=1.5"), the opponent pool and the clocks.
Every variant plays every opponent at every clock with both colours, `reps`
times. The work is split into shards so remote workers can each run one and
report a compact result line; the variant is the innermost loop, so every
shard holds an even mix of variants.

    python3 tools/ab.py run --config tuning/ab1.json --shard 3/9 --jobs 4
        -> prints "DIGITS 3/9 1h0t..." ('1' variant won, 'h' draw, '0' lost,
           't' lost by its own timeout, crash or illegal move)
    python3 tools/ab.py report --config tuning/ab1.json --digits tuning/ab1_digits_*.txt
"""
import argparse
import glob
import json
import math
import random
import multiprocessing as mp
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import arena  # noqa: E402


def load(path):
    with open(path) as f:
        cfg = json.load(f)
    lo, hi, n = cfg["clocks"]
    cfg["clock_list"] = [round(lo + (hi - lo) * i / (n - 1), 3) for i in range(n)]
    return cfg


def jobs(cfg):
    """All games in a fixed order: (variant, opponent, clock, variant_black).
    Optional "colours": [false] plays the variants as white only."""
    out = []
    for rep in range(cfg.get("reps", 1)):
        for clock in cfg["clock_list"]:
            for opp in cfg["pool"]:
                for black in cfg.get("colours", (True, False)):
                    for name in cfg["variants"]:
                        out.append((name, opp, clock, black))
    return out


def opening(cfg, index):
    """Optional "openings": [n, ...] starts every game from n random stones
    near the centre (n cycling over the list). All colours and variants of
    one (rep, clock, opponent) group share the opening, so comparisons stay
    paired while each group gets a fresh position."""
    sizes = cfg.get("openings")
    if not sizes:
        return []
    group = index // (len(cfg.get("colours", (True, False))) * len(cfg["variants"]))
    rng = random.Random(cfg.get("opening_seed", 1) * 1000003 + group)
    return arena.random_opening(rng, sizes[group % len(sizes)])


def _play(job):
    return arena.play_game(job)


def run(args):
    cfg = load(args.config)
    shard, n = (int(x) for x in args.shard.split("/"))
    mine = [(i, j) for i, j in enumerate(jobs(cfg)) if i % n == shard]
    games = []
    for k, (i, (name, opp, clock, black)) in enumerate(mine):
        spec = cfg["variants"][name]
        b, w = (spec, opp) if black else (opp, spec)
        games.append((b, w, clock, opening(cfg, i), None, k))
    mine = [j for _, j in mine]
    with mp.Pool(args.jobs) as pool:
        results = pool.map(_play, games)
    digits = []
    for (name, opp, clock, black), res in zip(mine, results):
        me = 0 if black else 1
        if res["winner"] is None:
            digits.append("h")
        elif res["winner"] == me:
            digits.append("1")
        else:
            # 't': lost by the variant's own crash, timeout or illegal move.
            digits.append("t" if res["reason"] in ("crash", "timeout", "illegal") else "0")
    print(f"DIGITS {args.shard} " + "".join(digits))


def report(args):
    cfg = load(args.config)
    all_jobs = jobs(cfg)
    score, faults = {}, {}
    for path in sorted(sum((glob.glob(p) for p in args.digits), [])):
        with open(path) as f:
            tag, shard_s, digits = f.read().split()
        assert tag == "DIGITS", path
        shard, n = (int(x) for x in shard_s.split("/"))
        mine = [j for i, j in enumerate(all_jobs) if i % n == shard]
        if len(mine) != len(digits):
            sys.exit(f"{path}: {len(digits)} digits for {len(mine)} games")
        for (name, opp, clock, black), d in zip(mine, digits):
            v = {"1": 1.0, "h": 0.5, "0": 0.0, "t": 0.0}[d]
            for key in ((name,), (name, opp), (name, "black" if black else "white")):
                s = score.setdefault(key, [0.0, 0])
                s[0] += v
                s[1] += 1
            if d == "t":
                faults[name] = faults.get(name, 0) + 1
    names = list(cfg["variants"])
    base = names[0]
    opps = cfg["pool"]
    head = f"{'variant':10s} {'total':>14s}  " + "  ".join(f"{o.split('/')[-2][:10]:>10s}" for o in opps)
    print(head + f"  {'black':>9s} {'white':>9s}  vs {base}")
    bs, bn = score.get((base,), (0, 0))
    for name in names:
        s, n = score.get((name,), (0, 0))
        if not n:
            continue
        cols = "  ".join("%10s" % ("%g/%d" % tuple(score.get((name, o), (0, 0)))) for o in opps)
        col = "  ".join("%9s" % ("%g/%d" % tuple(score.get((name, c), (0, 0)))) for c in ("black", "white"))
        diff = ""
        if name != base and bn:
            p1, p0 = s / n, bs / bn
            se = math.sqrt(p1 * (1 - p1) / n + p0 * (1 - p0) / bn) or 1e-9
            diff = f"{p1 - p0:+.3f} (z {(p1 - p0) / se:+.2f})"
        flt = f"  timeouts/crashes {faults[name]}" if faults.get(name) else ""
        print(f"{name:10s} {s:6g}/{n:<4d} {s / n:.3f}  {cols}  {col}  {diff}{flt}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["run", "report", "count"])
    ap.add_argument("--config", required=True)
    ap.add_argument("--shard", default="0/1")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--digits", nargs="+", default=[])
    args = ap.parse_args()
    if args.mode == "run":
        run(args)
    elif args.mode == "report":
        report(args)
    else:
        cfg = load(args.config)
        print(len(jobs(cfg)), "games;", len(cfg["variants"]), "variants; clocks", cfg["clock_list"])


if __name__ == "__main__":
    main()
