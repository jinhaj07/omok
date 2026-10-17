"""Geonwoo5 Omok++ agent. Standard library only.

AI disclosure: ChatGPT adapted the uploaded JangJinha v11 engine/search and
Geonwoo2/Minjun v3 safety and proof ideas. The JangJinha source credits Claude
Code and team review. Geonwoo4 integrates tactical-search ideas from the supplied JRM v15.
Review the code and declare assistance per course rules.
"""
import random
import time
from collections import OrderedDict
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
CELL_MOVE_LINES = tuple(tuple((lid, power, offset)
                             for (lid, power), (_, offset) in zip(CELL_LINES[p], CELL_POS[p]))
                        for p in range(NCELL))
NLINES = len(LINES)
LINE_BASE = [len(cells) for cells in LINES]
_rng = random.Random(20261019)
ZOBRIST = [[0] * NCELL] + [[_rng.getrandbits(64) for _ in range(NCELL)] for _ in (1, 2)]
ZOBRIST_SIDE = _rng.getrandbits(64)

class _TimeUp(Exception):
    pass
_LINE_CACHES = {}
_LINE_CACHE_LIMIT = 100_000
_POSITION_CACHE_LIMIT = 1024
_CANDIDATE_CACHE_LIMIT = 2048
_TACTICAL_CACHE_LIMIT = 4096
_PVS_EPSILON = 1e-6
_BIT_COUNT = getattr(int, 'bit_count', lambda n: bin(n).count('1'))
_LINE_WINDOWS = tuple(tuple((31 << s,
                            (1 << (s - 1) if s else 0) |
                            (1 << (s + 5) if s + 5 < length else 0))
                           for s in range(max(0, length - 4)))
                      for length in range(SIZE + 1))

def _bit_positions(mask):
    out = []
    while mask:
        bit = mask & -mask
        out.append(bit.bit_length() - 1)
        mask ^= bit
    return tuple(out)

def _win_cells(cells, x, length):
    """Empty cells of a line where colour x would complete an exact five."""
    own = other = 0
    for i, value in enumerate(cells[:length]):
        if value == x:
            own |= 1 << i
        elif value == 3 - x:
            other |= 1 << i
    wins = 0
    for window, outside in _LINE_WINDOWS[length]:
        if not other & window and not own & outside and _BIT_COUNT(own & window) == 4:
            wins |= window & ~own
    return set(_bit_positions(wins))

def _line_info_factory(params):
    weights = (0.0, params['w1'], params['w2'], params['w3'], params['w4'])
    capw = params['cap']
    o3w = params['o3']
    key = (weights, capw, o3w)
    cache = _LINE_CACHES.setdefault(key, OrderedDict())
    if not hasattr(cache, 'move_gains'):
        cache.move_gains = OrderedDict()

    def compute(k):
        """Stats of one line: (E1, E2, F1, F2, NW1, NW2, wins1, wins2, T1, T2).

        E = evaluation score, F = 1 if an exact five exists, NW = number of
        empty cells completing an exact five, wins = their positions,
        T = 1 if the line holds a threat (a four, or an open three that can
        become an open four)."""
        length = k & 31
        v = k >> 5
        masks = [0, 0, 0]
        for i in range(length):
            masks[v % 3] |= 1 << i
            v //= 3
        empty = masks[0]
        windows = _LINE_WINDOWS[length]
        count = _BIT_COUNT
        captures = [0, 0, 0]
        for x in (1, 2):
            own, other = masks[x], masks[3 - x]
            pair = (other >> 1) & (other >> 2)
            captures[x] = count(pair & ((own & (empty >> 3)) | (empty & (own >> 3))))
        out = []
        for x in (1, 2):
            own, other = masks[x], masks[3 - x]
            score = 0.0
            five = 0
            wins = 0
            pairs = []
            for window, outside in windows:
                if other & window:
                    continue
                n = count(own & window)
                if n == 0:
                    continue
                if n >= 4:
                    if own & outside:
                        continue
                    if n == 5:
                        five = 1
                        continue
                    wins |= window & empty
                elif n == 3 and not own & outside:
                    pairs.append(window & empty)
                score += weights[n]
            open3 = 0
            if not wins and not five and pairs:
                # Each valid three-window has two holes. Playing one hole
                # makes the other a winning endpoint. Two DISTINCT endpoints
                # after the same placement exactly match the original test.
                targets = {}
                for holes in pairs:
                    a = holes & -holes
                    b = holes ^ a
                    ta = targets.get(a, 0) | b
                    tb = targets.get(b, 0) | a
                    if count(ta) >= 2 or count(tb) >= 2:
                        open3 = 1
                        break
                    targets[a], targets[b] = ta, tb
            threat = 1 if wins or open3 else 0
            score -= 0.45 * capw * captures[3 - x]
            out.append((score + capw * captures[x] + o3w * open3,
                        five, count(wins), _bit_positions(wins), threat))
        info = (out[0][0], out[1][0], out[0][1], out[1][1], out[0][2], out[1][2], out[0][3], out[1][3], out[0][4], out[1][4])
        if len(cache) >= _LINE_CACHE_LIMIT:
            cache.popitem(last=False)
        cache[k] = info
        return info
    return (cache, compute)

