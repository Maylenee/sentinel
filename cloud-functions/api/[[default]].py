"""SENTINEL di EdgeOne Pages (Cloud Functions, Python/ASGI).

Stateless: tidak ada job di memori, tidak ada proses latar, tidak ada cache disk.
Setiap endpoint selesai dalam satu request (< 120 dtk):

  POST /api/context  {url}                          -> {post, items, context}
  POST /api/analyze  {post, items, context, ...}    -> hasil heuristik (cepat, tanpa LLM)
  POST /api/llm      {items, analysis, context}     -> penilaian LLM (request terpisah)
  GET  /api/health

Router dipasang dengan dan tanpa prefix /api, jadi tetap jalan baik runtime
memotong prefix file-route maupun tidak.
"""
import asyncio
import os
import sys
from typing import List, Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (os.path.dirname(_HERE), _HERE):  # cloud-functions/ berisi paket `sentinel`
    if _p not in sys.path:
        sys.path.insert(0, _p)

from fastapi import APIRouter, FastAPI, HTTPException, Request  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from sentinel.analysis import engine, evidence  # noqa: E402
from sentinel.context import asr as asr_mod  # noqa: E402
from sentinel.context import builder as context_mod  # noqa: E402
from sentinel.llm import advanced as llm_mod  # noqa: E402
from sentinel.llm import makers as llm_client  # noqa: E402
from sentinel.sources import public as sources_public  # noqa: E402

MAX_ITEMS = 600  # batas keamanan; body request Cloud Functions maksimal 6 MB
LLM_BUDGET = 85  # detik; sisakan ruang di bawah 120 dtk
ASR_BUDGET = 100  # detik; unduh media + transkripsi, di bawah 120 dtk
ALLOWED_ORIGINS = [x.strip() for x in os.environ.get('ALLOWED_ORIGINS', '').split(',') if x.strip()]

app = FastAPI(title='SENTINEL', docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware('http')
async def _origin_guard(request: Request, call_next):
    """Opsional: bila ALLOWED_ORIGINS diisi, POST dari origin lain ditolak."""
    if ALLOWED_ORIGINS and request.method == 'POST':
        origin = request.headers.get('origin', '')
        if origin not in ALLOWED_ORIGINS:
            return JSONResponse({'detail': 'Origin tidak diizinkan'}, status_code=403)
    return await call_next(request)


class ContextReq(BaseModel):
    url: str
    media: bool = False  # diabaikan; dipertahankan agar klien lama tidak error


class AnalyzeReq(BaseModel):
    url: Optional[str] = ''
    post: Optional[dict] = None
    items: List[dict]
    context: Optional[dict] = None
    win: int = 1440
    cluster_span: int = 360


class TranscribeReq(BaseModel):
    url: str
    post: Optional[dict] = None


class LlmReq(BaseModel):
    items: List[dict]
    analysis: dict
    context: Optional[dict] = None


def _cfg():
    return dict(os.environ)


def _clean_items(items):
    out = []
    for it in items[:MAX_ITEMS]:
        try:
            out.append({
                'id': str(it['id']), 'handle': str(it.get('handle') or it['id']),
                'platform': str(it.get('platform') or ''), 'text': str(it.get('text') or '')[:600],
                't': float(it['t']), 'url': str(it.get('url') or ''), 'reply': bool(it.get('reply')),
                'profile': it.get('profile') if isinstance(it.get('profile'), dict) else None,
                'kind': str(it.get('kind') or 'comment'),
            })
        except (KeyError, TypeError, ValueError):
            continue
    return out


router = APIRouter()


@router.get('/health')
def health():
    return {'ok': True, 'runtime': 'edgeone-cloud-functions',
            'asr': {'available': asr_mod.available(os.environ), 'model': asr_mod.model(os.environ)},
            'public_sources': sources_public.available(),
            'llm': {'enabled': llm_client.enabled(os.environ), 'available': llm_client.available(os.environ),
                    'provider': 'edgeone-makers', 'model': llm_client.model(os.environ),
                    'max_tokens': llm_client.max_tokens(os.environ),
                    'thinking_disabled': llm_client.thinking_disabled(os.environ)}}


@router.post('/context')
async def make_context(req: ContextReq):
    url = (req.url or '').strip()
    if not sources_public.detect(url):
        raise HTTPException(400, 'URL harus tautan publik TikTok atau Instagram')
    try:
        meta, items = await sources_public.fetch_public_post(url, _cfg())
    except sources_public.SourceError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, 'Gagal mengambil postingan: ' + e.__class__.__name__)
    ctx = context_mod.build_context(meta, _cfg())
    return {'post': meta, 'items': items, 'items_count': len(items), 'context': ctx,
            'asr_available': asr_mod.available(os.environ) and '/photo/' not in url}


