"""Bangun konteks video: caption + transkrip audio + teks layar (OCR).

Ringkasan bersifat ekstraktif: kalimat diambil dari sumber, bukan dibuat ulang
oleh model generatif. Klaim dan indikator persuasi adalah heuristik yang selalu
menyertakan bukti sumber/timestamp agar bisa diperiksa manusia.
"""
import re
from collections import Counter

STOP = set('''yang dan di ke dari untuk dengan ini itu karena juga sudah tidak ada akan pada bisa saya kamu
dia kami kita mereka atau tapi kalau jika saat lebih sangat banget aja saja nya para agar oleh dalam
sebagai menjadi telah masih hanya antara setelah sebelum sudah belum apa siapa mana kapan bagaimana
the and this that for you with are was were have has had not but from they their our your'''.split())

_SENT = re.compile(r'(?<=[.!?])\s+|\n+')
_WORD = re.compile(r'[a-zA-ZÀ-ÿ0-9]+')
_TAG = re.compile(r'#([\w.-]+)')
_MENTION = re.compile(r'@([\w.]+)')
_NUM = re.compile(r'\b\d+(?:[.,]\d+)?%?\b')

CLAIM_CUES = ('harus', 'jangan', 'wajib', 'perlu', 'penting', 'seharusnya', 'akan', 'telah', 'sudah',
              'adalah', 'bukan', 'tidak', 'mereka', 'kita', 'karena', 'akibat', 'menurut', 'data',
              'laporan', 'penelitian', 'studi', 'fakta', 'bukti', 'katanya', 'bahaya', 'aman',
              'untung', 'rugi', 'naik', 'turun', 'dilarang', 'dilarang', 'mendukung', 'menolak')
QUESTION_CUES = ('?', 'apakah', 'kenapa', 'mengapa', 'bagaimana', 'siapa', 'kapan', 'benarkah')
CALL_CUES = ('ayo', 'mari', 'dukung', 'tolak', 'sebarkan', 'bagikan', 'tuntut', 'pilih', 'jangan',
             'harus', 'wajib', 'serukan')
FACT_CUES = ('menurut', 'data', 'laporan', 'penelitian', 'studi', 'persen', '%', 'tahun', 'juta',
             'miliar', 'ribu', 'tanggal', 'fakta', 'bukti')

FLAG_WORDS = {
    'emosional': ('marah', 'benci', 'takut', 'cemas', 'sedih', 'bangga', 'kecewa', 'geram', 'muak',
                  'hancur', 'kacau', 'parah', 'biadab', 'gila'),
    'urgensi': ('sekarang', 'segera', 'hari ini', 'mendesak', 'darurat', 'buruan', 'jangan sampai',
                'sebelum terlambat', 'saat ini'),
    'absolut': ('semua', 'selalu', 'tidak pernah', 'pasti', 'seluruh', 'satu-satunya', 'semuanya',
                'tidak ada satu pun'),
    'kambing_hitam': ('mereka', 'asing', 'antek', 'pengkhianat', 'komunis', 'penjajah', 'kafir',
                      'provokator', 'buzzer', 'cina', 'asing'),
    'seruan_aksi': ('ayo', 'mari', 'dukung', 'tolak', 'sebarkan', 'bagikan', 'tuntut', 'pilih',
                    'serukan', 'gabung'),
    'sumber': ('menurut', 'data', 'laporan', 'penelitian', 'studi', 'sumber', 'rilis', 'kementerian'),
}

PRONOUNS = {'saya', 'aku', 'kamu', 'dia', 'kami', 'kita', 'mereka', 'gue', 'lo', 'anda'}


def _tokens(text):
    return [w.lower() for w in _WORD.findall(str(text or ''))]


def _content_tokens(text):
    return [w for w in _tokens(text) if len(w) >= 3 and w not in STOP]


def _clean(text):
    return re.sub(r'\s+', ' ', str(text or '')).strip()


def sentences(text):
    out = []
    for part in _SENT.split(str(text or '')):
        part = _clean(part)
        if len(part) >= 12:
            out.append(part)
    return out


def top_terms(texts, n=10):
    c = Counter(w for t in texts for w in _content_tokens(t))
    return [{'term': w, 'count': k} for w, k in c.most_common(n)]


