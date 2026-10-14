"""Hybrid Omok++ agent. Standard library only.

AI disclosure: ChatGPT adapted the uploaded JangJinha v11 engine/search and
Geonwoo2/Minjun v3 safety and proof ideas. The JangJinha source credits Claude
Code and team review. Review the code and declare assistance per course rules.
"""
import random
import time
from time import monotonic as _now
from playerJRM import PlayerJRM
SIZE = 19
NCELL = SIZE * SIZE
EMPTY = -1
WIN = 10000000
DEFAULT_PARAMS = {'w1': 1.8797, 'w2': 23.1797, 'w3': 100.0, 'w4': 411.2181, 'cap': 108.8743, 'tempo': 1.561, 'defw': 1.0648, 'capb': 640.9005, 'width': 10, 'root_width': 20, 'o3': 150.0, 'fork': 3000.0, 'forko': 2000.0, 'vct': 5, 'vctk': 8, 'svct': 0, 'vfrac': 0.15, 'widen': 1, 'abfrac': 0.7, 'xcap': 1, 'qvcf': 0, 'safety': 1, 'tmax': 2.5, 'tmoves': 35, 'tsoft': 0.45}

def _build_geometry():
    lines = []
    for r in range(SIZE):
        lines.append([r * SIZE + c for c in range(SIZE)])
    for c in range(SIZE):
        lines.append([r * SIZE + c for r in range(SIZE)])
    for k in range(-(SIZE - 5), SIZE - 4):
        lines.append([r * SIZE + (r + k) for r in range(SIZE) if 0 <= r + k < SIZE])
    for s in range(4, 2 * SIZE - 5):
        lines.append([r * SIZE + (s - r) for r in range(SIZE) if 0 <= s - r < SIZE])
    cell_lines = [[] for _ in range(NCELL)]
    cell_pos = [[] for _ in range(NCELL)]
    for lid, cells in enumerate(lines):
        for i, p in enumerate(cells):
            cell_pos[p].append((lid, i))
            cell_lines[p].append((lid, 32 * 3 ** i))
    near = []
    cap_rays = []
    dirs8 = [(dr, dc) for dr in (-1, 0, 1) for dc in (-1, 0, 1) if dr or dc]
    for p in range(NCELL):
        r, c = divmod(p, SIZE)
        near.append(tuple(((r + dr) * SIZE + (c + dc) for dr in range(-2, 3) for dc in range(-2, 3) if (dr or dc) and 0 <= r + dr < SIZE and (0 <= c + dc < SIZE))))
        rays = []
        for dr, dc in dirs8:
            if 0 <= r + 3 * dr < SIZE and 0 <= c + 3 * dc < SIZE:
                rays.append(tuple(((r + k * dr) * SIZE + (c + k * dc) for k in (1, 2, 3))))
        cap_rays.append(tuple(rays))
    return (lines, [tuple(x) for x in cell_lines], tuple(near), tuple(cap_rays), [tuple(x) for x in cell_pos])
LINES, CELL_LINES, NEAR, CAP_RAYS, CELL_POS = _build_geometry()
NLINES = len(LINES)
LINE_BASE = [len(cells) for cells in LINES]
_rng = random.Random(20261019)
ZOBRIST = [[0] * NCELL] + [[_rng.getrandbits(64) for _ in range(NCELL)] for _ in (1, 2)]
ZOBRIST_SIDE = _rng.getrandbits(64)

class _TimeUp(Exception):
    pass
_LINE_CACHES = {}

def _win_cells(cells, x, length):
    """Empty cells of a line where colour x would complete an exact five."""
    o = 3 - x
    wins = set()
    for s in range(length - 4):
        seg = cells[s:s + 5]
        if o in seg or seg.count(x) != 4:
            continue
        if s > 0 and cells[s - 1] == x or (s + 5 < length and cells[s + 5] == x):
            continue
        wins.add(s + seg.index(0))
    return wins