def _transcribe_blocking(url, cfg):
    path, tmp = asr_mod.download(url, cfg)
    try:
        return asr_mod.transcribe(path, cfg)
    finally:
        asr_mod.cleanup(tmp)


@router.post('/transcribe')
async def transcribe(req: TranscribeReq):
    """Langkah terpisah (request sendiri): unduh media -> ASR -> bangun ulang konteks."""
    url = (req.url or '').strip()
    cfg = _cfg()
    if not sources_public.detect(url):
        raise HTTPException(400, 'URL harus tautan publik TikTok atau Instagram')
    if not asr_mod.available(cfg):
        raise HTTPException(400, 'ASR belum dikonfigurasi (isi ASR_API_KEY di Environment Variables)')
    try:
        tr = await asyncio.wait_for(asyncio.to_thread(_transcribe_blocking, url, cfg), ASR_BUDGET)
    except asyncio.TimeoutError:
        raise HTTPException(504, 'Transkripsi melebihi batas waktu; coba video yang lebih pendek')
    except asr_mod.ASRError as e:
        raise HTTPException(502, str(e))
    meta = req.post or {}
    ctx = context_mod.build_context(meta, cfg, transcript=tr['segments'], asr_info=tr)
    return {'context': ctx, 'segments': len(tr['segments'])}


@router.post('/analyze')
async def analyze(req: AnalyzeReq):
    items = _clean_items(req.items)
    if not items:
        raise HTTPException(400, 'Tidak ada komentar publik yang bisa dianalisis')
    meta = req.post or {}
    ctx = req.context if isinstance(req.context, dict) else {}
    win = max(1, min(10080, req.win))
    span = max(1, min(10080, req.cluster_span))
    out = await asyncio.to_thread(engine.analyze_items, items, win, ctx, span)
    query = req.url or meta.get('url') or ''
    out['post'] = meta
    out['context'] = ctx
    out['sources'] = {meta.get('platform') or 'sumber': len(items)}
    out['errors'] = {}
    out['query'] = query
    out['llm'] = {'available': True, 'pending': True, 'accounts': [],
                  'note': 'Analisis LLM sedang berjalan…'}
    out['dossier'] = evidence.build(query, meta, ctx, out)
    return out


@router.post('/llm')
async def llm_review(req: LlmReq):
    items = _clean_items(req.items)
    cfg = _cfg()
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(llm_mod.analyze, items, req.analysis, req.context or {}, cfg), LLM_BUDGET)
    except asyncio.TimeoutError:
        return {'available': True, 'provider': 'edgeone-makers', 'model': llm_client.model(cfg),
                'error': 'timeout', 'accounts': [],
                'note': 'Analisis LLM melebihi batas waktu; hasil heuristik tetap dapat digunakan.'}
    except Exception as e:
        return {'available': True, 'provider': 'edgeone-makers', 'model': llm_client.model(cfg),
                'error': e.__class__.__name__, 'accounts': [],
                'note': 'Analisis LLM gagal; hasil heuristik tetap dapat digunakan.'}


app.include_router(router)
app.include_router(router, prefix='/api')
