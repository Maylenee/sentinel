"""Analisis lanjutan memakai LLM: indikasi buzzer/bot per akun.

LLM tidak menggantikan mesin heuristik. Ia membaca sinyal yang sudah dihitung
(clique, risiko, duplikasi, contoh komentar) lalu memberi penilaian probabilistik
yang tetap harus ditinjau manusia. Tidak ada tuduhan identitas nyata.
"""
import json
from datetime import datetime, timezone

from sentinel.llm import makers

LABELS = ('buzzer', 'bot', 'organic', 'tidak_jelas')

_ALIASES = {
    'buzzer': 'buzzer',
    'buz': 'buzzer',
    'buzzer_bayaran': 'buzzer',
    'koordinator': 'buzzer',
    'bot': 'bot',
    'robot': 'bot',
    'otomasi': 'bot',
    'automated': 'bot',
    'organic': 'organic',
    'organik': 'organic',
    'wajar': 'organic',
    'normal': 'organic',
    'tidak_jelas': 'tidak_jelas',
    'tidak jelas': 'tidak_jelas',
    'unknown': 'tidak_jelas',
    'uncertain': 'tidak_jelas',
}

SYSTEM = """Anda analis OSINT untuk deteksi perilaku tidak autentik di media sosial.
Tugas Anda: menilai SETIAP akun pada data yang diberikan, apakah indikasinya
lebih dekat ke "buzzer", "bot", "organic", atau "tidak_jelas".

Definisi:
- buzzer: pola amplifikasi narasi secara terkoordinasi, teks sangat mirip dengan
  akun lain dalam waktu berdekatan, agenda berulang, atau anggota clique.
- bot: indikasi otomasi seperti volume posting ekstrem, jeda antarpost nyaris
  seragam, teks template/berulang, atau perilaku terlalu konsisten.
- organic: perilaku wajar, tidak ada sinyal koordinasi/otomasi yang menonjol.
- tidak_jelas: data terlalu sedikit atau sinyal saling bertentangan.

Aturan:
1. Gunakan HANYA bukti pada data. Jangan mengarang kutipan, metrik, atau identitas.
2. Ini penilaian probabilistik, bukan tuduhan. Jangan mengklaim siapa orangnya.
3. Teks mirip bisa berasal dari kutipan viral yang wajar; pertimbangkan waktu,
   clique, dan konteks sebelum menyebut buzzer/bot.
4. Sertakan tepat satu entri untuk setiap id akun yang diberikan. Jangan membuat id baru.
5. Balas HANYA dengan JSON valid, tanpa markdown atau teks lain.

Skema JSON:
{
  "summary": "ringkasan 2-4 kalimat dalam bahasa Indonesia",
  "overall_label": "buzzer|bot|organic|tidak_jelas",
  "overall_confidence": 0.0,
  "accounts": [
    {
      "id": "id akun persis dari input",
      "label": "buzzer|bot|organic|tidak_jelas",
      "confidence": 0.0,
      "reasons": ["alasan singkat berbasis sinyal"],
      "evidence": ["kutipan pendek dari contoh komentar, bila ada"]
    }
  ],
  "caveats": ["batasan atau hal yang perlu diverifikasi manusia"]
}"""


def _int(cfg, name, default, lo, hi):
    try:
        return max(lo, min(hi, int(float((cfg or {}).get(name) or default))))
    except (TypeError, ValueError):
        return default


def _samples(items, cfg=None):
    cfg = cfg or {}
    limit = _int(cfg, 'LLM_MAX_SAMPLES', 3, 1, 8)
    out = {}
    for it in items or []:
        if it.get('kind') == 'post':
            continue
        text = str(it.get('text') or '').strip()
        if not text:
            continue
        row = out.setdefault(it.get('id'), [])
        if len(row) < limit:
            row.append(text[:280])
    return out


