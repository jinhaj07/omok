"""Check that v15's cached four_moves matches the original per-candidate version."""
import sys, json, random
sys.path.insert(0, 'tools')
import arena
p = arena.make_player('agents/v15/smartplayerJRM.py', 0)
G = type(p).take_turn.__globals__
CAP_RAYS, CELL_LINES = G['CAP_RAYS'], G['CELL_LINES']

def old_four_moves(self, me, cand):
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

e = p.engine
stats = {'checked': 0, 'nonempty': 0, 'mism': 0, 'caps': 0}
def compare():
    cand = e.candidates()
    for me in (1, 2):
        h0 = e.h
        a = old_four_moves(e, me, cand)
        b = e.four_moves(me, cand)
        assert e.h == h0
        stats['checked'] += 1
        stats['nonempty'] += bool(a)
        stats['caps'] += bool(e._capture_cells(me))
        if a != b:
            stats['mism'] += 1
            if stats['mism'] < 5:
                print('MISMATCH', me, a[:6], b[:6])

games = json.load(open('tuning/book_games.json')) + json.load(open('tuning/book2_games.json'))
for g in games:
    e.load([[-1] * 19 for _ in range(19)])
    color = 1
    for (r, c) in g['history']:
        q = r * 19 + c
        if e.cells[q]:
            break
        e.make(q, color)
        color = 3 - color
        compare()
rng = random.Random(7)
for t in range(3000):
    e.load([[-1] * 19 for _ in range(19)])
    color = 1
    for _ in range(rng.randint(6, 60)):
        r = min(18, max(0, int(rng.gauss(9, 3))))
        c = min(18, max(0, int(rng.gauss(9, 3))))
        q = r * 19 + c
        if e.cells[q]:
            continue
        e.make(q, color)
        color = 3 - color if rng.random() < 0.8 else color
    compare()
print(stats)