def summarize(texts, max_sentences=4, weights=None):
    """Ringkasan ekstraktif berbasis frekuensi kata + posisi kalimat."""
    ss = []
    for i, text in enumerate(texts):
        for j, s in enumerate(sentences(text)):
            ss.append((i, j, s))
    if not ss:
        return ''
    freq = Counter()
    for i, _j, s in ss:
        w = weights[i] if weights and i < len(weights) else 1.0
        for word in _content_tokens(s):
            freq[word] += w
    if not freq:
        return ss[0][2][:1200]
    mx = max(freq.values())
    scored = []
    for i, j, s in ss:
        words = _content_tokens(s)
        if not words:
            continue
        base = sum(freq[w] / mx for w in words) / (len(words) ** 0.5)
        pos = 0.18 if i == 0 and j == 0 else 0.08 if j <= 1 else 0
        scored.append((base + pos, i, j, s))
    scored.sort(key=lambda x: -x[0])
    picked = []
    seen = set()
    for _score, i, j, s in scored:
        key = ' '.join(_content_tokens(s)[:8])
        if key in seen:
            continue
        seen.add(key)
        picked.append((i, j, s))
        if len(picked) >= max_sentences:
            break
    picked.sort(key=lambda x: (x[0], x[1]))
    return ' '.join(x[2] for x in picked)[:1600]


def entities(text):
    tags = sorted(set(_TAG.findall(text or '')))
    mentions = sorted(set(_MENTION.findall(text or '')))
    numbers = sorted(set(_NUM.findall(text or '')))
    caps = []
    for m in re.finditer(r'\b(?:[A-Z][\w.-]+)(?:\s+[A-Z][\w.-]+){1,3}\b', text or ''):
        val = _clean(m.group(0))
        if val.lower() not in PRONOUNS and len(val) > 3:
            caps.append(val)
    return {'hashtags': tags[:20], 'mentions': mentions[:20], 'numbers': numbers[:20],
            'names': sorted(set(caps))[:20]}


def extract_claims(text, source='caption', max_claims=8):
    out = []
    for s in sentences(text):
        low = s.lower()
        if not any(c in low for c in CLAIM_CUES) and not _NUM.search(s):
            continue
        if len(s) < 18:
            continue
        if '?' in s or any(c in low for c in QUESTION_CUES):
            kind = 'pertanyaan'
        elif any(c in low for c in CALL_CUES):
            kind = 'seruan'
        elif any(c in low for c in FACT_CUES) or _NUM.search(s):
            kind = 'fakta'
        else:
            kind = 'opini'
        verifiable = kind == 'fakta' and bool(_NUM.search(s) or entities(s)['names'])
        out.append({'text': s[:420], 'kind': kind, 'verifiable': verifiable,
                    'source': source, 'cue': next((c for c in CLAIM_CUES if c in low), '')})
        if len(out) >= max_claims:
            break
    return out


def flags(text):
    low = ' ' + _clean(text).lower() + ' '
    out = []
    for name, words in FLAG_WORDS.items():
        hits = [w for w in words if w in low]
        if hits:
            out.append({'name': name, 'hits': sorted(set(hits))[:8], 'count': len(hits)})
    return out


def _on(v, default=True):
    if v is None:
        return default
    return str(v).strip().lower() not in ('0', 'false', 'no', 'off', '')


