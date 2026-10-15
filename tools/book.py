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


def tasks(args):
    with open(args.games) as f:
        games = json.load(f)
    seen = {}
    for g in games:
        if g["outcome"] != "loss":
            continue
        a_color = 0 if g["a_black"] else 1
        hist = [tuple(m) for m in g["history"]]
        for i in range(min(args.plies, len(hist))):
            if i % 2 != a_color:
                continue
            board, color = replay([], hist, i)
            key, _ = canonical(board)
            item = seen.setdefault((key, g["opponent"]), {
                "key": key, "opponent": g["opponent"], "prefix": [list(m) for m in hist[:i]],
                "color": color, "played": list(hist[i]), "losses": 0})
            item["losses"] += 1
    out = []
    for item in seen.values():
        board, color = replay([], [tuple(m) for m in item["prefix"]], len(item["prefix"]))
        cands = candidates_for(args.agent, board, color, args.k)
        played = tuple(item["played"])
        if played not in cands:
            cands = [played] + cands
        for mv in cands:
            out.append({**item, "move": list(mv)})
    with open(args.out, "w") as f:
        json.dump(out, f)
    print(f"{len(seen)} positions, {len(out)} (position, move) tasks")


def run(args):
    with open(args.tasks) as f:
        items = json.load(f)
    shard, nshards = (int(x) for x in args.shard.split("/"))
    jobs, meta = [], []
    for ti, t in enumerate(items):
        for ci, clock in enumerate(CLOCKS):
            idx = ti * len(CLOCKS) + ci
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
    by_pos = {}
    for ti, t in enumerate(items):
        if ti in totals:
            by_pos.setdefault((t["key"], t["opponent"]), []).append((t, totals[ti]))
    book = {}
    if os.path.exists(args.book):
        with open(args.book) as f:
            book = json.load(f)
    report = []
    for (key, opp), rows in by_pos.items():
        played = next((s for t, s in rows if t["move"] == t["played"]), None)
        best_t, best_s = max(rows, key=lambda x: x[1][0] / max(1, x[1][1]))
        line = f"{opp.split('/')[1]:9s} ply {len(best_t['prefix']):2d} played {tuple(best_t['played'])} " \
               f"{played[0] if played else '?'}/{played[1] if played else '?'}  best {tuple(best_t['move'])} " \
               f"{best_s[0]}/{best_s[1]}"
        if played is not None and best_t["move"] != best_t["played"] and best_s[0] >= played[0] + args.margin:
            board, _ = replay([], [tuple(m) for m in best_t["prefix"]], len(best_t["prefix"]))
            k, ti = canonical(board)
            r, c = TRANSFORMS[ti](*best_t["move"])
            book[k] = [r, c]
            line += "  -> BOOK"
        report.append(line)
    print("\n".join(sorted(report)))
    with open(args.book, "w") as f:
        json.dump(book, f, indent=0)
    print(f"book entries: {len(book)}")


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
    ap.add_argument("mode", choices=["collect", "tasks", "run", "build", "embed"])
    ap.add_argument("--agent", default="agents/v13/smartplayerJRM.py")
    ap.add_argument("--pool", nargs="+", default=POOL)
    ap.add_argument("--games", default="tuning/book_games.json")
    ap.add_argument("--tasks", default="tuning/book_tasks.json")
    ap.add_argument("--results", nargs="+", default=["tuning/book_res_*.json"])
    ap.add_argument("--book", default="tuning/book.json")
    ap.add_argument("--out")
    ap.add_argument("--plies", type=int, default=8, help="decisions within the first N plies")
    ap.add_argument("--k", type=int, default=5, help="engine candidates per position")
    ap.add_argument("--shard", default="0/1")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--margin", type=float, default=2.0, help="wins needed over the played move")
    args = ap.parse_args()
    {"collect": collect, "tasks": tasks, "run": run, "build": build, "embed": embed}[args.mode](args)


if __name__ == "__main__":
    main()
