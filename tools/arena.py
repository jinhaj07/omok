"""Headless match runner for Omok++ agents (development tool, not submitted).

Plays games with the same rules and clock semantics as the team's
GameManager (total time per player for the whole game, measured around each
take_turn call), but without printing boards, and reports results.

Examples (from the repository root):
    python3 tools/arena.py smart random --games 8
    python3 tools/arena.py smart simple --games 8 --time 60
    python3 tools/arena.py "smart:params=tuning/best.json" smart --games 40 --nodes 4000
    python3 tools/arena.py smart simple --games 8 --time 30 --jobs 1   # slow-machine check

Player specs:
    random | simple | smart[:key=value,...]
    smart options: params=<json file>, depth=<int>, nodes=<int>, movetime=<sec>,
                   and any DEFAULT_PARAMS key, e.g. smart:w3=120,cap=200
"""
import argparse
import json
import multiprocessing as mp
import os
import random
import sys
import time
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "omok-agent"))
sys.path.insert(0, os.path.join(ROOT, "omok-game"))

from board import Board  # noqa: E402
from randomplayer import RandomPlayer  # noqa: E402
from simpleplayer import SimplePlayer  # noqa: E402
import smartplayerjinhajang as sp  # noqa: E402

SIZE = 19


def make_player(spec, color, nodes=None):
    name, _, opts = spec.partition(":")
    if name == "random":
        return RandomPlayer(color)
    if name == "simple":
        return SimplePlayer(color)
    if name != "smart":
        raise ValueError("unknown player " + spec)
    params, kwargs = {}, {}
    if nodes is not None:
        kwargs["node_limit"] = nodes
    for item in filter(None, opts.split(",")):
        k, _, v = item.partition("=")
        if k == "params":
            with open(os.path.join(ROOT, v) if not os.path.isabs(v) else v) as f:
                params.update(json.load(f))
        elif k == "depth":
            kwargs["max_depth"] = int(v)
        elif k == "nodes":
            kwargs["node_limit"] = int(v)
        elif k == "movetime":
            kwargs["move_time"] = float(v)
        else:
            params[k] = float(v) if "." in v else int(v)
    return sp.SmartPlayerJinhaJang(color, params=params, **kwargs)


def play_game(job):
    """Returns a dict describing one finished game."""
    spec_black, spec_white, time_limit, opening, nodes, seed = job
    random.seed(seed)
    ref = Board()
    players = [make_player(spec_black, 0, nodes), make_player(spec_white, 1, nodes)]
    clocks = [time_limit * 60.0 if time_limit > 0 else None] * 2
    max_move = [0.0, 0.0]
    moves = 0
    color = 0
    for r, c in opening:
        ref.PlaceStone(r, c, color)
        ref.TakeStone(r, c, color)
        color = 1 - color
        moves += 1

    def result(winner, reason):
        return {"winner": winner, "reason": reason, "moves": moves,
                "max_move": max_move, "used": [
                    (time_limit * 60.0 - c) if c is not None else None for c in clocks]}

    while True:
        player = players[color]
        board = ref.GetBoard()
        t_ms = clocks[color] * 1000 if clocks[color] is not None else -1
        start = time.monotonic()
        try:
            r, c = player.take_turn(board, t_ms)
        except Exception:
            traceback.print_exc()
            return result(1 - color, "crash")
        spent = time.monotonic() - start
        max_move[color] = max(max_move[color], spent)
        if clocks[color] is not None:
            if spent > clocks[color]:
                return result(1 - color, "timeout")
            clocks[color] -= spent
        try:
            r, c = int(r), int(c)
            if not ref.ValidPosition(r, c):
                raise ValueError
        except Exception:
            return result(1 - color, "illegal")
        ref.PlaceStone(r, c, color)
        ref.TakeStone(r, c, color)
        moves += 1
        b5, w5 = ref.CheckOmok(0), ref.CheckOmok(1)
        if b5 and w5:
            return result(None, "double-five")
        if b5:
            return result(0, "five")
        if w5:
            return result(1, "five")
        if ref.FullBoard():
            return result(None, "full")
        color = 1 - color