class _Engine:

    def __init__(self, params):
        self.p = params
        self.cache, self.compute = _line_info_factory(params)
        self.move_cache = self.cache.move_gains
        self.tt = {}
        self.vtt = {}
        self.history = [0] * NCELL
        self.score_cache = OrderedDict()
        self.candidate_cache = OrderedDict()
        self.reset()

    def info(self, k):
        inf = self.cache.get(k)
        return inf if inf is not None else self.compute(k)

    def _move_info(self, k, power, offset, before):
        """Immutable placement gains for BOTH colors on one encoded line."""
        first = self.info(k + power)
        second = self.info(k + 2 * power)
        result = (first[0] - before[0], second[1] - before[1],
                  first[4] - before[4], second[5] - before[5],
                  first[8] - before[8], second[9] - before[9])
        if len(self.move_cache) >= _LINE_CACHE_LIMIT:
            self.move_cache.popitem(last=False)
        self.move_cache[(k << 5) | offset] = result
        return result

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
        self.line_info = []
        self.win_lines = [0, 0, 0]
        base = self.info
        for k in self.lk:
            inf = base(k)
            self.line_info.append(inf)
            self.E[1] += inf[0]
            self.E[2] += inf[1]

    def load(self, board):
        self.reset()
        for r in range(SIZE):
            row = board[r]
            for c in range(SIZE):
                v = row[c]
                if v == 0 or v == 1:
                    p, color = r * SIZE + c, v + 1
                    self.cells[p] = color
                    self.h ^= ZOBRIST[color][p]
                    self.stones += 1
                    for lid, pw in CELL_LINES[p]:
                        self.lk[lid] += color * pw
                    for q in NEAR[p]:
                        self.nb[q] += 1
        # Decode each FINAL line once; intermediate loading positions have
        # no relevance to a search and need no evaluation or cache entries.
        self.E = [0.0, 0.0, 0.0]
        for lid, k in enumerate(self.lk):
            inf = self.info(k)
            self.line_info[lid] = inf
            self.E[1] += inf[0]
            self.E[2] += inf[1]
            self.F[1] += inf[2]
            self.F[2] += inf[3]
            self.NW[1] += inf[4]
            self.NW[2] += inf[5]
            self.T[1] += inf[8]
            self.T[2] += inf[9]
            if inf[4]:
                self.win_lines[1] |= 1 << lid
            if inf[5]:
                self.win_lines[2] |= 1 << lid

    def _put(self, p, v):
        self.cells[p] = v
        self.h ^= ZOBRIST[v][p]
        self.stones += 1
        lk, E, F, NW, T = (self.lk, self.E, self.F, self.NW, self.T)
        cache, compute = (self.cache, self.compute)
        for lid, pw in CELL_LINES[p]:
            k = lk[lid]
            o = self.line_info[lid]
            k2 = k + v * pw
            n = cache.get(k2) or compute(k2)
            lk[lid] = k2
            self.line_info[lid] = n
            E[1] += n[0] - o[0]
            E[2] += n[1] - o[1]
            F[1] += n[2] - o[2]
            F[2] += n[3] - o[3]
            NW[1] += n[4] - o[4]
            NW[2] += n[5] - o[5]
            T[1] += n[8] - o[8]
            T[2] += n[9] - o[9]
            if n[4]:
                self.win_lines[1] |= 1 << lid
            elif o[4]:
                self.win_lines[1] &= ~(1 << lid)
            if n[5]:
                self.win_lines[2] |= 1 << lid
            elif o[5]:
                self.win_lines[2] &= ~(1 << lid)
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
            o = self.line_info[lid]
            k2 = k - v * pw
            n = cache.get(k2) or compute(k2)
            lk[lid] = k2
            self.line_info[lid] = n
            E[1] += n[0] - o[0]
            E[2] += n[1] - o[1]
            F[1] += n[2] - o[2]
            F[2] += n[3] - o[3]
            NW[1] += n[4] - o[4]
            NW[2] += n[5] - o[5]
            T[1] += n[8] - o[8]
            T[2] += n[9] - o[9]
            if n[4]:
                self.win_lines[1] |= 1 << lid
            elif o[4]:
                self.win_lines[1] &= ~(1 << lid)
            if n[5]:
                self.win_lines[2] |= 1 << lid
            elif o[5]:
                self.win_lines[2] &= ~(1 << lid)
        nb = self.nb
        for q in NEAR[p]:
            nb[q] -= 1

    def _batch_change(self, changes):
        """Apply a capture/undo batch, refreshing each affected line once."""
        deltas = {}
        cells, nb = self.cells, self.nb
        for p, color in changes:
            before = cells[p]
            if before == color:
                continue
            cells[p] = color
            self.h ^= ZOBRIST[before][p] ^ ZOBRIST[color][p]
            occupied_delta = int(bool(color)) - int(bool(before))
            self.stones += occupied_delta
            for q in NEAR[p]:
                nb[q] += occupied_delta
            for lid, pw in CELL_LINES[p]:
                deltas[lid] = deltas.get(lid, 0) + (color - before) * pw
        E, F, NW, T = self.E, self.F, self.NW, self.T
        for lid, delta in deltas.items():
            if not delta:
                continue
            old = self.line_info[lid]
            k = self.lk[lid] + delta
            new = self.info(k)
            self.lk[lid] = k
            self.line_info[lid] = new
            E[1] += new[0] - old[0]
            E[2] += new[1] - old[1]
            F[1] += new[2] - old[2]
            F[2] += new[3] - old[3]
            NW[1] += new[4] - old[4]
            NW[2] += new[5] - old[5]
            T[1] += new[8] - old[8]
            T[2] += new[9] - old[9]
            for color, index in ((1, 4), (2, 5)):
                if new[index]:
                    self.win_lines[color] |= 1 << lid
                elif old[index]:
                    self.win_lines[color] &= ~(1 << lid)

    def make(self, p, me):
        """Place a stone for `me` (1 or 2) and apply Omok++ captures."""
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
            self._batch_change([(p, me)] + [(q, 0) for q in captured])
        else:
            self._put(p, me)
        return captured

    def unmake(self, p, me, captured):
        if captured:
            o = 3 - me
            self._batch_change([(q, o) for q in captured] + [(p, 0)])
        else:
            self._take(p)

    def win_points(self, x):
        """Empty cells where colour x completes an exact five."""
        pts = []
        idx = 6 + x - 1
        active = self.win_lines[x]
        while active:
            bit = active & -active
            lid = bit.bit_length() - 1
            active ^= bit
            inf = self.line_info[lid]
            w = inf[idx]
            if w:
                cells = LINES[lid]
                for i in w:
                    pts.append(cells[i])
        return list(dict.fromkeys(pts))

    def candidates(self):
        hit = self.candidate_cache.get(self.h)
        if hit is not None:
            self.candidate_cache.move_to_end(self.h)
            return list(hit)
        cells, nb = (self.cells, self.nb)
        result = [p for p in range(NCELL) if nb[p] and (not cells[p])]
        if len(self.candidate_cache) >= _CANDIDATE_CACHE_LIMIT:
            self.candidate_cache.popitem(last=False)
        self.candidate_cache[self.h] = tuple(result)
        return result

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
        move_get = self.move_cache.get
        move_compute = self._move_info
        score_key = (self.h, me, defw, capb, xcap)
        saved = self.score_cache.get(score_key)
        if saved is None:
            if len(self.score_cache) >= _POSITION_CACHE_LIMIT:
                self.score_cache.popitem(last=False)
            saved = {}
            self.score_cache[score_key] = saved
        else:
            self.score_cache.move_to_end(score_key)
        out = []
        for p in cand:
            value = saved.get(p)
            if value is not None:
                out.append((value + hist[p], p))
                continue
            att = 0.0
            dfn = 0.0
            for lid, pw, offset in CELL_MOVE_LINES[p]:
                k = lk[lid]
                gains = move_get((k << 5) | offset)
                if gains is None:
                    gains = move_compute(k, pw, offset, self.line_info[lid])
                att += gains[ei]
                dfn += gains[eo]
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
            value = att + defw * dfn
            saved[p] = value
            out.append((value + hist[p], p))
        out.sort(reverse=True)
        return out

    def threat_moves(self, me, cand):
        """Moves creating a four or a new open three for `me`, strongest first.
        Returns (move, makes_four) pairs."""
        lk = self.lk
        cache, compute = (self.cache, self.compute)
        i4, i3, ie = (2 + me - 1, 4 + me - 1, me - 1)
        move_get, move_compute = self.move_cache.get, self._move_info
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
            for lid, pw, offset in CELL_MOVE_LINES[p]:
                k = lk[lid]
                gains = move_get((k << 5) | offset)
                if gains is None:
                    gains = move_compute(k, pw, offset, self.line_info[lid])
                g4 += gains[i4]
                g3 += gains[i3]
                ev += gains[ie]
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
        idx = 2 + me - 1
        move_get, move_compute = self.move_cache.get, self._move_info
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
            for lid, pw, offset in CELL_MOVE_LINES[p]:
                k = lk[lid]
                gains = move_get((k << 5) | offset)
                if gains is None:
                    gains = move_compute(k, pw, offset, self.line_info[lid])
                gain += gains[idx]
            if gain > 0:
                out.append((gain, p))
        out.sort(reverse=True)
        return [p for _, p in out]

