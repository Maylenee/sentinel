"""Mesin deteksi SENTINEL: perilaku akun + koordinasi teks, skor linear yang bisa dijelaskan."""
import math
import re
from collections import Counter

SLANG = {'gak': 'tidak', 'ga': 'tidak', 'nggak': 'tidak', 'tdk': 'tidak', 'yg': 'yang', 'dgn': 'dengan',
         'udah': 'sudah', 'bgt': 'banget', 'utk': 'untuk', 'krn': 'karena', 'jg': 'juga'}
_URL = re.compile(r'https?://\S+|@\w+')
_NON = re.compile(r'[^a-z0-9\s]')

STOP = set('''yang dan di ke dari untuk dengan ini itu karena juga sudah tidak ada akan pada bisa saya kamu
dia kami kita mereka atau tapi kalau jika saat lebih sangat banget aja saja nya para agar oleh dalam
sebagai menjadi telah masih hanya antara setelah sebelum sudah belum apa siapa mana kapan bagaimana
the and this that for you with are was were have has had not but from they their our your'''.split())

POS = set('''bagus baik setuju dukung mendukung benar mantap keren suka senang hebat tepat bangga terima
kasih membantu bermanfaat positif maju adil aman sehat berhasil'''.split())
NEG = set('''buruk jelek salah bohong tolak menolak benci marah kecewa gagal korup penipu provokasi hina
rusak parah curiga negatif bahaya ancam anarkis kacau'''.split())


def norm(text):
    t = _NON.sub(' ', _URL.sub(' ', str(text).lower()))
    return [SLANG.get(w, w) for w in t.split()]


def shingles(text):
    w = norm(text)
    s = {' '.join(w[i:i + 3]) for i in range(len(w) - 2)}
    return s or set(w)


def jaccard(a, b):
    if not a or not b:
        return 0.0
    i = len(a & b)
    u = len(a) + len(b) - i
    return i / u if u else 0.0


def top_terms(texts, n=12):
    c = Counter(w for t in texts for w in norm(t) if len(w) >= 3 and w not in STOP)
    return [{'term': w, 'count': k} for w, k in c.most_common(n)]


def sentiment_counts(texts):
    pos = neg = total = 0
    for t in texts:
        for w in norm(t):
            total += 1
            if w in POS:
                pos += 1
            elif w in NEG:
                neg += 1
    return {'positive_words': pos, 'negative_words': neg, 'total_words': total}


