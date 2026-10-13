# SmartPlayerJinhaJang: Omok++ game agent.
#
# LLM usage: this file was written with Claude Code (Anthropic) and reviewed
# by the team. See README.txt and llm-usage/ for the full record.
#
# Overview
#   * Board engine with incremental line evaluation. Every row, column and
#     diagonal (length >= 5) is encoded as a base-3 integer; a per-line cache
#     maps that integer to its pattern statistics, so placing or removing a
#     stone only re-reads the 4 lines through that cell.
#   * Evaluation counts every 5-cell window that holds stones of only one
#     colour (the classic "tuple" evaluation), respecting the exact-five rule
#     (a window flanked by the same colour would be an overline and does not
#     count), plus Omok++ capture threats (X O O _ patterns).
#   * Search is negamax alpha-beta with iterative deepening, a transposition
#     table (Zobrist hashing), forced-move pruning when the opponent threatens
#     five (block it or capture to break it) and a threat extension, plus a
#     victory-by-continuous-fours (VCF) search for the side to move.
#   * Time management spends a share of the remaining game clock on each move
#     and always keeps a reserve, falling back to a quick heuristic move.

import random
import time

from playerjinhajang import PlayerJinhaJang

SIZE = 19
NCELL = SIZE * SIZE
EMPTY = -1
WIN = 10_000_000

# Tunable parameters. Values were set by tools/tune.py (self-play hill climb).
DEFAULT_PARAMS = {
    "w1": 1.8797,        # window with 1 own stone
    "w2": 15.3219,       # window with 2 own stones
    "w3": 100.0,      # window with 3 own stones
    "w4": 411.2181,     # window with 4 own stones (one move from five)
    "cap": 108.8743,     # capture threat (X O O _ pattern)
    "tempo": 1.7603,     # weight on the side to move's own score
    "defw": 1.0648,      # move ordering: weight of blocking the opponent's gain
    "capb": 475.0187,    # move ordering: bonus per pair a move captures
    "width": 10,      # moves searched at interior nodes
    "root_width": 20, # moves searched at the root
}


# ---------------------------------------------------------------------------
# Static board geometry (built once at import time).

def _build_geometry():
    lines = []
    for r in range(SIZE):
        lines.append([r * SIZE + c for c in range(SIZE)])
    for c in range(SIZE):
        lines.append([r * SIZE + c for r in range(SIZE)])
    for k in range(-(SIZE - 5), SIZE - 4):          # "\" diagonals: c - r = k
        lines.append([r * SIZE + (r + k) for r in range(SIZE) if 0 <= r + k < SIZE])
    for s in range(4, 2 * SIZE - 5):                # "/" diagonals: r + c = s
        lines.append([r * SIZE + (s - r) for r in range(SIZE) if 0 <= s - r < SIZE])

    cell_lines = [[] for _ in range(NCELL)]
    for lid, cells in enumerate(lines):
        for i, p in enumerate(cells):
            # Each line key stores its length in the low 5 bits, digit i of the
            # base-3 number above that, so the key alone identifies the line.
            cell_lines[p].append((lid, 32 * 3 ** i))

    near = []
    cap_rays = []
    dirs8 = [(dr, dc) for dr in (-1, 0, 1) for dc in (-1, 0, 1) if dr or dc]
    for p in range(NCELL):
        r, c = divmod(p, SIZE)
        near.append(tuple(
            (r + dr) * SIZE + (c + dc)
            for dr in range(-2, 3) for dc in range(-2, 3)
            if (dr or dc) and 0 <= r + dr < SIZE and 0 <= c + dc < SIZE
        ))
        rays = []
        for dr, dc in dirs8:
            if 0 <= r + 3 * dr < SIZE and 0 <= c + 3 * dc < SIZE:
                rays.append(tuple((r + k * dr) * SIZE + (c + k * dc) for k in (1, 2, 3)))
        cap_rays.append(tuple(rays))
    return lines, [tuple(x) for x in cell_lines], tuple(near), tuple(cap_rays)


LINES, CELL_LINES, NEAR, CAP_RAYS = _build_geometry()
NLINES = len(LINES)
LINE_BASE = [len(cells) for cells in LINES]   # key of an empty line

_rng = random.Random(20261019)
ZOBRIST = [[0] * NCELL] + [[_rng.getrandbits(64) for _ in range(NCELL)] for _ in (1, 2)]
ZOBRIST_SIDE = _rng.getrandbits(64)


