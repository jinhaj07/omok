"""Tactical regression suite built from real losses (development tool).

harvest: play games against an opponent; in every lost game, find our moves
         that a long search proves were losing while a safe alternative
         existed, and store those positions in tuning/suite.json.
test:    let an agent variant choose a move in every stored position with a
         realistic game clock, and count how often it avoids the losing move.
         Moves never seen before are verified with a long search and cached.

    python3 tools/suite.py harvest --agent smart:vct=5 --games 16
    python3 tools/suite.py test --agent smart:vct=5

A position counts as solved when the chosen move is not proven losing: after
it, a deep search (--verify seconds) for the opponent finds no forced win.
"""
import argparse
import json
import multiprocessing as mp
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import arena  # noqa: E402
from analyze import replay  # noqa: E402
import smartplayerJangJinha as sp  # noqa: E402

SUITE = os.path.join(ROOT, "tuning", "suite.json")
WIN_EDGE = sp.WIN - 100


def load_suite():
    if os.path.exists(SUITE):
        with open(SUITE) as f:
            return json.load(f)
    return []


def save_suite(items):
    os.makedirs(os.path.dirname(SUITE), exist_ok=True)
    with open(SUITE, "w") as f:
        json.dump(items, f)


def deep_player(color, think):
    p = sp.SmartPlayerJangJinha(color, move_time=think, params={"vct": 5})
    return p


def loses(board, color, move, think):
    """True if `move` by `color` is proven losing by a deep opponent search."""
    import copy
    from board import Board
    ref = Board()
    ref._grid = copy.deepcopy(board)
    r, c = move
    ref.PlaceStone(r, c, color)
    ref.TakeStone(r, c, color)
    if ref.CheckOmok(color) and not ref.CheckOmok(1 - color):
        return False
    if ref.CheckOmok(1 - color):
        return True
    opp = deep_player(1 - color, think)
    opp.take_turn(ref.GetBoard(), -1)
    kind, depth, score, nodes = opp.last_info or ("?", 0, 0, 0)
    return kind in ("vcf", "vct") or score >= WIN_EDGE


def _harvest_game(job):
    g, think, last = job
    if g["outcome"] != "loss":
        return []
    a_color = 0 if g["a_black"] else 1
    n_open = len(g["opening"])
    idx = [i for i in range(len(g["history"])) if (n_open + i) % 2 == a_color][-last:]
    found = []
    for i in idx:
        board, color = replay(g["opening"], g["history"], i)
        played = tuple(g["history"][i])
        deep = deep_player(color, think)
        good = tuple(deep.take_turn(board, -1))
        kind, depth, score, nodes = deep.last_info or ("?", 0, 0, 0)
        if good == played or score <= -WIN_EDGE:
            continue
        if not loses(board, color, played, think):
            continue
        if loses(board, color, good, think):
            continue
        found.append({"board": board, "color": color, "bad": list(played), "good": list(good),
                      "moves_played": i // 2, "time_left": 40000,
                      "verified": {f"{played[0]},{played[1]}": True, f"{good[0]},{good[1]}": False}})
    return found


def harvest(args):
    s = arena.run_match(args.agent, args.opponent, args.games, 1, jobs=4,
                        opening_stones=args.openings, seed=args.seed)
    jobs = [(g, args.think, args.last) for g in s["games"]]
    with mp.Pool(2) as pool:
        results = pool.map(_harvest_game, jobs)
    items = load_suite()
    seen = {json.dumps([it["board"], it["color"]]) for it in items}
    added = 0
    for found in results:
        for it in found:
            key = json.dumps([it["board"], it["color"]])
            if key not in seen:
                seen.add(key)
                items.append(it)
                added += 1
    save_suite(items)
    print(f"harvest: {added} new positions, suite size {len(items)}")


def _test_one(job):
    spec, it, verify = job
    p = arena.make_player(spec, it["color"])
    p.moves_played = it["moves_played"]
    mv = tuple(p.take_turn(it["board"], it["time_left"]))
    key = f"{mv[0]},{mv[1]}"
    if key in it["verified"]:
        bad = it["verified"][key]
        fresh = False
    else:
        bad = loses(it["board"], it["color"], mv, verify)
        fresh = True
    return key, bad, fresh


def test(args):
    items = load_suite()
    if not items:
        sys.exit("suite is empty; run harvest first")
    jobs = [(args.agent, it, args.verify) for it in items]
    with mp.Pool(args.jobs) as pool:
        results = pool.map(_test_one, jobs)
    solved = 0
    for it, (key, bad, fresh) in zip(items, results):
        if fresh:
            it["verified"][key] = bad
        solved += not bad
    save_suite(items)
    print(f"{args.agent}: solved {solved}/{len(items)} ({solved / len(items):.0%})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["harvest", "test"])
    ap.add_argument("--agent", default="smart")
    ap.add_argument("--opponent", default="agents/geonwoo2/smartplayerJRM.py")
    ap.add_argument("--games", type=int, default=16)
    ap.add_argument("--openings", type=int, default=0)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--think", type=float, default=8.0, help="deep search seconds")
    ap.add_argument("--verify", type=float, default=6.0)
    ap.add_argument("--last", type=int, default=5)
    ap.add_argument("--jobs", type=int, default=2)
    args = ap.parse_args()
    (harvest if args.mode == "harvest" else test)(args)


if __name__ == "__main__":
    main()
