"""Check that v15's tracked win lines give the same win_points as a full line scan."""
import sys, json, random
sys.path.insert(0, 'tools')
import arena
p = arena.make_player('agents/v15/smartplayerJRM.py', 0)
G = type(p).take_turn.__globals__
NLINES, LINES = G['NLINES'], G['LINES']


def old_win_points(self, x):
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


e = p.engine
stats = {'checked': 0, 'nonempty': 0, 'mism': 0}


def compare():
    for x in (1, 2):
        a = old_win_points(e, x)
        b = e.win_points(x)
        lines = {lid for lid in range(NLINES) if e.info(e.lk[lid])[4 + x - 1]}
        stats['checked'] += 1
        stats['nonempty'] += bool(a)
        if a != b or lines != e.WL[x] or len(a) > e.NW[x]:
            stats['mism'] += 1
            if stats['mism'] < 5:
                print('MISMATCH', x, a, b, sorted(lines ^ e.WL[x]))


def probe(rng):
    # make/unmake round trips, as the search does.
    cand = e.candidates()
    for q in rng.sample(cand, min(6, len(cand))):
        for me in (1, 2):
            cap = e.make(q, me)
            compare()
            e.unmake(q, me, cap)
            compare()


games = json.load(open('tuning/book_games.json')) + json.load(open('tuning/book2_games.json'))
rng = random.Random(11)
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
    probe(rng)
for t in range(3000):
    e.load([[-1] * 19 for _ in range(19)])
    color = 1
    for _ in range(rng.randint(6, 80)):
        r = min(18, max(0, int(rng.gauss(9, 3))))
        c = min(18, max(0, int(rng.gauss(9, 3))))
        q = r * 19 + c
        if e.cells[q]:
            continue
        e.make(q, color)
        color = 3 - color if rng.random() < 0.8 else color
    compare()
    probe(rng)
print(stats)