class _TimeUp(Exception):
    pass


# Line statistics caches, one per evaluation weight set.
_LINE_CACHES = {}


def _line_info_factory(params):
    weights = (0.0, params["w1"], params["w2"], params["w3"], params["w4"])
    capw = params["cap"]
    key = (weights, capw)
    cache = _LINE_CACHES.setdefault(key, {})

    def compute(k):
        """Stats of one line: (E1, E2, F1, F2, NW1, NW2, wins1, wins2).

        E = evaluation score, F = 1 if an exact five exists, NW = number of
        empty cells completing an exact five, wins = their positions."""
        length = k & 31
        v = k >> 5
        cells = []
        for _ in range(length):
            cells.append(v % 3)
            v //= 3
        out = []
        for x in (1, 2):
            o = 3 - x
            score = 0.0
            five = 0
            wins = set()
            for s in range(length - 4):
                seg = cells[s:s + 5]
                if o in seg:
                    continue
                n = seg.count(x)
                if n == 0:
                    continue
                if n >= 4:
                    # Exact-five rule: a neighbour of the same colour would
                    # turn this window into an overline, which never wins.
                    if (s > 0 and cells[s - 1] == x) or (s + 5 < length and cells[s + 5] == x):
                        continue
                    if n == 5:
                        five = 1
                        continue
                    wins.add(s + seg.index(0))
                score += weights[n]
            caps = 0
            for i in range(length - 3):
                if cells[i + 1] == o and cells[i + 2] == o:
                    a, d = cells[i], cells[i + 3]
                    if (a == x and d == 0) or (a == 0 and d == x):
                        caps += 1
            out.append((score + capw * caps, five, len(wins), tuple(sorted(wins))))
        info = (out[0][0], out[1][0], out[0][1], out[1][1],
                out[0][2], out[1][2], out[0][3], out[1][3])
        cache[k] = info
        return info

    return cache, compute


# ---------------------------------------------------------------------------
# Engine

