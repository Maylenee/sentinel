import asyncio
import datetime
import pathlib
import sys
from datetime import timezone

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
from sentinel.context import builder as context_mod  # noqa: E402
from sentinel.analysis import engine  # noqa: E402
from sentinel.sources import public as sp  # noqa: E402

T = datetime.datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
LIKE = 'kebijakan ini harus didukung semua pihak sekarang juga'


class Profile:
    def __init__(self, uid, name, followers=0):
        self.userid, self.username, self.followers, self.followees = uid, name, followers, 5


class Comment:
    def __init__(self, cid, user, text, t):
        self.id, self.owner, self.text, self.created_at_utc = cid, user, text, t


class Post:
    def __init__(self, caption, comments):
        self.owner_profile, self.caption, self.date_utc = Profile(1, 'pemilik', 120), caption, T
        self.url, self._comments = 'https://instagram.com/p/abc/', comments

    def get_comments(self):
        return iter(self._comments)


def tiktok_case():
    info = {'id': '1', 'webpage_url': 'https://tiktok.com/@x/video/1', 'uploader': 'akun', 'uploader_id': 'u1',
            'description': 'isu publik', 'timestamp': T.timestamp(),
            'comments': [{'author': 'a', 'author_id': 'c1', 'text': LIKE, 'timestamp': T.timestamp(), 'parent': 'root'},
                         {'author': 'b', 'author_id': 'c2', 'text': LIKE, 'timestamp': T.timestamp() + 60, 'parent': 'c1'}]}
    items = sp._tiktok_items(info, 'https://tiktok.com/@x/video/1')
    assert len(items) == 3, items
    assert items[2]['reply'] is True and items[1]['reply'] is False
    out = engine.analyze_items(items)
    assert out['stats']['posts'] == 3 and out['stats']['accounts'] == 3
    info['duration'] = 87
    info['view_count'] = 1000
    meta = sp._tiktok_meta(info, info['webpage_url'])
    assert 'embed/v2/1' in meta['preview']['embed_url']
    assert meta['duration'] == 87 and meta['stats']['views'] == 1000 and meta['caption'] == 'isu publik'
    print('TikTok:', len(items), 'item,', out['stats'])


def instagram_case():
    p = Post(LIKE, [Comment(1, Profile(2, 'komentator', 80), LIKE, T),
                    Comment(2, Profile(3, 'lain', 30), 'komentar biasa saja', T + datetime.timedelta(minutes=5))])
    items = sp._ig_items(p, p.url)
    assert len(items) == 3 and items[0]['platform'] == 'Instagram'
    assert items[0]['profile']['followers'] == 120 and items[1]['handle'] == '@komentator'
    meta = sp._ig_meta(p, p.url, {'kind': 'image', 'embed_url': 'embed-test'})
    assert meta['preview']['embed_url'] == 'embed-test'
    print('Instagram:', len(items), 'item')


def facebook_case():
    post = {'post_id': 'p1', 'user_id': 'u1', 'username': 'halaman', 'text': LIKE, 'time': T,
            'post_url': 'https://facebook.com/p1',
            'comments_full': [{'comment_id': '1', 'commenter_id': 'c1', 'commenter_name': 'A', 'commenter_url': 'https://facebook.com/a',
                               'comment_text': LIKE, 'comment_time': T,
                               'replies': [{'comment_id': '2', 'commenter_id': 'c2', 'commenter_name': 'B',
                                            'comment_text': LIKE, 'comment_time': T + datetime.timedelta(minutes=2)}]}]}
    items = sp._fb_items(post, post['post_url'])
    assert len(items) == 3 and items[2]['reply'] is True, items
    meta = sp._fb_meta(post, post['post_url'])
    assert meta['comments'] == 2 and 'plugins/post.php?href=' in meta['preview']['embed_url']
    print('Facebook:', len(items), 'item')


def tiktok_comment_case():
    c = {'text': 'isu yang sama', 'create_time': 1700000000,
         'user': {'uid': 'u9', 'unique_id': 'akun9', 'nickname': 'Akun'}}
    x = sp._tt_comment(c)
    assert x['author_id'] == 'u9' and x['author'] == '@akun9' and x['timestamp'] == 1700000000
    assert sp._tt_comment({'text': '', 'user': {}}) is None
    print('TikTok comment: OK')