def content_summary(items, clusters=0, context=None, narrative=None):
    """Ringkasan konteks video + komentar: volume, akun, kemiripan, waktu, kata kunci, sikap."""
    post = next((it for it in items if it.get('kind') == 'post'), None)
    comments = [it for it in items if it.get('kind') != 'post']
    post_text = (post.get('text') or '').strip() if post else ''
    comment_texts = [c['text'].strip() for c in comments if (c.get('text') or '').strip()]
    texts = ([post_text] if post_text else []) + comment_texts
    uniq = {c['id'] for c in comments if (c.get('text') or '').strip()}
    rows = [(c['id'], shingles(c['text'])) for c in comments if (c.get('text') or '').strip()]
    rows = [(i, s) for i, s in rows if s]
    dup = set()
    for i in range(len(rows)):
        for j in range(i + 1, len(rows)):
            if rows[i][0] != rows[j][0] and jaccard(rows[i][1], rows[j][1]) >= 0.7:
                dup.update((rows[i][0], rows[j][0]))
    dup_pct = round(100 * len(dup) / len(rows)) if rows else 0
    ts = [c['t'] for c in comments if c.get('t') is not None]
    span = round((max(ts) - min(ts)) / 60, 1) if len(ts) > 1 else 0
    top = top_terms(texts)
    sent = sentiment_counts(texts)
    n_txt = len(comment_texts)
    if n_txt:
        head = f"Caption dan {n_txt} komentar teks dari {len(uniq)} akun dianalisis."
    elif post_text:
        head = "Hanya caption postingan yang berisi teks; tidak ada komentar teks yang bisa dianalisis."
    else:
        head = "Tidak ada teks postingan maupun komentar yang bisa dianalisis."
    ctx = context or {}
    narr = narrative or {}
    claims = ctx.get('claims') or []
    parts = []
    if ctx.get('summary'):
        parts.append("Konteks video: " + ctx['summary'])
    parts.append(head)
    if n_txt:
        parts.append(f"{dup_pct}% komentar memiliki teks nyaris sama dengan komentar akun lain."
                     if dup_pct else "Tidak ada komentar dari akun berbeda yang teksnya nyaris sama.")
    if clusters:
        parts.append(f"Terdeteksi {clusters} clique akun yang menulis teks mirip dalam jendela waktu pendek.")
    else:
        parts.append("Tidak ada clique akun yang bergerak serempak.")
    if claims:
        parts.append(f"Konteks memuat {len(claims)} klaim utama yang dipakai untuk memetakan komentar.")
    if narr.get('total'):
        lab = narr.get('labels') or {}
        parts.append(f"Sikap komentar: {lab.get('dukung', 0)} dukung, {lab.get('tolak', 0)} tolak, "
                     f"{lab.get('tanya', 0)} tanya, {lab.get('netral', 0)} netral.")
    if top:
        parts.append("Kata yang paling sering muncul: " + ", ".join(f"{t['term']} ({t['count']})" for t in top[:8]) + ".")
    if ctx.get('video', {}).get('transcript'):
        parts.append("Transkrip audio tersedia; ringkasan konteks memakai transkrip, OCR, dan caption.")
    else:
        parts.append("Catatan: transkrip audio tidak tersedia; konteks memakai caption/teks yang bisa dibaca.")
    why = ''
    if not clusters and dup_pct < 20:
        why = ("Skor rendah wajar: tidak ada teks komentar yang nyaris sama antar akun berbeda "
               "dan tidak ada clique yang bergerak serempak.")
        if n_txt == 0:
            why = "Skor rendah karena tidak ada komentar teks untuk dibandingkan; yang dianalisis hanya caption."
    elif not clusters:
        why = ("Ada komentar yang teksnya mirip, tetapi belum membentuk kelompok/clique minimal 3 akun; "
               "skor akun terkait naik sedikit namun belum melewati ambang.")
    else:
        why = (f"Terdapat {clusters} clique akun dengan teks mirip dalam jendela waktu pendek. "
               "Periksa rentang waktu, nilai p, dan contoh komentar sebelum menyimpulkan koordinasi.")
    if ctx and not clusters:
        why += " Konteks video dipakai lebih dulu; skor komentar tidak menambah bukti koordinasi yang cukup."
    samples = []
    for c in comments:
        txt = (c.get('text') or '').strip()
        if txt:
            samples.append({'handle': c.get('handle') or c.get('id'), 'text': txt[:280],
                            'url': c.get('url') or ''})
        if len(samples) >= 8:
            break
    return {'text_comments': n_txt, 'unique_commenters': len(uniq), 'duplicate_pct': dup_pct,
            'time_span_hours': span, 'reply_comments': sum(1 for c in comments if c.get('reply')),
            'top_terms': top, 'sentiment': sent, 'summary': ' '.join(parts), 'why_low': why,
            'post_text': post_text[:600], 'samples': samples,
            'video_summary': ctx.get('summary', ''), 'claims': claims,
            'context_confidence': ctx.get('confidence', 0),
            'transcript_available': bool(ctx.get('video', {}).get('transcript')),
            'ocr_available': bool(ctx.get('video', {}).get('ocr')),
            'context_sources': ctx.get('evidence', {}),
            'data_notes': ctx.get('data_notes', ''),
            'manipulation_flags': ctx.get('flags', []),
            'stance': narr.get('labels', {}), 'dominant_stance': narr.get('dominant', ''),
            'polarization_pct': narr.get('polarization_pct', 0),
            'claim_amplification': narr.get('claim_amplification', []),
            'narrative_confidence': narr.get('confidence', 0),
            'narrative_note': narr.get('note', '')}


