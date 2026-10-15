"""Opening-book builder from played-out games (development tool).

Pipeline
  collect  play the agent against a pool on the empty board at many clocks
           (the games are close to deterministic per clock, so clocks give
           the variety) and save the games with their move history.
  tasks    from the collected games, take the agent's early decisions in
           games it lost, and list candidate moves for each (the move it
           played plus the engine's top-ranked alternatives).
  run      play every (position, candidate) out against the opponent that
           produced the position, at every clock; supports sharding so the
           work can be split across machines.
  build    aggregate the results and keep a candidate only when it clearly
           beats the move the agent played; write tuning/book.json.

Positions are keyed by their board contents in a canonical orientation (the
lexicographically smallest of the 8 board symmetries), so a book entry also
covers rotated and mirrored versions of the same position.

    python3 tools/book.py collect --agent agents/v13/smartplayerJRM.py --out tuning/book_games.json
    python3 tools/book.py tasks --games tuning/book_games.json --out tuning/book_tasks.json
    python3 tools/book.py run --tasks tuning/book_tasks.json --shard 0/4 --out tuning/book_res_0.json
    python3 tools/book.py build --tasks tuning/book_tasks.json --results tuning/book_res_*.json
"""
import argparse
import glob
import json
import multiprocessing as mp
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import arena  # noqa: E402
from analyze import replay  # noqa: E402

SIZE = 19
POOL = ["omok-agent/smartplayerJangJinha.py", "agents/geonwoo3/smartplayerJRM.py",
        "agents/geonwoo2/smartplayerJRM.py", "agents/minjun3/smartplayerJRM.py"]
CLOCKS = [0.4, 0.5, 0.6, 0.75, 0.9, 1.0, 1.25, 1.5]

TRANSFORMS = [
    lambda r, c: (r, c), lambda r, c: (c, SIZE - 1 - r),
    lambda r, c: (SIZE - 1 - r, SIZE - 1 - c), lambda r, c: (SIZE - 1 - c, r),
    lambda r, c: (r, SIZE - 1 - c), lambda r, c: (c, r),
    lambda r, c: (SIZE - 1 - r, c), lambda r, c: (SIZE - 1 - c, SIZE - 1 - r),
]


def stones(board):
    return [(r, c, board[r][c]) for r in range(SIZE) for c in range(SIZE) if board[r][c] != -1]


def canonical(board):
    """(key, transform index) of the smallest symmetric image of the board."""
    pts = stones(board)
    best = None
    for i, t in enumerate(TRANSFORMS):
        img = tuple(sorted(t(r, c) + (v,) for r, c, v in pts))
        if best is None or img < best[0]:
            best = (img, i)
    key = ";".join(f"{r},{c},{v}" for r, c, v in best[0])
    return key, best[1]


def clock_list(args):
    return [float(x) for x in args.clocks.split(",")] if args.clocks else CLOCKS


def _play(job):
    return arena.play_game(job)


def collect(args):
    jobs, meta = [], []
    for opp in args.pool:
        for ci, clock in enumerate(CLOCKS):
            for a_black in (True, False):
                black, white = (args.agent, opp) if a_black else (opp, args.agent)
                jobs.append((black, white, clock, [], None, ci))
                meta.append({"opponent": opp, "clock": clock, "a_black": a_black})
    with mp.Pool(args.jobs) as pool:
        results = pool.map(_play, jobs)
    games = []
    for m, res in zip(meta, results):
        a_color = 0 if m["a_black"] else 1
        outcome = "draw" if res["winner"] is None else ("win" if res["winner"] == a_color else "loss")
        games.append({**m, "outcome": outcome, "history": res["history"]})
    with open(args.out, "w") as f:
        json.dump(games, f)
    w = sum(g["outcome"] == "win" for g in games)
    print(f"collected {len(games)} games, agent won {w}")


