"""Uji end-to-end alur stateless dengan sumber data dipalsukan (tanpa jaringan)."""
import importlib.util
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'cloud-functions'))
spec = importlib.util.spec_from_file_location('entry', ROOT / 'cloud-functions' / 'api' / '[[default]].py')
entry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(entry)

from fastapi.testclient import TestClient  # noqa: E402

client = TestClient(entry.app)
NOW = time.time() / 60


def fake_items():
    out = [{'id': 'tiktok:a', 'handle': '@a', 'platform': 'TikTok', 'text': 'Menurut data, harga naik 20 persen.',
            't': NOW - 900, 'url': '', 'reply': False, 'profile': None, 'kind': 'post'}]
    for i in range(12):
        out.append({'id': f'tiktok:u{i}', 'handle': f'@u{i}', 'platform': 'TikTok',
                    'text': 'Ayo tolak kebijakan ini sekarang juga, sebarkan!', 't': NOW - 600 + i,
                    'url': '', 'reply': False, 'profile': None, 'kind': 'comment'})
    return out


async def fake_fetch(url, cfg=None):
    return ({'platform': 'TikTok', 'url': url, 'author': 'a', 'caption': 'Menurut data, harga naik 20 persen.',
             'text': 'x', 'preview': {'kind': 'video'}, 'stats': {}, 'note': ''}, fake_items())


_orig_fetch = entry.sources_public.fetch_public_post
entry.sources_public.fetch_public_post = fake_fetch

for prefix in ('', '/api'):
    assert client.get(prefix + '/health').json()['ok'] is True
    r = client.post(prefix + '/context', json={'url': 'https://www.tiktok.com/@a/video/1'})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j['items_count'] == 13 and j['context']['summary']

r = client.post('/api/context', json={'url': 'https://example.com/x'})
assert r.status_code == 400
import asyncio  # noqa: E402
from sentinel.sources import public as _real  # noqa: E402
try:
    asyncio.run(_orig_fetch('https://www.facebook.com/x/posts/1', {}))
    raise AssertionError('Facebook harus ditolak')
except _real.SourceError as e:
    assert 'Facebook' in str(e)

a = client.post('/api/analyze', json={'url': 'u', 'post': j['post'], 'items': j['items'], 'context': j['context']})
assert a.status_code == 200, a.text
res = a.json()
assert res['accounts'] and res['dossier'] and res['llm']['pending'] is True
assert client.post('/api/analyze', json={'items': []}).status_code == 400

l = client.post('/api/llm', json={'items': j['items'], 'analysis': {'accounts': res['accounts'][:40],
                                                                  'clusters': res['clusters'], 'stats': res['stats']},
                                  'context': j['context']})
assert l.status_code == 200 and l.json()['available'] is False  # tanpa kunci: dinonaktifkan dengan sopan
print('api end-to-end: OK;', len(res['accounts']), 'akun,', len(res['clusters']), 'clique')