def features(a):
    """t = menit sejak epoch."""
    ts = sorted(p['t'] for p in a['posts'])
    gaps = [y - x for x, y in zip(ts, ts[1:])]
    m = sum(gaps) / len(gaps) if gaps else 0
    sd = math.sqrt(sum((g - m) ** 2 for g in gaps) / len(gaps)) if gaps else 0
    span = max((ts[-1] - ts[0]) / 1440, 1)
    sh = [shingles(p['text']) for p in a['posts']]
    dup = sum(1 for i in range(len(sh)) if any(jaccard(sh[i], sh[j]) >= 0.7 for j in range(i + 1, len(sh))))
    return {'ppd': len(a['posts']) / span, 'cv': sd / m if len(gaps) > 2 and m > 0 else 1.0, 'age': a['ageDays'],
            'fr': a['following'] / max(a['followers'], 1), 'dup': dup / max(len(a['posts']), 1)}


def coordination(accs, win=30, min_pairs=2, cluster_span=None):
    """Deteksi clique waktu-lokal; lihat coordination.py untuk metodologi."""
    from sentinel.analysis import coordination as _coord
    span = cluster_span if cluster_span is not None else min(360, max(60, win))
    res = _coord.detect(accs, win=win, min_pairs=min_pairs, cluster_span=span)
    return res['edges'], res['clusters'], res


def _clamp(x, lo, hi):
    return min(hi, max(lo, x))


def analyze(accounts, max_accounts=300, min_posts=2, min_pairs=2, win=30, cluster_span=None):
    accs = [a for a in accounts if len(a['posts']) >= min_posts][:max_accounts]
    edges, clusters, coord_res = coordination(accs, win, min_pairs, cluster_span)
    cid = {i: ci for ci, g in enumerate(clusters) for i in g}
    partners = {}
    for x, y, _w in edges:
        partners.setdefault(x, set()).add(y)
        partners.setdefault(y, set()).add(x)
    out = []
    for i, a in enumerate(accs):
        f = features(a)
        size = len(clusters[cid[i]]) if i in cid else 0
        n_links = len(partners.get(i, ()))
        pv = (coord_res.get('stats') or {}).get('p_value', 1.0)
        if size:
            coord_label = f"Anggota clique {size} akun (teks mirip dalam jendela pendek; p={pv})"
            coord_pts = 2.0 + min(1.5, size / 10)
            if pv < 0.05:
                coord_pts += 0.5
            if pv < 0.01:
                coord_pts += 0.3
        elif n_links:
            coord_label = f"Teks mirip dengan {n_links} akun lain, tetapi belum membentuk clique"
            coord_pts = 0.35 + min(0.55, n_links / 60)
        else:
            coord_label = "Tidak ada teks mirip dengan akun lain dalam jendela waktu"
            coord_pts = 0
        c = [
            (f"Frekuensi posting sangat tinggi ({f['ppd']:.1f} post/hari)", _clamp((f['ppd'] - 10) / 15, 0, 2.5)),
            (f"Jeda antarpost nyaris seragam (variasi {f['cv']:.2f})", 2.2 if f['cv'] < 0.3 else 1.0 if f['cv'] < 0.6 else 0),
            (f"Akun baru ({round(f['age'])} hari)", 1.2 if f['age'] < 30 else 0.5 if f['age'] < 90 else 0),
            ('Mengikuti jauh lebih banyak akun daripada pengikutnya', 1.0 if f['fr'] > 5 else 0),
            (f"Teks berulang pada akun sendiri ({round(f['dup'] * 100)}%)", f['dup'] * 2.5),
            (coord_label, coord_pts),
        ]
        breakdown = [{'label': l, 'pts': round(p, 2), 'hit': p > 0} for l, p in c]
        score = sum(r['pts'] for r in breakdown)
        reasons = [r for r in breakdown if r['pts'] >= 0.3]
        risk = 1 / (1 + math.exp(-(score - 2.5)))
        level = 'tinggi' if risk >= 0.7 else 'sedang' if risk >= 0.4 else 'rendah'
        hits = [r for r in breakdown if r['hit']]
        if hits:
            why = "Poin terkumpul: " + "; ".join(f"{r['label']} (+{r['pts']:g})" for r in hits)
            why += f". Total {score:.2f} poin dari ambang 2.50."
            if risk < 0.4:
                why += " Skor tetap rendah karena total poin belum mencapai ambang."
        else:
            why = (f"Tidak ada faktor pemicu yang aktif. Total 0 poin dari ambang 2.50, sehingga skor dasar "
                   f"{round(risk * 100)}%. Ini normal untuk akun dengan sedikit post dan perilaku wajar.")
        if not a['profile_known']:
            why += (" Catatan: umur dan jumlah pengikut akun tidak tersedia dari platform, jadi faktor "
                    "'akun baru' dan 'rasio pengikut' tidak bisa dinilai; skor bisa tampak lebih rendah.")
        out.append({**{k: v for k, v in a.items() if k != 'posts'}, 'risk': round(risk, 3), 'level': level,
                    'cluster': cid.get(i), 'n_posts': len(a['posts']), 'score': round(score, 2),
                    'threshold': 2.5, 'breakdown': breakdown, 'explain': why,
                    'reasons': sorted(reasons, key=lambda r: -r['pts'])})
    return {'accounts': out, 'edges': [(accs[a]['id'], accs[b]['id'], w) for a, b, w in edges],
            'clusters': [[accs[i]['id'] for i in g] for g in clusters],
            'cluster_stats': coord_res.get('cluster_stats') or [], 'coord_stats': coord_res.get('stats') or {},
            '_accs': accs}


