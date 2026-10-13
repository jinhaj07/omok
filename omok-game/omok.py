from board import Board
from gamemanager import GameManager

import sys

p1 = int(sys.argv[1])
p2 = int(sys.argv[2])
TimeLimit = int(sys.argv[3])

manager = GameManager(p1, p2, TimeLimit)

Player1 = manager.MakePlayer(p1, 0)
Player2 = manager.MakePlayer(p2, 1)

board = Board()

board.GetBoard()
board.PrintBoard()

manager.PlayOmok(TimeLimit)