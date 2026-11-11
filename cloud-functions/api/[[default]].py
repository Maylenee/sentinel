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
from sentinel.context import builder as context_mod  # noqa: E402
from sentinel.llm import advanced as llm_mod  # noqa: E402
from sentinel.llm import makers as llm_client  # noqa: E402
from sentinel.sources import public as sources_public  # noqa: E402

MAX_ITEMS = 600  # batas keamanan; body request Cloud Functions maksimal 6 MB
LLM_BUDGET = 85  # detik; sisakan ruang di bawah 120 dtk
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
    return {'post': meta, 'items': items, 'items_count': len(items), 'context': ctx}


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