def analyze_items(items, win=1440, context=None, cluster_span=360):
    """items = daftar post dari sumber mana pun -> hasil siap tampil di dashboard."""
    by = {}
    for it in items:
        a = by.setdefault(it['id'], {'id': it['id'], 'handle': it['handle'], 'platform': it['platform'], 'ageDays': 365.0,
                                     'followers': 100, 'following': 100, 'profile_known': False, 'posts': []})
        pr = it.get('profile')
        if pr:
            a.update(ageDays=pr['ageDays'], followers=pr['followers'], following=pr['following'], profile_known=True)
        a['posts'].append({'t': it['t'], 'text': it['text'], 'url': it.get('url', ''), 'reply': it.get('reply', False)})
    res = analyze(list(by.values()), max_accounts=400, min_posts=1, min_pairs=1, win=win,
                  cluster_span=cluster_span)
    acc_by = {a['id']: a for a in res['_accs']}
    risk = {a['id']: a for a in res['accounts']}
    cstats = {i: s for i, s in enumerate(res.get('cluster_stats') or [])}
    clusters = []
    for ci, ids in enumerate(res['clusters']):
        samples = []
        for m in ids[:4]:
            p = max(acc_by[m]['posts'], key=lambda x: x['t'])
            samples.append({'who': acc_by[m]['handle'], 'platform': acc_by[m]['platform'], 'text': p['text'], 'url': p['url'], 'reply': p['reply']})
        st = cstats.get(ci) or {}
        clusters.append({'id': ci, 'size': len(ids), 'avg_risk': round(sum(risk[m]['risk'] for m in ids) / len(ids), 2),
                         'members': [acc_by[m]['handle'] for m in ids[:12]], 'samples': samples,
                         'span_min': st.get('span_min'), 'edges': st.get('edges'),
                         'p_value': (res.get('coord_stats') or {}).get('p_value'),
                         'method': (res.get('coord_stats') or {}).get('method', '')})
    accounts = sorted(res['accounts'], key=lambda a: -a['risk'])
    from sentinel.analysis import narrative
    narr = narrative.analyze(items, context)
    content = content_summary(items, len(clusters), context=context, narrative=narr)
    cs = res.get('coord_stats') or {}
    return {'stats': {'posts': len(items), 'accounts': len(accounts), 'clusters': len(clusters),
                      'high': sum(a['level'] == 'tinggi' for a in accounts), 'mid': sum(a['level'] == 'sedang' for a in accounts),
                      'coord_p': cs.get('p_value') if clusters else None,
                      'coord_window_min': cs.get('window_min')},
            'accounts': accounts[:300], 'edges': [{'a': a, 'b': b, 'w': w} for a, b, w in res['edges']],
            'clusters': sorted(clusters, key=lambda c: -c['size']), 'content': content,
            'narrative': narr, 'coordination': cs}