def content_explain_case():
    items = [
        {'id': 'tiktok:u1', 'handle': '@pemilik', 'platform': 'TikTok', 'text': 'kebijakan baru untuk semua',
         't': 100, 'url': '', 'reply': False, 'kind': 'post'},
        {'id': 'tiktok:u2', 'handle': '@a', 'platform': 'TikTok', 'text': 'kebijakan ini bagus dan membantu',
         't': 101, 'url': '', 'reply': False, 'kind': 'comment'},
        {'id': 'tiktok:u3', 'handle': '@b', 'platform': 'TikTok', 'text': 'kebijakan ini bagus dan membantu',
         't': 102, 'url': '', 'reply': False, 'kind': 'comment'},
    ]
    c = engine.content_summary(items)
    assert c['text_comments'] == 2 and c['unique_commenters'] == 2 and c['duplicate_pct'] == 100, c
    assert c['top_terms'] and c['summary'] and 'komentar' in c['summary']
    assert c['post_text'] and len(c['samples']) == 2
    assert 'belum membentuk kelompok' in c['why_low']
    out = engine.analyze_items(items)
    assert out['content']['duplicate_pct'] == 100
    a = out['accounts'][0]
    assert len(a['breakdown']) == 6 and a['explain'] and a['threshold'] == 2.5
    print('content/explain: OK')


def detect_case():
    assert sp.detect('https://www.tiktok.com/@a/video/1') == 'tiktok'
    assert sp.detect('https://www.instagram.com/reel/abc/') == 'instagram'
    assert sp.detect('https://web.facebook.com/x/posts/1') == 'facebook'
    assert sp.detect('https://example.com/x') is None
    print('detect: OK')


async def dispatch_case():
    def fake(url, cfg):
        return {'platform': 'TikTok', 'comments': 0}, sp._tiktok_items(
            {'uploader': 'x', 'uploader_id': 'u', 'description': LIKE, 'timestamp': T.timestamp(), 'comments': []}, url)
    old = sp._tiktok_fetch
    sp._tiktok_fetch = fake
    try:
        meta, items = await sp.fetch_public_post('https://www.tiktok.com/@a/video/1')
        assert meta['platform'] == 'TikTok' and len(items) == 1
    finally:
        sp._tiktok_fetch = old
    try:
        await sp.fetch_public_post('https://example.com/x')
        raise AssertionError('seharusnya SourceError')
    except sp.SourceError as e:
        assert 'TikTok' in str(e)
    print('dispatch: OK')


def context_case():
    meta = {'platform': 'TikTok', 'url': 'https://tiktok.com/@x/video/1', 'author': 'x',
            'caption': 'Pemerintah harus segera menurunkan harga bahan bakar. Menurut data, kenaikan mencapai 30 persen.',
            'duration': 87, 'preview': {'kind': 'video'}, 'stats': {'views': 10}, 'media_kind': 'video'}
    ctx = context_mod.build_context(meta, {'PUBLIC_ASR': '0', 'PUBLIC_OCR': '0'}, use_media=False)
    assert ctx['summary'] and ctx['confidence'] == 0.3
    assert len(ctx['claims']) >= 2, ctx['claims']
    assert ctx['entities']['numbers']
    print('context:', len(ctx['claims']), 'klaim')


def narrative_case():
    items = [
        {'id': 'p', 'handle': '@pemilik', 'platform': 'TikTok', 'text': 'harga bahan bakar harus turun',
         't': 1, 'url': '', 'reply': False, 'kind': 'post'},
        {'id': 'a', 'handle': '@a', 'platform': 'TikTok', 'text': 'setuju, harga bahan bakar harus turun',
         't': 2, 'url': '', 'reply': False, 'kind': 'comment'},
        {'id': 'b', 'handle': '@b', 'platform': 'TikTok', 'text': 'tolak, harga bahan bakar tidak mungkin turun',
         't': 3, 'url': '', 'reply': False, 'kind': 'comment'},
        {'id': 'c', 'handle': '@c', 'platform': 'TikTok', 'text': 'apakah data harga itu benar?',
         't': 4, 'url': '', 'reply': False, 'kind': 'comment'},
    ]
    ctx = {'summary': 'Harga bahan bakar harus turun.',
           'claims': [{'text': 'harga bahan bakar harus turun', 'kind': 'seruan', 'source': 'caption'}]}
    from sentinel.analysis import narrative
    assert narrative.stance('tidak setuju')['label'] == 'tolak'
    assert narrative.stance('tidak benar')['label'] == 'tolak'
    assert narrative.stance('benar')['label'] == 'dukung'
    out = engine.analyze_items(items, context=ctx)
    st = out['content']['stance']
    assert st['dukung'] == 1 and st['tolak'] == 1 and st['tanya'] == 1, st
    assert out['content']['claim_amplification'][0]['comments'] >= 1
    assert out['content']['summary'].startswith('Konteks video:')
    print('narrative:', st)