def _line_info_factory(params):
    weights = (0.0, params['w1'], params['w2'], params['w3'], params['w4'])
    capw = params['cap']
    o3w = params['o3']
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
                    if s > 0 and cells[s - 1] == x or (s + 5 < length and cells[s + 5] == x):
                        continue
                    if n == 5:
                        five = 1
                        continue
                    wins.add(s + seg.index(0))
                score += weights[n]
            caps = 0
            for i in range(length - 3):
                if cells[i + 1] == o and cells[i + 2] == o:
                    a, d = (cells[i], cells[i + 3])
                    if a == x and d == 0 or (a == 0 and d == x):
                        caps += 1
            open3 = 0
            if not wins and (not five) and (cells.count(x) >= 3):
                for e in range(length):
                    # Only a cell with 3+ own stones within reach can turn
                    # the line into an open four (JangJinha v12 speedup).
                    if cells[e] == 0 and cells[max(0, e - 4):e + 5].count(x) >= 3:
                        cells[e] = x
                        if len(_win_cells(cells, x, length)) >= 2:
                            open3 = 1
                        cells[e] = 0
                        if open3:
                            break
            threat = 1 if wins or open3 else 0
            vulnerable = 0
            for i in range(length - 3):
                if cells[i + 1] == x and cells[i + 2] == x:
                    if cells[i] == o and cells[i + 3] == 0 or (cells[i] == 0 and cells[i + 3] == o):
                        vulnerable += 1
            score -= 0.45 * capw * vulnerable
            out.append((score + capw * caps + o3w * open3, five, len(wins), tuple(sorted(wins)), threat))
        info = (out[0][0], out[1][0], out[0][1], out[1][1], out[0][2], out[1][2], out[0][3], out[1][3], out[0][4], out[1][4])
        cache[k] = info
        return info
    return (cache, compute)

class _Engine:

    def __init__(self, params):
        self.p = params
        self.cache, self.compute = _line_info_factory(params)
        self.tt = {}
        self.vtt = {}
        self.ocache = {}
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

    def _put(self, p, v):
        self.cells[p] = v
        self.h ^= ZOBRIST[v][p]
        self.stones += 1
        lk, E, F, NW, T = (self.lk, self.E, self.F, self.NW, self.T)
        cache, compute = (self.cache, self.compute)
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
        lk, E, F, NW, T = (self.lk, self.E, self.F, self.NW, self.T)
        cache, compute = (self.cache, self.compute)
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
            if cells[a] == o and cells[b] == o and (cells[d] == me):
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

    def win_points(self, x):
        """Empty cells where colour x completes an exact five."""
        pts = []
        idx = 6 + x - 1
        lk, cache, compute = (self.lk, self.cache, self.compute)
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
        cells, nb = (self.cells, self.nb)
        return [p for p in range(NCELL) if nb[p] and (not cells[p])]

    def capture_moves(self, me, cand):
        o = 3 - me
        cells = self.cells
        out = []
        for p in cand:
            for a, b, d in CAP_RAYS[p]:
                if cells[a] == o and cells[b] == o and (cells[d] == me):
                    out.append(p)
                    break
        return out

    def evaluate(self, me):
        o = 3 - me
        v = self.p['tempo'] * self.E[me] - self.E[o]
        if self.T[me] >= 2:
            v += self.p['fork']
        if self.T[o] >= 2:
            v -= self.p['forko']
        return v

    def score_moves(self, me, cand, with_history=True):
        """Heuristic move ordering: own gain + weighted opponent gain denied."""
        o = 3 - me
        ei, eo = (me - 1, o - 1)
        lk, cells = (self.lk, self.cells)
        cache, compute = (self.cache, self.compute)
        defw, capb = (self.p['defw'], self.p['capb'])
        xcap = self.p['xcap']
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
                if cells[a] == o and cells[b] == o and (cells[d] == me):
                    ncap += 1
            if ncap:
                if xcap:
                    E = self.E
                    e_me, e_o = (E[me], E[o])
                    cap = self.make(p, me)
                    try:
                        att = E[me] - e_me + (e_o - E[o])
                    finally:
                        self.unmake(p, me, cap)
                att += capb * ncap
            out.append((att + defw * dfn + hist[p], p))
        out.sort(reverse=True)
        return out

    def threat_moves(self, me, cand):
        """Moves creating a four or a new open three for `me`, strongest first.
        Returns (move, makes_four) pairs."""
        lk = self.lk
        cache, compute = (self.cache, self.compute)
        i4, i3, ie = (4 + me - 1, 8 + me - 1, me - 1)
        o = 3 - me
        cells = self.cells
        xcap = self.p['xcap']
        out = []
        for p in cand:
            if xcap and any((cells[a] == o and cells[b] == o and (cells[d] == me) for a, b, d in CAP_RAYS[p])):
                nw0, t0, e0 = (self.NW[me], self.T[me], self.E[me])
                cap = self.make(p, me)
                try:
                    g4, g3, ev = (self.NW[me] - nw0, self.T[me] - t0, self.E[me] - e0)
                finally:
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
        cache, compute = (self.cache, self.compute)
        idx = 4 + me - 1
        o = 3 - me
        cells = self.cells
        xcap = self.p['xcap']
        out = []
        for p in cand:
            if xcap and any((cells[a] == o and cells[b] == o and (cells[d] == me) for a, b, d in CAP_RAYS[p])):
                nw0 = self.NW[me]
                cap = self.make(p, me)
                try:
                    gain = self.NW[me] - nw0
                finally:
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

