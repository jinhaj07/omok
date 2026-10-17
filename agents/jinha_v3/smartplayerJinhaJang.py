"""
SmartPlayerJinhaJang -- Omok++ game agent (CAS1102 Project 1, Part 2)

[LLM usage] This whole file was written with the help of an LLM
(Claude, used through the Hermes Agent app). See README.txt / llm-usage/.

How it plays (version 3)
  * The board is copied into a flat list of 361 cells (-1 / 0 / 1).
  * Every line of the board (rows, columns and the diagonals that are at
    least 5 cells long) is scored by sliding a 5-cell window over it.
    A window is "alive" for a color when it has no opponent stone and the
    cells right outside it are not that color, i.e. it can still become
    EXACTLY five (6+ in a row does not win).  A window holding k stones
    is worth WINDOW_VALUE[k].
  * Line results are cached by the text of the line, and after a move
    (or a capture) only the lines through the changed cells are rescored.
  * Negamax alpha-beta search + iterative deepening inside a per-move time
    budget (the whole game only has 1 minute).
  * Forcing moves: if the opponent can make five on the next turn, only the
    moves that remove every such threat (blocking OR capturing) are
    searched, and these forced replies do not use up search depth.
    (v1 also gave free depth to the move that MAKES a four; that blew up
    the tree in busy positions, so v2 removed it: search depth 3 -> ~6.)
  v2 additions
  * Each line also reports "four cells" (a stone there makes a four) and
    "open-four cells" (a stone there makes two winning cells at once,
    i.e. the line holds a live three).
  * Evaluation knows that a live three for the side to move is nearly a
    win, and that two live threes for the opponent are nearly a loss.
  * If the opponent has a live three, only answers to it (blocks, own
    fours, captures) are searched.
  * VCF search (victory by continuous fours, captures counted as defenses)
    to find deep forced wins, and to refuse moves that give the opponent one.
  v3 additions
  * Lines are keyed by integers (2 bits per cell) instead of strings, and the
    candidate set is only touched when a neighbour count goes 0 <-> 1
    (identical search, ~15% faster).
  * Evaluation bonus when the side to move can capture right now.
  * Every move made during search goes on a stack, so a search stopped by
    the clock / node limit is rewound exactly (v2 could keep searching on
    a board with leftover stones after an aborted VCF).
  * Hard time limit for every part of a move, and a no-search emergency
    mode when less than 1 second is left.
"""
from time import perf_counter
import random

from playerJinhaJang import PlayerJinhaJang