class _Engine:
    def __init__(self, params):
        self.p = params
        self.cache, self.compute = _line_info_factory(params)
        self.tt = {}
        self.history = [0] * NCELL
        self.reset()

    def info(self, k):
        inf = self.cache.get(k)
        return inf if inf is not None else self.compute(k)

    def reset(self):
        self.cells = [0] * NCELL
        self.lk = list(LINE_BASE)
        self.nb = [0] * NCELL
        self.E = [0.0, 0.0, 0.0]
        self.F = [0, 0, 0]
        self.NW = [0, 0, 0]
        self.h = 0
        self.stones = 0
        base = self.info
        for k in self.lk:
            inf = base(k)
            self.E[1] += inf[0]
            self.E[2] += inf[1]

    def load(self, board):
        self.reset()
        for r in range(SIZE):
            row = board[r]
            for c in range(SIZE):
                v = row[c]
                if v == 0 or v == 1:
                    self._put(r * SIZE + c, v + 1)

    # -- primitive updates ---------------------------------------------------
    def _put(self, p, v):
        self.cells[p] = v
        self.h ^= ZOBRIST[v][p]
        self.stones += 1
        lk, E, F, NW = self.lk, self.E, self.F, self.NW
        cache, compute = self.cache, self.compute
        for lid, pw in CELL_LINES[p]:
            k = lk[lid]
            o = cache.get(k) or compute(k)
            k2 = k + v * pw
            n = cache.get(k2) or compute(k2)
            lk[lid] = k2
            E[1] += n[0] - o[0]
            E[2] += n[1] - o[1]
            F[1] += n[2] - o[2]
            F[2] += n[3] - o[3]
            NW[1] += n[4] - o[4]
            NW[2] += n[5] - o[5]
        nb = self.nb
        for q in NEAR[p]:
            nb[q] += 1

    def _take(self, p):
        v = self.cells[p]
        self.cells[p] = 0
        self.h ^= ZOBRIST[v][p]
        self.stones -= 1
        lk, E, F, NW = self.lk, self.E, self.F, self.NW
        cache, compute = self.cache, self.compute
        for lid, pw in CELL_LINES[p]:
            k = lk[lid]
            o = cache.get(k) or compute(k)
            k2 = k - v * pw
            n = cache.get(k2) or compute(k2)
            lk[lid] = k2
            E[1] += n[0] - o[0]
            E[2] += n[1] - o[1]
            F[1] += n[2] - o[2]
            F[2] += n[3] - o[3]
            NW[1] += n[4] - o[4]
            NW[2] += n[5] - o[5]
        nb = self.nb
        for q in NEAR[p]:
            nb[q] -= 1

    def make(self, p, me):
        """Place a stone for `me` (1 or 2) and apply Omok++ captures."""
        self._put(p, me)
        o = 3 - me
        cells = self.cells
        captured = None
        for a, b, d in CAP_RAYS[p]:
            if cells[a] == o and cells[b] == o and cells[d] == me:
                if captured is None:
                    captured = [a, b]
                else:
                    captured += (a, b)
        if captured:
            for q in captured:
                self._take(q)
        return captured

    def unmake(self, p, me, captured):
        if captured:
            o = 3 - me
            for q in captured:
                self._put(q, o)
        self._take(p)

    # -- queries -------------------------------------------------------------
    def win_points(self, x):
        """Empty cells where colour x completes an exact five."""
        pts = []
        idx = 6 + x - 1
        lk, cache, compute = self.lk, self.cache, self.compute
        for lid in range(NLINES):
            k = lk[lid]
            inf = cache.get(k) or compute(k)
            w = inf[idx]
            if w:
                cells = LINES[lid]
                for i in w:
                    pts.append(cells[i])
        return list(dict.fromkeys(pts))

    def candidates(self):
        cells, nb = self.cells, self.nb
        return [p for p in range(NCELL) if nb[p] and not cells[p]]

    def capture_moves(self, me, cand):
        o = 3 - me
        cells = self.cells
        out = []
        for p in cand:
            for a, b, d in CAP_RAYS[p]:
                if cells[a] == o and cells[b] == o and cells[d] == me:
                    out.append(p)
                    break
        return out

    def evaluate(self, me):
        o = 3 - me
        return self.p["tempo"] * self.E[me] - self.E[o]

    def score_moves(self, me, cand):
        """Heuristic move ordering: own gain + weighted opponent gain denied."""
        o = 3 - me
        ei, eo = me - 1, o - 1
        lk, cells = self.lk, self.cells
        cache, compute = self.cache, self.compute
        defw, capb = self.p["defw"], self.p["capb"]
        hist = self.history
        out = []
        for p in cand:
            att = 0.0
            dfn = 0.0
            for lid, pw in CELL_LINES[p]:
                k = lk[lid]
                b = cache.get(k) or compute(k)
                km = k + me * pw
                a = cache.get(km) or compute(km)
                ko = k + o * pw
                d = cache.get(ko) or compute(ko)
                att += a[ei] - b[ei]
                dfn += d[eo] - b[eo]
            for a, b, d in CAP_RAYS[p]:
                if cells[a] == o and cells[b] == o and cells[d] == me:
                    att += capb
            out.append((att + defw * dfn + hist[p], p))
        out.sort(reverse=True)
        return out

    def four_moves(self, me, cand):
        """Moves that give `me` a new way to complete five (fours)."""
        lk = self.lk
        cache, compute = self.cache, self.compute
        idx = 4 + me - 1
        out = []
        for p in cand:
            gain = 0
            for lid, pw in CELL_LINES[p]:
                k = lk[lid]
                b = cache.get(k) or compute(k)
                k2 = k + me * pw
                a = cache.get(k2) or compute(k2)
                gain += a[idx] - b[idx]
            if gain > 0:
                out.append((gain, p))
        out.sort(reverse=True)
        return [p for _, p in out]


# ---------------------------------------------------------------------------
# Search