class _HybridEngine(_Engine):
    """Fast line engine with capture-aware wins and complete tactical escapes."""

    def __init__(self, params):
        self.clock = None
        self.win_cache = {}
        self.defence_cache = {}
        super().__init__(params)

    def check_time(self):
        if self.clock is not None:
            self.clock()

    def load(self, board):
        super().load(board)
        self.win_cache.clear()
        self.defence_cache.clear()

    def outcome(self, me):
        if self.F[me] and self.F[3 - me]:
            return 0
        if self.F[me]:
            return 1
        if self.F[3 - me]:
            return -1
        return 0 if self.stones == NCELL else None

    def strict_wins(self, me):
        """Winning line completions that remain wins AFTER all captures."""
        if not self.NW[me]:
            return []
        key = (self.h, me)
        hit = self.win_cache.get(key)
        if hit is not None:
            return list(hit)
        result = []
        enemy = 3 - me
        for p in self.win_points(me):
            self.check_time()
            capture = any(self.cells[a] == enemy and self.cells[b] == enemy
                          and self.cells[end] == me for a, b, end in CAP_RAYS[p])
            if not capture:
                result.append(p)
                continue
            record = self.make(p, me)
            try:
                if self.outcome(me) == 1:
                    result.append(p)
            finally:
                self.unmake(p, me, record)
        self.win_cache[key] = tuple(result)
        return result

    def defence_candidates(self, me):
        """Every reply that can remove a strict win or produce a draw/win.

        A remaining quiet reply neither changes a winning line nor creates a
        capture at its endpoint. At least one strict winning continuation is
        therefore unchanged. This lets the verifier consider it without
        doing a full make/unmake, while still enumerating all legal replies.
        """
        enemy = 3 - me
        threats = self.strict_wins(enemy)
        if not threats:
            return set()
        cand = self.candidates()
        captures = set(self.capture_moves(me, cand))
        enemy_captures = set(self.capture_moves(enemy, threats))
        choices = set(threats) | captures | set(self.win_points(me))
        for threat in threats:
            if threat in enemy_captures:
                record = self.make(threat, enemy)
                try:
                    choices.update(self.win_points(me))
                finally:
                    self.unmake(threat, enemy, record)
            for a, b, end in CAP_RAYS[threat]:
                if self.cells[end] != enemy:
                    continue
                if self.cells[a] == me and self.cells[b] == 0:
                    choices.add(b)
                elif self.cells[a] == 0 and self.cells[b] == me:
                    choices.add(a)
        return {p for p in choices if not self.cells[p]}

    def defences(self, me):
        """Blocks, captures and quiet capture-induced draw escapes."""
        key = (self.h, me)
        if key in self.defence_cache:
            return list(self.defence_cache[key])
        enemy = 3 - me
        choices = self.defence_candidates(me)
        ordered = self.score_moves(me, [p for p in choices if not self.cells[p]])
        safe, draws = [], []
        for _, p in ordered:
            self.check_time()
            record = self.make(p, me)
            try:
                outcome = self.outcome(me)
                if outcome == 1:
                    safe.insert(0, p)
                elif outcome == 0:
                    draws.append(p)
                elif outcome is None and not self.strict_wins(enemy):
                    safe.append(p)
            finally:
                self.unmake(p, me, record)
        self.defence_cache[key] = tuple(safe + draws)
        return safe + draws