SIZE = 19
EMPTY = -1
NCELL = SIZE * SIZE
CENTER = (SIZE // 2) * SIZE + SIZE // 2
CHARS = ('.', '0', '1')            # index = cell value + 1

AXES = ((0, 1), (1, 0), (1, 1), (1, -1))
DIRS = AXES + tuple((-dr, -dc) for dr, dc in AXES)

# evaluation / move-ordering weights
WINDOW_VALUE = (0, 2, 16, 130, 1300, 2000000)
BLOCK_VALUE = (0, 1, 12, 110, 400000)
CAPTURE_GAIN = 350
SAVE_GAIN = 250
VULNERABLE = 45
FOUR_BONUS = 3000
OPEN_FOUR_BONUS = 60000
THREAT_WIN = 300000
DOUBLE_THREE = 150000

WIN = 100000000
INF = 1 << 60
MAX_PLY = 24
MAX_DEPTH = 20
ROOT_WIDTH = 22
WIDTH = (22, 14, 10, 8, 7, 6)
VCF_DEPTH = 12
VCF_NODES = 6000

# feature switches (used for testing the value of each part)
USE_THREE_RULE = True
USE_THREAT_EVAL = True
USE_VCF = True

# time management (whole game = 1 minute)
BUDGET_DIV = 18.0      # use remaining / BUDGET_DIV per move ...
BUDGET_CAP = 3.0       # ... but never more than this (seconds)
ITER_STOP = 0.45       # do not start a new depth after this share of budget
PANIC_MS = 1000        # below this much time left: no search at all

CAP_TEMPO = 200        # eval bonus: side to move can capture right now


def _build_tables():
    lines = []
    for r in range(SIZE):
        lines.append(tuple(r * SIZE + c for c in range(SIZE)))
    for c in range(SIZE):
        lines.append(tuple(r * SIZE + c for r in range(SIZE)))
    starts = [(0, c) for c in range(SIZE)] + [(r, 0) for r in range(1, SIZE)]
    for r0, c0 in starts:
        cells = []
        r, c = r0, c0
        while r < SIZE and c < SIZE:
            cells.append(r * SIZE + c)
            r += 1
            c += 1
        if len(cells) >= 5:
            lines.append(tuple(cells))
    starts = ([(0, c) for c in range(SIZE)]
              + [(r, SIZE - 1) for r in range(1, SIZE)])
    for r0, c0 in starts:
        cells = []
        r, c = r0, c0
        while r < SIZE and c >= 0:
            cells.append(r * SIZE + c)
            r += 1
            c -= 1
        if len(cells) >= 5:
            lines.append(tuple(cells))

    cell_lines = [[] for _ in range(NCELL)]
    for lid, cells in enumerate(lines):
        for off, idx in enumerate(cells):
            cell_lines[idx].append((lid, off, 1 << (2 * off)))

    caps, rays, near = [], [], []
    for idx in range(NCELL):
        r, c = divmod(idx, SIZE)
        t = []
        for dr, dc in DIRS:
            r3, c3 = r + 3 * dr, c + 3 * dc
            if 0 <= r3 < SIZE and 0 <= c3 < SIZE:
                t.append(((r + dr) * SIZE + c + dc,
                          (r + 2 * dr) * SIZE + c + 2 * dc,
                          r3 * SIZE + c3))
        caps.append(tuple(t))

        rr = []
        for dr, dc in AXES:
            both = []
            for sign in (1, -1):
                ray = []
                for k in range(1, 7):
                    r2, c2 = r + sign * k * dr, c + sign * k * dc
                    if not (0 <= r2 < SIZE and 0 <= c2 < SIZE):
                        break
                    ray.append(r2 * SIZE + c2)
                both.append(tuple(ray))
            rr.append(tuple(both))
        rays.append(tuple(rr))

        nb = []
        for dr in range(-2, 3):
            for dc in range(-2, 3):
                r2, c2 = r + dr, c + dc
                if (dr or dc) and 0 <= r2 < SIZE and 0 <= c2 < SIZE:
                    nb.append(r2 * SIZE + c2)
        near.append(tuple(nb))
    return (tuple(lines), tuple(tuple(x) for x in cell_lines),
            tuple(caps), tuple(rays), tuple(near))


LINES, CELL_LINES, CAPS, RAYS, NEAR = _build_tables()

_rng = random.Random(20261017)
ZOB = tuple(tuple(_rng.getrandbits(64) for _ in range(NCELL))
            for _ in range(2))
ZSIDE = (0, _rng.getrandbits(64))

_CACHE = {}


def _line_key(values):
    """Integer key of a line: 2 bits per cell (empty 1, black 2, white 3)
    plus a sentinel bit on top, so lines of different length never clash."""
    key = 1 << (2 * len(values))
    for off, v in enumerate(values):
        key |= (v + 2) << (2 * off)
    return key


def _line_info(key):
    """Analyse one line given its integer key (see _line_key).

    Returns a tuple, per color (0 / 1):
      [0, 1]   window score
      [2, 3]   wins   : offsets where that color makes exactly five
      [4, 5]   caps   : offsets where that color captures a pair
      [6, 7]   gain   : per-offset move-ordering bonus
      [8, 9]   fours  : offsets where that color makes a four
      [10, 11] ofours : offsets where that color makes an open four
    """
    n = (key.bit_length() - 1) // 2
    s = ''.join('?.01'[(key >> (2 * off)) & 3] for off in range(n))
    score = [0, 0]
    wins = ([], [])
    caps = ([], [])
    fours = ([], [])
    ofours = ([], [])
    gain = ([0] * n, [0] * n)
    for me in (0, 1):
        ch = CHARS[me + 1]
        oc = CHARS[2 - me]
        g_me = gain[me]
        g_op = gain[1 - me]
        partner = {}
        for i in range(n - 4):
            w = s[i:i + 5]
            if oc in w:
                continue
            if i > 0 and s[i - 1] == ch:
                continue
            if i + 5 < n and s[i + 5] == ch:
                continue
            k = w.count(ch)
            if k == 5:
                continue
            score[me] += WINDOW_VALUE[k]
            if k == 4:
                wins[me].append(i + w.index('.'))
            elif k == 3:
                e1 = i + w.index('.')
                e2 = i + w.rindex('.')
                partner.setdefault(e1, set()).add(e2)
                partner.setdefault(e2, set()).add(e1)
            att = WINDOW_VALUE[k + 1] - WINDOW_VALUE[k]
            blk = BLOCK_VALUE[k]
            for j in range(i, i + 5):
                if s[j] == '.':
                    g_me[j] += att
                    g_op[j] += blk
        for j, ps in partner.items():
            fours[me].append(j)
            g_me[j] += FOUR_BONUS
            if len(ps) >= 2:
                ofours[me].append(j)
                g_me[j] += OPEN_FOUR_BONUS
        # pair captures along this line:  me opp opp .  /  . opp opp me
        for i in range(n - 3):
            if s[i + 1] == oc and s[i + 2] == oc:
                a = s[i]
                d = s[i + 3]
                if a == ch and d == '.':
                    j = i + 3
                elif a == '.' and d == ch:
                    j = i
                else:
                    continue
                caps[me].append(j)
                g_me[j] += CAPTURE_GAIN
                g_op[j] += SAVE_GAIN
                score[1 - me] -= VULNERABLE
    info = (score[0], score[1], tuple(wins[0]), tuple(wins[1]),
            tuple(caps[0]), tuple(caps[1]), tuple(gain[0]), tuple(gain[1]),
            tuple(sorted(fours[0])), tuple(sorted(fours[1])),
            tuple(sorted(ofours[0])), tuple(sorted(ofours[1])))
    if len(_CACHE) > 60000:
        _CACHE.clear()
    _CACHE[key] = info
    return info


def _cells(table):
    """Union of board cells stored as {line id: offsets}."""
    out = set()
    for lid, offs in table.items():
        cells = LINES[lid]
        for off in offs:
            out.add(cells[off])
    return out


class _TimeUpJinhaJang(Exception):
    pass


class _VcfAbortJinhaJang(Exception):
    pass


class _BoardJinhaJang:
    """Search board with incremental line scores (internal helper)."""

    def __init__(self, flat):
        self.b = list(flat)
        self.lkey = []
        self.linfo = []
        self.score = [0, 0]
        self.wins = ({}, {})
        self.caps = ({}, {})
        self.fours = ({}, {})
        self.ofours = ({}, {})
        slots = ((2, self.wins[0]), (3, self.wins[1]), (4, self.caps[0]),
                 (5, self.caps[1]), (8, self.fours[0]), (9, self.fours[1]),
                 (10, self.ofours[0]), (11, self.ofours[1]))
        for lid, cells in enumerate(LINES):
            key = _line_key([self.b[i] for i in cells])
            info = _CACHE.get(key)
            if info is None:
                info = _line_info(key)
            self.lkey.append(key)
            self.linfo.append(info)
            self.score[0] += info[0]
            self.score[1] += info[1]
            for k, table in slots:
                if info[k]:
                    table[lid] = info[k]
        self.stack = []          # (idx, color, captured) of moves made
        self.near = [0] * NCELL
        self.cand = set()
        self.h = 0
        self.stones = 0
        for idx in range(NCELL):
            v = self.b[idx]
            if v != EMPTY:
                self.stones += 1
                self.h ^= ZOB[v][idx]
                for j in NEAR[idx]:
                    self.near[j] += 1
        # cand = every cell with a stone within distance 2 (occupied cells
        # included; they are skipped when moves are generated)
        for idx in range(NCELL):
            if self.near[idx]:
                self.cand.add(idx)

    def _lines(self, idx, delta):
        lkey = self.lkey
        linfo = self.linfo
        sc = self.score
        w0, w1 = self.wins
        c0, c1 = self.caps
        f0, f1 = self.fours
        o0, o1 = self.ofours
        for lid, off, mult in CELL_LINES[idx]:
            key = lkey[lid] + delta * mult
            lkey[lid] = key
            info = _CACHE.get(key)
            if info is None:
                info = _line_info(key)
            old = linfo[lid]
            linfo[lid] = info
            sc[0] += info[0] - old[0]
            sc[1] += info[1] - old[1]
            if info[2]:
                w0[lid] = info[2]
            elif old[2]:
                del w0[lid]
            if info[3]:
                w1[lid] = info[3]
            elif old[3]:
                del w1[lid]
            if info[4]:
                c0[lid] = info[4]
            elif old[4]:
                del c0[lid]
            if info[5]:
                c1[lid] = info[5]
            elif old[5]:
                del c1[lid]
            if info[8]:
                f0[lid] = info[8]
            elif old[8]:
                del f0[lid]
            if info[9]:
                f1[lid] = info[9]
            elif old[9]:
                del f1[lid]
            if info[10]:
                o0[lid] = info[10]
            elif old[10]:
                del o0[lid]
            if info[11]:
                o1[lid] = info[11]
            elif old[11]:
                del o1[lid]

    def _put(self, idx, v):
        self.b[idx] = v
        self._lines(idx, v + 1)
        self.h ^= ZOB[v][idx]
        self.stones += 1
        near = self.near
        cand = self.cand
        for j in NEAR[idx]:
            n = near[j] + 1
            near[j] = n
            if n == 1:
                cand.add(j)

    def _take(self, idx):
        b = self.b
        v = b[idx]
        b[idx] = EMPTY
        self._lines(idx, -1 - v)
        self.h ^= ZOB[v][idx]
        self.stones -= 1
        near = self.near
        cand = self.cand
        for j in NEAR[idx]:
            n = near[j] - 1
            near[j] = n
            if not n:
                cand.discard(j)

    def make(self, idx, c):
        """Play c at idx (with captures).

        Returns (captured cells, status) where status bit 1 = mover made
        exactly five, bit 2 = opponent got exactly five because a capture
        cut a longer line (3 = both -> draw).
        """
        o = 1 - c
        self._put(idx, c)
        b = self.b
        captured = None
        for i1, i2, i3 in CAPS[idx]:
            if b[i1] == o and b[i2] == o and b[i3] == c:
                if captured is None:
                    captured = [i1, i2]
                else:
                    captured.append(i1)
                    captured.append(i2)
        status = 0
        if captured:
            for x in captured:
                self._take(x)
            for x in captured:
                if self._five_next_to(x, o):
                    status = 2
                    break
        if self._five_through(idx, c):
            status |= 1
        self.stack.append((idx, c, captured))
        return captured, status

    def unmake(self, idx, c, captured):
        self.stack.pop()
        if captured:
            o = 1 - c
            for x in captured:
                self._put(x, o)
        self._take(idx)

    def unwind(self, height):
        """Take back moves until the stack has `height` entries again
        (used when a search is aborted by the clock or a node limit)."""
        while len(self.stack) > height:
            idx, c, captured = self.stack[-1]
            self.unmake(idx, c, captured)

    def _five_through(self, idx, c):
        b = self.b
        for fw, bw in RAYS[idx]:
            n = 1
            for j in fw:
                if b[j] != c:
                    break
                n += 1
            for j in bw:
                if b[j] != c:
                    break
                n += 1
            if n == 5:
                return True
        return False

    def _five_next_to(self, x, o):
        b = self.b
        for ray_pair in RAYS[x]:
            for ray in ray_pair:
                n = 0
                for j in ray:
                    if b[j] != o:
                        break
                    n += 1
                if n == 5:
                    return True
        return False

    def win_cells(self, c):
        return _cells(self.wins[c])

    def capture_cells(self, c):
        return _cells(self.caps[c])

    def gain(self, idx, c):
        gi = 6 + c
        linfo = self.linfo
        s = 0
        for lid, off, _ in CELL_LINES[idx]:
            s += linfo[lid][gi][off]
        return s

    def evaluate(self, c):
        o = 1 - c
        a = self.score[c]
        v = a - self.score[o] + (a >> 3)
        if CAP_TEMPO and self.caps[c]:
            v += CAP_TEMPO
        if not USE_THREAT_EVAL:
            return v
        if self.ofours[c]:
            # live three and it is our move: open four next
            v += THREAT_WIN if not self.fours[o] else THREAT_WIN // 2
        elif len(self.ofours[o]) >= 2 and not self.fours[c]:
            # two live threes against us and no forcing reply
            v -= DOUBLE_THREE
        return v


class SmartPlayerJinhaJang(PlayerJinhaJang):
    def __init__(self, color):
        super().__init__(color)
        self._tt = {}
        self._vtt = {}
        self._deadline = 0.0
        self._hard = 0.0
        self._nodes = 0
        self._vnodes = 0
        self._vlimit = 0
        self._iter_best = None
        self._killers = []
        self.last_info = None

    # ------------------------------------------------------------ interface
    def take_turn(self, board, time):
        t0 = perf_counter()
        flat = [int(board[r][c]) for r in range(SIZE) for c in range(SIZE)]
        try:
            idx = self._think(flat, time, t0)
            if idx is not None and flat[idx] == EMPTY:
                return (idx // SIZE, idx % SIZE)
        except Exception:
            pass
        return self._fallback(flat)

    # ------------------------------------------------------------- planning
    def _budget(self, time_ms, stones):
        """(soft budget, hard limit) in seconds for this move."""
        if time_ms is None or time_ms < 0:
            return 2.0, 4.0
        rem = time_ms / 1000.0
        budget = min(BUDGET_CAP, rem / BUDGET_DIV)
        if rem < 5.0:
            budget = rem / 30.0
        if stones < 4:
            budget = min(budget, 0.3)
        budget = max(budget, 0.003)
        # absolute limit for everything (search + VCF checks)
        hard = min(budget * 1.5 + 0.1, rem * 0.25)
        return budget, hard

    def _think(self, flat, time_ms, t0):
        c = self.color
        o = 1 - c
        st = _BoardJinhaJang(flat)
        if st.stones == 0:
            return CENTER
        budget, hard = self._budget(time_ms, st.stones)
        self._deadline = t0 + budget
        self._hard = t0 + hard
        self._nodes = 0
        self._killers = [[None, None] for _ in range(MAX_PLY + 2)]
        if len(self._tt) > 250000:
            self._tt = {}
        self._vtt = {}
        self.last_info = ('?', 0, 0)

        # 1) win right now
        for m in st.win_cells(c):
            cap, status = st.make(m, c)
            st.unmake(m, c, cap)
            if status == 1:
                self.last_info = ('win', 0, 0)
                return m

        # 2) the opponent threatens five -> only real defenses
        if st.wins[o]:
            moves = self._defenses(st, c)
            if not moves:
                return min(st.win_cells(o))
            if len(moves) == 1:
                self.last_info = ('forced', 0, 0)
                return moves[0]
        elif time_ms is not None and 0 <= time_ms < PANIC_MS:
            # almost out of time: no search, best-ordered move
            self.last_info = ('panic', 0, 0)
            moves = self._moves(st, c, ROOT_WIDTH, None, 0)
            return moves[0] if moves else None
        else:
            # 3) our own forced win by continuous fours
            m = -1
            if USE_VCF:
                m = self._try_vcf(st, c, VCF_DEPTH, VCF_NODES * 3)
            if m >= 0:
                self.last_info = ('vcf', 0, 0)
                return m
            moves = self._moves(st, c, ROOT_WIDTH, None, 0)
            if not moves:
                return None
            if len(moves) == 1:
                return moves[0]

        # 4) iterative deepening alpha-beta
        best = moves[0]
        order = moves
        depth = 1
        val = 0
        while depth <= MAX_DEPTH:
            height = len(st.stack)
            try:
                val, m, order2 = self._root(st, moves, depth, c)
            except _TimeUpJinhaJang:
                st.unwind(height)
                if self._iter_best is not None:
                    best = self._iter_best
                break
            best = m
            moves = order = order2
            if val >= WIN - 1000 or val <= -(WIN - 1000):
                break
            if perf_counter() - t0 > budget * ITER_STOP:
                break
            depth += 1
        self.last_info = ('search', depth, self._nodes)

        # 5) do not hand the opponent a forced win by fours
        if USE_VCF and not st.wins[o] and val > -(WIN - 1000):
            best = self._vcf_safe(st, c, best, order)
        return best

    def _root(self, st, moves, depth, c):
        o = 1 - c
        alpha = -INF
        best_v = -INF
        best_m = moves[0]
        scored = []
        self._iter_best = None
        for i, m in enumerate(moves):
            cap, status = st.make(m, c)
            if status:
                if status == 1:
                    v = WIN - 1
                elif status == 2:
                    v = -(WIN - 1)
                else:
                    v = 0
            else:
                v = -self._negamax(st, depth - 1, -INF, -alpha, o, 1)
            st.unmake(m, c, cap)
            scored.append((v, -i, m))
            if v > best_v:
                best_v = v
                best_m = m
                self._iter_best = m
                if v > alpha:
                    alpha = v
        scored.sort(reverse=True)
        return best_v, best_m, [m for _, _, m in scored]

    # --------------------------------------------------------------- search
    def _negamax(self, st, depth, alpha, beta, c, ply):
        self._nodes += 1
        if not (self._nodes & 127) and perf_counter() > self._deadline:
            raise _TimeUpJinhaJang()
        o = 1 - c
        if st.wins[c]:
            return WIN - ply
        if ply >= MAX_PLY:
            return st.evaluate(c)
        forced = bool(st.wins[o])
        if forced:
            moves = self._defenses(st, c)
            if not moves:
                return -(WIN - ply - 1)
        elif depth <= 0:
            return st.evaluate(c)
        else:
            moves = None

        key = st.h ^ ZSIDE[c]
        ent = self._tt.get(key)
        tt_move = None
        if ent is not None:
            e_depth, e_flag, e_val, tt_move = ent
            if e_depth >= depth:
                if e_flag == 0:
                    return e_val
                if e_flag == 1 and e_val >= beta:
                    return e_val
                if e_flag == 2 and e_val <= alpha:
                    return e_val
        if moves is None:
            width = WIDTH[ply] if ply < len(WIDTH) else WIDTH[-1]
            moves = self._moves(st, c, width, tt_move, ply)
            if not moves:
                return 0
        elif tt_move is not None and tt_move in moves:
            moves.remove(tt_move)
            moves.insert(0, tt_move)

        a0 = alpha
        best = -INF
        best_m = moves[0]
        for m in moves:
            cap, status = st.make(m, c)
            if status:
                if status == 1:
                    v = WIN - ply - 1
                elif status == 2:
                    v = -(WIN - ply - 1)
                else:
                    v = 0
            else:
                # forced replies (blocking a five-threat) do not use depth
                nd = depth if forced else depth - 1
                v = -self._negamax(st, nd, -beta, -alpha, o, ply + 1)
            st.unmake(m, c, cap)
            if v > best:
                best = v
                best_m = m
                if v > alpha:
                    alpha = v
                    if alpha >= beta:
                        if not forced and not cap:
                            ks = self._killers[ply]
                            if ks[0] != m:
                                ks[1] = ks[0]
                                ks[0] = m
                        break
        if best <= a0:
            flag = 2
        elif best >= beta:
            flag = 1
        else:
            flag = 0
        self._tt[key] = (depth, flag, best, best_m)
        return best

    def _moves(self, st, c, width, tt_move, ply):
        o = 1 - c
        gi = 6 + c
        linfo = st.linfo
        b = st.b
        if USE_THREE_RULE and st.ofours[o] and not st.ofours[c]:
            # the opponent has a live three: block it, make a four, or capture
            cand = set()
            for lid in st.ofours[o]:
                cells = LINES[lid]
                for off in linfo[lid][8 + o]:
                    cand.add(cells[off])
            cand |= _cells(st.fours[c])
            cand |= _cells(st.caps[c])
            scored = []
            for m in cand:
                s = 0
                for lid, off, _ in CELL_LINES[m]:
                    s += linfo[lid][gi][off]
                scored.append((s, m))
            scored.sort(reverse=True)
            moves = [m for _, m in scored]
        else:
            scored = []
            for idx in st.cand:
                if b[idx] != EMPTY:
                    continue
                s = 0
                for lid, off, _ in CELL_LINES[idx]:
                    s += linfo[lid][gi][off]
                scored.append((s, idx))
            scored.sort(reverse=True)
            moves = [m for _, m in scored[:width]]
            if ply < len(self._killers):
                for k in self._killers[ply]:
                    if (k is not None and b[k] == EMPTY and st.near[k]
                            and k not in moves):
                        moves.append(k)
        if tt_move is not None and b[tt_move] == EMPTY:
            if tt_move in moves:
                moves.remove(tt_move)
            moves.insert(0, tt_move)
        return moves

    def _defenses(self, st, c):
        """Moves after which the opponent has no five-threat left."""
        o = 1 - c
        cand = st.win_cells(o) | st.capture_cells(c)
        good = []
        for m in cand:
            cap, status = st.make(m, c)
            if status & 1:
                ok = True
            elif status & 2:
                ok = False
            else:
                ok = not st.wins[o]
            st.unmake(m, c, cap)
            if ok:
                good.append((st.gain(m, c), m))
        good.sort(reverse=True)
        return [m for _, m in good]

    # ------------------------------------------------------------------ VCF
    def _try_vcf(self, st, c, depth, limit):
        """Winning first move by continuous fours for c, or -1."""
        if not st.fours[c]:
            return -1
        self._vnodes = 0
        self._vlimit = limit
        height = len(st.stack)
        try:
            return self._vcf(st, c, depth)
        except (_VcfAbortJinhaJang, _TimeUpJinhaJang):
            st.unwind(height)
            return -1

    def _vcf(self, st, c, depth):
        self._vnodes += 1
        if self._vnodes > self._vlimit:
            raise _VcfAbortJinhaJang()
        if not (self._vnodes & 63) and perf_counter() > self._hard:
            raise _TimeUpJinhaJang()
        o = 1 - c
        if st.wins[c]:
            return min(st.win_cells(c))
        if st.wins[o] or depth <= 0 or not st.fours[c]:
            return -1
        key = st.h ^ ZSIDE[c]
        ent = self._vtt.get(key)
        if ent is not None:
            if ent[0]:
                return ent[1]
            if ent[1] >= depth:
                return -1
        opens = _cells(st.ofours[c])
        rest = _cells(st.fours[c]) - opens
        for m in list(opens) + sorted(rest):
            cap, status = st.make(m, c)
            if status or st.wins[o] or not st.wins[c]:
                st.unmake(m, c, cap)
                continue
            ok = True
            for d in self._defenses(st, o):
                cap2, status2 = st.make(d, o)
                if status2 & 1:
                    ok = False
                elif not status2 & 2:
                    ok = self._vcf(st, c, depth - 1) >= 0
                st.unmake(d, o, cap2)
                if not ok:
                    break
            st.unmake(m, c, cap)
            if ok:
                self._vtt[key] = (True, m)
                return m
        self._vtt[key] = (False, depth)
        return -1

    def _vcf_safe(self, st, c, best, order):
        o = 1 - c
        tried = 0
        for m in [best] + [x for x in order if x != best]:
            if tried >= 6:
                break
            tried += 1
            cap, status = st.make(m, c)
            if status:
                st.unmake(m, c, cap)
                return m if status & 1 else best
            danger = (not st.wins[c]
                      and self._try_vcf(st, o, VCF_DEPTH, VCF_NODES) >= 0)
            st.unmake(m, c, cap)
            if not danger:
                return m
        return best

    # ------------------------------------------------------------- fallback
    def _fallback(self, flat):
        best = None
        for idx in range(NCELL):
            if flat[idx] == EMPTY:
                r, c = divmod(idx, SIZE)
                d = abs(r - SIZE // 2) + abs(c - SIZE // 2)
                if best is None or d < best[0]:
                    best = (d, r, c)
        if best is None:
            return (0, 0)
        return (best[1], best[2])
