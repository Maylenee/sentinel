"""SENTINEL (Python): dashboard analisis postingan publik Facebook/Instagram/TikTok.

Alur: POST /api/context (job konteks video) -> GET /api/job/{id} -> POST /api/analyze.
Modul inti berada di paket `sentinel/`; jalankan dengan `python app.py`.
"""
import asyncio
import hashlib
import json
import os
import pathlib
import secrets
import threading
import time
import webbrowser
from typing import Optional

ROOT = pathlib.Path(__file__).parent


def _load_env():
    try:
        for line in (ROOT / '.env').read_text(encoding='utf-8').splitlines():
            k, sep, v = line.partition('=')
            k = k.strip()
            if sep and k and not k.startswith('#') and k not in os.environ:
                os.environ[k] = v.strip().strip('"\'')
    except FileNotFoundError:
        pass


_load_env()

try:
    import uvicorn
    from fastapi import FastAPI, HTTPException, Request
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import FileResponse, JSONResponse
    from pydantic import BaseModel
except ImportError:
    raise SystemExit('Pustaka belum terpasang. Jalankan dulu:  pip install -r requirements.txt')

from sentinel.analysis import engine, evidence
from sentinel.context import builder as context_mod
from sentinel.context import media as media_mod
from sentinel.context import ocr as ocr_mod
from sentinel.context import transcribe as asr_mod
from sentinel.llm import advanced as llm_mod
from sentinel.llm import makers as llm_client
from sentinel.sources import public as sources_public

app = FastAPI(title='SENTINEL')

_FRONTEND = ROOT.parent / 'frontend' / 'index.html'
_API_TOKEN = os.environ.get('SENTINEL_API_TOKEN', '').strip()
_cors_origins = [x.strip() for x in os.environ.get('CORS_ORIGINS', '').split(',') if x.strip()]
_cors_regex = os.environ.get('CORS_ORIGIN_REGEX', '').strip() or None

if _cors_origins or _cors_regex:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_origin_regex=_cors_regex,
        allow_methods=['*'],
        allow_headers=['*'],
        allow_credentials=False,
    )


@app.middleware('http')
async def _api_guard(request: Request, call_next):
    path = request.url.path
    if _API_TOKEN and path.startswith('/api/') and path != '/api/health' and request.method != 'OPTIONS':
        auth = request.headers.get('authorization', '')
        if not secrets.compare_digest(auth, f'Bearer {_API_TOKEN}'):
            return JSONResponse({'detail': 'Unauthorized'}, status_code=401)
    return await call_next(request)


JOBS = {}
TASKS = set()
_JOB_TTL = 2 * 60 * 60
_LOCK = threading.Lock()
_CACHE = ROOT / '.cache' / 'context'


class PostReq(BaseModel):
    url: str


class ContextReq(BaseModel):
    url: str
    media: bool = True


class AnalyzeReq(BaseModel):
    job_id: str
    context: Optional[dict] = None
    win: int = 1440
    cluster_span: int = 360


def _job(job_id, **kw):
    with _LOCK:
        j = JOBS.setdefault(job_id, {'id': job_id, 'created_at': time.time()})
        j.update(kw)
        j['updated_at'] = time.time()

def _cleanup_jobs():
    now = time.time()
    with _LOCK:
        for k in [k for k, v in JOBS.items() if v.get('status') in ('done', 'error')
                  and now - v.get('updated_at', now) > _JOB_TTL]:
            JOBS.pop(k, None)


def _cache_key(url, media):
    return hashlib.sha256((str(url) + '|' + ('media' if media else 'caption') + '|v6').encode()).hexdigest()


def _cache_read(url, media):
    try:
        p = _CACHE / (_cache_key(url, media) + '.json')
        if p.exists() and time.time() - p.stat().st_mtime < 7 * 86400:
            return json.loads(p.read_text(encoding='utf-8'))
    except Exception:
        pass
    return None


def _cache_write(url, media, data):
    try:
        _CACHE.mkdir(parents=True, exist_ok=True)
        p = _CACHE / (_cache_key(url, media) + '.json')
        p.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    except Exception:
        pass


async def _llm_review(items, result, context):
    """Jalankan analisis LLM tanpa menggagalkan analisis heuristik."""
    cfg = dict(os.environ)
    try:
        timeout = max(5.0, float(cfg.get('LLM_TOTAL_TIMEOUT') or 90))
    except (TypeError, ValueError):
        timeout = 90.0
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(llm_mod.analyze, items, result, context, cfg), timeout=timeout)
    except asyncio.TimeoutError:
        return {'available': True, 'provider': 'edgeone-makers', 'model': llm_client.model(cfg),
                'error': 'timeout', 'accounts': [],
                'note': 'Analisis LLM melebihi batas waktu; hasil heuristik tetap dapat digunakan.'}
    except Exception as e:
        return {'available': True, 'provider': 'edgeone-makers', 'model': llm_client.model(cfg),
                'error': e.__class__.__name__, 'accounts': [],
                'note': 'Analisis LLM gagal; hasil heuristik tetap dapat digunakan.'}


