# Shared v3: adaptive clock + bounded forcing-line verification. AI-assisted.
"""Merged capture-aware Omok++ agent for team JRM. Standard library only.

AI disclosure: ChatGPT generated the implementation, comments and supporting
verification in this file. The team must review and understand it before use.
Based on the second JRM agent, with vulnerable-pair evaluation and capture-safe
move ordering inspired by the third JangJinha agent. See README.txt.

Public interface: SmartPlayerJRM(color).take_turn(board, time) -> (row, col).
The caller's board is never modified. Time is the remaining GAME time in ms.
"""
from functools import lru_cache
from random import Random
from time import perf_counter

from playerJRM import PlayerJRM

SIZE = 19
STRIDE = 21
EMPTY = -1
BORDER = 2
AXES = (1, STRIDE, STRIDE + 1, STRIDE - 1)
DIRECTIONS = AXES + tuple(-d for d in AXES)
CELLS = tuple((r + 1) * STRIDE + c + 1 for r in range(SIZE) for c in range(SIZE))
CENTER = 10 * STRIDE + 10
MATE = 10_000_000
INF = 20_000_000
CHARS = '.XO#'
VULNERABLE_PAIR_PENALTY = 700
LOCAL_PAIR_PENALTY = 900


def _geometry():
    """Precompute lines, line membership and radius-two neighborhoods."""
    valid = frozenset(CELLS)
    lines = []
    memberships = [[] for _ in range(STRIDE * STRIDE)]
    neighbors = [[] for _ in range(STRIDE * STRIDE)]
    for step in AXES:
        for p in CELLS:
            if p - step in valid:
                continue
            line = []
            q = p
            while q in valid:
                line.append(q)
                q += step
            # Four-cell lines still matter for captures near the corners.
            if len(line) >= 4:
                lid = len(lines)
                lines.append(tuple(line))
                for q in line:
                    memberships[q].append(lid)
    for p in CELLS:
        r, c = divmod(p, STRIDE)
        neighbors[p] = tuple(q for q in CELLS if q != p
                             and abs(q // STRIDE - r) <= 2
                             and abs(q % STRIDE - c) <= 2)
    return tuple(lines), tuple(map(tuple, memberships)), tuple(neighbors)


LINES, MEMBERSHIPS, NEIGHBORS = _geometry()
_rng = Random(20261006)
ZOBRIST = tuple((_rng.getrandbits(64), _rng.getrandbits(64))
                for _ in range(STRIDE * STRIDE))
SIDE_KEY = _rng.getrandbits(64)
del _rng
CENTER_BONUS = tuple(20 - abs(p // STRIDE - 10) - abs(p % STRIDE - 10)
                     for p in range(STRIDE * STRIDE))


@lru_cache(maxsize=48_000)
def _line_info(s):
    """Describe one line; offsets, rather than board coordinates, are cached.

    Five-cell windows with a friendly stone immediately outside are excluded:
    filling such a window would make an overline, not an exact-five win.
    Repeated three-stone groups are combined to recognize broken open threes.
    """
    data = []
    length = len(s)
    for me, other in (('X', 'O'), ('O', 'X')):
        heat = [0] * length
        wins = 0
        start = 0
        while start < length:
            if s[start] != me:
                start += 1
                continue
            end = start + 1
            while end < length and s[end] == me:
                end += 1
            wins += end - start == 5
            start = end
        winning = set()
        threes = {}
        pairs = {}
        score = s.count(me)
        for start in range(length - 4):
            end = start + 5
            if (start and s[start - 1] == me) or (end < length and s[end] == me):
                continue
            window = s[start:end]
            if other in window:
                continue
            n = window.count(me)
            if not n or n == 5:
                continue
            holes = tuple(start + j for j, value in enumerate(window) if value == '.')
            if n == 4:
                winning.update(holes)
                continue
            weight = (0, 3, 65, 1_100)[n]
            for j in holes:
                heat[j] += weight
            if n == 3:
                group = tuple(start + j for j, value in enumerate(window) if value == me)
                counts = threes.setdefault(group, {})
                for j in holes:
                    counts[j] = counts.get(j, 0) + 1
            elif n == 2:
                group = tuple(start + j for j, value in enumerate(window) if value == me)
                pairs[group] = pairs.get(group, 0) + 1
        strong_threes = 0
        for counts in threes.values():
            extensions = [j for j, n in counts.items() if n >= 2]
            if extensions:
                strong_threes += 1
                score += 5_500 + 500 * (len(extensions) - 1)
                for j in extensions:
                    heat[j] += 5_000
            else:
                score += 450
        score += sum(35 + 15 * min(n, 4) for n in pairs.values())
        if winning:
            score += 14_000 if len(winning) == 1 else 140_000 + 10_000 * len(winning)
            for j in winning:
                heat[j] += 300_000
        captures = set()
        for pattern, offset in (('.' + other * 2 + me, 0),
                                (me + other * 2 + '.', 3)):
            start = s.find(pattern)
            while start >= 0:
                captures.add(start + offset)
                start = s.find(pattern, start + 1)
        for j in captures:
            heat[j] += 1_300
        score += 150 * len(captures)
        # Third agent's safety heuristic: a pair bracketed by an opponent and
        # an empty cell can be removed on the opponent's next move. Evaluate
        # this on the actual position AFTER captures, not before simulation.
        for pattern in (other + me * 2 + '.', '.' + me * 2 + other):
            start = s.find(pattern)
            while start >= 0:
                score -= VULNERABLE_PAIR_PENALTY
                start = s.find(pattern, start + 1)
        data.append((score, wins, tuple(sorted(winning)), tuple(sorted(captures)),
                     tuple(heat), strong_threes))
    return tuple(data)


class PositionJRM:
    """Private position with reversible captures and incremental line features."""
    def __init__(self, board):
        self.cells = [BORDER] * (STRIDE * STRIDE)
        self.near = [0] * (STRIDE * STRIDE)
        self.heat = [[0] * (STRIDE * STRIDE) for _ in range(2)]
        self.scores = [0, 0]
        self.fives = [0, 0]
        self.threes = [0, 0]
        self.winning = [{}, {}]
        self.captures = [{}, {}]
        self.occupied = 0
        self.key = 0
        for r in range(SIZE):
            for c in range(SIZE):
                p = (r + 1) * STRIDE + c + 1
                color = int(board[r][c])
                self.cells[p] = color
                if color != EMPTY:
                    self.occupied += 1
                    self.key ^= ZOBRIST[p][color]
                    for q in NEIGHBORS[p]:
                        self.near[q] += 1
        self.info = []
        for lid, line in enumerate(LINES):
            info = _line_info(''.join(CHARS[self.cells[p] + 1] for p in line))
            self.info.append(info)
            self._add_info(lid, info, 1)

    def _add_info(self, lid, info, sign):
        line = LINES[lid]
        for color in (0, 1):
            score, fives, winning, captures, heat, threes = info[color]
            self.scores[color] += sign * score
            self.fives[color] += sign * fives
            self.threes[color] += sign * threes
            for offsets, table in ((winning, self.winning[color]),
                                   (captures, self.captures[color])):
                for j in offsets:
                    p = line[j]
                    value = table.get(p, 0) + sign
                    if value:
                        table[p] = value
                    else:
                        table.pop(p, None)
            target = self.heat[color]
            for p, value in zip(line, heat):
                if value:
                    target[p] += sign * value

    def make(self, p, color):
        """Place a stone, collect ALL captures, then remove them simultaneously."""
        cells = self.cells
        opponent = 1 - color
        captured = []
        for d in DIRECTIONS:
            if cells[p + d] == opponent and cells[p + 2 * d] == opponent and cells[p + 3 * d] == color:
                captured.extend((p + d, p + 2 * d))
        changes = [(p, EMPTY, color)] + [(q, opponent, EMPTY) for q in captured]
        affected = set()
        old_key = self.key
        for q, old, new in changes:
            cells[q] = new
            if old != EMPTY:
                self.key ^= ZOBRIST[q][old]
            if new != EMPTY:
                self.key ^= ZOBRIST[q][new]
            change = 1 if old == EMPTY else -1
            self.occupied += change
            for v in NEIGHBORS[q]:
                self.near[v] += change
            affected.update(MEMBERSHIPS[q])
        previous = []
        for lid in affected:
            old_info = self.info[lid]
            new_info = _line_info(''.join(CHARS[cells[q] + 1] for q in LINES[lid]))
            previous.append((lid, old_info))
            self._add_info(lid, old_info, -1)
            self._add_info(lid, new_info, 1)
            self.info[lid] = new_info
        return changes, previous, old_key

    def undo(self, record):
        changes, previous, old_key = record
        for lid, old_info in previous:
            self._add_info(lid, self.info[lid], -1)
            self._add_info(lid, old_info, 1)
            self.info[lid] = old_info
        for q, old, new in changes:
            self.cells[q] = old
            change = -1 if old == EMPTY else 1
            self.occupied += change
            for v in NEIGHBORS[q]:
                self.near[v] += change
        self.key = old_key

    def outcome(self, color):
        """None = ongoing, 1 = win, -1 = loss, 0 = draw, AFTER captures."""
        mine, theirs = self.fives[color], self.fives[1 - color]
        if mine and theirs:
            return 0
        if mine:
            return 1
        if theirs:
            return -1
        return 0 if self.occupied == SIZE * SIZE else None

    def evaluate(self, color):
        opponent = 1 - color
        value = self.scores[color] - self.scores[opponent]
        # Threats in different directions can force incompatible responses.
        for side, sign in ((color, 1), (opponent, -1)):
            count = self.threes[side]
            if count >= 2:
                value += sign * (6_000 * min(count - 1, 3))
        return max(-MATE // 4, min(MATE // 4, value))


class _ProofUnknownJRM(Exception):
    pass


class SearchTimeoutJRM(Exception):
    """Internal control flow: a finished iteration remains available."""


class SmartPlayerJRM(PlayerJRM):
    """Iterative-deepening alpha-beta with tactical extensions and a game clock."""
    def __init__(self, color, adaptive_time=True, forcing_search=True):
        super().__init__(color)
        self.adaptive_time = adaptive_time
        self.forcing_search = forcing_search
        if color not in (0, 1):
            raise ValueError('color must be 0 (black) or 1 (white)')
        self._tt = {}
        self._history = [[0] * (STRIDE * STRIDE) for _ in range(2)]
        self._turns = 0
        self.last_search = {}  # Optional diagnostics; never printed by the agent.

    def take_turn(self, board, time):
        started = perf_counter()
        legal = [(r,c) for r in range(SIZE) for c in range(SIZE) if board[r][c] == EMPTY]
        if not legal:
            raise ValueError('No legal move')
        fallback = min(legal, key=lambda rc: abs(rc[0]-9)+abs(rc[1]-9))
        self._turns += 1
        self.last_search = {'depth':0,'nodes':0,'seconds':0.0}
        if len(legal) == SIZE*SIZE:
            self.last_search['seconds']=perf_counter()-started
            return (9,9)
        remaining = None if time is None or time < 0 else float(time)/1000
        if remaining is not None and remaining < .025:
            self.last_search['seconds']=perf_counter()-started
            return fallback
        self._nodes=0; self._killers={}; self._extended=False
        self._allow_extension=False; self._proof_nodes=0; self._proof_seconds=0.0
        self._deadline=started+self._budget(remaining,SIZE*SIZE-len(legal))
        self._hard_deadline=self._deadline
        if len(self._tt)>70_000: self._tt.clear()
        for values in self._history:
            for p in CELLS: values[p]//=2
        pos=PositionJRM(board)
        threat=self._classify(pos,self.color)
        soft,hard=self._time_limits(remaining,pos.occupied,threat)
        self._deadline=started+soft; self._hard_deadline=started+hard
        self._allow_extension=self.adaptive_time and threat['pressure']
        moves=self._ranked(pos,self.color,0,None,30)
        best=moves[0] if moves else (fallback[0]+1)*STRIDE+fallback[1]+1
        completed=0; value=None; unstable=False; proof_move=None
        try:
            forced,forced_value=self._tactics(pos,self.color,0)
            if forced: best=forced[0]
            if forced_value is not None: value=forced_value
            elif forced is not None and len(forced)==1: best=forced[0]
            else:
                for depth in range(1,11):
                    self._check_time()
                    self._iteration_best=best
                    self._q_depth=0 if depth==1 else 10
                    score=self._search(pos,self.color,depth,-INF,INF,0)
                    candidate=self._iteration_best
                    unstable=(completed>0 and (candidate!=best or score<value-5000))
                    self._allow_extension=self.adaptive_time and (threat['pressure'] or unstable)
                    best=candidate; value=score; completed=depth
                    if score>=MATE-100: break
                    # A bounded proof attempt shares the turn's clock and uses
                    # the same root threat summary as time allocation.
                    if depth==1 and self.forcing_search and threat['own_threes']:
                        proof_start=perf_counter()
                        proof_end=min(self._deadline,proof_start+min(.65,soft*.22))
                        proof_move=self._forcing_move(pos,self.color,proof_end)
                        self._proof_seconds=perf_counter()-proof_start
                        if proof_move is not None:
                            best=proof_move; value=MATE-20
                            break
                    if perf_counter()>=started+soft*.80:
                        if self._allow_extension:
                            self._deadline=self._hard_deadline;self._extended=True
                        else: break
        except SearchTimeoutJRM:
            pass
        self.last_search={'depth':completed,'nodes':self._nodes,
            'seconds':perf_counter()-started,'score':value,'phase':threat['phase'],
            'soft_budget':soft,'hard_budget':hard,'extended':self._extended,
            'unstable':unstable,'proof_nodes':self._proof_nodes,
            'proof_seconds':self._proof_seconds,'proof_found':proof_move is not None}
        return (best//STRIDE-1,best%STRIDE-1)

    @staticmethod
    def _classify(pos,color):
        own=len(pos.winning[color]); enemy=len(pos.winning[1-color])
        threes=pos.threes[color]; enemy_threes=pos.threes[1-color]
        pressure=bool(own or enemy or enemy_threes or threes>=2)
        return {'own_threes':threes,'enemy_threes':enemy_threes,
                'pressure':pressure,
                'phase':'immediate' if own or enemy else 'threat' if pressure or threes else 'quiet'}

    def _time_limits(self,remaining,stones,threat):
        if not self.adaptive_time:
            base=self._budget(remaining,stones)
            return base,base
        base=2.0 if remaining is None else min(3.5,remaining/max(12,20-self._turns//3))
        soft=base*(1.35 if threat['pressure'] else .85)
        hard=min(6.0,soft*1.9)
        if remaining is not None:
            cap=max(.001,min(remaining*.28,remaining-.025))
            soft=min(soft,cap);hard=min(hard,cap)
        if stones<=2:soft=min(soft,.4);hard=soft
        elif stones<=5:soft=min(soft,1.1);hard=min(hard,1.8)
        return max(.001,soft),max(.001,hard)

    def _forcing_move(self,pos,color,deadline):
        """Find a verified forcing-four sequence, or return UNKNOWN (None).

        Attack candidates are selective; defender replies are ALL legal cells.
        A bound/timeout/refutation means unknown, never a claimed forced loss.
        """
        self._proof_end=deadline;self._proof_limit=1800
        try:
            return self._prove_attack(pos,color,3)
        except _ProofUnknownJRM:
            return None

    def _proof_check(self):
        self._proof_nodes+=1
        if self._proof_nodes>self._proof_limit or perf_counter()>=self._proof_end:
            raise _ProofUnknownJRM
        self._check_time()

    def _prove_attack(self,pos,color,left):
        self._proof_check()
        wins=self._strict_wins(pos,color)
        if wins:return wins[0]
        if left<=0:return None
        candidates=[p for p in CELLS if pos.cells[p]==EMPTY and pos.heat[color][p]>=1100]
        candidates.sort(key=lambda p:(-pos.heat[color][p],p))
        for p in candidates[:8]:
            self._proof_check()
            record=pos.make(p,color)
            try:
                outcome=pos.outcome(color)
                if outcome==1:return p
                if outcome is None and self._strict_wins(pos,color):
                    if self._prove_defence(pos,color,left-1):return p
            finally:pos.undo(record)
        return None

    def _prove_defence(self,pos,attacker,left):
        self._proof_check()
        defender=1-attacker
        if self._strict_wins(pos,defender):return False
        # Check plausible blocks/captures first, but never omit a legal reply.
        priority=set(pos.winning[attacker])|set(pos.captures[defender])|set(pos.winning[defender])
        replies=[p for p in CELLS if pos.cells[p]==EMPTY]
        replies.sort(key=lambda p:(p not in priority,-pos.heat[defender][p],p))
        for p in replies:
            self._proof_check()
            record=pos.make(p,defender)
            try:
                outcome=pos.outcome(attacker)
                if outcome in (-1,0):return False
                if outcome==1:continue
                if self._strict_wins(pos,attacker):continue
                if self._prove_attack(pos,attacker,left) is None:return False
            finally:pos.undo(record)
        return True

    def _budget(self, remaining, stones):
        if remaining is None:
            budget = 2.0
        else:
            expected_turns = max(16, 28 - self._turns // 3)
            budget = min(2.8, remaining / expected_turns)
            # Leave a margin for interpreter/OS overhead and the caller's clock.
            budget = min(budget, max(0.001, remaining * 0.85 - 0.010))
        if stones <= 2:
            budget = min(budget, 0.40)
        elif stones <= 5:
            budget = min(budget, 1.10)
        return max(0.001, budget)

    def _check_time(self):
        now=perf_counter()
        if now>=self._deadline:
            if (self.adaptive_time and self._allow_extension
                    and self._deadline<self._hard_deadline and now<self._hard_deadline):
                self._deadline=self._hard_deadline;self._extended=True
            else:raise SearchTimeoutJRM

    def _strict_wins(self, pos, color):
        """A line-completing capture may instead make BOTH players win (draw)."""
        result = []
        for p in tuple(pos.winning[color]):
            if p not in pos.captures[color]:
                result.append(p)
            else:
                record = pos.make(p, color)
                try:
                    if pos.outcome(color) == 1:
                        result.append(p)
                finally:
                    pos.undo(record)
        return result

    def _tactics(self, pos, color, ply):
        """Return forced moves and/or a proven terminal tactical value.

        Defence includes every capture, not just occupying the threatened square.
        This is essential when a pair capture breaks a four elsewhere on the board.
        """
        wins = self._strict_wins(pos, color)
        if wins:
            return wins, MATE - ply - 1
        threats = self._strict_wins(pos, 1 - color)
        if not threats:
            return None, None
        candidates = set(threats) | set(pos.captures[color])
        # Include a move that creates a simultaneous-five draw as an escape.
        candidates.update(pos.winning[color])
        for threat in threats:
            # A quiet move can also turn the enemy's winning capture into a DRAW.
            # Case 1: our move completes five only AFTER that future capture.
            if threat in pos.captures[1 - color]:
                record = pos.make(threat, 1 - color)
                try:
                    candidates.update(pos.winning[color])
                finally:
                    pos.undo(record)
            # Case 2: our move supplies the second stone of a newly capturable
            # pair; removing the pair may trim one of our overlines to five.
            for d in DIRECTIONS:
                first, second, end = threat + d, threat + 2*d, threat + 3*d
                if pos.cells[first] == color and pos.cells[second] == EMPTY:
                    if pos.cells[end] == 1 - color:
                        candidates.add(second)
                elif pos.cells[first] == EMPTY and pos.cells[second] == color:
                    if pos.cells[end] == 1 - color:
                        candidates.add(first)
        candidates = {p for p in candidates if pos.cells[p] == EMPTY}
        safe = []
        draws = []
        for p in sorted(candidates, key=lambda q: (-pos.heat[color][q], q)):
            self._check_time()
            record = pos.make(p, color)
            try:
                outcome = pos.outcome(color)
                if outcome == 1:
                    return [p], MATE - ply - 1
                if outcome == 0:
                    draws.append(p)
                elif outcome is None and not self._strict_wins(pos, 1 - color):
                    safe.append(p)
            finally:
                pos.undo(record)
        if safe or draws:
            return safe + draws, None
        # No block or capture can prevent the opponent's next-turn win.
        return sorted(candidates, key=lambda q: (-pos.heat[color][q], q)), -MATE + ply + 2

    def _ranked(self, pos, color, ply, tt_move, width):
        mine, theirs = pos.heat[color], pos.heat[1 - color]
        history = self._history[color]
        killers = self._killers.get(ply, ())
        moves = [p for p in CELLS if pos.cells[p] == EMPTY and pos.near[p]]
        if not moves:
            moves = [p for p in CELLS if pos.cells[p] == EMPTY]
        def key(p):
            bonus = (2_000_000 if p == tt_move else 0) + (3_000 if p in killers else 0)
            # Approximate local exposure only guides ordering; terminal tactics
            # and post-capture evaluation remain authoritative.
            risk = 0
            protection = 0
            for d in DIRECTIONS:
                if pos.cells[p + d] == color:
                    behind, ahead = pos.cells[p - d], pos.cells[p + 2*d]
                    if (behind == 1-color and ahead == EMPTY or
                            behind == EMPTY and ahead == 1-color):
                        risk += 1
                    if ahead == color and pos.cells[p + 3*d] == 1-color:
                        protection += 1
            safety = -LOCAL_PAIR_PENALTY * risk + VULNERABLE_PAIR_PENALTY * protection
            return mine[p] * 10 + theirs[p] * 9 + safety + bonus + min(history[p], 2_000) + CENTER_BONUS[p]
        moves.sort(key=lambda p: (key(p), -p), reverse=True)
        return moves[:width]

    @staticmethod
    def _pack_score(score, ply):
        return score + ply if score > MATE - 1000 else score - ply if score < -MATE + 1000 else score

    @staticmethod
    def _unpack_score(score, ply):
        return score - ply if score > MATE - 1000 else score + ply if score < -MATE + 1000 else score

    def _search(self, pos, color, depth, alpha, beta, ply):
        self._nodes += 1
        if self._nodes & 15 == 0:
            self._check_time()
        outcome = pos.outcome(color)
        if outcome is not None:
            return outcome * (MATE - ply) if outcome else 0
        if depth <= 0:
            return self._quiescence(pos, color, alpha, beta, ply,
                                    self._q_depth, self._nodes + 128)
        original_alpha = alpha
        key = pos.key ^ (SIDE_KEY if color else 0)
        entry = self._tt.get(key)
        tt_move = entry[3] if entry else None
        if entry and entry[0] >= depth and ply:
            score = self._unpack_score(entry[1], ply)
            if entry[2] == 0:
                return score
            if entry[2] == 1:
                alpha = max(alpha, score)
            else:
                beta = min(beta, score)
            if alpha >= beta:
                return score
        moves, tactical_value = self._tactics(pos, color, ply)
        if tactical_value is not None:
            if ply == 0 and moves:
                self._iteration_best = moves[0]
            return tactical_value
        forced = moves is not None
        if not forced:
            width = 26 if ply == 0 else 16 if ply == 1 else 12 if ply == 2 else 9
            moves = self._ranked(pos, color, ply, tt_move, width)
        elif tt_move in moves:
            moves.remove(tt_move)
            moves.insert(0, tt_move)
        best_score, best_move = -INF, moves[0]
        for number, p in enumerate(moves):
            self._check_time()
            tactical_move = p in pos.captures[color] or pos.heat[color][p] >= 5_000
            record = pos.make(p, color)
            try:
                child_depth = depth - 1
                # Only quiet, late alternatives are reduced; promising ones are re-searched.
                reduction = int(depth >= 3 and number >= 5 and not forced
                                and not tactical_move and not pos.winning[color])
                if number == 0:
                    score = -self._search(pos, 1 - color, child_depth, -beta, -alpha, ply + 1)
                else:
                    score = -self._search(pos, 1 - color, child_depth - reduction,
                                          -alpha - 1, -alpha, ply + 1)
                    if score > alpha and (reduction or score < beta):
                        score = -self._search(pos, 1 - color, child_depth, -beta, -alpha, ply + 1)
            finally:
                pos.undo(record)
            if score > best_score:
                best_score, best_move = score, p
                if ply == 0:
                    self._iteration_best = p
            alpha = max(alpha, score)
            if alpha >= beta:
                self._history[color][p] += depth * depth * 20
                old = self._killers.get(ply, ())
                self._killers[ply] = (p,) + tuple(q for q in old if q != p)[:1]
                break
        flag = 2 if best_score <= original_alpha else 1 if best_score >= beta else 0
        old = self._tt.get(key)
        if old is None or depth >= old[0]:
            self._tt[key] = (depth, self._pack_score(best_score, ply), flag, best_move)
        return best_score

    def _quiescence(self, pos, color, alpha, beta, ply, left, node_limit):
        """Resolve immediate wins and captures, then extend forcing-four attacks."""
        self._nodes += 1
        if self._nodes & 15 == 0:
            self._check_time()
        outcome = pos.outcome(color)
        if outcome is not None:
            return outcome * (MATE - ply) if outcome else 0
        moves, tactical_value = self._tactics(pos, color, ply)
        if tactical_value is not None:
            return tactical_value
        forced = moves is not None
        if left <= 0 or self._nodes >= node_limit:
            return pos.evaluate(color)
        if forced:
            best = -INF
        else:
            best = pos.evaluate(color)
            if best >= beta:
                return best
            alpha = max(alpha, best)
            # Rank forcing attacks by OUR threat strength. Defensive heat must
            # not push an available winning sequence out of this extension.
            moves = [p for p in CELLS if pos.cells[p] == EMPTY
                     and pos.heat[color][p] >= 1_100]
            moves.sort(key=lambda p: (pos.heat[color][p], CENTER_BONUS[p], -p), reverse=True)
            moves = moves[:12]
        for p in moves:
            self._check_time()
            record = pos.make(p, color)
            try:
                if not forced and pos.outcome(color) is None and not pos.winning[color]:
                    continue
                score = -self._quiescence(pos, 1 - color, -beta, -alpha,
                                          ply + 1, left - 1, node_limit)
            finally:
                pos.undo(record)
            best = max(best, score)
            alpha = max(alpha, score)
            if alpha >= beta:
                break
        return best