class _Searcher:
    def __init__(self, engine):
        self.e = engine
        self.deadline = float("inf")
        self.node_limit = None
        self.nodes = 0

    def _tick(self):
        self.nodes += 1
        if not self.nodes & 255:
            if time.monotonic() > self.deadline:
                raise _TimeUp()
            if self.node_limit is not None and self.nodes > self.node_limit:
                raise _TimeUp()

    def _after_move(self, me, ply):
        """Terminal score from `me`'s view right after `me` moved, else None."""
        F = self.e.F
        o = 3 - me
        if F[me] and F[o]:
            return 0
        if F[me]:
            return WIN - ply
        if F[o]:
            return -(WIN - ply)
        return None

    def negamax(self, depth, alpha, beta, me, ply, ext):
        self._tick()
        e = self.e
        o = 3 - me
        if e.NW[me]:
            return WIN - ply
        threatened = e.NW[o] > 0
        if depth <= 0:
            if threatened and ext > 0:
                depth = 1
                ext -= 1
            else:
                return e.evaluate(me)

        key = e.h ^ (ZOBRIST_SIDE if me == 2 else 0)
        entry = e.tt.get(key)
        tt_move = None
        if entry is not None:
            d, flag, val, mv = entry
            tt_move = mv
            if d >= depth:
                if flag == 0:
                    return val
                if flag == 1 and val >= beta:
                    return val
                if flag == 2 and val <= alpha:
                    return val

        cand = e.candidates()
        if not cand:
            return 0
        if threatened:
            moves = e.win_points(o)
            for p in e.capture_moves(me, cand):
                if p not in moves:
                    moves.append(p)
        else:
            width = e.p["width"]
            moves = [p for _, p in e.score_moves(me, cand)[:width]]
        if tt_move is not None and tt_move in moves:
            moves.remove(tt_move)
            moves.insert(0, tt_move)

        alpha0 = alpha
        best = -WIN * 2
        best_move = None
        for p in moves:
            cap = e.make(p, me)
            val = self._after_move(me, ply + 1)
            if val is None:
                val = -self.negamax(depth - 1, -beta, -alpha, o, ply + 1, ext)
            e.unmake(p, me, cap)
            if val > best:
                best = val
                best_move = p
                if val > alpha:
                    alpha = val
                    if alpha >= beta:
                        e.history[p] += depth * depth
                        break
        flag = 0 if alpha0 < best < beta else (1 if best >= beta else 2)
        e.tt[key] = (depth, flag, best, best_move)
        return best

    def vcf(self, me, depth, ply=0):
        """True if `me` (to move) wins by consecutive fours."""
        self._tick()
        e = self.e
        o = 3 - me
        if e.NW[me]:
            return True
        if depth <= 0 or e.NW[o]:
            return False
        cand = e.candidates()
        for p in e.four_moves(me, cand)[:12]:
            cap = e.make(p, me)
            ok = False
            res = self._after_move(me, ply + 1)
            if res is not None:
                ok = res > 0
            elif e.NW[me]:
                ok = self._vcf_defend(me, depth, ply + 1)
            e.unmake(p, me, cap)
            if ok:
                return True
        return False

    def _vcf_defend(self, me, depth, ply):
        """`o` to move, facing `me`'s five threat: True if every reply loses."""
        e = self.e
        o = 3 - me
        replies = e.win_points(me)
        for p in e.capture_moves(o, e.candidates()):
            if p not in replies:
                replies.append(p)
        for p in replies:
            cap = e.make(p, o)
            res = self._after_move(o, ply + 1)
            if res is not None:
                lost = res < 0
            elif e.NW[o]:
                # The reply made a four of its own; only an immediate win saves us.
                lost = e.NW[me] > 0
            else:
                lost = self.vcf(me, depth - 1, ply + 1)
            e.unmake(p, o, cap)
            if not lost:
                return False
        return True

    def find_vcf_move(self, me, depth):
        e = self.e
        if e.NW[3 - me]:
            return None
        for p in e.four_moves(me, e.candidates())[:12]:
            cap = e.make(p, me)
            res = self._after_move(me, 1)
            if res is not None:
                ok = res > 0
            else:
                ok = e.NW[me] > 0 and self._vcf_defend(me, depth, 1)
            e.unmake(p, me, cap)
            if ok:
                return p
        return None

    def root(self, me, max_depth, soft_time, start):
        """Iterative deepening at the root. Returns (move, score, depth)."""
        e = self.e
        o = 3 - me
        cand = e.candidates()
        if e.NW[o]:
            moves = e.win_points(o)
            for p in e.capture_moves(me, cand):
                if p not in moves:
                    moves.append(p)
        else:
            moves = [p for _, p in e.score_moves(me, cand)[:e.p["root_width"]]]
        if not moves:
            return None, 0, 0
        if len(moves) == 1:
            return moves[0], 0, 0

        best_move, best_score, done_depth = moves[0], -WIN * 2, 0
        for depth in range(1, max_depth + 1):
            alpha, beta = -WIN * 2, WIN * 2
            iter_best, iter_score = None, -WIN * 2
            scores = {}
            try:
                for p in moves:
                    cap = e.make(p, me)
                    val = self._after_move(me, 1)
                    if val is None:
                        val = -self.negamax(depth - 1, -beta, -alpha, o, 1, 6)
                    e.unmake(p, me, cap)
                    scores[p] = val
                    if val > iter_score:
                        iter_score, iter_best = val, p
                        if val > alpha:
                            alpha = val
            except _TimeUp:
                # Moves are searched best-first, so a move that beat the
                # previous best within this iteration is trustworthy.
                if iter_best is not None and (iter_best == best_move or iter_score > best_score):
                    best_move, best_score = iter_best, iter_score
                break
            best_move, best_score, done_depth = iter_best, iter_score, depth
            if best_score >= WIN - 100 or best_score <= -(WIN - 100):
                break
            moves.sort(key=lambda m: scores.get(m, -WIN * 3), reverse=True)
            if time.monotonic() - start > soft_time:
                break
        return best_move, best_score, done_depth


