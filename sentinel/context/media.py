"""Unduh media sementara untuk ASR/OCR. Tidak menyimpan video setelah diproses."""
import os
import pathlib
import re
import shutil
import subprocess
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[2]
CACHE = ROOT / '.cache' / 'media'


def ffmpeg_exe():
    cand = os.environ.get('FFMPEG_BINARY')
    if cand and pathlib.Path(cand).exists():
        return cand
    cand = shutil.which('ffmpeg')
    if cand:
        return cand
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def ffmpeg_available():
    return bool(ffmpeg_exe())


def _size_mb(path):
    try:
        return round(pathlib.Path(path).stat().st_size / (1024 * 1024), 1)
    except OSError:
        return 0


def _max_sec(cfg):
    try:
        return max(10, int(float(cfg.get('PUBLIC_MAX_MEDIA_SEC') or 600)))
    except (TypeError, ValueError):
        return 600


def _max_mb(cfg):
    try:
        return max(5, int(float(cfg.get('PUBLIC_MAX_MEDIA_MB') or 80)))
    except (TypeError, ValueError):
        return 80


def _direct(url):
    return bool(re.search(r'\.(?:mp4|m4v|webm|mov)(?:\?|$)', url or '', re.I))


def _download_direct(url, dest, max_mb):
    import httpx
    limit = max_mb * 1024 * 1024
    got = 0
    with httpx.stream('GET', url, follow_redirects=True, timeout=60,
                      headers={'user-agent': 'Mozilla/5.0'}) as r:
        r.raise_for_status()
        with open(dest, 'wb') as f:
            for chunk in r.iter_bytes(64 * 1024):
                got += len(chunk)
                if got > limit:
                    raise ValueError('ukuran media melebihi batas')
                f.write(chunk)
    return dest


def acquire(meta, cfg=None, progress=None):
    """Kembalikan {ok, path, note, duration}. Pemanggil wajib cleanup()."""
    cfg = cfg or {}
    meta = meta or {}

    def tick(pct, msg=''):
        if progress:
            try:
                progress(max(0, min(100, int(pct))), msg)
            except Exception:
                pass

    if (meta.get('preview') or {}).get('kind') != 'video' and meta.get('media_kind') != 'video':
        return {'ok': False, 'note': 'Bukan video; ASR/OCR tidak dijalankan.'}
    if not ffmpeg_exe():
        return {'ok': False, 'note': 'ffmpeg tidak ditemukan; ASR/OCR dilewati.'}
    duration = meta.get('duration')
    if duration and float(duration) > _max_sec(cfg):
        return {'ok': False, 'note': f"Durasi {int(float(duration))} detik melebihi batas."}

    CACHE.mkdir(parents=True, exist_ok=True)
    work = pathlib.Path(tempfile.mkdtemp(prefix='sentinel-', dir=str(CACHE)))
    url = meta.get('media_url') or meta.get('url') or ''
    media_url = meta.get('media_url') or ''
    max_mb, max_sec = _max_mb(cfg), _max_sec(cfg)
    try:
        tick(5, 'Mengunduh media')
        if media_url and _direct(media_url):
            dest = work / 'media.mp4'
            _download_direct(media_url, str(dest), max_mb)
            return {'ok': True, 'path': str(dest), 'note': 'Media diunduh langsung.', 'duration': duration,
                    'workdir': str(work)}
        try:
            import yt_dlp
        except ImportError:
            return {'ok': False, 'note': 'yt-dlp belum terpasang; media tidak bisa diunduh.',
                    'workdir': str(work)}
        def hook(d):
            if d.get('status') != 'downloading':
                return
            try:
                p = float(str(d.get('_percent_str') or '0').strip().strip('%'))
            except ValueError:
                p = 0
            tick(8 + int(max(0, min(100, p)) * 0.22), 'Mengunduh media')

        opts = {
            'quiet': True, 'no_warnings': True, 'noplaylist': True,
            'outtmpl': str(work / 'media.%(ext)s'),
            'format': 'best[height<=720]/best',
            'max_filesize': max_mb * 1024 * 1024,
            'retries': 2, 'socket_timeout': 25,
            'progress_hooks': [hook],
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True) or {}
        if info.get('duration') and float(info['duration']) > max_sec:
            return {'ok': False, 'note': 'Durasi media melebihi batas.', 'workdir': str(work)}
        files = [p for p in work.iterdir() if p.is_file() and p.suffix.lower() not in ('.part', '.ytdl')]
        if not files:
            return {'ok': False, 'note': 'Media tidak menghasilkan file.', 'workdir': str(work)}
        path = max(files, key=lambda p: p.stat().st_size)
        return {'ok': True, 'path': str(path), 'note': '', 'duration': info.get('duration') or duration,
                'workdir': str(work)}
    except Exception as e:
        return {'ok': False, 'note': 'Unduh media gagal: ' + e.__class__.__name__, 'workdir': str(work)}


def extract_audio(video, cfg=None):
    ff = ffmpeg_exe()
    if not ff or not video:
        return None
    out = str(pathlib.Path(video).with_suffix('.wav'))
    try:
        subprocess.run([ff, '-y', '-i', str(video), '-vn', '-ac', '1', '-ar', '16000', out],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=240, check=True)
        return out if pathlib.Path(out).exists() else None
    except Exception:
        return None


def extract_frames(video, cfg=None):
    ff = ffmpeg_exe()
    if not ff or not video:
        return []
    cfg = cfg or {}
    try:
        fps = max(0.1, min(2.0, float(cfg.get('OCR_FPS') or 0.5)))
    except (TypeError, ValueError):
        fps = 0.5
    try:
        maxf = max(1, min(200, int(cfg.get('OCR_MAX_FRAMES') or 60)))
    except (TypeError, ValueError):
        maxf = 60
    outdir = pathlib.Path(video).parent / 'frames'
    outdir.mkdir(exist_ok=True)
    try:
        subprocess.run([ff, '-y', '-i', str(video), '-vf', f'fps={fps},scale=1280:-2',
                        '-frames:v', str(maxf), str(outdir / 'frame_%05d.jpg')],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=240, check=True)
    except Exception:
        return []
    return sorted(str(p) for p in outdir.glob('frame_*.jpg'))


def frame_time(path, fps=0.5):
    m = re.search(r'frame_(\d+)', pathlib.Path(path).name)
    return round(((int(m.group(1)) - 1) / fps), 1) if m else None


def cleanup(md):
    try:
        work = (md or {}).get('workdir')
        if work:
            shutil.rmtree(work, ignore_errors=True)
    except Exception:
        pass