class _HybridEngine(_Engine):
    """Fast line engine with capture-aware wins and complete tactical escapes."""

    def __init__(self, params):
        self.clock = None
        self.win_cache = OrderedDict()
        self.defence_cache = OrderedDict()
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
            self.win_cache.move_to_end(key)
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
        if len(self.win_cache) >= _TACTICAL_CACHE_LIMIT:
            self.win_cache.popitem(last=False)
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
            self.defence_cache.move_to_end(key)
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
        if len(self.defence_cache) >= _TACTICAL_CACHE_LIMIT:
            self.defence_cache.popitem(last=False)
        self.defence_cache[key] = tuple(safe + draws)
        return safe + draws


class _Searcher:

    def __init__(self, engine):
        self.e = engine
        self.deadline = float('inf')
        self.node_limit = None
        self.nodes = 0
        self.killers = {}

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
                if flag == 1:
                    alpha = max(alpha, val)
                elif flag == 2:
                    beta = min(beta, val)
                if alpha >= beta:
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
        elif not threatened and tt_move is not None and tt_move in rest:
            # Retain a previously good legal move even when its new heuristic
            # rank falls outside the quiet width. Do not drop another move.
            rest.remove(tt_move)
            moves.insert(0, tt_move)
        for killer in reversed(self.killers.get(ply, ())):
            if killer != tt_move and killer in moves:
                moves.remove(killer)
                moves.insert(1 if tt_move in moves else 0, killer)
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
                        if best_move is None or depth <= 1:
                            val = -self.negamax(depth - 1, -beta, -alpha, o, ply + 1, ext)
                        else:
                            # A narrow-window test often proves that a later
                            # move cannot improve alpha. Re-search improvements
                            # with the full window before trusting their score.
                            val = -self.negamax(depth - 1, -alpha - _PVS_EPSILON,
                                                -alpha, o, ply + 1, ext)
                            if alpha < val < beta:
                                val = -self.negamax(depth - 1, -beta, -alpha,
                                                    o, ply + 1, ext)
                finally:
                    e.unmake(p, me, cap)
                if val > best:
                    best = val
                    best_move = p
                    if val > alpha:
                        alpha = val
                        if alpha >= beta:
                            e.history[p] += depth * depth
                            if not cap:
                                old = self.killers.get(ply, ())
                                self.killers[ply] = (p,) + tuple(q for q in old if q != p)[:1]
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
        if preferred is None:
            entry = e.tt.get(e.h ^ (ZOBRIST_SIDE if me == 2 else 0))
            if entry is not None:
                preferred = entry[3]
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
                            if iter_best is None or depth <= 1:
                                val = -self.negamax(depth - 1, -beta, -alpha, o, 1, 6)
                            else:
                                val = -self.negamax(depth - 1, -alpha - _PVS_EPSILON,
                                                    -alpha, o, 1, 6)
                                if alpha < val < beta:
                                    val = -self.negamax(depth - 1, -beta, -alpha, o, 1, 6)
                    finally:
                        e.unmake(p, me, cap)
                    scores[p] = val
                    if val > iter_score:
                        iter_score, iter_best = (val, p)
                        if val > alpha:
                            alpha = val
            except _TimeUp:
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



