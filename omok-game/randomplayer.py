import random

from player import Player

SIZE = 19
EMPTY = -1


class RandomPlayer(Player):
    def __init__(self, color):
        super().__init__(color)
        self._prev_board = None

    def take_turn(self, board, time):
        opponent = 1 - self.color
        last_move = self._find_last_opponent_move(board, opponent)

        candidates = []
        if last_move is not None:
            candidates = self._empty_neighbors(board, *last_move)
        if not candidates:
            candidates = self._empty_cells_near_any_stone(board)
        if not candidates:
            candidates = [
                (r, c) for r in range(SIZE) for c in range(SIZE)
                if board[r][c] == EMPTY
            ]
            if len(candidates) == SIZE * SIZE:
                candidates = [(SIZE // 2, SIZE // 2)]

        if not candidates:
            raise ValueError("No legal move: take_turn was called on a full board.")
        choice = random.choice(candidates)
        self._prev_board = self._board_after_move(board, *choice, self.color)
        return choice

    def _find_last_opponent_move(self, board, opponent):
        if self._prev_board is None:
            stones = [
                (r, c) for r in range(SIZE) for c in range(SIZE)
                if board[r][c] == opponent
            ]
            return stones[0] if len(stones) == 1 else None

        appeared = [
            (r, c) for r in range(SIZE) for c in range(SIZE)
            if self._prev_board[r][c] == EMPTY and board[r][c] == opponent
        ]
        return appeared[0] if len(appeared) == 1 else None

    def _empty_neighbors(self, board, row, col):
        return [
            (row + dr, col + dc)
            for dr in (-1, 0, 1) for dc in (-1, 0, 1)
            if (dr or dc)
            and 0 <= row + dr < SIZE and 0 <= col + dc < SIZE
            and board[row + dr][col + dc] == EMPTY
        ]

    def _empty_cells_near_any_stone(self, board):
        result = set()
        for r in range(SIZE):
            for c in range(SIZE):
                if board[r][c] != EMPTY:
                    result.update(self._empty_neighbors(board, r, c))
        return sorted(result)

    def _board_after_move(self, board, row, col, color):
        after = [list(values) for values in board]
        after[row][col] = color
        opponent = 1 - color
        captured = set()
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                if not (dr or dc):
                    continue
                end_r, end_c = row + 3 * dr, col + 3 * dc
                if not (0 <= end_r < SIZE and 0 <= end_c < SIZE):
                    continue
                r1, c1 = row + dr, col + dc
                r2, c2 = row + 2 * dr, col + 2 * dc
                if (after[r1][c1] == opponent
                        and after[r2][c2] == opponent
                        and after[end_r][end_c] == color):
                    captured.update(((r1, c1), (r2, c2)))
        for r, c in captured:
            after[r][c] = EMPTY
        return after
