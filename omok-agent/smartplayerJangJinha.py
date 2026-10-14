# SmartPlayerJangJinha (v12): Omok++ game agent.
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

from playerJangJinha import PlayerJangJinha

SIZE = 19
NCELL = SIZE * SIZE
EMPTY = -1
WIN = 10_000_000

# Tunable parameters. Values were set by tools/tune.py (self-play hill climb).
DEFAULT_PARAMS = {
    "w1": 1.8797,        # window with 1 own stone
    "w2": 23.1797,       # window with 2 own stones
    "w3": 100.0,      # window with 3 own stones
    "w4": 411.2181,     # window with 4 own stones (one move from five)
    "cap": 108.8743,     # capture threat (X O O _ pattern)
    "tempo": 1.561,     # weight on the side to move's own score
    "defw": 1.0648,      # move ordering: weight of blocking the opponent's gain
    "capb": 640.9005,    # move ordering: bonus per pair a move captures
    "width": 10,      # moves searched at interior nodes
    "root_width": 20, # moves searched at the root
    "o3": 150.0,        # bonus per line holding an open three (can make an open four)
    "fork": 3000.0,      # side to move holds threats (open three / four) on 2+ lines
    "forko": 2000.0,     # opponent holds threats on 2+ lines
    "vct": 5,         # attacker threat moves in the root VCT search (0 = off)
    "vctk": 8,        # threat moves tried per VCT node
    "svct": 0,
    "vfrac": 0.15,
    "widen": 1,       # 1 = search all moves when the selected ones all lose
    "abfrac": 0.7,    # share of the hard limit for alpha-beta (rest: safety)
    "xcap": 1,        # 1 = score capture moves exactly (make/unmake), so a
                      # capture that unblocks our lines counts as a threat    # share of the move's hard limit the root VCT may use        # VCT depth used to vet our move against the opponent
    "qvcf": 0,        # VCF depth searched at quiet leaves (0 = off)
    "safety": 1,      # 1 = reject root moves that allow an opponent VCF
    "tmax": 2.5,      # cap on the planned seconds per move
    "tmoves": 35,     # expected own moves per game for the time plan
    "tsoft": 0.45,    # start no new depth after this share of the planned time
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
    cell_pos = [[] for _ in range(NCELL)]
    for lid, cells in enumerate(lines):
        for i, p in enumerate(cells):
            cell_pos[p].append((lid, i))
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
    return (lines, [tuple(x) for x in cell_lines], tuple(near), tuple(cap_rays),
            [tuple(x) for x in cell_pos])


LINES, CELL_LINES, NEAR, CAP_RAYS, CELL_POS = _build_geometry()
NLINES = len(LINES)
LINE_BASE = [len(cells) for cells in LINES]   # key of an empty line

_rng = random.Random(20261019)
ZOBRIST = [[0] * NCELL] + [[_rng.getrandbits(64) for _ in range(NCELL)] for _ in (1, 2)]
ZOBRIST_SIDE = _rng.getrandbits(64)


class _TimeUp(Exception):
    pass


# Line statistics caches, one per evaluation weight set.
_LINE_CACHES = {}


def _win_cells(cells, x, length):
    """Empty cells of a line where colour x would complete an exact five."""
    o = 3 - x
    wins = set()
    for s in range(length - 4):
        seg = cells[s:s + 5]
        if o in seg or seg.count(x) != 4:
            continue
        if (s > 0 and cells[s - 1] == x) or (s + 5 < length and cells[s + 5] == x):
            continue
        wins.add(s + seg.index(0))
    return wins


def _line_info_factory(params):
    weights = (0.0, params["w1"], params["w2"], params["w3"], params["w4"])
    capw = params["cap"]
    o3w = params["o3"]
    key = (weights, capw, o3w)
    cache = _LINE_CACHES.setdefault(key, {})

    def compute(k):
        """Stats of one line: (E1, E2, F1, F2, NW1, NW2, wins1, wins2, T1, T2).

        E = evaluation score, F = 1 if an exact five exists, NW = number of
        empty cells completing an exact five, wins = their positions,
        T = 1 if the line holds a threat (a four, or an open three that can
        become an open four)."""
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
            open3 = 0
            if not wins and not five and cells.count(x) >= 3:
                for e in range(length):
                    # Only a cell with 3+ own stones within reach can turn
                    # the line into an open four.
                    if cells[e] == 0 and cells[max(0, e - 4):e + 5].count(x) >= 3:
                        cells[e] = x
                        if len(_win_cells(cells, x, length)) >= 2:
                            open3 = 1
                        cells[e] = 0
                        if open3:
                            break
            threat = 1 if (wins or open3) else 0
            out.append((score + capw * caps + o3w * open3, five, len(wins),
                        tuple(sorted(wins)), threat))
        info = (out[0][0], out[1][0], out[0][1], out[1][1],
                out[0][2], out[1][2], out[0][3], out[1][3], out[0][4], out[1][4])
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
        self.vtt = {}
        self.ocache = {}   # move ordering per position (reused across depths)
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
        self.T = [0, 0, 0]
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
        lk, E, F, NW, T = self.lk, self.E, self.F, self.NW, self.T
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
            T[1] += n[8] - o[8]
            T[2] += n[9] - o[9]
        nb = self.nb
        for q in NEAR[p]:
            nb[q] += 1

    def _take(self, p):
        v = self.cells[p]
        self.cells[p] = 0
        self.h ^= ZOBRIST[v][p]
        self.stones -= 1
        lk, E, F, NW, T = self.lk, self.E, self.F, self.NW, self.T
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
            T[1] += n[8] - o[8]
            T[2] += n[9] - o[9]
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
        v = self.p["tempo"] * self.E[me] - self.E[o]
        if self.T[me] >= 2:
            v += self.p["fork"]
        if self.T[o] >= 2:
            v -= self.p["forko"]
        return v

    def score_moves(self, me, cand, with_history=True):
        """Heuristic move ordering: own gain + weighted opponent gain denied."""
        o = 3 - me
        ei, eo = me - 1, o - 1
        lk, cells = self.lk, self.cells
        cache, compute = self.cache, self.compute
        defw, capb = self.p["defw"], self.p["capb"]
        xcap = self.p["xcap"]
        hist = self.history if with_history else [0] * NCELL
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
            ncap = 0
            for a, b, d in CAP_RAYS[p]:
                if cells[a] == o and cells[b] == o and cells[d] == me:
                    ncap += 1
            if ncap:
                if xcap:
                    # Removing stones changes lines through the captured
                    # cells too; measure the real effect.
                    E = self.E
                    e_me, e_o = E[me], E[o]
                    cap = self.make(p, me)
                    att = (E[me] - e_me) + (e_o - E[o])
                    self.unmake(p, me, cap)
                att += capb * ncap
            out.append((att + defw * dfn + hist[p], p))
        out.sort(reverse=True)
        return out

    def threat_moves(self, me, cand):
        """Moves creating a four or a new open three for `me`, strongest first.
        Returns (move, makes_four) pairs."""
        lk = self.lk
        cache, compute = self.cache, self.compute
        i4, i3, ie = 4 + me - 1, 8 + me - 1, me - 1
        o = 3 - me
        cells = self.cells
        xcap = self.p["xcap"]
        out = []
        for p in cand:
            if xcap and any(cells[a] == o and cells[b] == o and cells[d] == me
                            for a, b, d in CAP_RAYS[p]):
                nw0, t0, e0 = self.NW[me], self.T[me], self.E[me]
                cap = self.make(p, me)
                g4, g3, ev = self.NW[me] - nw0, self.T[me] - t0, self.E[me] - e0
                self.unmake(p, me, cap)
                if g4 > 0 or g3 > 0:
                    out.append((g4 > 0, g4 + g3, ev, p))
                continue
            g4 = g3 = 0
            ev = 0.0
            for lid, pw in CELL_LINES[p]:
                k = lk[lid]
                b = cache.get(k) or compute(k)
                k2 = k + me * pw
                a = cache.get(k2) or compute(k2)
                g4 += a[i4] - b[i4]
                g3 += a[i3] - b[i3]
                ev += a[ie] - b[ie]
            if g4 > 0 or g3 > 0:
                out.append((g4 > 0, g4 + g3, ev, p))
        out.sort(reverse=True)
        return [(p, f) for f, _, _, p in out]

    def line_cells_near(self, p, dist=4):
        """Empty cells on the four lines through p within `dist` of p."""
        cells = self.cells
        out = []
        for lid, i in CELL_POS[p]:
            line = LINES[lid]
            for j in range(max(0, i - dist), min(len(line), i + dist + 1)):
                q = line[j]
                if not cells[q]:
                    out.append(q)
        return out

    def four_moves(self, me, cand):
        """Moves that give `me` a new way to complete five (fours)."""
        lk = self.lk
        cache, compute = self.cache, self.compute
        idx = 4 + me - 1
        o = 3 - me
        cells = self.cells
        xcap = self.p["xcap"]
        out = []
        for p in cand:
            if xcap and any(cells[a] == o and cells[b] == o and cells[d] == me
                            for a, b, d in CAP_RAYS[p]):
                nw0 = self.NW[me]
                cap = self.make(p, me)
                gain = self.NW[me] - nw0
                self.unmake(p, me, cap)
                if gain > 0:
                    out.append((gain, p))
                continue
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
                qd = e.p["qvcf"]
                if qd and not threatened and self.vcf(me, qd, ply):
                    return WIN - ply - 2 * qd
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
        rest = ()
        if not threatened:
            width = e.p["width"]
            # Static move scores are cached per position (the expensive
            # part); the history bonus changes during the search, so it is
            # added fresh before the selection.
            static = e.ocache.get(key)
            if static is None:
                static = e.score_moves(me, cand, with_history=False)
                e.ocache[key] = static
            hist = e.history
            ranked = [p for _, p in sorted(((sc + hist[p], p) for sc, p in static), reverse=True)]
            moves, rest = ranked[:width], ranked[width:]
        if tt_move is not None and tt_move in moves:
            moves.remove(tt_move)
            moves.insert(0, tt_move)

        alpha0 = alpha
        best = -WIN * 2
        best_move = None
        cut = False
        for batch in (moves, rest):
            # Selective search only looks at the best `width` moves. If all
            # of them lose, a defence may have been pruned: widen before
            # concluding that this position is lost.
            if batch is rest and (cut or best > -(WIN - 100) or not e.p["widen"]):
                break
            for p in batch:
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
                            cut = True
                            break
                if batch is rest and best > -(WIN - 100):
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

    def vct(self, a, depth, ply=0, width=8):
        """True if attacker `a` (to move) wins by continuous threats
        (fours and open threes). Conservative: a defender's counter-four
        counts as a successful defence unless `a` can win at once."""
        self._tick()
        e = self.e
        d = 3 - a
        if e.NW[a]:
            return True
        if depth <= 0 or e.NW[d]:
            return False
        key = (e.h, a, depth)
        hit = e.vtt.get(key)
        if hit is not None:
            return hit
        result = False
        for p, four in e.threat_moves(a, e.candidates())[:width]:
            cap = e.make(p, a)
            res = self._after_move(a, ply + 1)
            if res is not None:
                ok = res > 0
            else:
                ok = self._vct_defend(a, depth, ply + 1, None if e.NW[a] else p, width)
            e.unmake(p, a, cap)
            if ok:
                result = True
                break
        e.vtt[key] = result
        return result

    def _vct_defend(self, a, depth, ply, three_at, width):
        """Defender to move after `a`'s threat: True if every reply loses."""
        e = self.e
        d = 3 - a
        cand = e.candidates()
        if three_at is None:
            replies = e.win_points(a)
        else:
            replies = e.line_cells_near(three_at)
            replies += e.four_moves(d, cand)
        replies += e.capture_moves(d, cand)
        for r in dict.fromkeys(replies):
            cap = e.make(r, d)
            res = self._after_move(d, ply + 1)
            if res is not None:
                lost = res < 0
            elif e.NW[d]:
                lost = e.NW[a] > 0
            else:
                lost = self.vct(a, depth - 1, ply + 1, width)
            e.unmake(r, d, cap)
            if not lost:
                return False
        return True

    def find_vct_move(self, me, depth, width):
        e = self.e
        if e.NW[3 - me]:
            return None
        for p, four in e.threat_moves(me, e.candidates())[:width]:
            cap = e.make(p, me)
            res = self._after_move(me, 1)
            if res is not None:
                ok = res > 0
            else:
                ok = self._vct_defend(me, depth, 1, None if e.NW[me] else p, width)
            e.unmake(p, me, cap)
            if ok:
                return p
        return None

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
        self.root_order = list(moves)
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
            moves.sort(key=lambda m: scores.get(m, -WIN * 3), reverse=True)
            self.root_order = list(moves)
            if best_score >= WIN - 100 or best_score <= -(WIN - 100):
                break
            if time.monotonic() - start > soft_time:
                break
        return best_move, best_score, done_depth


# ---------------------------------------------------------------------------
# Player

class SmartPlayerJangJinha(PlayerJangJinha):
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
        expected_left = max(12, self.params["tmoves"] - self.moves_played)
        per_move = min(usable / expected_left, self.params["tmax"])
        return per_move * self.params["tsoft"], min(per_move * 2.0, usable * 0.2)

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
        if len(e.vtt) > 200_000:
            e.vtt.clear()
        if len(e.ocache) > 100_000:
            e.ocache.clear()
        e.history = [h >> 2 for h in e.history]

        # 1. Win now if possible.
        if e.NW[me]:
            for p in e.win_points(me):
                cap = e.make(p, me)
                ok = e.F[me] and not e.F[o]
                e.unmake(p, me, cap)
                if ok:
                    self.last_info = ("win", 0, WIN, 0)
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
        # 2b. Forced win by continuous threats (fours and open threes).
        vct_depth = self.params["vct"]
        if vct_depth:
            try:
                if self.node_limit is None:
                    s.deadline = start + hard * self.params["vfrac"]
                t_vct = time.monotonic()
                p = s.find_vct_move(me, vct_depth, self.params["vctk"])
                self.last_vct = (time.monotonic() - t_vct, p is not None)
                if p is not None:
                    self.last_info = ("vct", 0, 0, s.nodes)
                    return divmod(p, SIZE)
            except _TimeUp:
                self.last_vct = (time.monotonic() - t_vct, None)
                e.load(board)
        s.deadline = start + hard
        if self.node_limit is not None:
            s.nodes = 0

        # 3. Alpha-beta search. With the safety check on, keep part of the
        # budget for verifying the chosen move.
        safety = self.params["safety"]
        if safety and self.node_limit is None:
            s.deadline = start + hard * self.params["abfrac"]
        # The soft limit (whether to start another depth) counts from here,
        # so time spent in the VCF/VCT phases does not starve the search.
        move, score, depth = s.root(me, self.max_depth, soft, time.monotonic())
        self.last_info = ("ab", depth, score, s.nodes)
        if move is None:
            return None

        # 4. Safety: skip moves after which the opponent wins by continuous
        # fours (the alpha-beta horizon can miss long four sequences).
        if safety and score < WIN - 100:
            s.deadline = start + hard
            order = [move] + [m for m in getattr(s, "root_order", []) if m != move]
            proven = set()
            try:
                for m in order[:8]:
                    cap = e.make(m, me)
                    res = s._after_move(me, 1)
                    lost = res is not None and res < 0
                    if res is None:
                        lost = s.vcf(o, 8)
                        if not lost and self.params["svct"]:
                            lost = s.vct(o, self.params["svct"], 1, self.params["vctk"])
                    e.unmake(m, me, cap)
                    if lost:
                        proven.add(m)
                    else:
                        if m != move:
                            self.last_info = ("safe", depth, score, s.nodes)
                        move = m
                        break
            except _TimeUp:
                # Out of time: never play a move already proven to lose
                # when an unchecked alternative is available.
                if move in proven:
                    for m in order[:8]:
                        if m not in proven:
                            move = m
                            self.last_info = ("safe?", depth, score, s.nodes)
                            break
        return divmod(move, SIZE)
