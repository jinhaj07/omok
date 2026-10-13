"""Self-play parameter tuning for SmartPlayerJinhaJang (development tool).

(1+1) hill climbing: each iteration perturbs 1-3 evaluation parameters of the
current best set (multiplicatively, in log space), plays a paired match
(each random opening twice, colours swapped) under a fixed node budget per
move, and accepts the candidate if it scores above the acceptance threshold.

Fixed node budgets make games independent of machine load, so several games
can run in parallel without distorting the result.

    python3 tools/tune.py --iters 30 --games 32 --nodes 3000
    python3 tools/tune.py --resume          # continue from tuning/best.json

Outputs: tuning/best.json (current best params), tuning/log.jsonl (history).
"""
import argparse
import json
import math
import os
import random
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "omok-agent"))

import arena  # noqa: E402
import smartplayerjinhajang as sp  # noqa: E402

TUNABLE = ["w1", "w2", "w3", "w4", "cap", "tempo", "defw", "capb"]
OUT_DIR = os.path.join(ROOT, "tuning")


def spec_for(params, path):
    with open(path, "w") as f:
        json.dump(params, f, indent=1, sort_keys=True)
    return "smart:params=" + os.path.relpath(path, ROOT)


def perturb(params, rng, sigma):
    cand = dict(params)
    keys = rng.sample(TUNABLE, rng.randint(1, 3))
    for k in keys:
        cand[k] = round(cand[k] * math.exp(rng.gauss(0, sigma)), 4)
    return cand, keys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--iters", type=int, default=30)
    ap.add_argument("--games", type=int, default=32)
    ap.add_argument("--nodes", type=int, default=3000)
    ap.add_argument("--openings", type=int, default=4)
    ap.add_argument("--sigma", type=float, default=0.35)
    ap.add_argument("--accept", type=float, default=0.56)
    ap.add_argument("--jobs", type=int, default=None)
    ap.add_argument("--seed", type=int, default=int(time.time()))
    ap.add_argument("--resume", action="store_true")
    args = ap.parse_args()

    os.makedirs(OUT_DIR, exist_ok=True)
    best_path = os.path.join(OUT_DIR, "best.json")
    best = {k: sp.DEFAULT_PARAMS[k] for k in TUNABLE}
    if args.resume and os.path.exists(best_path):
        with open(best_path) as f:
            best.update(json.load(f))
    rng = random.Random(args.seed)
    log_path = os.path.join(OUT_DIR, "log.jsonl")

    for it in range(args.iters):
        cand, keys = perturb(best, rng, args.sigma)
        spec_best = spec_for(best, os.path.join(OUT_DIR, "_best_tmp.json"))
        spec_cand = spec_for(cand, os.path.join(OUT_DIR, "_cand_tmp.json"))
        t0 = time.time()
        res = arena.run_match(spec_cand, spec_best, args.games, time_limit=-1,
                              jobs=args.jobs, nodes=args.nodes,
                              opening_stones=args.openings,
                              seed=rng.randrange(1 << 30), verbose=False)
        score, wdl = res["score"], [res["win"], res["draw"], res["loss"]]
        if score >= args.accept:
            # Confirmation run on fresh openings to filter lucky candidates.
            res2 = arena.run_match(spec_cand, spec_best, args.games, time_limit=-1,
                                   jobs=args.jobs, nodes=args.nodes,
                                   opening_stones=args.openings,
                                   seed=rng.randrange(1 << 30), verbose=False)
            score = (score + res2["score"]) / 2
            wdl = [wdl[0] + res2["win"], wdl[1] + res2["draw"], wdl[2] + res2["loss"]]
        accepted = score >= args.accept
        res = {"score": score, "win": wdl[0], "draw": wdl[1], "loss": wdl[2]}
        entry = {"iter": it, "changed": keys, "score": res["score"],
                 "wdl": [res["win"], res["draw"], res["loss"]],
                 "accepted": accepted, "cand": cand, "best_before": best,
                 "secs": round(time.time() - t0, 1)}
        with open(log_path, "a") as f:
            f.write(json.dumps(entry) + "\n")
        print(f"[{it}] {keys} score={res['score']:.3f} "
              f"W/D/L={res['win']}/{res['draw']}/{res['loss']} "
              f"{'ACCEPT' if accepted else 'reject'} ({entry['secs']}s)", flush=True)
        if accepted:
            best = cand
            with open(best_path, "w") as f:
                json.dump(best, f, indent=1, sort_keys=True)
    print("best:", json.dumps(best, sort_keys=True))


if __name__ == "__main__":
    main()
