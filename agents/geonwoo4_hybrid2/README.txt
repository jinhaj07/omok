JRM HYBRID v2 -- OMOK++ AGENT

INSTALL
Copy smartplayerJRM.py and playerJRM.py into your existing game directory,
replacing the previous player files. The class name and interface are unchanged:

    from smartplayerJRM import SmartPlayerJRM
    agent = SmartPlayerJRM(0)  # 0 black; 1 white
    row, col = agent.take_turn(board, remaining_time_ms)

Only these two files are needed to play. Python 3 standard library only.
The board is a 19x19 list: -1 empty, 0 black, 1 white. Coordinates are zero-based.
The time argument is the player's remaining TOTAL GAME clock in milliseconds.
It is not a new allowance per move. -1/None means no external limit, with a
finite internal thinking budget. The supplied board is never modified.

WHAT CHANGED
1. Faster line evaluation. Open threes are derived from three-stone windows
   directly, replacing repeated trial placements and full-line scans. All line
   statistics matched the old implementation on 39,159 patterns, including
   every length-5, length-6 and length-7 pattern. A separate 2,500-line benchmark
   measured about 4x median speed for line evaluation only, not the whole agent.
2. Cached move ordering. Reuse per-line gains and position rankings across
   transpositions. Search the transposition move, killer moves, and moves with
   a successful cutoff history early. Keep capture moves and four-related
   moves outside the normal quiet candidate width.
3. Principal variation search (PVS) and aspiration windows. Promising moves get
   the full search window; other moves first receive a narrow-window search
   and are re-searched when needed. Failed aspiration searches are widened.
4. Tactical quiescence. Continue forcing fours and complete immediate defensive
   replies beyond the normal depth cutoff. A bounded, unsettled frontier is
   an estimate, never labeled a proved mate merely because the limit expired.
5. Time allocation. Reduce routine pre-search scouting, remove repeated final
   VCF scouting, reuse exact tactical caches, and allow one extension when the
   best move changes or its score drops. Only one safe reply returns quickly.
6. Search consistency. Keep the last fully completed root iteration on timeout.
   Separate main-search table entries from scout entries and tactical budgets;
   normalize mate distances when storing and loading table scores.
7. Evaluation trial. Compared the original evaluation with a more defensive
   setting. The original won 5/6 pilot games versus the old hybrid; the
   alternative won 4/6, so the original weights were retained. This is a small
   tuning trial and does not establish optimal weights.

RULES
Pair captures are applied before checking both players. Exactly five contiguous
stones wins; six or more does not. Simultaneous exact fives are a draw. Black
opens in the centre. Immediate wins, complete immediate defences (including
capture-induced draw escapes), and verified forcing wins retain priority.
General search remains selective; it is not an exhaustive solution of Omok++.

WHY THESE CHANGES
The previous 60-game run had 39 wins and 21 losses, with 18 losses as white.
Several logs showed a positive evaluation followed by recognition of a forced
loss. This motivates better tactical frontiers, but does not independently
prove which earlier move was the first decisive mistake. Profiling identified
move ranking and initial VCT scouting as major costs on a sampled loss position.
See development-results.json for the measurements and evaluation-setting trial.

TESTS
From this directory:
    python3 -m unittest discover -p 'tests*.py' -v

23 tests passed. These cover independent rules, captures, exact-five/overlines,
quiet draw escapes, forced defences versus every legal reply, input immutability,
clocks, interrupted undo, fast line features versus trial placements, PVS versus
full two-ply search, tactical horizon cases, and completed-iteration selection.
boardJRM.py is the independent test referee, not an agent dependency.

MATCH VALIDATION
The companion validation-results.json and validation-games/ directory contain
the actual final-version games. Each opponent is tested on three starts, once
per colour: empty board; (9,9),(8,8),(10,9); (9,9),(9,10),(8,9).
The listed moves alternate black, white, black. Each player receives 60 seconds
of thinking time for the continuation. Fresh agents and module caches are used
for each game. Four pairings run on separate CPU cores.
"Hybrid" in the machine-readable logs means this v2 agent; "Hybrid_v1" means
the original uploaded hybrid. Timing and machine load can change decisions.
Small match samples do not establish a guaranteed win rate.

AI DISCLOSURE AND ATTRIBUTION
ChatGPT generated the v2 changes, tests, analysis, and documentation. The base
hybrid adapted the uploaded JangJinha v11 engine and Geonwoo2/Minjun v3 ideas.
The original JangJinha source credits Claude Code and team review. Preserve
these attributions, understand the implementation, and record assistance as
required by your course. This package provides the agent and validation files.

FINAL MEASURED RESULTS (6 GAMES PER OPPONENT)
v2 vs Geonwoo2: 6 wins, 0 losses, 0 draws.
v2 vs Hybrid_v1: 4 wins, 2 losses, 0 draws.
v2 vs JangJinha_v11: 4 wins, 2 losses, 0 draws.
v2 vs Minjun_v3: 6 wins, 0 losses, 0 draws.
Total: 20 wins, 4 losses, 0 draws. All 24 games ended by exact five.
No illegal moves, clock forfeits, input mutations or escaping exceptions.
