"""ASR lewat API Whisper kompatibel OpenAI (Groq, OpenAI, dll.), tanpa ffmpeg dan tanpa model lokal.

Alur: yt-dlp mengunduh versi video berkualitas terendah ke /tmp (hanya perlu audionya),
lalu file dikirim apa adanya ke endpoint /audio/transcriptions. Kunci dibaca dari
ASR_API_KEY dan tidak pernah dikirim ke frontend.
"""
import os
import pathlib
import shutil
import tempfile

import httpx

DEFAULT_BASE_URL = 'https://api.groq.com/openai/v1'
DEFAULT_MODEL = 'whisper-large-v3-turbo'
MAX_MB = 24  # batas upload umum API Whisper adalah 25 MB


class ASRError(Exception):
    pass


def _get(cfg, name, default=''):
    v = (cfg or {}).get(name)
    return default if v is None or str(v).strip() == '' else str(v).strip()


def available(cfg=None):
    return bool(_get(cfg, 'ASR_API_KEY')) and _get(cfg, 'ASR_ENABLED', '1').lower() not in ('0', 'false', 'no', 'off')


def model(cfg=None):
    return _get(cfg, 'ASR_MODEL', DEFAULT_MODEL)


def download(url, cfg=None):
    """Unduh media sementara; kembalikan (path, folder_sementara). Panggil cleanup(folder) sesudahnya."""
    try:
        import yt_dlp
    except ImportError:
        raise ASRError('yt-dlp belum terpasang')
    tmp = tempfile.mkdtemp(prefix='sentinel_')
    opts = {'quiet': True, 'no_warnings': True, 'noprogress': True, 'socket_timeout': 15, 'retries': 1,
            'format': 'worst[ext=mp4]/worst', 'max_filesize': MAX_MB * 1024 * 1024,
            'outtmpl': os.path.join(tmp, 'media.%(ext)s')}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
    except Exception as e:
        cleanup(tmp)
        raise ASRError('Media tidak bisa diunduh: ' + str(e).splitlines()[0][:160])
    files = sorted(pathlib.Path(tmp).glob('media.*'))
    if not files:
        cleanup(tmp)
        raise ASRError('Media tidak ditemukan (postingan foto atau melebihi batas ukuran)')
    if files[0].stat().st_size > MAX_MB * 1024 * 1024:
        cleanup(tmp)
        raise ASRError(f'Media lebih dari {MAX_MB} MB')
    return str(files[0]), tmp


def cleanup(folder):
    shutil.rmtree(folder, ignore_errors=True)


def transcribe(path, cfg=None):
    """Kirim file ke API Whisper. Kembalikan {'segments': [{start,end,text}], 'language', 'model'}."""
    if not available(cfg):
        raise ASRError('ASR_API_KEY belum diisi')
    base = _get(cfg, 'ASR_BASE_URL', DEFAULT_BASE_URL).rstrip('/')
    data = {'model': model(cfg), 'response_format': 'verbose_json', 'temperature': '0'}
    lang = _get(cfg, 'ASR_LANGUAGE', 'id')
    if lang:
        data['language'] = lang
    try:
        with open(path, 'rb') as fh:
            r = httpx.post(base + '/audio/transcriptions', headers={'Authorization': 'Bearer ' + _get(cfg, 'ASR_API_KEY')},
                           data=data, files={'file': (pathlib.Path(path).name, fh, 'application/octet-stream')},
                           timeout=45)
    except httpx.HTTPError as e:
        raise ASRError('API ASR tidak bisa dihubungi: ' + e.__class__.__name__)
    if r.status_code != 200:
        raise ASRError(f'API ASR menolak (status {r.status_code}): {r.text[:160]}')
    try:
        d = r.json()
    except ValueError:
        raise ASRError('Respons API ASR tidak dikenali')
    segs = [{'start': float(s.get('start') or 0), 'end': float(s.get('end') or 0), 'text': str(s.get('text') or '').strip()}
            for s in (d.get('segments') or []) if str(s.get('text') or '').strip()]
    if not segs and str(d.get('text') or '').strip():
        segs = [{'start': 0.0, 'end': 0.0, 'text': str(d['text']).strip()}]
    if not segs:
        raise ASRError('Tidak ada ucapan yang terdeteksi')
    return {'segments': segs, 'language': d.get('language') or lang, 'model': model(cfg)}
