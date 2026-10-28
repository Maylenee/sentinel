"""Deteksi koordinasi waktu-lokal.

Pendekatan lama menyatukan semua edge sepanjang waktu sehingga komentar yang
tersebar berbulan-bulan bisa membentuk satu "kelompok" raksasa lewat rantai
transitif. Modul ini membatasi edge pada jendela waktu pendek, menolak pasangan
yang rentang kejadiannya terlalu panjang, dan hanya menerima kelompok yang
benar-benar saling terhubung (clique), bukan komponen transitif.
"""
import random
from collections import defaultdict

SLANG = {'gak': 'tidak', 'ga': 'tidak', 'nggak': 'tidak', 'tdk': 'tidak', 'yg': 'yang',
         'dgn': 'dengan', 'udah': 'sudah', 'bgt': 'banget', 'utk': 'untuk', 'krn': 'karena', 'jg': 'juga'}
STOP = set('''yang dan di ke dari untuk dengan ini itu karena juga sudah tidak ada akan pada bisa saya kamu
dia kami kita mereka atau tapi kalau jika saat lebih sangat banget aja saja nya para agar oleh dalam
sebagai menjadi telah masih hanya antara setelah sebelum sudah belum apa siapa mana kapan bagaimana
the and this that for you with are was were have has had not but from they their our your'''.split())


def norm(text):
    out = []
    for w in str(text or '').lower().replace('#', ' ').replace('@', ' ').split():
        w = ''.join(ch for ch in w if ch.isalnum())
        if w:
            out.append(SLANG.get(w, w))
    return out


def shingles(text):
    w = norm(text)
    s = {' '.join(w[i:i + 3]) for i in range(len(w) - 2)}
    return s or set(w)


def jaccard(a, b):
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a) + len(b) - inter
    return inter / union if union else 0.0


def _cliques(adj, min_size=3, max_cliques=30, max_steps=200000):
    """Bron-Kerbosch dengan pivot, dibatasi agar tetap aman untuk data besar."""
    result = []
    steps = [0]

    def bk(r, p, x):
        if len(result) >= max_cliques or steps[0] >= max_steps:
            return
        steps[0] += 1
        if not p and not x:
            if len(r) >= min_size:
                result.append(frozenset(r))
            return
        u = max(p | x, key=lambda v: len(adj[v] & p), default=None)
        skip = adj[u] if u is not None else set()
        for v in list(p - skip):
            bk(r | {v}, p & adj[v], x & adj[v])
            p.remove(v)
            x.add(v)

    bk(set(), set(adj), set())
    return [set(c) for c in result]


def _span(times):
    return (max(times) - min(times)) if times else 0.0


def detect(accs, win=1440, min_pairs=1, similarity=0.6, cluster_span=360, pair_span=None,
           permutations=120, seed=7):
    """Kembalikan edge, clique, dan statistik.

    win            : jendela (menit) untuk menganggap dua post berdekatan.
    min_pairs      : jumlah kecocokan minimal untuk satu edge akun.
    cluster_span   : rentang maksimum (menit) seluruh anggota clique.
    pair_span      : rentang maksimum kecocokan untuk satu pasangan akun.
    """
    pair_span = win if pair_span is None else pair_span
    posts = []
    for ai, a in enumerate(accs):
        for p in a.get('posts') or []:
            t = p.get('t')
            text = str(p.get('text') or '').strip()
            # Komentar satu-dua kata seperti "sepakat" atau "setuju" tidak cukup
            # spesifik untuk dijadikan bukti koordinasi.
            if t is None or len(norm(text)) < 3 or len(text) < 12:
                continue
            posts.append((float(t), ai, shingles(text), p))
    posts.sort(key=lambda x: x[0])

    matches = defaultdict(list)
    similar_pairs = []
    for i in range(len(posts)):
        ti, ai, si, _pi = posts[i]
        for j in range(i + 1, len(posts)):
            tj, aj, sj, _pj = posts[j]
            if tj - ti > win:
                break
            if ai == aj:
                continue
            if jaccard(si, sj) < similarity:
                continue
            similar_pairs.append((i, j))
            matches[(min(ai, aj), max(ai, aj))].append((ti, tj))

    edges = []
    edge_info = {}
    for (a, b), hits in matches.items():
        if len(hits) < min_pairs:
            continue
        times = [t for pair in hits for t in pair]
        pspan = _span(times)
        if pspan > pair_span:
            continue
        edges.append((a, b, len(hits)))
        edge_info[(a, b)] = {'n': len(hits), 'span_min': round(pspan, 1),
                             'first': min(times), 'last': max(times)}

    adj = defaultdict(set)
    for a, b, _w in edges:
        adj[a].add(b)
        adj[b].add(a)

    candidates = _cliques(adj)
    clusters, cluster_stats = [], []
    for group in candidates:
        times = [p[0] for p in posts if p[1] in group]
        span = _span(times)
        if span > cluster_span:
            continue
        inside = [(a, b, w) for a, b, w in edges if a in group and b in group]
        clusters.append(sorted(group))
        cluster_stats.append({'size': len(group), 'span_min': round(span, 1),
                              'edges': len(inside), 'members': sorted(group)})

    # Uji permutasi: apakah kemunculan teks mirip dalam jendela waktu lebih
    # banyak daripada yang diharapkan bila waktu komentar acak?
    observed = 0
    for i, j in similar_pairs:
        if abs(posts[i][0] - posts[j][0]) <= win:
            observed += 1
    rng = random.Random(seed)
    times = [p[0] for p in posts]
    null = []
    if similar_pairs:
        for _ in range(max(20, int(permutations))):
            rng.shuffle(times)
            count = 0
            for i, j in similar_pairs:
                if abs(times[i] - times[j]) <= win:
                    count += 1
            null.append(count)
    expected = sum(null) / len(null) if null else 0.0
    p_value = (1 + sum(1 for x in null if x >= observed)) / (len(null) + 1) if null else 1.0

    return {
        'edges': edges,
        'edge_info': edge_info,
        'clusters': clusters,
        'cluster_stats': cluster_stats,
        'stats': {
            'method': 'time-local weighted cliques + permutation test',
            'window_min': win,
            'pair_span_min': pair_span,
            'cluster_span_min': cluster_span,
            'min_pairs': min_pairs,
            'similar_pairs': len(similar_pairs),
            'observed_pairs': observed,
            'expected_pairs': round(expected, 2),
            'p_value': round(p_value, 4),
            'permutations': len(null),
        },
    }
