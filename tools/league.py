"""Team league: round-robin between the team's agents (development tool).

Mirrors the course's final stage: every pair plays 8 games (4 as black,
4 as white) with a 1 minute clock; a win is 2 coins, a draw 1 coin. Each
agent is also checked against RandomPlayer and SimplePlayer (>= 5/8 wins).
The top agent becomes the base for the next upgrade round.

    python3 tools/league.py agents/jinha/smartplayerJangJinha.py \
        agents/geonwoo/smartplayergeonwoo.py agents/minjun/smartplayerminjun.py
    python3 tools/league.py smart path/to/other.py --games 8 --jobs 2

Players use arena.py specs (`smart`, a .py path, ...). Results are printed and
saved under league/ as Markdown.
"""
import argparse
import datetime
import itertools
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import arena  # noqa: E402

BAD = ("crash", "timeout", "illegal")


def short(spec):
    base = os.path.basename(spec.split(":")[0]) if ".py" in spec else spec
    return base[:-3] if base.endswith(".py") else base


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("agents", nargs="+")
    ap.add_argument("--games", type=int, default=8)
    ap.add_argument("--time", type=float, default=1)
    ap.add_argument("--jobs", type=int, default=2,
                    help="parallel games; keep <= cores/2 so clocks stay realistic")
    ap.add_argument("--openings", type=int, default=0,
                    help="random opening stones (adds variety between deterministic agents)")
    ap.add_argument("--skip-qualify", action="store_true")
    args = ap.parse_args()

    names = [short(a) for a in args.agents]
    coins = {n: 0 for n in names}
    wdl = {n: [0, 0, 0] for n in names}
    bad = {n: 0 for n in names}
    lines = []

    def record(name, s):
        for k, v in s["reasons"].items():
            if k.startswith("loss:") and k[5:] in BAD:
                bad[name] += v

    if not args.skip_qualify:
        lines.append("## Qualification (need >= 5 wins of 8)\n")
        lines.append("| agent | vs Random W/D/L | vs Simple W/D/L |")
        lines.append("|---|---|---|")
        for spec, name in zip(args.agents, names):
            cells = []
            for opp in ("random", "simple"):
                s = arena.run_match(spec, opp, 8, args.time, jobs=args.jobs)
                record(name, s)
                mark = "" if s["win"] >= 5 else " ❌"
                cells.append(f"{s['win']}/{s['draw']}/{s['loss']}{mark}")
            lines.append(f"| {name} | {cells[0]} | {cells[1]} |")
        lines.append("")

    lines.append("## Head to head (row agent's W/D/L)\n")
    pair_res = {}
    for (i, a), (j, b) in itertools.combinations(enumerate(args.agents), 2):
        s = arena.run_match(a, b, args.games, args.time, jobs=args.jobs,
                            opening_stones=args.openings)
        na, nb = names[i], names[j]
        record(na, s)
        for k, v in s["reasons"].items():
            if k.startswith("win:") and k[4:] in BAD:
                bad[nb] += v
        pair_res[(na, nb)] = (s["win"], s["draw"], s["loss"])
        pair_res[(nb, na)] = (s["loss"], s["draw"], s["win"])
        coins[na] += 2 * s["win"] + s["draw"]
        coins[nb] += 2 * s["loss"] + s["draw"]
        for n, t in ((na, (s["win"], s["draw"], s["loss"])), (nb, (s["loss"], s["draw"], s["win"]))):
            for k in range(3):
                wdl[n][k] += t[k]

    lines.append("| | " + " | ".join(names) + " |")
    lines.append("|---" * (len(names) + 1) + "|")
    for na in names:
        row = [("-" if na == nb else "%d/%d/%d" % pair_res[(na, nb)]) for nb in names]
        lines.append(f"| {na} | " + " | ".join(row) + " |")
    lines.append("\n## Ranking (win = 2 coins, draw = 1)\n")
    lines.append("| rank | agent | coins | W/D/L | crashes/timeouts/illegal |")
    lines.append("|---|---|---|---|---|")
    ranked = sorted(names, key=lambda n: (-coins[n], bad[n]))
    for r, n in enumerate(ranked, 1):
        lines.append(f"| {r} | {n} | {coins[n]} | {'/'.join(map(str, wdl[n]))} | {bad[n]} |")

    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    header = (f"# League {stamp}\n\n{args.games} games per pair, {args.time} min clock, "
              f"openings={args.openings}\n\nAgents:\n" + "\n".join(f"- {n}: `{a}`" for n, a in zip(names, args.agents)) + "\n")
    text = header + "\n" + "\n".join(lines) + "\n"
    print(text)
    os.makedirs(os.path.join(ROOT, "league"), exist_ok=True)
    with open(os.path.join(ROOT, "league", f"league-{stamp}.md"), "w") as f:
        f.write(text)


if __name__ == "__main__":
    main()