def coordination_case():
    def acc(uid, text, t):
        return {'id': uid, 'handle': uid, 'platform': 'TikTok', 'ageDays': 365, 'followers': 100,
                'following': 100, 'profile_known': False,
                'posts': [{'t': t, 'text': text, 'url': '', 'reply': False}]}

    a = 'satu dua tiga empat lima enam'
    b = 'satu dua tiga empat lima tujuh'
    c = 'dua tiga empat lima tujuh delapan'
    edges, clusters, stats = engine.coordination(
        [acc('A', a, 100), acc('B', b, 101), acc('C', c, 102)], win=60, min_pairs=1, cluster_span=360)
    assert clusters == [], ('rantai transisi tidak boleh jadi clique', edges, clusters)
    edges2, clusters2, stats2 = engine.coordination(
        [acc('A', a, 100), acc('B', a, 101), acc('C', a, 102)], win=60, min_pairs=1, cluster_span=360)
    assert len(clusters2) == 1 and len(clusters2[0]) == 3, clusters2
    assert 0 <= stats2['stats']['p_value'] <= 1
    edges3, clusters3, _ = engine.coordination(
        [acc('A', a, 100), acc('B', a, 5000)], win=60, min_pairs=1, cluster_span=360)
    assert not edges3 and not clusters3
    edges4, clusters4, _ = engine.coordination(
        [acc('A', 'sepakat', 100), acc('B', 'sepakat', 101), acc('C', 'sepakat', 102)],
        win=60, min_pairs=1, cluster_span=360)
    assert not edges4 and not clusters4, ('komentar kata umum tidak boleh jadi clique', clusters4)
    items = [{'id': 'p', 'handle': '@p', 'platform': 'TikTok', 'text': 'postingan',
              't': 99, 'url': '', 'reply': False, 'kind': 'post'}]
    for i, uid in enumerate(('a', 'b', 'c')):
        items.append({'id': uid, 'handle': '@' + uid, 'platform': 'TikTok', 'text': a,
                      't': 100 + i, 'url': '', 'reply': False, 'kind': 'comment'})
    out = engine.analyze_items(items)
    assert out['stats']['clusters'] == 1
    assert any(x['level'] in ('sedang', 'tinggi') for x in out['accounts']), out['accounts']
    print('coordination: clique/time-local OK')


def ocr_case():
    import os
    import tempfile
    from sentinel.context import ocr
    if not ocr.available():
        print('ocr: dilewati (backend tidak tersedia)')
        return
    from PIL import Image, ImageDraw, ImageFont
    try:
        font = ImageFont.load_default(size=42)
    except TypeError:
        font = ImageFont.load_default()
    img = Image.new('RGB', (900, 220), 'white')
    d = ImageDraw.Draw(img)
    d.text((24, 40), 'SENTINEL KONTEKS VIDEO', fill='black', font=font)
    d.text((24, 110), 'Prabowo berbicara di forum', fill='black', font=font)
    fd, path = tempfile.mkstemp(suffix='.png')
    os.close(fd)
    try:
        img.save(path)
        lines, note = ocr.read_frames([path], {'OCR_FPS': 1})
        assert lines, ('OCR tidak menghasilkan teks', note)
        assert any(len(x['text']) >= 4 for x in lines), lines
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    print('ocr:', ocr.backend(), 'OK')


def app_flow_case():
    import app as appmod
    meta = {'platform': 'TikTok', 'url': 'https://tiktok.com/@x/video/1', 'author': 'x',
            'caption': 'Harga bahan bakar harus turun.', 'preview': {'kind': 'video'},
            'media_kind': 'video', 'comments': 2, 'text': 'Harga bahan bakar harus turun.'}
    items = [
        {'id': 'tiktok:p', 'handle': '@p', 'platform': 'TikTok', 'text': 'Harga bahan bakar harus turun.',
         't': 100.0, 'url': '', 'reply': False, 'kind': 'post'},
        {'id': 'tiktok:a', 'handle': '@a', 'platform': 'TikTok', 'text': 'Saya setuju harga harus turun',
         't': 101.0, 'url': '', 'reply': False, 'kind': 'comment'},
    ]

    async def fake_fetch(_url, _cfg):
        return meta, items

    async def run():
        old_fetch = appmod.sources_public.fetch_public_post
        old_read, old_write = appmod._cache_read, appmod._cache_write
        appmod.sources_public.fetch_public_post = fake_fetch
        appmod._cache_read = lambda *a, **k: None
        appmod._cache_write = lambda *a, **k: None
        try:
            jid = 'test-flow'
            appmod.JOBS[jid] = {'id': jid, 'created_at': 0, 'status': 'queued'}
            await appmod._context_task(jid, meta['url'], False)
            assert appmod.JOBS[jid]['status'] == 'done', appmod.JOBS[jid]
            out = await appmod.analyze_job(appmod.AnalyzeReq(job_id=jid))
            assert out['content']['stance']['dukung'] == 1
            assert out['dossier']['context']['summary']
            return out
        finally:
            appmod.sources_public.fetch_public_post = old_fetch
            appmod._cache_read, appmod._cache_write = old_read, old_write
            appmod.JOBS.pop('test-flow', None)

    asyncio.run(run())
    print('app flow: OK')


def main():
    detect_case()
    tiktok_comment_case()
    tiktok_case()
    content_explain_case()
    context_case()
    narrative_case()
    coordination_case()
    ocr_case()
    instagram_case()
    facebook_case()
    asyncio.run(dispatch_case())
    app_flow_case()
    print('SEMUA TES POSTINGAN PUBLIK LULUS')


if __name__ == '__main__':
    main()
