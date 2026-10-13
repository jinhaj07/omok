import time

from board import Board
from humanplayer import HumanPlayer
from randomplayer import RandomPlayer
from simpleplayer import SimplePlayer

# Player code 3: our Game Agent (Project part 2), loaded from ../omok-agent.
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "omok-agent"))
from smartplayerjinhajang import SmartPlayerJinhaJang


class GameManager:
    def __init__(self, p1, p2, TimeLimit):
        self.board = Board()

        self.player1 = self.MakePlayer(p1, 0)
        self.player2 = self.MakePlayer(p2, 1)

        self.currentplayer = 0
        self.TimeLimit = TimeLimit

    def MakePlayer(self, player, color):
        if player == 0:
            return HumanPlayer(color)
        elif player == 1:
            return RandomPlayer(color)
        elif player == 2:
            return SimplePlayer(color)
        elif player == 3:
            return SmartPlayerJinhaJang(color)
        else:
            raise ValueError("Invalid player code")
        

    def PlayOmok(self, TimeLimit):
        # no time limit
        if TimeLimit == -1:
            while True:
                #1. choose current player
                if self.currentplayer == 0:
                    player = self.player1
                else:
                    player = self.player2

                #2. get current board
                board = self.board.GetBoard()
                row, col = player.take_turn(board, -1)

                #3. place the stone
                self.board.PlaceStone(row, col, player.color)
                self.board.TakeStone(row, col, player.color)

                #4. check the winning
                p1_has_omok = self.board.CheckOmok(0)
                p2_has_omok = self.board.CheckOmok(1)

                self.board.PrintBoard()

                if p1_has_omok and p2_has_omok:
                    print("Draw")
                    return None
                elif p1_has_omok:
                    print("Black Wins")
                    return None
                elif p2_has_omok:
                    print("White Wins")
                    return None
                elif self.board.FullBoard():
                    print("Draw")
                    return None

                #5. next player
                self.currentplayer = 1 - self.currentplayer

        # time limit exists
        else:
            TimeLimit = 60 * TimeLimit

            TimeLimit_p1 = TimeLimit
            TimeLimit_p2 = TimeLimit

            while True:
                #1. choose current player
                if self.currentplayer == 0:
                    player = self.player1

                    #2. get current board
                    board = self.board.GetBoard()

                    if not isinstance(player, HumanPlayer):
                        print(f"남은 시간 {TimeLimit_p1:.3f}초")

                    start = time.monotonic()
                    row, col = player.take_turn(board, TimeLimit_p1 * 1000)
                    end = time.monotonic()

                    #3. place the stone
                    if end - start <= TimeLimit_p1:
                        self.board.PlaceStone(row, col, player.color)
                        self.board.TakeStone(row, col, player.color)

                        #4. check the winning
                        p1_has_omok = self.board.CheckOmok(0)
                        p2_has_omok = self.board.CheckOmok(1)

                        self.board.PrintBoard()

                        if p1_has_omok and p2_has_omok:
                            print("Draw")
                            return None
                        elif p1_has_omok:
                            print("Black Wins")
                            return None
                        elif p2_has_omok:
                            print("White Wins")
                            return None
                        elif self.board.FullBoard():
                            print("Draw")
                            return None

                        #5. next player
                        self.currentplayer = 1 - self.currentplayer

                        TimeLimit_p1 = TimeLimit_p1 - (end - start)

                    else:
                        print("Time Out! White Wins")
                        return None

                else:
                    player = self.player2

                    #2. get current board
                    board = self.board.GetBoard()

                    if not isinstance(player, HumanPlayer):
                        print(f"남은 시간 {TimeLimit_p2:.3f}초")

                    start = time.monotonic()
                    row, col = player.take_turn(board, TimeLimit_p2 * 1000)
                    end = time.monotonic()

                    #3. place the stone
                    if end - start <= TimeLimit_p2:
                        self.board.PlaceStone(row, col, player.color)
                        self.board.TakeStone(row, col, player.color)

                        #4. check the winning
                        p1_has_omok = self.board.CheckOmok(0)
                        p2_has_omok = self.board.CheckOmok(1)

                        self.board.PrintBoard()

                        if p1_has_omok and p2_has_omok:
                            print("Draw")
                            return None
                        elif p1_has_omok:
                            print("Black Wins")
                            return None
                        elif p2_has_omok:
                            print("White Wins")
                            return None
                        elif self.board.FullBoard():
                            print("Draw")
                            return None

                        #5. next player
                        self.currentplayer = 1 - self.currentplayer

                        TimeLimit_p2 = TimeLimit_p2 - (end - start)

                    else:
                        print("Time Out! Black Wins")
                        return None
