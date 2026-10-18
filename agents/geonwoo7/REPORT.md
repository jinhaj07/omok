# Omok_JRM_Geonwoo7 — measured comparison

The final release played 40 fresh games against the exact uploaded JRM v15: **26 wins, 14 losses, 0 draws**.

| Geonwoo7 side | Games | Wins | Losses | Draws |
|---|---:|---:|---:|---:|
| Black | 20 | 19 | 1 | 0 |
| White | 20 | 7 | 13 | 0 |
| All | 40 | 26 | 14 | 0 |

## Changes and reason

The uploaded engine already implemented a guarded partial-root policy, but disabled it. Geonwoo7 enables it. If a deeper iteration times out after a later candidate has finished its PVS evaluation above the previous best at that same depth, the search can retain the better candidate. An interrupted candidate is not eligible. The previous best must have an exact in-window score, and a previous iteration must have completed. This is a search comparison, not a proof of a forced win.

At a 60-second starting clock, White now plays the searched first reply instead of sometimes overriding it with a random knight-offset reply. The original low-clock knight shortcut remains available below 54 seconds.

The release retains the uploaded evaluator, captures, exact-five rules, PVS,
transposition tables, tactical search, and time allocation. Extra bit-mask,
capture-batching, and candidate-cache experiments did not consistently improve
the measurements, so they were excluded. No general calculation-speed increase
is claimed for the delivered release.

## Final test conditions

- 40 games total, with Geonwoo7 playing 20 as Black and 20 as White.
- 60 seconds **total per player per game**, not per move.
- Only the two automated SmartPlayerJRM agents played; no SimplePlayer or RandomPlayer.
- Empty 19 × 19 boards; any legal opening is permitted by the supplied game manager.
- Captures are applied before exact-five checks for both colors. Simultaneous fives draw.
- Source was frozen before the final games; the original opponent was unchanged.
- The seed base was 2026111800; per-game seeds are recorded.
- Paired games swap colors and reuse opening RNG streams by color.
- Each game creates fresh players and clears module-level search caches.
- Games ran on separate CPU-pinned worker processes; both players in a game used the same CPU.
- All 40 move logs were replayed with independent capture and exact-five checks.
- There were no illegal-move, timeout, or exception forfeits.

## Development selection, excluded from the final 40

First round (8 games per candidate): full optimization bundle 4–4;
the bundle plus partial-root policy 7–1; the bundle with tactical depth 6 was 5–3.
Second round on a different seed set: bundle plus partial-root policy 3–5;
smaller optimization bundle plus partial-root policy 3–5;
original evaluator plus partial-root policy 4–4.
The original evaluator was retained. The small early 7–1 result did not reproduce.

A final four-game White-only diagnostic, reusing the second-round opening seeds, scored 1 win and 3 losses with the searched opening, versus 0 wins and 4 losses for the partial-only candidate. The searched opening was selected; this small diagnostic is not conclusive evidence of general opening superiority.

The final seed set was separate from all development games. There were 52
development games in total, excluded from the requested final 40.
Full development records and source variants are in validation/development/.

## Diagnostics and limits

The improved agent actually played a partial-root replacement on
72 turns. Its average completed main-search depth
was 5.20 plies; the maximum completed main
depth was 10. The engine uses adaptive depth,
up to 20 main plies, with tactical continuations; it is not a guarantee of a
fixed depth on every move. One ply means one move by either player. When a
partial-root replacement is used, the diagnostic score and depth still refer
to the last fully completed iteration; `partial` identifies the replacement.

The unit-test output is in unit-test-results.txt. Tests cover capture directions,
exact-five versus overlines, simultaneous-win draws, defence by capture, draw
escapes, unchanged input boards, clocks, undo on interruption, and the guarded
partial-root timeout cases. These checks do not prove absence of all bugs.
The original broad exception fallback remains, so absence of exception
forfeits does not establish that no internally caught exception ever occurred.

These are 20 paired opening streams against one opponent on one machine.
Some openings repeat. This result is not a population win probability, a
statistical significance claim, or a guarantee against other opponents or clocks.
Wall-clock-limited searches can choose differently on another machine even
with the same opening seeds. The logged games, unlike a new timed run, are
exactly replayable.

## Reproduce and inspect

From the package folder:

```bash
python3 -m unittest tests_hybrid tests_geonwoo7 tests_partial -v
cd validation
python3 replay_results.py final-results.json
python3 run_matches.py --schedule schedule.json --out new-run.json --seed-base 2026111800
```

The match runner requires Linux/WSL for CPU affinity and timer signals.
The agent itself uses the Python standard library. `changes-from-upload.diff`
shows every delivered source change. Original attribution is retained.

Uploaded smartplayerJRM.py SHA-256:
`7ac5d21e8602238d86e5ff63c67e28df35d1d9080cb0143129ba0014d285e5be`

Released smartplayerJRM.py SHA-256:
`81510590fad74947a490a994d764b1c0050e70053cdd979e6dba6d7cd705e82d`

Next requested version name: **Omok_JRM_Geonwoo8.zip**.
