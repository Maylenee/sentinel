"""ASR lokal opsional memakai faster-whisper (CPU, int8)."""
import os
import pathlib
import threading

ROOT = pathlib.Path(__file__).resolve().parents[2]
_LOCK = threading.Lock()
_MODEL = None
_MODEL_NAME = None


def available():
    try:
        import faster_whisper  # noqa: F401
        return True
    except Exception:
        return False


def _model(cfg):
    global _MODEL, _MODEL_NAME
    name = (cfg or {}).get('WHISPER_MODEL') or 'small'
    if _MODEL is not None and _MODEL_NAME == name:
        return _MODEL
    from faster_whisper import WhisperModel
    device = (cfg or {}).get('WHISPER_DEVICE') or 'cpu'
    compute = (cfg or {}).get('WHISPER_COMPUTE') or 'int8'
    root = (cfg or {}).get('WHISPER_DOWNLOAD_ROOT') or str(ROOT / '.cache' / 'whisper')
    pathlib.Path(root).mkdir(parents=True, exist_ok=True)
    _MODEL = WhisperModel(name, device=device, compute_type=compute, download_root=root)
    _MODEL_NAME = name
    return _MODEL


def transcribe(wav, cfg=None):
    cfg = cfg or {}
    if not available():
        return {'ok': False, 'note': 'faster-whisper belum terpasang.', 'segments': []}
    if not wav or not pathlib.Path(wav).exists():
        return {'ok': False, 'note': 'Audio tidak ditemukan.', 'segments': []}
    lang = (cfg.get('WHISPER_LANGUAGE') or 'id').strip()
    lang = None if lang.lower() in ('auto', '') else lang
    try:
        with _LOCK:
            model = _model(cfg)
            segments, info = model.transcribe(
                str(wav), language=lang, vad_filter=True, beam_size=1,
                condition_on_previous_text=False, word_timestamps=False)
            out = []
            for s in segments:
                txt = (s.text or '').strip()
                if txt:
                    out.append({'start': float(s.start or 0), 'end': float(s.end or 0), 'text': txt})
        return {'ok': True, 'segments': out, 'language': getattr(info, 'language', lang or ''),
                'model': _MODEL_NAME, 'note': ''}
    except Exception as e:
        return {'ok': False, 'note': 'ASR gagal: ' + (str(e)[:160] or e.__class__.__name__), 'segments': []}
