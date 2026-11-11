"""Pemetaan komentar ke konteks video: sikap dan klaim yang diamplifikasi.

Ini heuristik leksikal, bukan model terlatih. Setiap label menyertakan
keyakinan dan contoh agar analis bisa memeriksa, terutama untuk sarkasme.
"""
import re
from collections import Counter

SUP = set('''setuju sepakat dukung mendukung benar bagus baik mantap keren suka senang hebat tepat
bangga terima kasih membantu bermanfaat positif maju adil aman sehat berhasil percaya kagum
salut apresiasi'''.split())
OPP = set('''tolak menolak tidak salah bohong benci marah kecewa gagal korup penipu provokasi hina
rusak parah curiga negatif bahaya ancam anarkis kacau menolak tidak_setuju keliru dusta'''.split())
NEG = set('tidak bukan belum jangan nggak ga gak tak enggak'.split())
Q = set('apakah kenapa mengapa bagaimana siapa kapan benarkah serius'.split())
STOP = set('''yang dan di ke dari untuk dengan ini itu karena juga sudah tidak ada akan pada bisa saya kamu
dia kami kita mereka atau tapi kalau jika saat lebih sangat banget aja saja nya para agar oleh dalam
sebagai menjadi telah masih hanya antara setelah sebelum belum apa siapa mana kapan bagaimana'''.split())
_WORD = re.compile(r'[a-zA-ZÀ-ÿ0-9]+')


def tokens(text):
    return [w.lower() for w in _WORD.findall(str(text or ''))]


def content(text):
    return [w for w in tokens(text) if len(w) >= 4 and w not in STOP]


def stance(text):
    w = tokens(text)
    low = ' ' + ' '.join(w) + ' '
    sup = opp = 0
    for i, word in enumerate(w):
        neg = i > 0 and w[i - 1] in NEG
        if word in SUP:
            if neg:
                opp += 1
            else:
                sup += 1
        elif word in OPP:
            if neg:
                sup += 1
            else:
                opp += 1
    for a, b in (('tidak', 'setuju'), ('tidak', 'mendukung'), ('tidak', 'percaya'),
                 ('bukan', 'solusi'), ('jangan', 'dukung')):
        if f' {a} {b} ' in low:
            opp += 2
            sup = max(0, sup - 1)
    is_q = '?' in str(text) or any(x in w for x in Q)
    if is_q and not any(x in low for x in (' tidak setuju ', ' tidak mendukung ', ' menolak ')):
        return {'label': 'tanya', 'support': 0, 'oppose': 0, 'confidence': 0.3}
    if sup == 0 and opp == 0:
        return {'label': 'netral', 'support': 0, 'oppose': 0, 'confidence': 0.25}
    if sup and opp:
        label = 'campur'
    elif sup:
        label = 'dukung'
    else:
        label = 'tolak'
    conf = min(0.9, 0.35 + 0.12 * (sup + opp))
    if label == 'campur':
        conf = min(conf, 0.5)
    return {'label': label, 'support': sup, 'oppose': opp, 'confidence': round(conf, 2)}


def claim_keywords(claim):
    return content(claim)[:12]


def map_claim(text, claims):
    """Kembalikan indeks klaim yang paling cocok, atau None."""
    if not claims:
        return None
    cw = set(content(text))
    if not cw:
        return None
    best, score = None, 0.0
    for i, c in enumerate(claims):
        kws = set(claim_keywords(c.get('text', '')))
        if not kws:
            continue
        overlap = len(cw & kws) / min(len(cw), max(3, min(len(kws), 8)))
        if overlap > score:
            best, score = i, overlap
    return best if score >= 0.22 else None


def analyze(items, context=None):
    comments = [it for it in items if it.get('kind') != 'post' and (it.get('text') or '').strip()]
    claims = (context or {}).get('claims') or []
    labels = Counter()
    per_claim = [{'comments': 0, 'unique': set(), 'samples': []} for _ in claims]
    confs, mapped = [], 0
    for c in comments:
        st = stance(c['text'])
        labels[st['label']] += 1
        confs.append(st['confidence'])
        ci = map_claim(c['text'], claims)
        if ci is not None:
            mapped += 1
            row = per_claim[ci]
            row['comments'] += 1
            row['unique'].add(c.get('handle') or c.get('id'))
            if len(row['samples']) < 3:
                row['samples'].append({'handle': c.get('handle') or c.get('id'),
                                       'text': (c.get('text') or '')[:280], 'url': c.get('url') or ''})
    total = len(comments)
    amplification = []
    for i, c in enumerate(claims):
        row = per_claim[i]
        amplification.append({
            'claim': c.get('text', '')[:420],
            'kind': c.get('kind', ''),
            'source': c.get('source', ''),
            'comments': row['comments'],
            'unique_commenters': len(row['unique']),
            'share_pct': round(100 * row['comments'] / total, 1) if total else 0,
            'samples': row['samples'],
        })
    amplification.sort(key=lambda x: -x['comments'])
    sup, opp = labels.get('dukung', 0), labels.get('tolak', 0)
    polar = round(100 * max(sup, opp) / (sup + opp), 1) if (sup + opp) else 0
    dominant = 'dukung' if sup > opp else 'tolak' if opp > sup else 'seimbang'
    return {
        'total': total,
        'labels': {'dukung': sup, 'tolak': opp, 'tanya': labels.get('tanya', 0),
                   'netral': labels.get('netral', 0), 'campur': labels.get('campur', 0)},
        'dominant': dominant,
        'polarization_pct': polar,
        'mapped_comments': mapped,
        'claim_amplification': amplification,
        'confidence': round(sum(confs) / len(confs), 2) if confs else 0.0,
        'note': 'Label sikap memakai leksikon; sarkasme dan konteks rumit bisa salah. Periksa contoh.',
    }