class _TacticalEngine(_HybridEngine):
    """Keep Geonwoo3's incremental engine and share tactical ordering work."""

    def __init__(self, params):
        self.feature_cache = OrderedDict()
        self.four_cache = OrderedDict()
        super().__init__(params)

    def features(self, me):
        key = (self.h, me, self.p['defw'], self.p['capb'], self.p['xcap'])
        hit = self.feature_cache.get(key)
        if hit is not None:
            return hit
        enemy, out = 3 - me, []
        cells = self.cells
        for index, p in enumerate(self.candidates()):
            if not index & 15:
                self.check_time()
            attack = defence = 0.0
            flags = 0
            for lid, power, offset in CELL_MOVE_LINES[p]:
                k = self.lk[lid]
                gains = self.move_cache.get((k << 5) | offset)
                if gains is None:
                    gains = self._move_info(k, power, offset, self.line_info[lid])
                attack += gains[me - 1]
                defence += gains[enemy - 1]
                if gains[me + 1] > 0 or gains[enemy + 1] > 0:
                    flags |= 1  # A four for either side must survive width pruning.
                if gains[me + 3] > 0 or gains[enemy + 3] > 0:
                    flags |= 2
            ncap = 0
            for a, b, end in CAP_RAYS[p]:
                if cells[a] == cells[b] == enemy and cells[end] == me:
                    ncap += 1
                if cells[a] == cells[b] == me and cells[end] == enemy:
                    flags |= 4  # Prevent an enemy pair capture.
            if ncap:
                if self.p['xcap']:
                    before = self.E[me] - self.E[enemy]
                    captured = self.make(p, me)
                    try:
                        attack = self.E[me] - self.E[enemy] - before
                    finally:
                        self.unmake(p, me, captured)
                attack += self.p['capb'] * ncap
                flags |= 4
            out.append((attack + self.p['defw'] * defence, p, flags))
        out.sort(reverse=True)
        result = tuple(out)
        if len(self.feature_cache) >= _POSITION_CACHE_LIMIT:
            self.feature_cache.popitem(last=False)
        self.feature_cache[key] = result
        return result

    def _four_line(self, k, me):
        key = k * 4 + me
        hit = self.four_cache.get(key)
        if hit is not None:
            return hit
        digits, value = [], k >> 5
        for _ in range(k & 31):
            digits.append(value % 3)
            value //= 3
        out = []
        # Fewer than three own stones cannot produce a four by one placement.
        if digits.count(me) >= 3:
            before, power = self.info(k)[3 + me], 32
            for offset, cell in enumerate(digits):
                if not cell:
                    delta = self.info(k + me * power)[3 + me] - before
                    if delta:
                        out.append((offset, delta))
                power *= 3
        result = tuple(out)
        if len(self.four_cache) >= _LINE_CACHE_LIMIT:
            self.four_cache.popitem(last=False)
        self.four_cache[key] = result
        return result

    def _capture_cells(self, me):
        enemy, cells, out = 3 - me, self.cells, set()
        for end, cell in enumerate(cells):
            if cell == me:
                for a, b, p in CAP_RAYS[end]:
                    if cells[a] == cells[b] == enemy and not cells[p]:
                        out.add(p)
        return out

    def four_moves(self, me, cand):
        gains = {}
        for lid, k in enumerate(self.lk):
            if not lid & 15:
                self.check_time()
            for offset, delta in self._four_line(k, me):
                p = LINES[lid][offset]
                gains[p] = gains.get(p, 0) + delta
        captures = self._capture_cells(me) if self.p['xcap'] else ()
        out = []
        for p in cand:
            if p in captures:
                before = self.NW[me]
                record = self.make(p, me)
                try:
                    gain = self.NW[me] - before
                finally:
                    self.unmake(p, me, record)
            else:
                gain = gains.get(p, 0)
            if gain > 0:
                out.append((gain, p))
        out.sort(reverse=True)
        return [p for _, p in out]

    def threat_breaking_captures(self, me):
        """Only captures that reduce enemy threat lines, with exact undo."""
        enemy, out = 3 - me, []
        before = self.T[enemy]
        if not before:
            return out
        for p in self._capture_cells(me):
            self.check_time()
            record = self.make(p, me)
            try:
                gain = before - self.T[enemy]
                if gain > 0 and self.outcome(me) != -1:
                    out.append((gain, p))
            finally:
                self.unmake(p, me, record)
        out.sort(reverse=True)
        return [p for _, p in out]


