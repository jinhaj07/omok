from player import Player

SIZE = 19
EMPTY = -1

DEFENCE_WEIGHT = 0.9
CAPTURE_SCORE = 300
VULNERABLE_PENALTY = 500
PROTECT_SCORE = 400
THREAT_SCORE = 120
OVERLINE_PENALTY = 200

LINE_SCORE = {
    (4, 2): 10_000, (4, 1): 1_000,
    (3, 2): 500, (3, 1): 100,
    (2, 2): 50, (2, 1): 10,
    (1, 2): 5,
}

AXES = ((0, 1), (1, 0), (1, 1), (1, -1))
DIRECTIONS = AXES + tuple((-r, -c) for r, c in AXES)


class SimplePlayer(Player):
    def __init__(self, color):
        super().__init__(color)

    def take_turn(self, board, time):
        me, opp = self.color, 1 - self.color
        candidates = self._candidate_cells(board)
        if not candidates:
            raise ValueError("No legal move: take_turn was called on a full board.")

        evaluated = []
        must_block = []
        for row, col in candidates:
            after_me, captured_me, outcome_me = self._simulate(board, row, col, me)
            if outcome_me == "win":
                return (row, col)
            if outcome_me == "loss":
                continue
            after_opp, captured_opp, outcome_opp = self._simulate(board, row, col, opp)
            if outcome_opp == "win":
                must_block.append((row, col))
            evaluated.append((row, col, after_me, captured_me, outcome_me, after_opp, captured_opp))

        if must_block:
            evaluated = [e for e in evaluated if (e[0], e[1]) in must_block]

        best = None
        for row, col, after_me, captured_me, outcome_me, after_opp, captured_opp in evaluated:
            attack = (
                self._line_score(after_me, row, col, me)
                + captured_me * CAPTURE_SCORE
                - self._vulnerable_pairs(after_me, row, col, me) * VULNERABLE_PENALTY
                + self._protected_pairs(board, row, col, me) * PROTECT_SCORE
                + self._capture_threats(after_me, row, col, me) * THREAT_SCORE
                - (VULNERABLE_PENALTY if outcome_me == "draw" else 0)
            )
            defence = self._line_score(after_opp, row, col, opp) + captured_opp * CAPTURE_SCORE
            score = attack + DEFENCE_WEIGHT * defence
            key = (score, -self._centre_distance(row, col), -row, -col)
            if best is None or key > best[0]:
                best = (key, (row, col))

        return best[1] if best else self._first_empty(board)

    def _candidate_cells(self, board):
        stones = [(r, c) for r in range(SIZE) for c in range(SIZE) if board[r][c] != EMPTY]
        if not stones:
            return [(SIZE // 2, SIZE // 2)]
        near = {
            (r + dr, c + dc)
            for r, c in stones
            for dr in range(-2, 3) for dc in range(-2, 3)
            if 0 <= r + dr < SIZE and 0 <= c + dc < SIZE and board[r + dr][c + dc] == EMPTY
        }
        return sorted(near)

    def _first_empty(self, board):
        for r in range(SIZE):
            for c in range(SIZE):
                if board[r][c] == EMPTY:
                    return (r, c)

    def _cell(self, board, r, c):
        return board[r][c] if 0 <= r < SIZE and 0 <= c < SIZE else None

    def _line_score(self, board, row, col, color):
        total = 0
        for dr, dc in AXES:
            length, open_ends = 1, 0
            for sign in (1, -1):
                r, c = row + dr * sign, col + dc * sign
                while self._cell(board, r, c) == color:
                    length += 1
                    r += dr * sign
                    c += dc * sign
                if self._cell(board, r, c) == EMPTY:
                    open_ends += 1
            if length >= 6:
                total -= OVERLINE_PENALTY
            else:
                total += LINE_SCORE.get((length, open_ends), 0)
        return total

    def _vulnerable_pairs(self, board, row, col, color):
        opp = 1 - color
        count = 0
        for dr, dc in DIRECTIONS:
            if self._cell(board, row + dr, col + dc) != color:
                continue
            behind = self._cell(board, row - dr, col - dc)
            ahead = self._cell(board, row + 2 * dr, col + 2 * dc)
            if {behind, ahead} == {opp, EMPTY}:
                count += 1
        return count

    def _protected_pairs(self, board, row, col, color):
        opp = 1 - color
        count = 0
        for dr, dc in DIRECTIONS:
            if (
                self._cell(board, row + dr, col + dc) == color
                and self._cell(board, row + 2 * dr, col + 2 * dc) == color
                and self._cell(board, row + 3 * dr, col + 3 * dc) == opp
            ):
                count += 1
        return count

    def _capture_threats(self, board, row, col, color):
        opp = 1 - color
        count = 0
        for dr, dc in DIRECTIONS:
            if (
                self._cell(board, row + dr, col + dc) == opp
                and self._cell(board, row + 2 * dr, col + 2 * dc) == opp
                and self._cell(board, row + 3 * dr, col + 3 * dc) == EMPTY
            ):
                count += 1
        return count

    def _centre_distance(self, row, col):
        return abs(row - SIZE // 2) + abs(col - SIZE // 2)

    def _simulate(self, board, row, col, color):
        if not (0 <= row < SIZE and 0 <= col < SIZE) or board[row][col] != EMPTY:
            raise ValueError("Simulation requires an empty, in-bounds cell.")
        after = [list(values) for values in board]
        after[row][col] = color
        opponent = 1 - color
        captured = set()
        for dr, dc in DIRECTIONS:
            r1, c1 = row + dr, col + dc
            r2, c2 = row + 2 * dr, col + 2 * dc
            r3, c3 = row + 3 * dr, col + 3 * dc
            if (self._cell(after, r1, c1) == opponent
                    and self._cell(after, r2, c2) == opponent
                    and self._cell(after, r3, c3) == color):
                captured.update(((r1, c1), (r2, c2)))
        for r, c in captured:
            after[r][c] = EMPTY

        mine = self._wins_at(after, row, col, color)
        theirs = bool(captured) and self._has_exact_five(after, opponent)
        outcome = "draw" if mine and theirs else "win" if mine else "loss" if theirs else None
        return after, len(captured), outcome

    def _wins_at(self, board, row, col, color):
        for dr, dc in AXES:
            length = 1
            for sign in (-1, 1):
                r, c = row + sign * dr, col + sign * dc
                while self._cell(board, r, c) == color:
                    length += 1
                    r += sign * dr
                    c += sign * dc
            if length == 5:
                return True
        return False

    def _has_exact_five(self, board, color):
        for row in range(SIZE):
            for col in range(SIZE):
                if board[row][col] != color:
                    continue
                for dr, dc in AXES:
                    if self._cell(board, row - dr, col - dc) == color:
                        continue
                    length = 0
                    r, c = row, col
                    while self._cell(board, r, c) == color:
                        length += 1
                        r += dr
                        c += dc
                    if length == 5:
                        return True
        return False