def candidates_for(agent, board, color, k):
    """The engine's own top-k moves for this position (root ordering)."""
    player = arena.make_player(agent, color)
    eng = player.engine
    eng.load(board)
    me = color + 1
    ranked = eng.score_moves(me, eng.candidates())
    return [divmod(p, SIZE) for _, p in ranked[:k]]


def _inverse(i):
    pts = [(0, 1), (2, 5)]
    return next(j for j in range(8) if all(TRANSFORMS[j](*TRANSFORMS[i](r, c)) == (r, c) for r, c in pts))


INVERSE = [_inverse(i) for i in range(8)]


def tasks(args):
    games = []
    for path in args.games:
        with open(path) as f:
            games += json.load(f)
    # Positions already evaluated in an earlier round are not re-run.
    done = set()
    for path in args.skip or []:
        with open(path) as f:
            done |= {(t["key"], t["opponent"]) for t in json.load(f)}
    seen, freq = {}, {}
    for g in games:
        if g["outcome"] != "loss" and not args.any_outcome:
            continue
        a_color = 0 if g["a_black"] else 1
        hist = [tuple(m) for m in g["history"]]
        for i in range(args.min_ply, min(args.plies, len(hist))):
            if i % 2 != a_color:
                continue
            board, color = replay([], hist, i)
            key, tr = canonical(board)
            if (key, g["opponent"]) in done:
                continue
            freq[key] = freq.get(key, 0) + 1
            item = seen.setdefault((key, g["opponent"]), {
                "key": key, "opponent": g["opponent"], "prefix": [list(m) for m in hist[:i]],
                "color": color, "tr": tr, "seen": {}, "losses": 0})
            item["losses"] += g["outcome"] == "loss"
            # The move this game played, in the orientation of the stored prefix.
            mv = TRANSFORMS[INVERSE[item["tr"]]](*TRANSFORMS[tr](*hist[i]))
            item["seen"][mv] = item["seen"].get(mv, 0) + 1
    out, npos = [], 0
    for item in seen.values():
        if freq[item["key"]] < args.min_count:
            continue
        npos += 1
        board, color = replay([], [tuple(m) for m in item["prefix"]], len(item["prefix"]))
        cands = candidates_for(args.agent, board, color, args.k)
        played_moves = sorted(item["seen"], key=item["seen"].get, reverse=True)
        cands = [m for m in played_moves if m not in cands] + cands
        base = {k: v for k, v in item.items() if k not in ("seen", "tr")}
        base["played"] = list(played_moves[0])
        for mv in cands:
            out.append({**base, "move": list(mv)})
    with open(args.out, "w") as f:
        json.dump(out, f)
    print(f"{npos} positions, {len(out)} (position, move) tasks")


def run(args):
    with open(args.tasks) as f:
        items = json.load(f)
    shard, nshards = (int(x) for x in args.shard.split("/"))
    clocks = clock_list(args)
    jobs, meta = [], []
    for ti, t in enumerate(items):
        for ci, clock in enumerate(clocks):
            idx = ti * len(clocks) + ci
            if idx % nshards != shard:
                continue
            opening = [tuple(m) for m in t["prefix"]] + [tuple(t["move"])]
            a_black = t["color"] == 0
            black, white = (args.agent, t["opponent"]) if a_black else (t["opponent"], args.agent)
            jobs.append((black, white, clock, opening, None, idx))
            meta.append((ti, clock))
    with mp.Pool(args.jobs) as pool:
        results = pool.map(_play, jobs)
    out = []
    for (ti, clock), res in zip(meta, results):
        a_color = items[ti]["color"]
        score = 0.5 if res["winner"] is None else (1.0 if res["winner"] == a_color else 0.0)
        out.append({"task": ti, "clock": clock, "score": score})
    if args.out:
        with open(args.out, "w") as f:
            json.dump(out, f)
    # Compact one-line result, so a remote worker can report it in chat.
    print("RESULT " + json.dumps({"shard": args.shard, "rows": [[r["task"], r["clock"], r["score"]] for r in out]},
                                 separators=(",", ":")))
    # Shorter form of the same rows, in job order (see the import mode).
    print(f"DIGITS {args.shard} " + "".join({1.0: "1", 0.5: "h", 0.0: "0"}[r["score"]] for r in out))


