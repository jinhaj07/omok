"""Rule and engine consistency tests for SmartPlayerJinhaJang.

Run from the repository root:  python3 -m unittest discover -s tests
"""
import os
import random
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "omok-agent"))
sys.path.insert(0, os.path.join(ROOT, "omok-game"))

from board import Board  # noqa: E402  (team's game infrastructure referee)
import smartplayerjinhajang as sp  # noqa: E402

SIZE = sp.SIZE


def empty_board():
    return [[-1] * SIZE for _ in range(SIZE)]


def engine_from(board):
    e = sp._Engine(dict(sp.DEFAULT_PARAMS))
    e.load(board)
    return e


def snapshot(e):
    return (list(e.cells), list(e.lk), list(e.nb), list(e.F), list(e.NW),
            round(e.E[1], 6), round(e.E[2], 6), e.h, e.stones)


class RuleTests(unittest.TestCase):
    def test_capture_horizontal(self):
        b = empty_board()
        b[9][9] = 0
        b[9][10] = 1
        b[9][11] = 1
        e = engine_from(b)
        cap = e.make(9 * SIZE + 12, 1)  # black closes X O O X
        self.assertEqual(sorted(cap), [9 * SIZE + 10, 9 * SIZE + 11])
        self.assertEqual(e.cells[9 * SIZE + 10], 0)

    def test_no_capture_when_filling_middle(self):
        b = empty_board()
        b[9][9] = 1
        b[9][11] = 1
        b[9][8] = 0
        b[9][12] = 0
        e = engine_from(b)
        self.assertIsNone(e.make(9 * SIZE + 10, 2))

    def test_no_capture_of_three(self):
        b = empty_board()
        b[9][9] = 0
        for c in (10, 11, 12):
            b[9][c] = 1
        e = engine_from(b)
        self.assertIsNone(e.make(9 * SIZE + 13, 1))

    def test_exact_five_and_overline(self):
        b = empty_board()
        for c in range(3, 7):
            b[5][c] = 0
        e = engine_from(b)
        self.assertIn(5 * SIZE + 7, e.win_points(1))
        self.assertIn(5 * SIZE + 2, e.win_points(1))
        b[5][8] = 0  # X X X X _ X : filling the gap makes six
        e = engine_from(b)
        self.assertNotIn(5 * SIZE + 7, e.win_points(1))
        cap = e.make(5 * SIZE + 7, 1)
        self.assertEqual(e.F[1], 0)
        e.unmake(5 * SIZE + 7, 1, cap)

    def test_capture_turns_six_into_five_for_opponent(self):
        # White overline on row 4 (columns 2..8). Black captures the vertical
        # pair (4,3)-(5,3), which leaves white an exact five on columns 4..8.
        b = empty_board()
        for c in range(2, 9):
            b[4][c] = 1
        b[5][3] = 1
        b[3][3] = 0
        e = engine_from(b)
        self.assertEqual(e.F[2], 0)
        e.make(6 * SIZE + 3, 1)
        self.assertEqual(e.F[2], 1)
        s = sp._Searcher(e)
        self.assertEqual(s._after_move(1, 1), -(sp.WIN - 1))


class ConsistencyTests(unittest.TestCase):
    def test_random_games_match_referee(self):
        rng = random.Random(7)
        for game in range(40):
            ref = Board()
            e = sp._Engine(dict(sp.DEFAULT_PARAMS))
            color = 0
            for move in range(160):
                empties = [(r, c) for r in range(SIZE) for c in range(SIZE)
                           if ref.ValidPosition(r, c)]
                # bias toward a crowded region so captures and fives happen
                near = [(r, c) for r, c in empties if 6 <= r <= 12 and 6 <= c <= 12]
                r, c = rng.choice(near or empties)
                ref.PlaceStone(r, c, color)
                ref.TakeStone(r, c, color)
                e.make(r * SIZE + c, color + 1)
                grid = ref.GetBoard()
                fresh = engine_from(grid)
                self.assertEqual(snapshot(e)[:2], snapshot(fresh)[:2])
                self.assertEqual(e.F, fresh.F)
                self.assertEqual(e.NW, fresh.NW)
                self.assertEqual(bool(e.F[1]), ref.CheckOmok(0), (game, move))
                self.assertEqual(bool(e.F[2]), ref.CheckOmok(1), (game, move))
                if ref.CheckOmok(0) or ref.CheckOmok(1):
                    break
                color = 1 - color

    def test_make_unmake_restores_state(self):
        rng = random.Random(3)
        for _ in range(20):
            b = empty_board()
            for _ in range(rng.randint(10, 60)):
                r, c = rng.randint(5, 13), rng.randint(5, 13)
                b[r][c] = rng.randint(0, 1)
            e = engine_from(b)
            before = snapshot(e)
            for p in e.candidates()[:30]:
                for me in (1, 2):
                    cap = e.make(p, me)
                    e.unmake(p, me, cap)
                    self.assertEqual(snapshot(e), before)


class PlayerTests(unittest.TestCase):
    def test_takes_immediate_win(self):
        b = empty_board()
        for c in range(5, 9):
            b[9][c] = 0
        b[10][5] = b[10][6] = b[11][7] = 1
        p = sp.SmartPlayerJinhaJang(0)
        self.assertIn(p.take_turn(b, 60000), [(9, 4), (9, 9)])

    def test_blocks_four(self):
        b = empty_board()
        b[0][5] = 0               # far away black stone
        for c in range(5, 9):
            b[9][c] = 0
        b[9][4] = 1
        b[3][3] = b[15][15] = 1
        p = sp.SmartPlayerJinhaJang(1)
        self.assertEqual(p.take_turn(b, 60000), (9, 9))

    def test_does_not_modify_board(self):
        b = empty_board()
        b[9][9] = 0
        b[9][10] = 1
        copy = [row[:] for row in b]
        sp.SmartPlayerJinhaJang(0).take_turn(b, 60000)
        self.assertEqual(b, copy)

    def test_first_moves(self):
        b = empty_board()
        self.assertEqual(sp.SmartPlayerJinhaJang(0).take_turn(b, 60000), (9, 9))
        b[9][9] = 0
        r, c = sp.SmartPlayerJinhaJang(1).take_turn(b, 60000)
        self.assertEqual(b[r][c], -1)

    def test_low_time_returns_quickly(self):
        import time
        b = empty_board()
        rng = random.Random(1)
        for _ in range(30):
            b[rng.randint(5, 13)][rng.randint(5, 13)] = rng.randint(0, 1)
        t = time.monotonic()
        mv = sp.SmartPlayerJinhaJang(0).take_turn(b, 300)
        self.assertLess(time.monotonic() - t, 0.3)
        self.assertEqual(b[mv[0]][mv[1]], -1)


if __name__ == "__main__":
    unittest.main()