# ---------------------------------------------------------------------------
# Player

class SmartPlayerJinhaJang(PlayerJinhaJang):
    def __init__(self, color, params=None, max_depth=20, node_limit=None, move_time=None):
        super().__init__(color)
        self.params = dict(DEFAULT_PARAMS)
        if params:
            self.params.update(params)
        self.max_depth = max_depth
        self.node_limit = node_limit      # for deterministic self-play tuning
        self.move_time = move_time        # fixed seconds per move (testing)
        self.engine = _Engine(self.params)
        self.moves_played = 0
        self.last_info = None

    def take_turn(self, board, time_left):
        start = time.monotonic()
        try:
            move = self._think(board, time_left, start)
        except Exception:
            move = None
        if move is None or not self._legal(board, move):
            move = self._fallback(board)
        self.moves_played += 1
        return move

    # -- helpers -------------------------------------------------------------
    @staticmethod
    def _legal(board, move):
        r, c = move
        return 0 <= r < SIZE and 0 <= c < SIZE and board[r][c] == EMPTY

    def _fallback(self, board):
        try:
            e = self.engine
            e.load(board)
            me = self.color + 1
            cand = e.candidates()
            if cand:
                p = e.score_moves(me, cand)[0][1]
                if board[p // SIZE][p % SIZE] == EMPTY:
                    return divmod(p, SIZE)
        except Exception:
            pass
        mid = SIZE // 2
        cells = sorted(((r, c) for r in range(SIZE) for c in range(SIZE)),
                       key=lambda rc: abs(rc[0] - mid) + abs(rc[1] - mid))
        for r, c in cells:
            if board[r][c] == EMPTY:
                return (r, c)
        return (0, 0)

    def _budget(self, time_left):
        """(soft, hard) seconds for this move."""
        if self.move_time is not None:
            return self.move_time * 0.5, self.move_time
        if time_left is None or time_left < 0:
            return 1.0, 3.0
        remaining = time_left / 1000.0
        usable = remaining - 4.0              # always keep a reserve
        if usable <= 0.5:
            return 0.02, max(0.05, min(0.3, remaining * 0.05))
        expected_left = max(12, 35 - self.moves_played)
        per_move = min(usable / expected_left, 2.5)
        return per_move * 0.45, min(per_move * 2.0, usable * 0.2)

    def _think(self, board, time_left, start):
        e = self.engine
        e.load(board)
        me = self.color + 1
        o = 3 - me
        mid = SIZE // 2

        if e.stones == 0:
            return (mid, mid)
        if len(e.tt) > 400_000:
            e.tt.clear()
        e.history = [h >> 2 for h in e.history]

        # 1. Win now if possible.
        if e.NW[me]:
            for p in e.win_points(me):
                cap = e.make(p, me)
                ok = e.F[me] and not e.F[o]
                e.unmake(p, me, cap)
                if ok:
                    return divmod(p, SIZE)

        soft, hard = self._budget(time_left)
        s = _Searcher(e)
        s.deadline = start + hard
        s.node_limit = self.node_limit

        # 2. Forced win by continuous fours.
        try:
            if self.node_limit is None:
                s.deadline = start + hard * 0.25
            p = s.find_vcf_move(me, 8)
            if p is not None:
                self.last_info = ("vcf", 0, 0, s.nodes)
                return divmod(p, SIZE)
        except _TimeUp:
            # The search was interrupted mid-line; rebuild the position.
            e.load(board)
        s.deadline = start + hard
        if self.node_limit is not None:
            s.nodes = 0

        # 3. Alpha-beta search.
        move, score, depth = s.root(me, self.max_depth, soft, start)
        self.last_info = ("ab", depth, score, s.nodes)
        if move is None:
            return None
        return divmod(move, SIZE)