def build(args):
    with open(args.tasks) as f:
        items = json.load(f)
    totals = {}
    for path in sorted(sum((glob.glob(p) for p in args.results), [])):
        with open(path) as f:
            text = f.read().strip()
        # Either a list of {task, clock, score} or a "RESULT {...}" line.
        if text.startswith("RESULT "):
            rows = [{"task": t, "clock": c, "score": s}
                    for t, c, s in json.loads(text[7:])["rows"]]
        else:
            rows = json.loads(text)
        for r in rows:
            s = totals.setdefault(r["task"], [0.0, 0])
            s[0] += r["score"]
            s[1] += 1
    # Group by canonical position across opponents: a position reached
    # against several opponents gets one entry, chosen on the combined games.
    by_key = {}
    for ti, t in enumerate(items):
        if ti not in totals:
            continue
        board, _ = replay([], [tuple(m) for m in t["prefix"]], len(t["prefix"]))
        key, tr = canonical(board)
        move = TRANSFORMS[tr](*t["move"])
        played = TRANSFORMS[tr](*t["played"])
        g = by_key.setdefault(key, {"moves": {}, "played": {}, "ply": len(t["prefix"]), "opps": set()})
        m = g["moves"].setdefault(move, [0.0, 0])
        m[0] += totals[ti][0]
        m[1] += totals[ti][1]
        g["played"][played] = g["played"].get(played, 0) + 1
        g["opps"].add(t["opponent"].split("/")[1])
    book = {}
    if os.path.exists(args.book):
        with open(args.book) as f:
            book = json.load(f)
    report, confirm = [], {}
    for key, g in by_key.items():
        played = max(g["played"], key=g["played"].get)
        # Games from before a book entry existed recorded the engine's old
        # move; the baseline to beat is what the agent plays now.
        if key in book and tuple(book[key]) in g["moves"]:
            played = tuple(book[key])
        ps, pn = g["moves"].get(played, (0.0, 0))
        best, (bs, bn) = max(g["moves"].items(), key=lambda kv: kv[1][0] / max(1, kv[1][1]))
        line = (f"ply {g['ply']:2d} vs {','.join(sorted(g['opps'])):40s} played {played} {ps}/{pn}"
                f"  best {best} {bs}/{bn}")
        if not pn or best == played or bs / bn - ps / pn < args.gain:
            report.append(line)
            continue
        # One-sided two-proportion z score of best over played.
        pool = (bs + ps) / (bn + pn)
        z = (bs / bn - ps / pn) / max(1e-9, (pool * (1 - pool) * (1 / bn + 1 / pn)) ** 0.5)
        line += f"  z {z:.2f}"
        if args.confirm_out:
            # Screening round: re-test best against played on fresh games.
            confirm[key] = (best, played)
            line += "  -> CONFIRM"
        elif bs - ps * bn / pn >= args.margin and (args.z is None or z >= args.z):
            book[key] = list(best)
            line += "  -> BOOK"
        report.append(line)
    if args.confirm_out:
        keep = []
        for t in items:
            board, _ = replay([], [tuple(m) for m in t["prefix"]], len(t["prefix"]))
            key, tr = canonical(board)
            if key in confirm and TRANSFORMS[tr](*t["move"]) in confirm[key]:
                keep.append({**t, "played": list(TRANSFORMS[INVERSE[tr]](*confirm[key][1]))})
        with open(args.confirm_out, "w") as f:
            json.dump(keep, f)
        print(f"{len(confirm)} positions to confirm, {len(keep)} tasks -> {args.confirm_out}")
    print("\n".join(sorted(report)))
    if args.confirm_out:
        return
    with open(args.book, "w") as f:
        json.dump(book, f, indent=0)
    print(f"book entries: {len(book)}")