def build_context(meta, cfg=None, progress=None, use_media=True):
    """Bangun konteks dari metadata + media (bila tersedia). Aman tanpa ffmpeg/ASR/OCR."""
    cfg = cfg or {}
    meta = meta or {}

    def tick(pct, msg=''):
        if progress:
            try:
                progress(max(0, min(100, int(pct))), msg)
            except Exception:
                pass

    caption = _clean(meta.get('caption') or meta.get('text') or '')
    preview = meta.get('preview') or {}
    kind = preview.get('kind') or meta.get('media_kind') or 'video'
    duration = meta.get('duration')
    notes = []
    transcript = []
    ocr_lines = []
    media_state = {'downloaded': False, 'asr': False, 'ocr': False, 'note': ''}

    tick(5, 'Menyiapkan konteks')
    if not caption:
        notes.append('Caption tidak tersedia.')

    md = None
    asr_on = _on(cfg.get('PUBLIC_ASR', '1'))
    ocr_on = _on(cfg.get('PUBLIC_OCR', '1'))
    if use_media and kind == 'video' and (asr_on or ocr_on):
        try:
            from sentinel.context import media as media_mod
            md = media_mod.acquire(meta, cfg, progress=lambda p, m='': tick(8 + int(p * 0.25), m))
            media_state.update({'downloaded': bool(md.get('ok')), 'note': md.get('note', '')})
            if md.get('ok'):
                if asr_on:
                    tick(36, 'Mengekstrak audio')
                    wav = media_mod.extract_audio(md['path'])
                    if wav:
                        from sentinel.context import transcribe as asr
                        if asr.available():
                            tick(42, 'Menjalankan ASR lokal')
                            tr = asr.transcribe(wav, cfg)
                            if tr.get('ok'):
                                transcript = tr.get('segments') or []
                                media_state['asr'] = bool(transcript)
                                media_state['asr_language'] = tr.get('language', '')
                                media_state['asr_model'] = tr.get('model', '')
                            else:
                                notes.append(tr.get('note') or 'ASR gagal.')
                        else:
                            notes.append('ASR lokal belum terpasang (pip install faster-whisper).')
                    else:
                        notes.append('Audio tidak bisa diekstrak; ffmpeg belum tersedia.')
                if ocr_on:
                    from sentinel.context import ocr as ocr_mod
                    if ocr_mod.available():
                        tick(68, 'Membaca teks layar (OCR)')
                        frames = media_mod.extract_frames(md['path'], cfg)
                        if frames:
                            lines, onote = ocr_mod.read_frames(frames)
                            ocr_lines = lines
                            media_state['ocr'] = bool(lines)
                            if onote:
                                notes.append(onote)
                        else:
                            notes.append('Frame video tidak bisa diekstrak untuk OCR.')
                    else:
                        notes.append('OCR belum siap (pasang rapidocr atau Tesseract).')
            else:
                notes.append(md.get('note') or 'Media tidak bisa diunduh.')
        except Exception as e:
            notes.append('Konteks media gagal: ' + e.__class__.__name__)
        finally:
            if md:
                try:
                    from sentinel.context import media as media_mod
                    media_mod.cleanup(md)
                except Exception:
                    pass

    tick(82, 'Menyusun ringkasan')
    transcript_text = ' '.join(seg.get('text', '') for seg in transcript)
    ocr_text = ' '.join(line.get('text', '') for line in ocr_lines)
    full = ' '.join(x for x in (caption, transcript_text, ocr_text) if x)
    # Transkrip lebih bersih daripada teks layar untuk ringkasan; OCR tetap
    # tersedia sebagai bukti dan dipakai bila ASR tidak menghasilkan transkrip.
    summary_sources = [caption, transcript_text]
    if not transcript_text:
        summary_sources.append(ocr_text)
    summary = summarize(summary_sources) if full else ''
    if not summary and caption:
        summary = caption[:1200]
    if not summary:
        summary = 'Tidak ada teks yang bisa disimpulkan dari postingan ini.'

    claims = []
    for source, txt in (('caption', caption), ('transcript', transcript_text), ('ocr', ocr_text)):
        for c in extract_claims(txt, source=source):
            key = ' '.join(_content_tokens(c['text'])[:10])
            if key and all(' '.join(_content_tokens(x['text'])[:10]) != key for x in claims):
                claims.append(c)
    claims = claims[:10]

    conf = 0.30 if caption else 0.10
    if transcript:
        conf = 0.72
    if ocr_lines:
        conf += 0.10
    if transcript and ocr_lines:
        conf = 0.88
    conf = min(0.95, conf)

    if duration and duration > 600:
        notes.append('Durasi video lebih dari 10 menit; transkripsi/OCR dibatasi.')
    if not media_state['downloaded'] and kind == 'video' and use_media:
        notes.append('Konteks audiovisual tidak tersedia; ringkasan hanya dari caption.')

    data_note = ' '.join(dict.fromkeys(notes))
    tick(100, 'Konteks selesai')
    return {
        'summary': summary,
        'claims': claims,
        'entities': entities(full),
        'keywords': top_terms([caption, transcript_text, ocr_text]),
        'flags': flags(full),
        'confidence': round(conf, 2),
        'caption': caption[:4000],
        'posted_at': meta.get('posted_at'),
        'duration': duration,
        'stats': meta.get('stats') or {},
        'video': {
            'kind': kind,
            'transcript': bool(transcript),
            'ocr': bool(ocr_lines),
            'asr_model': media_state.get('asr_model', ''),
            'asr_language': media_state.get('asr_language', ''),
            'media_note': media_state.get('note', ''),
        },
        'evidence': {
            'caption': caption[:4000],
            'transcript': [{'start': round(float(s.get('start') or 0), 1),
                            'end': round(float(s.get('end') or 0), 1),
                            'text': s.get('text', '')[:600]} for s in transcript[:400]],
            'ocr': [{'t': x.get('t'), 'text': x.get('text', '')[:400]} for x in ocr_lines[:120]],
        },
        'data_notes': data_note,
    }
