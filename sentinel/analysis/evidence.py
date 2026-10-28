"""Dossier bukti: provenance, konteks, sinyal, dan batasan."""
from datetime import datetime, timezone


def build(url, meta, context, analysis):
    meta = meta or {}
    context = context or {}
    analysis = analysis or {}
    content = analysis.get('content') or {}
    coord = analysis.get('coordination') or {}
    clusters = analysis.get('clusters') or []
    return {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'input': {'url': url},
        'post': {
            'platform': meta.get('platform'),
            'author': meta.get('author'),
            'posted_at': meta.get('posted_at'),
            'duration_sec': meta.get('duration'),
            'stats': meta.get('stats') or {},
            'note': meta.get('note') or '',
        },
        'context': {
            'summary': context.get('summary', ''),
            'claims': context.get('claims') or [],
            'confidence': context.get('confidence', 0),
            'video': context.get('video') or {},
            'data_notes': context.get('data_notes', ''),
            'evidence': context.get('evidence') or {},
            'flags': context.get('flags') or [],
        },
        'comment_signals': {
            'total_comments': content.get('text_comments', 0),
            'unique_commenters': content.get('unique_commenters', 0),
            'duplicate_pct': content.get('duplicate_pct', 0),
            'time_span_hours': content.get('time_span_hours', 0),
            'stance': content.get('stance') or {},
            'claim_amplification': content.get('claim_amplification') or [],
            'coordination': coord,
            'clusters': clusters,
            'limitations': [
                'Komentar diambil dari sampel yang tersedia (maksimal sesuai PUBLIC_MAX_COMMENTS).',
                'Label sikap memakai leksikon; sarkasme dan konteks rumit bisa salah.',
                'ASR/OCR bisa salah; ringkasan bersifat ekstraktif dari teks yang terbaca.',
                'Tidak ada bukti pembayaran/intent dari data publik; ini indikasi untuk ditinjau manusia.',
            ],
        },
    }