def import_digits(args):
    """Rebuild a shard's rows from a compact score string ('1' win, 'h' draw,
    '0' loss) in the shard's fixed job order, as reported by a remote worker."""
    with open(args.tasks) as f:
        items = json.load(f)
    shard, nshards = (int(x) for x in args.shard.split("/"))
    clocks = clock_list(args)
    order = [(ti, clock) for ti in range(len(items)) for ci, clock in enumerate(clocks)
             if (ti * len(clocks) + ci) % nshards == shard]
    digits = args.digits.strip()
    if len(digits) != len(order):
        sys.exit(f"length mismatch: {len(digits)} digits for {len(order)} games")
    value = {"1": 1.0, "h": 0.5, "0": 0.0}
    rows = [{"task": ti, "clock": clock, "score": value[d]} for (ti, clock), d in zip(order, digits)]
    with open(args.out, "w") as f:
        json.dump(rows, f)
    print(f"shard {args.shard}: {len(rows)} rows, score {sum(r['score'] for r in rows)}")


def embed(args):
    """Write tuning/book.json into the agent file between the BOOK markers."""
    with open(args.book) as f:
        book = json.load(f)
    with open(args.agent) as f:
        src = f.read()
    start = "# --- OPENING BOOK (generated by tools/book.py embed; do not edit by hand) ---\n"
    end = "# --- END OPENING BOOK ---"
    a, b = src.index(start) + len(start), src.index(end)
    body = "BOOK = {\n" + "".join(f"    {k!r}: ({v[0]}, {v[1]}),\n" for k, v in sorted(book.items())) + "}\n"
    with open(args.agent, "w") as f:
        f.write(src[:a] + body + src[b:])
    print(f"embedded {len(book)} entries into {args.agent}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["collect", "tasks", "run", "build", "embed", "import"])
    ap.add_argument("--digits", help="import: the compact score string from a worker")
    ap.add_argument("--agent", default="agents/v13/smartplayerJRM.py")
    ap.add_argument("--pool", nargs="+", default=POOL)
    ap.add_argument("--games", nargs="+", default=["tuning/book_games.json"])
    ap.add_argument("--tasks", default="tuning/book_tasks.json")
    ap.add_argument("--results", nargs="+", default=["tuning/book_res_*.json"])
    ap.add_argument("--book", default="tuning/book.json")
    ap.add_argument("--out")
    ap.add_argument("--plies", type=int, default=8, help="decisions within the first N plies")
    ap.add_argument("--skip", nargs="+", help="tasks: task files of earlier rounds whose positions to skip")
    ap.add_argument("--any-outcome", action="store_true", help="tasks: use won games too, not only losses")
    ap.add_argument("--min-count", type=int, default=1, help="tasks: positions seen at least this often")
    ap.add_argument("--min-ply", type=int, default=0, help="tasks: skip decisions before this ply")
    ap.add_argument("--z", type=float, help="build: also require this z score of best over played")
    ap.add_argument("--confirm-out", help="build: write best-vs-played re-test tasks instead of a book")
    ap.add_argument("--k", type=int, default=5, help="engine candidates per position")
    ap.add_argument("--shard", default="0/1")
    ap.add_argument("--clocks", help="run/import: comma-separated minutes (default: CLOCKS)")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--margin", type=float, default=2.0, help="wins needed over the played move")
    ap.add_argument("--gain", type=float, default=0.2, help="win-rate gain needed over the played move")
    args = ap.parse_args()
    {"collect": collect, "tasks": tasks, "run": run, "build": build, "embed": embed,
     "import": import_digits}[args.mode](args)


if __name__ == "__main__":
    main()