class _Searcher:

    def __init__(self, engine):
        self.e = engine
        self.deadline = float('inf')
        self.node_limit = None
        self.nodes = 0

    def _tick(self):
        self.nodes += 1
        if not self.nodes & 15:
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
        if self.e.stones == NCELL:
            return 0
        return None

    def negamax(self, depth, alpha, beta, me, ply, ext):
        self._tick()
        e = self.e
        o = 3 - me
        if e.strict_wins(me):
            return WIN - ply
        threatened = bool(e.strict_wins(o))
        if depth <= 0:
            if threatened and ext > 0:
                depth = 1
                ext -= 1
            else:
                qd = e.p['qvcf']
                if qd and (not threatened) and self.vcf(me, qd, ply):
                    return WIN - ply - 2 * qd
                return e.evaluate(me)
        key = e.h ^ (ZOBRIST_SIDE if me == 2 else 0)
        entry = e.tt.get(key)
        tt_move = None
        if entry is not None:
            d, flag, val, mv = entry
            if val > WIN - 1000:
                val -= ply
            elif val < -WIN + 1000:
                val += ply
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
            moves = e.defences(me)
            if not moves:
                return -WIN + ply + 2
        rest = ()
        if not threatened:
            width = e.p['width']
            # JangJinha v12 speedup: static move scores are cached per
            # position (reused across iterative-deepening depths); the
            # history bonus changes during the search, so it is added fresh.
            static = e.ocache.get(key)
            if static is None:
                static = e.score_moves(me, cand, with_history=False)
                e.ocache[key] = static
            hist = e.history
            ranked = [p for _, p in sorted(((sc + hist[p], p) for sc, p in static), reverse=True)]
            moves, rest = (ranked[:width], ranked[width:])
        if tt_move is not None and tt_move in moves:
            moves.remove(tt_move)
            moves.insert(0, tt_move)
        alpha0 = alpha
        best = -WIN * 2
        best_move = None
        cut = False
        for batch in (moves, rest):
            if batch is rest and (cut or best > -(WIN - 100) or (not e.p['widen'])):
                break
            for p in batch:
                cap = e.make(p, me)
                try:
                    val = self._after_move(me, ply + 1)
                    if val is None:
                        val = -self.negamax(depth - 1, -beta, -alpha, o, ply + 1, ext)
                finally:
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
        flag = 0 if alpha0 < best < beta else 1 if best >= beta else 2
        stored = best + ply if best > WIN - 1000 else best - ply if best < -WIN + 1000 else best
        e.tt[key] = (depth, flag, stored, best_move)
        return best

    def vcf(self, me, depth, ply=0):
        """True if `me` (to move) wins by consecutive fours."""
        self._tick()
        e = self.e
        o = 3 - me
        if e.strict_wins(me):
            return True
        if depth <= 0 or e.strict_wins(o):
            return False
        cand = e.candidates()
        for p in e.four_moves(me, cand)[:12]:
            cap = e.make(p, me)
            try:
                ok = False
                res = self._after_move(me, ply + 1)
                if res is not None:
                    ok = res > 0
                elif e.strict_wins(me):
                    ok = self._vcf_defend(me, depth, ply + 1)
            finally:
                e.unmake(p, me, cap)
            if ok:
                return True
        return False

    def _vcf_defend(self, me, depth, ply):
        """`o` to move, facing `me`'s five threat: True if every reply loses."""
        e = self.e
        o = 3 - me
        replies = e.defences(o)
        for p in replies:
            cap = e.make(p, o)
            try:
                res = self._after_move(o, ply + 1)
                if res is not None:
                    lost = res < 0
                elif e.strict_wins(o):
                    lost = bool(e.strict_wins(me))
                else:
                    lost = self.vcf(me, depth - 1, ply + 1)
            finally:
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
        if e.strict_wins(a):
            return True
        if depth <= 0 or e.strict_wins(d):
            return False
        key = (e.h, a, depth)
        hit = e.vtt.get(key)
        if hit is not None:
            return hit
        result = False
        for p, four in e.threat_moves(a, e.candidates())[:width]:
            cap = e.make(p, a)
            try:
                res = self._after_move(a, ply + 1)
                if res is not None:
                    ok = res > 0
                else:
                    ok = self._vct_defend(a, depth, ply + 1, None if e.strict_wins(a) else p, width)
            finally:
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
            replies = e.defences(d)
        else:
            replies = e.line_cells_near(three_at)
            replies += e.four_moves(d, cand)
        replies += e.capture_moves(d, cand)
        replies += e.strict_wins(d)
        for r in dict.fromkeys(replies):
            cap = e.make(r, d)
            try:
                res = self._after_move(d, ply + 1)
                if res is not None:
                    lost = res < 0
                elif e.strict_wins(d):
                    lost = bool(e.strict_wins(a))
                else:
                    lost = self.vct(a, depth - 1, ply + 1, width)
            finally:
                e.unmake(r, d, cap)
            if not lost:
                return False
        return True

    def find_vct_move(self, me, depth, width):
        e = self.e
        if e.strict_wins(3 - me):
            return None
        for p, four in e.threat_moves(me, e.candidates())[:width]:
            cap = e.make(p, me)
            try:
                res = self._after_move(me, 1)
                if res is not None:
                    ok = res > 0
                else:
                    ok = self._vct_defend(me, depth, 1, None if e.strict_wins(me) else p, width)
            finally:
                e.unmake(p, me, cap)
            if ok:
                return p
        return None

    def find_vcf_move(self, me, depth):
        e = self.e
        if e.strict_wins(3 - me):
            return None
        for p in e.four_moves(me, e.candidates())[:12]:
            cap = e.make(p, me)
            try:
                res = self._after_move(me, 1)
                if res is not None:
                    ok = res > 0
                else:
                    ok = bool(e.strict_wins(me)) and self._vcf_defend(me, depth, 1)
            finally:
                e.unmake(p, me, cap)
            if ok:
                return p
        return None

    def root(self, me, max_depth, soft_time, start):
        """Iterative deepening at the root. Returns (move, score, depth)."""
        e = self.e
        o = 3 - me
        cand = e.candidates()
        if e.strict_wins(o):
            moves = e.defences(me)
        else:
            moves = [p for _, p in e.score_moves(me, cand)[:e.p['root_width']]]
        preferred = getattr(self, 'preferred', None)
        if preferred is not None:
            if preferred in moves:
                moves.remove(preferred)
                moves.insert(0, preferred)
            elif preferred in cand and not e.strict_wins(o):
                moves.insert(0, preferred)
        self.root_order = list(moves)
        if not moves:
            return (None, 0, 0)
        if len(moves) == 1:
            return (moves[0], 0, 0)
        best_move, best_score, done_depth = (moves[0], -WIN * 2, 0)
        for depth in range(1, max_depth + 1):
            alpha, beta = (-WIN * 2, WIN * 2)
            iter_best, iter_score = (None, -WIN * 2)
            scores = {}
            try:
                for p in moves:
                    cap = e.make(p, me)
                    try:
                        val = self._after_move(me, 1)
                        if val is None:
                            val = -self.negamax(depth - 1, -beta, -alpha, o, 1, 6)
                    finally:
                        e.unmake(p, me, cap)
                    scores[p] = val
                    if val > iter_score:
                        iter_score, iter_best = (val, p)
                        if val > alpha:
                            alpha = val
            except _TimeUp:
                if iter_best is not None and (iter_best == best_move or iter_score > best_score):
                    best_move, best_score = (iter_best, iter_score)
                break
            unstable = done_depth > 0 and (iter_best != best_move or iter_score < best_score - 300)
            best_move, best_score, done_depth = (iter_best, iter_score, depth)
            moves.sort(key=lambda m: scores.get(m, -WIN * 3), reverse=True)
            self.root_order = list(moves)
            if best_score >= WIN - 100 or best_score <= -(WIN - 100):
                break
            if time.monotonic() - start > soft_time:
                if unstable and not getattr(self, 'extended', False):
                    soft_time = max(soft_time, (self.deadline - start) * 0.9)
                    self.extended = True
                else:
                    break
        return (best_move, best_score, done_depth)