def random_opening(rng, n):
    """n stones near the centre, alternating colours, no captures/fives."""
    stones = []
    used = set()
    while len(stones) < n:
        r, c = rng.randint(6, 12), rng.randint(6, 12)
        if (r, c) not in used:
            used.add((r, c))
            stones.append((r, c))
    return stones


def run_match(spec_a, spec_b, games, time_limit=1, jobs=None, nodes=None,
              opening_stones=0, seed=0, verbose=True):
    """Play `games` games, alternating colours; with openings, each opening
    is played twice with colours swapped. Returns a summary dict for A."""
    rng = random.Random(seed)
    job_list = []
    for g in range(games):
        if opening_stones and g % 2 == 0:
            opening = random_opening(rng, opening_stones)
        elif not opening_stones:
            opening = []
        a_black = g % 2 == 0
        black, white = (spec_a, spec_b) if a_black else (spec_b, spec_a)
        job_list.append(((black, white, time_limit, opening, nodes, seed * 1000 + g), a_black))
    jobs = jobs or max(1, mp.cpu_count())
    with mp.Pool(jobs) as pool:
        results = pool.map(play_game, [j for j, _ in job_list])

    summary = {"win": 0, "draw": 0, "loss": 0, "a_black": [0, 0, 0], "a_white": [0, 0, 0],
               "reasons": {}, "max_move_a": 0.0, "max_used_a": 0.0, "games": []}
    for (job, a_black), res in zip(job_list, results):
        a_color = 0 if a_black else 1
        if res["winner"] is None:
            outcome = "draw"
        elif res["winner"] == a_color:
            outcome = "win"
        else:
            outcome = "loss"
        summary[outcome] += 1
        idx = {"win": 0, "draw": 1, "loss": 2}[outcome]
        summary["a_black" if a_black else "a_white"][idx] += 1
        key = outcome + ":" + res["reason"]
        summary["reasons"][key] = summary["reasons"].get(key, 0) + 1
        summary["max_move_a"] = max(summary["max_move_a"], res["max_move"][a_color])
        if res["used"][a_color] is not None:
            summary["max_used_a"] = max(summary["max_used_a"], res["used"][a_color])
        summary["games"].append({"a_black": a_black, "outcome": outcome, **res})
    n = games
    summary["score"] = (summary["win"] + 0.5 * summary["draw"]) / n if n else 0.0
    if verbose:
        print(f"{spec_a}  vs  {spec_b}   ({games} games, time={time_limit}min, nodes={nodes})")
        print(f"  W/D/L = {summary['win']}/{summary['draw']}/{summary['loss']}"
              f"   score={summary['score']:.3f}")
        print(f"  as black W/D/L = {summary['a_black']}   as white W/D/L = {summary['a_white']}")
        print(f"  reasons: {summary['reasons']}")
        print(f"  A max single move: {summary['max_move_a']:.2f}s"
              f"   A max total used: {summary['max_used_a']:.2f}s")
    return summary


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("a")
    ap.add_argument("b")
    ap.add_argument("--games", type=int, default=8)
    ap.add_argument("--time", type=float, default=1, help="minutes per player per game (-1: none)")
    ap.add_argument("--jobs", type=int, default=None)
    ap.add_argument("--nodes", type=int, default=None, help="node limit per move for smart players")
    ap.add_argument("--openings", type=int, default=0, help="random opening stones")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--json", help="write full summary to this file")
    args = ap.parse_args()
    s = run_match(args.a, args.b, args.games, args.time, args.jobs, args.nodes,
                  args.openings, args.seed)
    if args.json:
        with open(args.json, "w") as f:
            json.dump(s, f, indent=1)


if __name__ == "__main__":
    main()
