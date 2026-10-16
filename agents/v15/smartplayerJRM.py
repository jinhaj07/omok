"""Hybrid v2 Omok++ agent (Geonwoo) with JangJinha additions (v15). Standard library only.

AI disclosure: ChatGPT adapted the uploaded JangJinha v11 engine/search and
Geonwoo2/Minjun v3 safety and proof ideas. The JangJinha source credits Claude
Code and team review. Review the code and declare assistance per course rules.
Version 2 adds cached ordering, PVS, tactical quiescence and completed-iteration
selection, with loss-position regression checks and measured match validation.
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
# v15: game-to-game randomness (opening variety), seeded from the OS.
_RAND = random.Random()
_LINE_CACHES = {}
# v15: per-line four gains, keyed by line contents and colour (see four_moves).
_FOUR_LINES = {}

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
    # v15: weight of a pair the opponent can capture next move (x O O _), in
    # units of the capture weight; Hybrid v2 used 0.45.
    vulnw = params.get('vulnw', 0.45)
    key = (weights, capw, o3w, vulnw)
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
            # e -> distinct winning endpoints created by playing at e.
            # This computes open threes directly from three-stone windows,
            # avoiding trial placements and repeated full-line rescans.
            three_ends = {}
            for s in range(length - 4):
                seg = cells[s:s + 5]
                if o in seg:
                    continue
                n = seg.count(x)
                if n == 0:
                    continue
                if n == 3 and not (s > 0 and cells[s - 1] == x or
                                   s + 5 < length and cells[s + 5] == x):
                    holes = [s + i for i, value in enumerate(seg) if value == 0]
                    a, b = holes
                    three_ends.setdefault(a, set()).add(b)
                    three_ends.setdefault(b, set()).add(a)
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
            open3 = int(not wins and not five and any(len(ends) >= 2 for ends in three_ends.values()))
            threat = 1 if wins or open3 else 0
            vulnerable = 0
            for i in range(length - 3):
                if cells[i + 1] == x and cells[i + 2] == x:
                    if cells[i] == o and cells[i + 3] == 0 or (cells[i] == 0 and cells[i + 3] == o):
                        vulnerable += 1
            score -= vulnw * capw * vulnerable
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
        # v15: ids of lines holding a five-completing cell, per colour.
        self.WL = [None, set(), set()]
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
        wl1, wl2 = self.WL[1], self.WL[2]
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
            if n[4] != o[4]:
                NW[1] += n[4] - o[4]
                if n[4]:
                    wl1.add(lid)
                else:
                    wl1.discard(lid)
            if n[5] != o[5]:
                NW[2] += n[5] - o[5]
                if n[5]:
                    wl2.add(lid)
                else:
                    wl2.discard(lid)
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
        wl1, wl2 = self.WL[1], self.WL[2]
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
            if n[4] != o[4]:
                NW[1] += n[4] - o[4]
                if n[4]:
                    wl1.add(lid)
                else:
                    wl1.discard(lid)
            if n[5] != o[5]:
                NW[2] += n[5] - o[5]
                if n[5]:
                    wl2.add(lid)
                else:
                    wl2.discard(lid)
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
        # v15: only lines known to hold such a cell, in the same line order.
        for lid in sorted(self.WL[x]):
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

    def score_moves(self, me, cand):
        """Heuristic move ordering: own gain + weighted opponent gain denied."""
        o = 3 - me
        ei, eo = (me - 1, o - 1)
        lk, cells = (self.lk, self.cells)
        cache, compute = (self.cache, self.compute)
        defw, capb = (self.p['defw'], self.p['capb'])
        xcap = self.p['xcap']
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
        """Moves that give `me` a new way to complete five (fours).

        v15 (JangJinha): the gain of every empty cell of a line is cached by
        the line's contents, so a call costs one lookup per line instead of
        eight per candidate, and capture moves are found from `me`'s stones.
        The result is identical to the per-candidate computation."""
        lk = self.lk
        gains = {}
        four_lines = _FOUR_LINES
        for lid in range(NLINES):
            k = lk[lid]
            ent = four_lines.get(k * 4 + me)
            if ent is None:
                ent = self._four_line(k, me)
            if ent:
                line = LINES[lid]
                for i, d in ent:
                    q = line[i]
                    gains[q] = gains.get(q, 0) + d
        caps = self._capture_cells(me) if self.p['xcap'] else ()
        out = []
        for p in cand:
            if p in caps:
                nw0 = self.NW[me]
                cap = self.make(p, me)
                try:
                    gain = self.NW[me] - nw0
                finally:
                    self.unmake(p, me, cap)
                if gain > 0:
                    out.append((gain, p))
                continue
            gain = gains.get(p, 0)
            if gain > 0:
                out.append((gain, p))
        out.sort(reverse=True)
        return [p for _, p in out]

    def _four_line(self, k, me):
        """(index, change in `me`'s five-completing cells) for each empty
        cell of line `k` where a stone of `me` changes that count."""
        cache, compute = self.cache, self.compute
        idx = 3 + me
        base = (cache.get(k) or compute(k))[idx]
        out = []
        v = k >> 5
        pw = 32
        for i in range(k & 31):
            if v % 3 == 0:
                k2 = k + me * pw
                d = (cache.get(k2) or compute(k2))[idx] - base
                if d:
                    out.append((i, d))
            v //= 3
            pw *= 3
        ent = tuple(out)
        _FOUR_LINES[k * 4 + me] = ent
        return ent

    def _capture_cells(self, me):
        """Empty cells where a stone of `me` captures a pair (as in make())."""
        o = 3 - me
        cells = self.cells
        out = set()
        for d in range(NCELL):
            if cells[d] == me:
                for a, b, p in CAP_RAYS[d]:
                    if cells[a] == o and cells[b] == o and not cells[p]:
                        out.add(p)
        return out

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
            ranked = [p for _, p in e.score_moves(me, cand)]
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


class _FastEngine(_HybridEngine):
    """Reuse line-order deltas and position rankings across transpositions."""

    def __init__(self, params):
        self.order_cache = {}
        self.rank_cache = {}
        super().__init__(params)

    def load(self, board):
        super().load(board)
        self.rank_cache.clear()
        if len(self.order_cache) > 180_000:
            self.order_cache.clear()

    def features(self, me, cand=None):
        key = (self.h, me)
        hit = self.rank_cache.get(key)
        if hit is not None:
            if cand is None:
                return hit
            allowed = set(cand)
            return [item for item in hit if item[1] in allowed]
        # Cache only the complete neighborhood list; distant forced defences
        # are scored separately without contaminating a full-position entry.
        full = cand is None
        if full:
            cand = self.candidates()
        enemy = 3 - me
        own_i, enemy_i = me - 1, enemy - 1
        cells, cache, compute = self.cells, self.cache, self.compute
        out = []
        for p in cand:
            score, flags, attack = 0.0, 0, 0.0
            for lid, power in CELL_LINES[p]:
                k = self.lk[lid]
                delta_key = (k, me, power)
                delta = self.order_cache.get(delta_key)
                if delta is None:
                    before = cache.get(k) or compute(k)
                    own = cache.get(k + me * power) or compute(k + me * power)
                    other = cache.get(k + enemy * power) or compute(k + enemy * power)
                    gain = own[own_i] - before[own_i]
                    denied = other[enemy_i] - before[enemy_i]
                    # Keep fours for either side even outside the quiet width.
                    four = own[4 + own_i] > before[4 + own_i] or other[4 + enemy_i] > before[4 + enemy_i]
                    three = own[8 + own_i] > before[8 + own_i] or other[8 + enemy_i] > before[8 + enemy_i]
                    delta = (gain + self.p['defw'] * denied,
                             (1 if four else 0) | (2 if three else 0), gain)
                    self.order_cache[delta_key] = delta
                score += delta[0]
                flags |= delta[1]
                attack += delta[2]
            ncap = 0
            for a, b, end in CAP_RAYS[p]:
                if cells[a] == enemy and cells[b] == enemy and cells[end] == me:
                    ncap += 1
                if cells[a] == me and cells[b] == me and cells[end] == enemy:
                    flags |= 4  # Preventing an enemy capture can be essential.
            if ncap:
                before = self.E[me] - self.E[enemy]
                captured = self.make(p, me)
                try:
                    # Replace the approximate attacking contribution with the
                    # exact evaluation gain AFTER captures, retaining defence.
                    after = self.E[me] - self.E[enemy]
                finally:
                    self.unmake(p, me, captured)
                score += after - before - attack + self.p['capb'] * ncap
                flags |= 4
            out.append((score, p, flags))
        out.sort(reverse=True)
        if full:
            self.rank_cache[key] = out
        return out

    def score_moves(self, me, cand):
        return sorted(((value + self.history[p], p)
                       for value, p, flags in self.features(me, cand)), reverse=True)


class _FastSearcher(_Searcher):
    """PVS with forcing continuations, side-specific history and safe undo."""

    def __init__(self, engine):
        super().__init__(engine)
        self.killers = {}
        self.history = [[0] * NCELL for _ in range(3)]
        self.root_order = []
        self.iterations = []
        self.root_scores = {}
        self.qnodes = 0
        self.tt_hits = 0
        self.extended = False
        self.qleft = 8
        self.noise = None

    def ordered(self, me, ply, tt_move=None, width=None):
        features = self.e.features(me)
        killers = self.killers.get(ply, ())
        history = self.history[me]
        ranked = sorted(features, key=lambda item:
                        (item[1] == tt_move, item[1] in killers,
                         item[0] + min(1200, history[item[1]])), reverse=True)
        if width is None:
            return [p for _, p, _ in ranked]
        selected = [p for _, p, flags in ranked[:width]]
        seen = set(selected)
        for _, p, flags in ranked[width:]:
            if flags & 5 or p == tt_move or p in killers:
                selected.append(p)
                seen.add(p)
        return selected

    @staticmethod
    def pack(value, ply):
        return value + ply if value > WIN - 1000 else value - ply if value < -WIN + 1000 else value

    @staticmethod
    def unpack(value, ply):
        return value - ply if value > WIN - 1000 else value + ply if value < -WIN + 1000 else value

    def quiet(self, alpha, beta, me, ply, left):
        self._tick()
        self.qnodes += 1
        e = self.e
        enemy = 3 - me
        result = e.outcome(me)
        if result is not None:
            return 0 if result == 0 else result * (WIN - ply)
        if e.strict_wins(me):
            return WIN - ply - 1
        threatened = bool(e.strict_wins(enemy))
        if threatened:
            moves = e.defences(me)
            if not moves:
                return -WIN + ply + 2
        else:
            stand = e.evaluate(me)
            if left <= 0:
                return stand
            if stand >= beta:
                return stand
            alpha = max(alpha, stand)
            # Continue fours only; quiet open threes are handled by the main
            # search. No stand-pat is permitted while under an immediate threat.
            moves = e.four_moves(me, e.candidates())[:8]
            if not moves:
                return stand
        if left <= -2:
            # A bounded tactical frontier is an estimate, never a mate claim.
            return e.evaluate(me) - (1500 if threatened else 0)
        best = -2 * WIN if threatened else stand
        for p in moves:
            captured = e.make(p, me)
            try:
                val = self._after_move(me, ply + 1)
                if val is None:
                    val = -self.quiet(-beta, -alpha, enemy, ply + 1, left - 1)
            finally:
                e.unmake(p, me, captured)
            best = max(best, val)
            alpha = max(alpha, val)
            if alpha >= beta:
                break
        return best

    def negamax(self, depth, alpha, beta, me, ply, ext=0):
        self._tick()
        e = self.e
        enemy = 3 - me
        if e.strict_wins(me):
            return WIN - ply - 1
        if depth <= 0:
            return self.quiet(alpha, beta, me, ply, self.qleft)
        threatened = bool(e.strict_wins(enemy))
        # The tactical budget is fixed for this search; separate table entries
        # from the inherited scout's different search/extension semantics.
        key = (e.h, me, 'pvs', self.qleft)
        entry = e.tt.get(key)
        tt_move = None
        if entry is not None:
            d, flag, val, tt_move = entry
            val = self.unpack(val, ply)
            self.tt_hits += 1
            if d >= depth:
                if flag == 0 or flag == 1 and val >= beta or flag == 2 and val <= alpha:
                    return val
        if threatened:
            moves = e.defences(me)
            if not moves:
                return -WIN + ply + 2
            if tt_move in moves:
                moves.remove(tt_move)
                moves.insert(0, tt_move)
        else:
            moves = self.ordered(me, ply, tt_move, e.p['width'])
        if not moves:
            return 0
        alpha0 = alpha
        best, best_move = -2 * WIN, None
        for index, p in enumerate(moves):
            captured = e.make(p, me)
            try:
                value = self._after_move(me, ply + 1)
                if value is None:
                    if index == 0:
                        value = -self.negamax(depth - 1, -beta, -alpha, enemy, ply + 1)
                    else:
                        # Values are floats. A one-point scout interval remains
                        # valid; any value above alpha is fully re-searched.
                        value = -self.negamax(depth - 1, -alpha - 1.0, -alpha, enemy, ply + 1)
                        if alpha < value < beta:
                            value = -self.negamax(depth - 1, -beta, -alpha, enemy, ply + 1)
            finally:
                e.unmake(p, me, captured)
            if value > best:
                best, best_move = value, p
            alpha = max(alpha, value)
            if alpha >= beta:
                old = self.killers.get(ply, ())
                self.killers[ply] = (p,) + tuple(q for q in old if q != p)[:1]
                self.history[me][p] += depth * depth
                break
        flag = 1 if best >= beta else 2 if best <= alpha0 else 0
        e.tt[key] = (depth, flag, self.pack(best, ply), best_move)
        return best

    def root_iteration(self, moves, me, depth, alpha, beta):
        e, enemy = self.e, 3 - me
        best, best_move = -2 * WIN, None
        scores = {}
        noise = self.noise
        for index, p in enumerate(moves):
            self._tick()
            # v15: opening variety. A fixed random bonus n per root move; the
            # move is searched as if its value were value + n by shifting the
            # window, so the choice is random among moves within the bonus
            # range of the best (only used in quiet opening positions).
            n = noise.get(p, 0.0) if noise else 0.0
            a, b = alpha - n, beta - n
            captured = e.make(p, me)
            try:
                value = self._after_move(me, 1)
                if value is None:
                    if index == 0:
                        value = -self.negamax(depth - 1, -b, -a, enemy, 1)
                    else:
                        value = -self.negamax(depth - 1, -a - 1.0, -a, enemy, 1)
                        if a < value < b:
                            value = -self.negamax(depth - 1, -b, -a, enemy, 1)
            finally:
                e.unmake(p, me, captured)
            value += n
            scores[p] = value
            if value > best:
                best, best_move = value, p
            alpha = max(alpha, value)
            if alpha >= beta:
                break
        return best_move, best, scores

    def root(self, me, max_depth, soft_time, start):
        e = self.e
        threatened = bool(e.strict_wins(3 - me))
        moves = e.defences(me) if threatened else self.ordered(me, 0, getattr(self, 'preferred', None), e.p['root_width'])
        self.root_order = list(moves)
        if not moves:
            return None, -WIN + 2, 0
        if len(moves) == 1:
            return moves[0], 0, 0
        best_move, best_score, done = moves[0], -2 * WIN, 0
        for depth in range(1, max_depth + 1):
            # First complete a cheap iteration before expanding tactical leaves.
            self.qleft = 0 if depth == 1 else 8
            lower, upper = -2 * WIN, 2 * WIN
            if done >= 2 and abs(best_score) < WIN - 1000:
                lower, upper = best_score - 450, best_score + 450
            try:
                move, score, scores = self.root_iteration(moves, me, depth, lower, upper)
                if score <= lower or score >= upper:
                    # A failed aspiration search is not a finished iteration.
                    move, score, scores = self.root_iteration(moves, me, depth, -2 * WIN, 2 * WIN)
            except _TimeUp:
                break  # Keep the last FULLY completed iteration.
            unstable = done > 0 and (move != best_move or score < best_score - 300)
            best_move, best_score, done = move, score, depth
            self.root_scores = scores
            self.iterations.append({'depth': depth, 'move': divmod(move, SIZE), 'score': score})
            moves.sort(key=lambda p: (p == best_move, scores.get(p, -3 * WIN)), reverse=True)
            self.root_order = list(moves)
            if best_score >= WIN - 1000:
                break
            # If all selective choices lose, widen at the same position before
            # treating a root loss as settled. This never removes forced replies.
            if best_score <= -WIN + 1000 and not threatened:
                wider = self.ordered(me, 0, best_move, None)
                if len(wider) > len(moves):
                    moves = list(dict.fromkeys(moves + wider))
                    self.root_order = list(moves)
            if time.monotonic() - start >= soft_time:
                if unstable and not self.extended:
                    soft_time = max(soft_time, (self.deadline - start) * 0.9)
                    self.extended = True
                else:
                    break
        return best_move, best_score, done


# --- OPENING BOOK (generated by tools/book.py embed; do not edit by hand) ---
BOOK = {
    '5,8,0;7,10,1;9,9,0': (9, 10),
    '5,8,0;7,9,0;7,10,1;9,9,0;10,10,1': (8, 9),
    '6,8,0;7,8,1;8,8,1;8,9,1;8,10,1;8,11,0;9,9,0;10,8,0;11,7,0': (6, 7),
    '6,9,0;7,8,1;9,9,0': (8, 9),
    '7,7,0;7,8,0;9,9,0;10,7,0;10,8,0;10,9,1;11,8,1': (11, 7),
    '7,7,1;7,10,1;8,8,0;8,10,0;9,9,0;10,10,0;11,11,1': (7, 11),
    '7,8,0;7,9,0;7,10,1;8,9,1;9,9,0;9,10,1': (10, 11),
    '7,8,0;7,9,0;8,7,1;9,7,1;9,9,0;10,7,1': (11, 7),
    '7,8,0;8,7,1;8,10,1;9,9,0': (8, 8),
    '7,8,0;8,7,1;9,9,0': (9, 10),
    '7,8,0;8,7,1;9,9,0;10,7,1': (11, 7),
    '7,8,0;8,9,1;8,10,1;9,9,0': (8, 12),
    '7,8,1;7,9,0;8,8,0;9,9,0;10,10,1': (6, 9),
    '7,8,1;9,9,0': (7, 7),
    '7,9,0;8,9,1;9,8,1;9,9,0': (10, 7),
    '8,9,1;9,9,0': (7, 10),
}
# --- END OPENING BOOK ---

# The 8 board symmetries (actual -> canonical) and their inverses.
_SYM = (
    lambda r, c: (r, c), lambda r, c: (c, SIZE - 1 - r),
    lambda r, c: (SIZE - 1 - r, SIZE - 1 - c), lambda r, c: (SIZE - 1 - c, r),
    lambda r, c: (r, SIZE - 1 - c), lambda r, c: (c, r),
    lambda r, c: (SIZE - 1 - r, c), lambda r, c: (SIZE - 1 - c, SIZE - 1 - r),
)
_SYM_INV = (
    lambda r, c: (r, c), lambda r, c: (SIZE - 1 - c, r),
    lambda r, c: (SIZE - 1 - r, SIZE - 1 - c), lambda r, c: (c, SIZE - 1 - r),
    lambda r, c: (r, SIZE - 1 - c), lambda r, c: (c, r),
    lambda r, c: (SIZE - 1 - r, c), lambda r, c: (SIZE - 1 - c, SIZE - 1 - r),
)


def _book_move(board):
    """Book reply for this position (any rotation/reflection), else None.
    v13/v15 (JangJinha): entries were chosen by playing candidate moves out
    against the team's agents at many clock speeds (tools/book.py)."""
    if not BOOK:
        return None
    pts = [(r, c, board[r][c]) for r in range(SIZE) for c in range(SIZE) if board[r][c] != EMPTY]
    if len(pts) > 16:
        return None
    best = None
    for i, t in enumerate(_SYM):
        img = tuple(sorted(t(r, c) + (v,) for r, c, v in pts))
        if best is None or img < best[0]:
            best = (img, i)
    key = ";".join("%d,%d,%d" % x for x in best[0])
    move = BOOK.get(key)
    if move is None:
        return None
    r, c = _SYM_INV[best[1]](*move)
    if 0 <= r < SIZE and 0 <= c < SIZE and board[r][c] == EMPTY:
        return (r, c)
    return None


class SmartPlayerJRM(PlayerJRM):
    """Hybrid v2. Public interface and remaining-game-clock units unchanged."""

    def __init__(self, color):
        super().__init__(color)
        if color not in (0, 1):
            raise ValueError('color must be 0 (black) or 1 (white)')
        self.params = dict(DEFAULT_PARAMS)
        self.params.update({'root_width': 24, 'width': 12})
        # v15 (JangJinha) switches: knight = white's first reply a knight's
        # move from black's stone, used only while white's clock is below
        # knight_below seconds; book = opening book from v13/v14; tscale =
        # scale on the time budget. A/B cycles 6-10 (team pool): the knight
        # reply lifts white below 0.9 min (0.5-0.75 min: 114/135 vs 41/135)
        # but not at 0.9-1.1 min, and at exactly 1 min it loses to Hybrid v2
        # (white 11/200 vs 128/200 without it). Book, tscale 1.25 and width 14
        # gave nothing, so they stay off.
        self.params.update({'knight': 1, 'knight_below': 54.0, 'book': 0, 'tscale': 1.0})
        # rnoise = random bonus range (evaluation units) on root moves while
        # the board has at most rstones stones and no threats, so repeated
        # games against the same opponent do not all follow one line.
        self.params.update({'rnoise': 0, 'rstones': 6})
        self.engine = _FastEngine(self.params)
        self.moves_played = 0
        self.last_search = {}

    def _budget(self, remaining, stones, pressure):
        ts = self.params.get('tscale', 1.0)
        expected = max(14, 24 - self.moves_played // 2) / ts
        base = 2.0 if remaining is None else min(3.0 * ts, remaining / expected)
        hard = min(4.0 * ts, base * (1.35 if pressure else 1.05))
        if remaining is not None:
            hard = min(hard, max(0.001, remaining * 0.8 - 0.025))
        # Opening caps (seconds) on the first moves; cap2w/cap5w override
        # them for white.
        cap2, cap5 = self.params.get('cap2', 0.5), self.params.get('cap5', 1.1)
        if self.color == 1:
            cap2, cap5 = self.params.get('cap2w', cap2), self.params.get('cap5w', cap5)
        if stones <= 2:
            hard = min(hard, cap2)
        elif stones <= 5:
            hard = min(hard, cap5)
        return max(0.001, hard * 0.67), max(0.001, hard)

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
            return 9, 9
        if self.params.get('book'):
            booked = _book_move(board)
            if booked is not None:
                self.last_search['phase'] = 'book'
                return booked
        if (self.params.get('knight') and len(legal) == NCELL - 1 and self.color == 1
                and time is not None and 0 <= time < self.params.get('knight_below', 54.0) * 1000):
            # White's first reply: a knight's move from black's stone, toward
            # the centre (v13/v14 measurement: best first reply for this engine
            # family against the team's other agents).
            r, c = next((r, c) for r in range(SIZE) for c in range(SIZE) if board[r][c] != EMPTY)
            reply = (r - 2 if r >= 9 else r + 2, c - 1 if c >= 9 else c + 1)
            if 0 <= reply[0] < SIZE and 0 <= reply[1] < SIZE and board[reply[0]][reply[1]] == EMPTY:
                self.last_search['phase'] = 'book'
                return reply
        remaining = None if time is None or time < 0 else float(time) / 1000
        if remaining is not None and remaining < 0.025:
            return fallback
        e = self.engine
        e.clock = None
        e.load(board)
        me, enemy = self.color + 1, 2 - self.color
        pressure = bool(e.NW[me] or e.NW[enemy] or e.T[me] or e.T[enemy])
        soft, hard = self._budget(remaining, e.stones, pressure)
        deadline = started + hard
        def check():
            if _now() >= deadline:
                raise _TimeUp
        e.clock = check
        if len(e.tt) > 100_000:
            e.tt.clear()
        if len(e.vtt) > 50_000:
            e.vtt.clear()
        best, phase, score, depth = fallback[0] * SIZE + fallback[1], 'ordered', None, 0
        searcher = _FastSearcher(e)
        scout_nodes = proof_nodes = 0
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
                    # Compute a legal tactical fallback before expensive work.
                    features = e.features(me)
                    choices = forced or [p for _, p, _ in features]
                    if choices:
                        best = choices[0]
                    hint = None
                    # Four-scouting only when a three/four exists; selective
                    # VCT scouting is omitted from every-turn preprocessing.
                    if not threatened and e.T[me] and hard > 0.15:
                        scout = _Searcher(e)
                        scout.deadline = min(deadline, started + min(0.16, hard * 0.08))
                        try:
                            hint = scout.find_vcf_move(me, 6)
                        except _TimeUp:
                            pass
                        scout_nodes = scout.nodes
                    verified = False
                    if hint is not None and _now() < started + hard * 0.2:
                        verifier = _ForcingVerifier(e, min(deadline, started + hard * 0.25), node_limit=2500)
                        verified = verifier.verify(hint, me) is True
                        proof_nodes = verifier.nodes
                    if verified:
                        best, phase = hint, 'verified-forcing-win'
                    else:
                        searcher.deadline = max(started, deadline - min(0.025, hard * 0.05))
                        searcher.preferred = hint
                        rnoise = self.params.get('rnoise', 0)
                        if rnoise and not pressure and e.stones <= self.params.get('rstones', 6):
                            searcher.noise = {q: _RAND.random() * rnoise for q in range(NCELL)}
                        move, score, depth = searcher.root(me, 20, soft, started)
                        if move is not None:
                            best = move
                        phase = 'pvs'
                        # Main search already resolves tactical frontiers.
                        # The final pass only checks immediate loss, sharing
                        # the exact same caches instead of repeating VCF.
                        candidates = [best] + [p for p in searcher.root_order if p != best]
                        for p in candidates:
                            check()
                            captured = e.make(p, me)
                            try:
                                outcome = e.outcome(me)
                                safe = outcome in (0, 1) or outcome is None and not e.strict_wins(enemy)
                            finally:
                                e.unmake(p, me, captured)
                            if safe:
                                if p != best:
                                    phase = 'safety-replacement'
                                best = p
                                break
        except _TimeUp:
            pass
        finally:
            e.clock = None
        self.last_search = {'phase': phase, 'depth': depth, 'score': score,
                            'nodes': searcher.nodes + scout_nodes, 'qnodes': searcher.qnodes,
                            'tt_hits': searcher.tt_hits, 'proof_nodes': proof_nodes,
                            'seconds': _now() - started, 'soft_budget': soft, 'hard_budget': hard,
                            'extended': searcher.extended, 'iterations': searcher.iterations}
        move = divmod(best, SIZE)
        return move if move in legal else fallback


