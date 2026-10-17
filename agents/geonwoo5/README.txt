OMOK_JRM_GEONWOO5

Copy smartplayerJRM.py and playerJRM.py into the existing Omok++ game folder.
Keep these internal filenames and the SmartPlayerJRM class name.
Only these two files are required to play. Python 3 standard library only.

player = SmartPlayerJRM(0)  # 0 black, 1 white
row, column = player.take_turn(board, remaining_total_game_ms)

Board: 19 x 19, -1 empty, 0 black, 1 white. Coordinates are zero-based.
The time argument is the player's TOTAL remaining game time in milliseconds.
A negative value requests a finite internal budget without an external clock.
The input board is never modified. Black opens (9,9); White replies (7,8) when
the only stone is Black's center stone.

All pair captures occur before checking exact five for both colors. Six or
more is not a win; simultaneous exact-five lines are a draw.

Changes: bounded tactical transposition caching; forcing-only default tactical
frontier; measured White opening adjustment. Capture wins, capture defences,
draw escapes and captures in ordinary search remain enabled.

41 tests passed. Fresh validation, 20 games against each opponent, 10 per color,
60 seconds TOTAL per player:
JRM_v15: 10 wins / 10 losses / 0 draws
Geonwoo4: 13 wins / 7 losses / 0 draws
Optimized_Geonwoo3: 13 wins / 7 losses / 0 draws

All 60 games replayed, no timeouts, exceptions or illegal-move forfeits.
These results describe the tested conditions, not a guaranteed win rate.
REPORT.md explains the diagnosis, rejected experiments and reproduction steps.

Current archive: Omok_JRM_Geonwoo5.zip
Next archive: Omok_JRM_Geonwoo6.zip
Increment the filename number for each following release.