class _ProofUnknown(Exception):
    pass


class _ForcingVerifier:
    """Bounded selective attacks, but EVERY legal defender reply is checked."""

    def __init__(self, engine, deadline, node_limit=1500):
        self.e = engine
        self.deadline = deadline
        self.node_limit = node_limit
        self.nodes = 0

    def tick(self):
        self.nodes += 1
        if self.nodes > self.node_limit or time.monotonic() >= self.deadline:
            raise _ProofUnknown
        self.e.check_time()

    def verify(self, move, attacker, depth=3):
        """True = proved; False/None = refuted or unknown, never a forced loss."""
        if self.e.cells[move]:
            return False
        try:
            self.tick()
            captured = self.e.make(move, attacker)
            try:
                result = self.e.outcome(attacker)
                if result is not None:
                    return result == 1
                if not self.e.strict_wins(attacker):
                    return None
                return self.defend(attacker, depth - 1)
            finally:
                self.e.unmake(move, attacker, captured)
        except (_ProofUnknown, _TimeUp):
            return None

    def attack(self, attacker, left):
        self.tick()
        if self.e.strict_wins(attacker):
            return True
        if left <= 0:
            return False
        candidates = self.e.four_moves(attacker, self.e.candidates())[:8]
        for move in candidates:
            self.tick()
            captured = self.e.make(move, attacker)
            try:
                result = self.e.outcome(attacker)
                if result == 1:
                    return True
                if result is None and self.e.strict_wins(attacker):
                    if self.defend(attacker, left - 1):
                        return True
            finally:
                self.e.unmake(move, attacker, captured)
        return False

    def defend(self, attacker, left):
        self.tick()
        defender = 3 - attacker
        if self.e.strict_wins(defender):
            return False
        replies = [p for p in range(NCELL) if not self.e.cells[p]]
        priority = set(self.e.strict_wins(attacker))
        priority.update(self.e.capture_moves(defender, replies))
        replies.sort(key=lambda p: (p not in priority, p))
        relevant = self.e.defence_candidates(defender)
        for move in replies:
            self.tick()
            if move not in relevant:
                # This legal reply leaves a verified winning endpoint intact.
                # Captures, counter-wins and all draw escapes are in relevant.
                continue
            captured = self.e.make(move, defender)
            try:
                result = self.e.outcome(attacker)
                if result in (-1, 0):
                    return False
                if result == 1 or self.e.strict_wins(attacker):
                    continue
                if not self.attack(attacker, left):
                    return False
            finally:
                self.e.unmake(move, defender, captured)
        return True