def build_payload(items, analysis, context=None, cfg=None):
    """Susun data ringkas yang dikirim ke LLM (tanpa handle ganda berlebihan)."""
    cfg = cfg or {}
    analysis = analysis or {}
    context = context or {}
    max_accounts = _int(cfg, 'LLM_MAX_ACCOUNTS', 30, 1, 100)
    sample_map = _samples(items, cfg)
    accounts = []
    for a in (analysis.get('accounts') or [])[:max_accounts]:
        signals = [r.get('label') for r in (a.get('breakdown') or []) if r.get('hit')]
        accounts.append({
            'id': a.get('id'),
            'handle': a.get('handle'),
            'platform': a.get('platform'),
            'risk': a.get('risk'),
            'level': a.get('level'),
            'score': a.get('score'),
            'n_posts': a.get('n_posts'),
            'cluster': a.get('cluster'),
            'signals': signals[:8],
            'samples': sample_map.get(a.get('id'), [])[:8],
        })
    clusters = []
    for c in (analysis.get('clusters') or [])[:10]:
        clusters.append({
            'size': c.get('size'),
            'span_min': c.get('span_min'),
            'edges': c.get('edges'),
            'p_value': c.get('p_value'),
            'members': (c.get('members') or [])[:12],
        })
    return {
        'post': {
            'platform': (analysis.get('post') or {}).get('platform'),
            'author': (analysis.get('post') or {}).get('author'),
            'summary': context.get('summary', '')[:1200],
            'claims': [c.get('text', '')[:300] for c in (context.get('claims') or [])[:6]],
        },
        'stats': analysis.get('stats') or {},
        'coordination': analysis.get('coordination') or {},
        'clusters': clusters,
        'accounts': accounts,
    }


def _label(value):
    s = str(value or '').strip().lower().replace('-', '_')
    s = ' '.join(s.split())
    return _ALIASES.get(s) or _ALIASES.get(s.replace(' ', '_')) or 'tidak_jelas'


def _conf(value):
    try:
        return round(max(0.0, min(1.0, float(value))), 2)
    except (TypeError, ValueError):
        return 0.0


def _lines(value, limit=4, maxlen=260):
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    out = []
    for x in value:
        s = str(x or '').strip()
        if s:
            out.append(s[:maxlen])
        if len(out) >= limit:
            break
    return out


def _normalize(data, payload):
    if not isinstance(data, dict):
        raise makers.LLMError('Jawaban LLM bukan objek JSON.')
    allowed, by_handle = {}, {}
    for a in payload.get('accounts') or []:
        if a.get('id'):
            allowed[str(a['id'])] = a
        if a.get('handle'):
            by_handle[str(a['handle']).lower()] = str(a.get('id'))
    out, seen = [], set()
    for row in data.get('accounts') or []:
        if not isinstance(row, dict):
            continue
        uid = str(row.get('id') or '')
        if uid not in allowed:
            uid = by_handle.get(str(row.get('handle') or '').lower(), '')
        if uid not in allowed or uid in seen:
            continue
        seen.add(uid)
        out.append({
            'id': uid,
            'handle': allowed[uid].get('handle') or uid,
            'label': _label(row.get('label')),
            'confidence': _conf(row.get('confidence')),
            'reasons': _lines(row.get('reasons'), 4),
            'evidence': _lines(row.get('evidence'), 3),
        })
    return {
        'summary': str(data.get('summary') or '').strip()[:1600],
        'overall_label': _label(data.get('overall_label')),
        'overall_confidence': _conf(data.get('overall_confidence')),
        'accounts': out,
        'caveats': _lines(data.get('caveats'), 6, 320),
        'missing': [i for i in allowed if i not in seen][:10],
    }


def analyze(items, analysis, context=None, cfg=None):
    """Kembalikan penilaian LLM; tidak pernah melempar exception ke pemanggil."""
    cfg = cfg or {}
    if not makers.available(cfg):
        note = ('LLM belum aktif. Isi MAKERS_MODELS_KEY di .env dan set LLM_ENABLED=1.'
                if makers.enabled(cfg) else 'LLM dinonaktifkan (LLM_ENABLED=0).')
        return {'available': False, 'enabled': makers.enabled(cfg), 'provider': 'edgeone-makers',
                'model': makers.model(cfg), 'note': note}
    payload = build_payload(items, analysis, context, cfg)
    if not payload.get('accounts'):
        return {'available': True, 'provider': 'edgeone-makers', 'model': makers.model(cfg),
                'note': 'Tidak ada akun untuk dinilai LLM.', 'accounts': []}
    messages = [
        {'role': 'system', 'content': SYSTEM},
        {'role': 'user', 'content': 'Data untuk dianalisis:\n' + json.dumps(payload, ensure_ascii=False)},
    ]
    try:
        raw = makers.chat(messages, cfg=cfg, temperature=0.2)
        data = makers.extract_json(raw)
        out = _normalize(data, payload)
        out.update({
            'available': True,
            'provider': 'edgeone-makers',
            'model': makers.model(cfg),
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'note': 'Penilaian LLM bersifat probabilistik; bukan bukti pembayaran atau niat.',
        })
        return out
    except Exception as e:
        return {'available': True, 'provider': 'edgeone-makers', 'model': makers.model(cfg),
                'error': str(e)[:300], 'accounts': [],
                'note': 'Analisis LLM gagal; hasil heuristik tetap dapat digunakan.'}
