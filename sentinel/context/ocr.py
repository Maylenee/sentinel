"""OCR teks layar opsional.

Prioritas: pytesseract + Tesseract bila tersedia; jika tidak, fallback lokal
berbasis RapidOCR (bundled model, tanpa binary eksternal).
"""
import os
import pathlib
import re
import shutil

from sentinel.context.media import frame_time

_RAPID = None


def _cmd():
    cand = os.environ.get('TESSERACT_CMD')
    if cand and pathlib.Path(cand).exists():
        return cand
    return shutil.which('tesseract')


def _tess_ready():
    try:
        import pytesseract  # noqa: F401
        from PIL import Image  # noqa: F401
    except Exception:
        return False
    return bool(_cmd())


def _rapid_ready():
    try:
        import rapidocr  # noqa: F401
        import onnxruntime  # noqa: F401
    except Exception:
        return False
    return True


def _rapid_engine():
    global _RAPID
    if _RAPID is None:
        from rapidocr import RapidOCR
        _RAPID = RapidOCR()
    return _RAPID


def backend():
    if _tess_ready():
        return 'tesseract'
    if _rapid_ready():
        return 'rapidocr'
    return ''


def available():
    return bool(backend())


def _clean(text):
    lines = []
    for line in str(text or '').splitlines():
        line = re.sub(r'\s+', ' ', line).strip()
        if len(line) >= 4 and re.search(r'[A-Za-z0-9]', line):
            lines.append(line)
    return lines


def _tesseract_text(path, lang):
    import pytesseract
    from PIL import Image
    cmd = _cmd()
    pytesseract.pytesseract.tesseract_cmd = cmd
    try:
        return pytesseract.image_to_string(Image.open(path), lang=lang)
    except Exception:
        return pytesseract.image_to_string(Image.open(path), lang='eng')


def _rapid_text(path):
    out = _rapid_engine()(str(path))
    return ' '.join(out.txts or ())


def read_frames(frames, cfg=None):
    cfg = cfg or {}
    mode = backend()
    if not mode:
        return [], 'OCR belum siap (pasang rapidocr atau Tesseract).'
    try:
        fps = max(0.1, min(2.0, float(cfg.get('OCR_FPS') or 0.5)))
    except (TypeError, ValueError):
        fps = 0.5
    lang = cfg.get('OCR_LANG') or 'ind+eng'
    out, seen = [], set()
    for path in frames:
        try:
            txt = _tesseract_text(path, lang) if mode == 'tesseract' else _rapid_text(path)
        except Exception:
            continue
        fresh = []
        for line in _clean(txt):
            key = line.lower()
            if key in seen:
                continue
            seen.add(key)
            fresh.append(line)
        joined = ' '.join(fresh)
        if joined:
            out.append({'t': frame_time(path, fps), 'text': joined[:800]})
    if not out:
        return [], 'OCR aktif, tetapi tidak ada teks layar yang terbaca.'
    return out, ''