class _TacticalSearcher(_Searcher):
    """PVS with bounded tactical leaves and completed-iteration decisions."""

    def __init__(self, engine):
        super().__init__(engine)
        self.side_history = [[0] * NCELL for _ in range(3)]
        self.root_order = []
        self.iterations = []
        self.qnodes = self.tt_hits = 0
        self.qtt = {}
        self.qtt_hits = 0
        self.lmr_researches = 0
        self.extended = False
        self.qleft = engine.p.get('qdepth', 8)

    def ordered(self, me, ply, tt_move=None, width=None):
        killers, history = self.killers.get(ply, ()), self.side_history[me]
        ranked = sorted(self.e.features(me), key=lambda item:
                        (item[1] == tt_move, item[1] in killers,
                         item[0] + min(1200, history[item[1]])), reverse=True)
        if width is None:
            return [p for _, p, _ in ranked]
        selected = [p for _, p, _ in ranked[:width]]
        selected.extend(p for _, p, flags in ranked[width:]
                        if flags & 5 or p == tt_move or p in killers)
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
        if not self.e.p.get('qcache', 1):
            return self._quiet(alpha, beta, me, ply, left)
        # Tactical transpositions are common after interleaved fours/captures.
        # The EXACT remaining budget is part of the key: a shallow frontier
        # estimate must never masquerade as a deeper tactical result.
        key = (self.e.h, me, left, self.e.p.get('qcaptures', 0),
               self.e.p.get('qwidth', 8))
        entry = self.qtt.get(key)
        if entry is not None:
            flag, packed = entry
            value = self.unpack(packed, ply)
            if flag == 0 or flag == 1 and value >= beta or flag == 2 and value <= alpha:
                self.qtt_hits += 1
                return value
        value = self._quiet(alpha, beta, me, ply, left)
        flag = 1 if value >= beta else 2 if value <= alpha else 0
        if len(self.qtt) >= 60000:
            self.qtt.clear()
        self.qtt[key] = (flag, self.pack(value, ply))
        return value

    def _quiet(self, alpha, beta, me, ply, left):
        e, enemy = self.e, 3 - me
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
            if left <= 0 or stand >= beta:
                return stand
            alpha = max(alpha, stand)
            moves = e.four_moves(me, e.candidates())[:e.p.get('qwidth', 8)]
            if e.p.get('qcaptures', 0) and left > 1 and e.T[enemy]:
                seen = set(moves)
                moves.extend(p for p in e.threat_breaking_captures(me)[:4] if p not in seen)
            if not moves:
                return stand
        if left <= -2:
            # An exhausted tactical budget is an estimate, never a mate proof.
            return e.evaluate(me) - (1500 if threatened else 0)
        best = -2 * WIN if threatened else stand
        for p in moves:
            captured = e.make(p, me)
            try:
                value = self._after_move(me, ply + 1)
                if value is None:
                    value = -self.quiet(-beta, -alpha, enemy, ply + 1, left - 1)
            finally:
                e.unmake(p, me, captured)
            best, alpha = max(best, value), max(alpha, value)
            if alpha >= beta:
                break
        return best

    def negamax(self, depth, alpha, beta, me, ply, ext=0):
        self._tick()
        e, enemy = self.e, 3 - me
        if e.strict_wins(me):
            return WIN - ply - 1
        if depth <= 0:
            return self.quiet(alpha, beta, me, ply, self.qleft)
        # Isolate this search from legacy scouts and different tactical budgets.
        key = (e.h, me, 'geonwoo5', self.qleft, e.p.get('qcaptures', 0), e.p['width'])
        entry, tt_move = e.tt.get(key), None
        if entry is not None:
            d, flag, value, tt_move = entry
            value = self.unpack(value, ply)
            self.tt_hits += 1
            if d >= depth and (flag == 0 or flag == 1 and value >= beta or flag == 2 and value <= alpha):
                return value
        if e.strict_wins(enemy):
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
        # Later, quiet choices receive a shallow probe first. A move that
        # challenges alpha is always searched again at the normal depth.
        # Threats, captures, blocks, TT and killer moves are never reduced.
        reducible = set()
        if e.p.get('lmr', 0) and depth >= 3 and not e.T[me] and not e.T[enemy]:
            protected = set(self.killers.get(ply, ())) | {tt_move}
            reducible = {p for _, p, flags in e.features(me) if not flags and p not in protected}
        alpha0, best, best_move = alpha, -2 * WIN, None
        for index, p in enumerate(moves):
            captured = e.make(p, me)
            try:
                value = self._after_move(me, ply + 1)
                if value is None:
                    if index == 0:
                        value = -self.negamax(depth - 1, -beta, -alpha, enemy, ply + 1)
                    else:
                        reduced = index >= 4 and p in reducible
                        value = -self.negamax(depth - 1 - int(reduced), -alpha - _PVS_EPSILON, -alpha, enemy, ply + 1)
                        if reduced and value > alpha:
                            self.lmr_researches += 1
                            value = -self.negamax(depth - 1, -alpha - _PVS_EPSILON, -alpha, enemy, ply + 1)
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
                self.side_history[me][p] += depth * depth
                break
        flag = 1 if best >= beta else 2 if best <= alpha0 else 0
        e.tt[key] = (depth, flag, self.pack(best, ply), best_move)
        return best

    def root_iteration(self, moves, me, depth, alpha, beta):
        e, enemy = self.e, 3 - me
        best, best_move, scores = -2 * WIN, None, {}
        for index, p in enumerate(moves):
            self._tick()
            captured = e.make(p, me)
            try:
                value = self._after_move(me, 1)
                if value is None:
                    if index == 0:
                        value = -self.negamax(depth - 1, -beta, -alpha, enemy, 1)
                    else:
                        value = -self.negamax(depth - 1, -alpha - _PVS_EPSILON, -alpha, enemy, 1)
                        if alpha < value < beta:
                            value = -self.negamax(depth - 1, -beta, -alpha, enemy, 1)
            finally:
                e.unmake(p, me, captured)
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
            return None, -WIN + 2 if threatened else 0, 0
        if len(moves) == 1:
            return moves[0], None, 0
        best_move, best_score, done = moves[0], None, 0
        for depth in range(1, max_depth + 1):
            self.qleft = 0 if depth == 1 else e.p.get('qdepth', 8)
            if depth > 1 and e.p.get('qprogressive', 1):
                self.qleft = min(self.qleft, 2 * depth)
            lower, upper = -2 * WIN, 2 * WIN
            if done >= 2 and abs(best_score) < WIN - 1000:
                lower, upper = best_score - 450, best_score + 450
            try:
                move, score, scores = self.root_iteration(moves, me, depth, lower, upper)
                if score <= lower or score >= upper:
                    move, score, scores = self.root_iteration(moves, me, depth, -2 * WIN, 2 * WIN)
            except _TimeUp:
                # Never compare scores from different, unfinished depths.
                break
            unstable = done > 0 and (move != best_move or score < best_score - 300)
            best_move, best_score, done = move, score, depth
            self.iterations.append({'depth': depth, 'qdepth': self.qleft,
                                    'move': divmod(move, SIZE), 'score': score})
            moves.sort(key=lambda p: (p == best_move, scores.get(p, -3 * WIN)), reverse=True)
            self.root_order = list(moves)
            if best_score >= WIN - 1000:
                break
            if best_score <= -WIN + 1000 and not threatened:
                wider = self.ordered(me, 0, best_move, None)
                if len(wider) > len(moves):
                    moves = list(dict.fromkeys(moves + wider))
                    self.root_order = list(moves)
            if _now() - start >= soft_time:
                if unstable and not self.extended:
                    soft_time = max(soft_time, (self.deadline - start) * 0.9)
                    self.extended = True
                else:
                    break
        return best_move, best_score, done