async def _context_task(job_id, url, use_media):
    try:
        _job(job_id, status='fetching', progress=3, message='Mengambil postingan dan komentar')
        cfg = dict(os.environ)
        meta, items = await sources_public.fetch_public_post(url, cfg)
        _job(job_id, progress=30, message=f'{len(items)} item ditemukan', post=meta, items_count=len(items))
        cached = _cache_read(url, use_media)
        if cached:
            ctx = cached
            _job(job_id, cached=True, message='Konteks dari cache')
        else:
            def prog(p, m=''):
                _job(job_id, progress=30 + int(max(0, min(100, p)) * 0.65), message=m or 'Menyusun konteks')
            ctx = await asyncio.to_thread(context_mod.build_context, meta, cfg, prog, use_media)
            bad = use_media and ('ASR gagal' in (ctx.get('data_notes') or '')
                                 or 'ASR lokal belum terpasang' in (ctx.get('data_notes') or ''))
            if not bad:
                _cache_write(url, use_media, ctx)
            _job(job_id, cached=False)
        _job(job_id, status='done', progress=100, message='Konteks siap', context=ctx,
             post=meta, items=items, context_media=use_media)
    except sources_public.SourceError as e:
        _job(job_id, status='error', progress=100, error=str(e))
    except Exception as e:
        _job(job_id, status='error', progress=100, error='Gagal membangun konteks: ' + e.__class__.__name__)


@app.get('/')
def index():
    if _FRONTEND.exists():
        return FileResponse(_FRONTEND)
    return {'ok': True, 'service': 'SENTINEL API', 'health': '/api/health'}


@app.get('/api/health')
def health():
    try:
        ff = media_mod.ffmpeg_available()
    except Exception:
        ff = False
    return {'ok': True, 'public_sources': sources_public.available(),
            'context': {'asr': asr_mod.available(), 'ocr': ocr_mod.available(), 'ffmpeg': ff},
            'llm': {'enabled': llm_client.enabled(os.environ), 'available': llm_client.available(os.environ),
                    'provider': 'edgeone-makers', 'model': llm_client.model(os.environ),
                    'max_tokens': llm_client.max_tokens(os.environ),
                    'thinking_disabled': llm_client.thinking_disabled(os.environ)}}


@app.post('/api/context')
async def make_context(req: ContextReq):
    _cleanup_jobs()
    url = (req.url or '').strip()
    if not sources_public.detect(url):
        raise HTTPException(400, 'URL harus tautan publik TikTok, Instagram, atau Facebook')
    job_id = secrets.token_hex(8)
    _job(job_id, status='queued', progress=0, message='Menunggu', url=url)
    task = asyncio.create_task(_context_task(job_id, url, bool(req.media)))
    TASKS.add(task)
    task.add_done_callback(TASKS.discard)
    return {'job_id': job_id}


@app.get('/api/job/{job_id}')
def get_job(job_id: str):
    _cleanup_jobs()
    with _LOCK:
        j = JOBS.get(job_id)
        if not j:
            raise HTTPException(404, 'Job tidak ditemukan atau sudah kedaluwarsa')
        out = {k: v for k, v in j.items() if k not in ('items',)}
    out['elapsed'] = round(time.time() - j.get('created_at', time.time()), 1)
    return out


@app.post('/api/analyze')
async def analyze_job(req: AnalyzeReq):
    with _LOCK:
        j = JOBS.get(req.job_id)
        if not j:
            raise HTTPException(404, 'Job konteks tidak ditemukan; ambil konteks ulang')
        if j.get('status') != 'done':
            raise HTTPException(409, 'Konteks belum selesai')
        items = j.get('items') or []
        meta = j.get('post') or {}
        ctx = req.context if isinstance(req.context, dict) else (j.get('context') or {})
    if not items:
        raise HTTPException(400, 'Tidak ada komentar publik yang bisa dianalisis')
    out = await asyncio.to_thread(engine.analyze_items, items, req.win, ctx, req.cluster_span)
    out['post'] = meta
    out['context'] = ctx
    out['sources'] = {meta.get('platform') or 'sumber': len(items)}
    out['errors'] = {}
    out['query'] = j.get('url') or meta.get('url') or ''
    out['llm'] = await _llm_review(items, out, ctx)
    out['dossier'] = evidence.build(out['query'], meta, ctx, out)
    return out


@app.post('/api/post')
async def analyze_post(req: PostReq):
    """Mode cepat lama: komentar + konteks caption saja (tanpa unduh media)."""
    url = req.url.strip()
    if not sources_public.detect(url):
        raise HTTPException(400, 'URL harus tautan publik TikTok, Instagram, atau Facebook')
    try:
        meta, items = await sources_public.fetch_public_post(url, os.environ)
    except sources_public.SourceError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, 'Gagal mengambil postingan: ' + e.__class__.__name__)
    if not items:
        raise HTTPException(400, 'Tidak ada komentar publik yang bisa dianalisis')
    ctx = context_mod.build_context(meta, dict(os.environ), use_media=False)
    out = engine.analyze_items(items, win=1440, context=ctx)
    out['post'] = meta
    out['context'] = ctx
    out['sources'] = {meta['platform']: len(items)}
    out['errors'] = {}
    out['query'] = url
    out['llm'] = await _llm_review(items, out, ctx)
    out['dossier'] = evidence.build(url, meta, ctx, out)
    return out


if __name__ == '__main__':
    host, port = os.environ.get('HOST', '127.0.0.1'), int(os.environ.get('PORT', 8787))
    print(f'SENTINEL berjalan di http://{host}:{port}')
    if os.environ.get('OPEN_BROWSER', '1') == '1':
        threading.Timer(1.2, lambda: webbrowser.open(f'http://{host}:{port}')).start()
    uvicorn.run(app, host=host, port=port, log_level='warning', ws='none')