class SmartPlayerJRM(PlayerJRM):
    """Jang's efficient engine, Minjun's verifier, conservative adaptive clock.

    v13 merge: Geonwoo v3 hybrid + JangJinha v12 search speedup (cached
    static move ordering with live history, faster open-three detection)."""

    def __init__(self, color):
        super().__init__(color)
        if color not in (0, 1):
            raise ValueError('color must be 0 (black) or 1 (white)')
        self.params = dict(DEFAULT_PARAMS)
        self.params.update({'root_width': 24, 'tmax': 2.4})
        self.engine = _HybridEngine(self.params)
        self.moves_played = 0
        self.last_search = {}

    def _budget(self, remaining, stones, pressure):
        expected = max(16, 28 - self.moves_played // 2)
        base = 2.0 if remaining is None else min(2.4, remaining / expected)
        hard = min(3.2, base * (1.25 if pressure else 1.0))
        if remaining is not None:
            hard = min(hard, max(0.001, remaining * 0.85 - 0.025))
        if stones <= 2:
            hard = min(hard, 0.4)
        elif stones <= 5:
            hard = min(hard, 1.0)
        return max(0.001, hard * 0.6), max(0.001, hard)

    def take_turn(self, board, time):
        started = _now()
        legal = [(r, c) for r in range(SIZE) for c in range(SIZE) if board[r][c] == EMPTY]
        if not legal:
            raise ValueError('No legal move: board is full')
        fallback = min(legal, key=lambda rc: abs(rc[0] - 9) + abs(rc[1] - 9))
        self.moves_played += 1
        self.last_search = {'phase': 'fallback', 'depth': 0, 'nodes': 0, 'proof_nodes': 0}
        if len(legal) == NCELL:
            self.last_search['phase'] = 'opening'
            return (9, 9)
        remaining = None if time is None or time < 0 else float(time) / 1000
        if remaining is not None and remaining < 0.025:
            return fallback
        # The parameter is named time for compatibility with the Player API.
        clock = _now
        e = self.engine
        e.clock = None
        e.load(board)
        me, enemy = self.color + 1, 2 - self.color
        pressure = bool(e.NW[me] or e.NW[enemy] or e.T[enemy] or e.T[me] >= 2)
        soft, hard = self._budget(remaining, e.stones, pressure)
        deadline = started + hard

        def check():
            if clock() >= deadline:
                raise _TimeUp

        e.clock = check
        if len(e.tt) > 120_000:
            e.tt.clear()
        if len(e.vtt) > 70_000:
            e.vtt.clear()
        if len(e.ocache) > 100_000:
            e.ocache.clear()
        e.history = [h >> 2 for h in e.history]
        best = fallback[0] * SIZE + fallback[1]
        phase, depth, score = 'ordered', 0, None
        proof_nodes, search_nodes = 0, 0
        rejected = set()
        order = [best]
        try:
            wins = e.strict_wins(me)
            if wins:
                best, phase = wins[0], 'immediate-win'
            else:
                threatened = bool(e.strict_wins(enemy))
                forced = e.defences(me) if threatened else None
                if forced and len(forced) == 1:
                    best, phase = forced[0], 'only-safe-move'
                else:
                    candidates = forced or e.candidates()
                    ranked = e.score_moves(me, candidates)
                    best = ranked[0][1] if ranked else best
                    if forced:
                        phase = 'defence'
                    hint = None
                    # Fast, selective threat searches propose candidates.
                    # A proposal is not returned as a proved win unless the
                    # verifier below checks every legal defensive reply.
                    if not threatened:
                        s = _Searcher(e)
                        s.deadline = min(deadline, started + hard * 0.18)
                        try:
                            hint = s.find_vcf_move(me, 7)
                            if hint is None and clock() < started + hard * 0.28:
                                s.deadline = min(deadline, started + hard * 0.28)
                                hint = s.find_vct_move(me, 4, 6)
                        except _TimeUp:
                            pass
                        search_nodes += s.nodes
                    verified = False
                    if hint is not None and clock() < started + hard * 0.45:
                        verifier = _ForcingVerifier(e, min(deadline, clock() + min(0.35, hard * 0.18)))
                        verified = verifier.verify(hint, me) is True
                        proof_nodes += verifier.nodes
                    if verified:
                        best, phase = hint, 'verified-forcing-win'
                    else:
                        # Keep unverified tactical hints as ordering advice,
                        # while the ordinary search still compares alternatives.
                        if hint is not None:
                            key = e.h ^ (ZOBRIST_SIDE if me == 2 else 0)
                            e.tt[key] = (-1, 0, 0, hint)
                        s = _Searcher(e)
                        s.deadline = started + hard * 0.82
                        s.preferred = hint
                        move, score, depth = s.root(me, 20, soft, clock())
                        search_nodes += s.nodes
                        if move is not None:
                            best = move
                        phase = 'alpha-beta'
                        # Check immediate losses exactly. Longer enemy forcing
                        # attacks reject a move only after bounded verification.
                        order = [best] + [p for p in getattr(s, 'root_order', []) if p != best]
                        for candidate in order[:5]:
                            check()
                            captured = e.make(candidate, me)
                            try:
                                result = e.outcome(me)
                                lost = result == -1
                                if result is None:
                                    lost = bool(e.strict_wins(enemy))
                                    if not lost and clock() < deadline - 0.03:
                                        scout = _Searcher(e)
                                        scout.deadline = min(deadline, clock() + min(0.12, hard * 0.06))
                                        try:
                                            response = scout.find_vcf_move(enemy, 5)
                                        except _TimeUp:
                                            response = None
                                        search_nodes += scout.nodes
                                        if response is not None and clock() < deadline - 0.02:
                                            verifier = _ForcingVerifier(e, deadline, node_limit=1500)
                                            lost = verifier.verify(response, enemy) is True
                                            proof_nodes += verifier.nodes
                            finally:
                                e.unmake(candidate, me, captured)
                            if not lost:
                                if candidate != best:
                                    phase = 'safety-replacement'
                                best = candidate
                                break
                            rejected.add(candidate)
                            if best in rejected:
                                best = next((p for p in order if p not in rejected), best)
        except _TimeUp:
            pass
        finally:
            e.clock = None
        self.last_search = {'phase': phase, 'depth': depth, 'score': score,
                            'nodes': search_nodes, 'proof_nodes': proof_nodes,
                            'seconds': clock() - started, 'soft_budget': soft, 'hard_budget': hard}
        move = divmod(best, SIZE)
        return move if move in legal else fallback