class SmartPlayerJRM(PlayerJRM):
    """Geonwoo5: cached tactical PVS and a remaining-game clock."""

    VERSION = 'Omok_JRM_Geonwoo5'

    def __init__(self, color):
        super().__init__(color)
        if color not in (0, 1):
            raise ValueError('color must be 0 (black) or 1 (white)')
        self.params = dict(DEFAULT_PARAMS)
        self.params.update({'root_width': 24, 'width': 12, 'qdepth': 8,
                            'qwidth': 8, 'qcaptures': 0, 'qcache': 1,
                            'qprogressive': 1, 'lmr': 0,
                            'white_opening': (10, 10)})
        self.engine = _TacticalEngine(self.params)
        self.moves_played = 0
        self.last_search = {}

    def _budget(self, remaining, stones, pressure):
        expected = max(14, 24 - self.moves_played // 2)
        base = 2.0 if remaining is None else min(3.0, remaining / expected)
        hard = min(4.0, base * (1.35 if pressure else 1.05))
        if remaining is not None:
            hard = min(hard, max(0.001, remaining * 0.8 - 0.025))
        if stones <= 2:
            hard = min(hard, 0.5)
        elif stones <= 5:
            hard = min(hard, 1.1)
        return max(0.001, hard * 0.67), max(0.001, hard)

    def take_turn(self, board, time):
        started = _now()
        legal = [(r, c) for r in range(SIZE) for c in range(SIZE) if board[r][c] == EMPTY]
        if not legal:
            raise ValueError('No legal move: board is full')
        fallback = min(legal, key=lambda rc: abs(rc[0] - 9) + abs(rc[1] - 9))
        self.moves_played += 1
        self.last_search = {'phase': 'fallback', 'depth': 0, 'nodes': 0, 'qnodes': 0, 'proof_nodes': 0}
        if len(legal) == NCELL:
            self.last_search['phase'] = 'opening'
            return 9, 9
        remaining = None if time is None or time < 0 else float(time) / 1000
        if remaining is not None and remaining < 0.025:
            return fallback
        e = self.engine
        e.clock = None
        e.load(board)
        # A deliberately small opening policy, selected by development games.
        reply = self.params.get('white_opening')
        if reply is not None and self.color == 1 and len(legal) == NCELL - 1 and board[9][9] == 0:
            reply = tuple(reply)
            if reply in legal:
                self.last_search.update(phase='opening-reply', seconds=_now() - started)
                return reply
        me, enemy = self.color + 1, 2 - self.color
        pressure = bool(e.NW[me] or e.NW[enemy] or e.T[me] or e.T[enemy])
        soft, hard = self._budget(remaining, e.stones, pressure)
        deadline = started + hard
        def check():
            if _now() >= deadline:
                raise _TimeUp()
        e.clock = check
        if len(e.tt) > 100_000:
            e.tt.clear()
        if len(e.vtt) > 50_000:
            e.vtt.clear()
        best, phase, score, depth = fallback[0] * SIZE + fallback[1], 'ordered', None, 0
        searcher = _TacticalSearcher(e)
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
                    choices = forced or [p for _, p, _ in e.features(me)]
                    if choices:
                        best = choices[0]
                    hint = None
                    # Scout only where an existing threat makes a forcing win
                    # plausible; the main search handles the other positions.
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
                        move, score, depth = searcher.root(me, 20, soft, started)
                        if move is not None:
                            best = move
                        phase = 'tactical-pvs'
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
                            'tt_hits': searcher.tt_hits, 'qtt_hits': searcher.qtt_hits, 'proof_nodes': proof_nodes,
                            'seconds': _now() - started, 'soft_budget': soft, 'hard_budget': hard,
                            'extended': searcher.extended, 'iterations': searcher.iterations}
        move = divmod(best, SIZE)
        return move if move in legal else fallback
