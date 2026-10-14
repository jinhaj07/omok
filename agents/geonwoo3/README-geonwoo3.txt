JRM HYBRID OMOK++ AGENT

Install
-------
Copy smartplayerJRM.py and playerJRM.py into your game folder, replacing the
previous copies. Keep these filenames. Existing GameManager code that imports
SmartPlayerJRM and uses player code 3 remains compatible.

Interface
---------
from smartplayerJRM import SmartPlayerJRM
agent = SmartPlayerJRM(0)  # 0 black, 1 white
row, column = agent.take_turn(board, remaining_time_ms)

The board is 19x19: -1 empty, 0 black, 1 white. Coordinates are zero-based.
Time is the player's remaining TOTAL GAME time in milliseconds, not a fresh
per-move allowance. -1 means no external limit (internal thinking is finite).
The supplied board is not modified. No packages beyond Python's standard
library are needed. Only the two player files are required for competition.

Move priorities
---------------
1. Complete exactly five after applying all captures; avoid confusing a draw
   with a win when captures expose the opponent's exact five.
2. Prevent an immediate enemy win: block, capture the threatening stones, or
   use a quiet move that converts the enemy's winning capture to a draw.
3. Find forcing-four/threat sequences. A selective search suggests a move;
   bounded verification checks every legal defender reply before labeling a
   forcing-four sequence as verified. An unfinished verification is unknown.
4. Build multiple threats, open/broken threes, and useful line extensions.
5. Capture when removal actually improves the position, and penalize pairs
   that are vulnerable to capture. Placement is judged after captures.
6. Check the chosen move for immediate losses and verified enemy forcing
   replies; retain a legal alternative if thinking time expires.

How these priorities are calculated
----------------------------------
The engine derives from the uploaded JangJinha v11 agent: integer-encoded
line features, caching, incremental updates, undoable captures, Zobrist
transposition tables, iterative-deepening negamax, alpha-beta pruning,
continuous-four/continuous-threat scouting, and widening of losing searches.
The evaluation compares friendly and enemy five-cell windows and adds bonuses
for open threes, capture opportunities and threats on multiple lines.

The bounded forcing verifier follows Minjun v3's approach: selective attacker
options, every legal defender reply, finite time and node budgets. A reply
that cannot block, capture, counter-win or create a draw is ruled out by
complete tactical analysis, avoiding unnecessary board simulations. It can
prove a short forcing-four sequence; failure to find one is not a proof that
the move loses. Longer unverified tactical hints still enter the normal
search ordering and compete with alternatives.

The clock uses Geonwoo2's conservative approach, with a modest increase when
the board contains tactical pressure. Typical planned time is capped at 2.4
seconds, pressure can raise the hard cap to 3.2 seconds, and small remaining
clocks reduce the budget. Early positions use shorter limits. One extension
is allowed when completed search iterations change the preferred move or
substantially lower its score; the hard deadline is unchanged.

Additional corrections
----------------------
- All temporary moves are undone in finally blocks, including interrupted
  root search and tactical scouting.
- Winning endpoints are checked after captures when necessary.
- Defence includes capture-induced draw escapes adapted from Geonwoo/Minjun.
- Transposition-table terminal distances are normalized for the current ply.
- Pair vulnerability penalties are scaled to this engine's evaluation units.

Verification
------------
Run: python3 tests_hybrid.py
boardJRM.py is only the independent test referee; the agent does not import it.
Tests cover randomized rule/cache/undo equivalence, exact-five and overlines,
multi-direction capture, simultaneous-five draws, capture-based defence,
quiet draw escapes, proof refutations, interrupted searches, clocks and input
immutability. validation-results.json contains the actual comparison games.
Small match samples do not guarantee superiority against every opponent.

AI disclosure
-------------
ChatGPT generated this hybrid, tests and supporting documentation using the
uploaded Geonwoo2, Minjun v3 and JangJinha v11 agents as references. JangJinha's
original file credits Claude Code and team review. Preserve these attributions,
review the implementation, and include the assistance in your course record.
This package is an agent deliverable; it does not claim to include every
document required by your professor's complete submission instructions.

Final validation results
------------------------
15 tests passed. Six games against each original agent, 60 seconds per player,
three games per color. Hybrid results: Geonwoo2 3 wins / 3 losses;
Minjun v3 6 wins / 0 losses; JangJinha v11 6 wins / 0 losses.
All games ended by exact five. No illegal moves, clock forfeits or escaping
exceptions occurred. These are small samples from empty-board starts.
The three Geonwoo losses all occurred with the hybrid playing black.
