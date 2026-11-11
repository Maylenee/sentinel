"""Analisis postingan publik Facebook/Instagram/TikTok memakai pustaka open-source (opsional).

Tidak ada API key dan tidak menyentuh akun sendiri: hanya membaca konten yang memang
tampil publik. Pustaka yang dipakai: yt-dlp (TikTok, Unlicense), instaloader (Instagram, MIT).
Versi EdgeOne: semua panggilan dibatasi waktu agar selalu selesai < 120 detik;
Facebook tidak didukung (facebook-scraper terlalu berat untuk serverless). Patuhi ToS platform dan UU PDP;
gunakan untuk riset/kajian, bukan untuk membuka data privat.
"""
import asyncio
import html
import re
import time
from datetime import timezone
import httpx


MAX_TEXT = 600


class SourceError(Exception):
    pass


class _NoLib(Exception):
    pass


def _now_min():
    return time.time() / 60


def _epoch_min(ts):
    try:
        return float(ts) / 60
    except (TypeError, ValueError):
        return None


def _dt_min(dt):
    if dt is None:
        return None
    if isinstance(dt, (int, float)):
        return float(dt) / 60
    try:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp() / 60
    except (AttributeError, ValueError, OSError):
        return None


def detect(url):
    u = (url or '').strip()
    if re.search(r'(?:^|\.)tiktok\.com/', u):
        return 'tiktok'
    if re.search(r'(?:^|\.)instagram\.com/', u):
        return 'instagram'
    if re.search(r'(?:^|\.)(?:facebook\.com|fb\.watch|fb\.com)/', u):
        return 'facebook'
    return None


def available():
    out = {}
    out['tiktok'] = True  # oEmbed selalu ada; yt-dlp menambah komentar
    try:
        __import__('instaloader')
        out['instagram'] = True
    except Exception:
        out['instagram'] = False
    out['facebook'] = False
    return out


def _mk(platform, uid, handle, text, t, url, reply=False, profile=None, kind='comment'):
    return {'id': f'{platform.lower()}:{uid}', 'handle': handle or str(uid), 'platform': platform,
            'text': str(text or '')[:MAX_TEXT], 't': t, 'url': url or '', 'reply': bool(reply),
            'profile': profile, 'kind': kind}


def _tags(text):
    t = str(text or '')
    return {'hashtags': sorted(set(re.findall(r'#([\w.-]+)', t)))[:30],
            'mentions': sorted(set(re.findall(r'@([\w.]+)', t)))[:30]}


def _meta(platform, url, author, text, n, note='', preview=None, caption=None, duration=None,
          stats=None, posted_at=None, media_url='', media_kind=None):
    cap = str(caption if caption is not None else (text or ''))
    tags = _tags(cap)
    pv = preview or {}
    return {'platform': platform, 'url': url, 'author': author or '', 'text': cap[:280],
            'caption': cap[:4000], 'comments': max(0, n - 1), 'note': note, 'preview': pv,
            'hashtags': tags['hashtags'], 'mentions': tags['mentions'],
            'duration': duration, 'stats': stats or {}, 'posted_at': posted_at,
            'media_url': media_url or '', 'media_kind': media_kind or pv.get('kind') or 'video'}


# ---------- TikTok (yt-dlp) ----------
def _tiktok_meta(info, url):
    vid = info.get('id')
    thumb = info.get('thumbnail')
    if isinstance(thumb, list):
        thumb = thumb[-1] if thumb else ''
    pv = {'kind': 'video', 'thumbnail': thumb if isinstance(thumb, str) else '',
          'embed_url': f'https://www.tiktok.com/embed/v2/{vid}' if vid else ''}
    stats = {'views': info.get('view_count'), 'likes': info.get('like_count'),
             'comments': info.get('comment_count'), 'shares': info.get('repost_count')}
    return _meta('TikTok', info.get('webpage_url') or url, info.get('uploader') or info.get('channel'),
                 info.get('description') or info.get('title'), len(info.get('comments') or []) + 1,
                 preview=pv, caption=info.get('description') or info.get('title'),
                 duration=info.get('duration'), stats=stats,
                 posted_at=_epoch_min(info.get('timestamp')) or _epoch_min(info.get('release_timestamp')),
                 media_url=info.get('webpage_url') or url, media_kind='video')


def _tiktok_items(info, url):
    post_url = info.get('webpage_url') or url
    author = info.get('uploader') or info.get('channel') or info.get('uploader_id') or 'tiktok'
    uid = info.get('uploader_id') or info.get('channel_id') or author
    t = _epoch_min(info.get('timestamp')) or _epoch_min(info.get('release_timestamp')) or _now_min()
    items = [_mk('TikTok', uid, author, info.get('description') or info.get('title'), t, post_url, kind='post')]
    for c in info.get('comments') or []:
        text, ct = c.get('text'), _epoch_min(c.get('timestamp'))
        if not text or ct is None:
            continue
        cu = c.get('author_id') or c.get('author') or 'unknown'
        parent = c.get('parent')
        items.append(_mk('TikTok', cu, c.get('author') or cu, text, ct, c.get('author_url') or post_url,
                         reply=bool(parent and parent != 'root')))
    return items


_ANSI = re.compile(r'\x1b\[[0-9;]*m')


def _clean_err(e):
    return _ANSI.sub('', str(e).splitlines()[0])[:200]


def _tt_comment(c):
    u = c.get('user') or {}
    text = (c.get('text') or '').strip()
    if not text:
        return None
    uname = u.get('unique_id') or u.get('nickname') or u.get('uid') or 'unknown'
    handle = uname if str(uname).startswith('@') else '@' + str(uname)
    return {'text': text, 'timestamp': c.get('create_time'), 'author_id': u.get('uid') or uname,
            'author': handle,
            'author_url': f'https://www.tiktok.com/@{u["unique_id"]}' if u.get('unique_id') else '',
            'parent': 'root'}


_UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
       'Chrome/124.0 Safari/537.36')


def _http_get(url, params, cookies, referer):
    headers = {'referer': referer, 'accept': 'application/json, text/plain, */*'}
    try:
        from curl_cffi import requests as creq  # opsional: impersonasi browser
        return creq.get(url, params=params, cookies=cookies, impersonate='chrome', timeout=15, headers=headers)
    except ImportError:
        headers['user-agent'] = _UA
        return httpx.get(url, params=params, cookies=cookies, headers=headers, timeout=15, follow_redirects=True)


def _tiktok_comments(page_url, cookies, aweme_id, maxc, deadline=None):
    """Komentar publik TikTok lewat endpoint web, memakai cookie hasil yt-dlp."""
    if not aweme_id:
        return [], 'ID video TikTok tidak ditemukan'
    out, cursor = [], 0
    while len(out) < maxc:
        if deadline and time.time() > deadline:
            return out, 'Pengambilan komentar TikTok dihentikan karena batas waktu'
        try:
            r = _http_get('https://www.tiktok.com/api/comment/list/',
                          {'aweme_id': aweme_id, 'count': max(1, min(50, maxc - len(out))),
                           'cursor': cursor, 'aid': '1988'}, cookies, page_url)
        except Exception as e:
            return out, 'API komentar TikTok gagal: ' + e.__class__.__name__
        if r.status_code != 200:
            return out, f'API komentar TikTok status {r.status_code}'
        try:
            d = r.json()
        except Exception:
            return out, 'API komentar TikTok mengembalikan data tak dikenal'
        if d.get('status_code') not in (None, 0):
            return out, 'API komentar TikTok menolak: ' + str(d.get('status_msg') or d.get('status_code'))
        batch = d.get('comments') or []
        out += batch
        if not d.get('has_more') or not batch:
            break
        cursor = d.get('cursor') or (cursor + len(batch))
    return out[:maxc], ''


def _tt_id(url):
    m = re.search(r'/(?:video|photo)/(\d+)', url or '')
    return m.group(1) if m else ''


def _tt_canon(url):
    """Ubah /photo/ID menjadi /video/ID: yt-dlp dan oEmbed hanya mengenali bentuk /video/."""
    vid = _tt_id(url)
    m = re.search(r'tiktok\.com/(@[^/?#]+)', url or '')
    if vid and m:
        return f'https://www.tiktok.com/{m.group(1)}/video/{vid}'
    return url


def _tiktok_direct(url, cfg):
    """Jalur tanpa yt-dlp (postingan foto/slideshow): caption dari halaman, komentar dari API web."""
    vid = _tt_id(url)
    if not vid:
        raise SourceError('ID postingan TikTok tidak ditemukan di tautan')
    maxc = max(0, int(cfg.get('PUBLIC_MAX_COMMENTS') or 200))
    deadline = time.time() + 40
    canon = _tt_canon(url)
    m = re.search(r'tiktok\.com/@([^/?#]+)', url)
    author = m.group(1) if m else 'tiktok'
    cookies, caption = {}, ''
    try:
        with httpx.Client(follow_redirects=True, timeout=15, headers={'user-agent': _UA}) as c:
            r = c.get(canon)
            cookies = dict(c.cookies)
            if r.status_code == 200:
                mm = (re.search(r'<meta[^>]+property="og:description"[^>]+content="([^"]*)"', r.text)
                      or re.search(r'<meta[^>]+content="([^"]*)"[^>]+property="og:description"', r.text))
                caption = html.unescape(mm.group(1)) if mm else ''
    except httpx.HTTPError:
        pass
    thumb = ''
    try:  # thumbnail untuk pratinjau (opsional)
        o = httpx.get('https://www.tiktok.com/oembed', params={'url': canon}, timeout=8, follow_redirects=True)
        if o.status_code == 200:
            thumb = o.json().get('thumbnail_url') or ''
    except Exception:
        pass
    raw, note = _tiktok_comments(canon, cookies, vid, maxc, deadline)
    comments = [x for x in (_tt_comment(c) for c in raw) if x]
    if not comments and not caption:
        raise SourceError('TikTok tidak mengembalikan caption maupun komentar' + (' (' + note + ')' if note else ''))
    info = {'id': vid, 'webpage_url': canon, 'uploader': author, 'description': caption, 'thumbnail': thumb,
            'comments': comments, 'timestamp': int(vid) >> 32}  # ID TikTok memuat waktu unggah
    meta = _tiktok_meta(info, url)
    if note:
        meta['note'] = note
    return meta, _tiktok_items(info, url)


def _tiktok_fetch(url, cfg):
    try:
        import yt_dlp
    except ImportError:
        raise _NoLib('yt-dlp')
    maxc = max(0, int(cfg.get('PUBLIC_MAX_COMMENTS') or 200))
    opts = {'quiet': True, 'no_warnings': True, 'skip_download': True, 'noprogress': True,
            'socket_timeout': 15, 'retries': 1, 'extractor_retries': 1}
    deadline = time.time() + 45
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(_tt_canon(url), download=False) or {}
            cookies = {c.name: c.value for c in ydl.cookiejar}
    except Exception as e:
        raise SourceError('post privat/dihapus/limit atau URL tidak didukung yt-dlp - ' + _clean_err(e))
    note = ''
    if maxc and not info.get('comments'):
        raw, note = _tiktok_comments(info.get('webpage_url') or url, cookies, info.get('id'), maxc, deadline)
        info['comments'] = [x for x in (_tt_comment(c) for c in raw) if x]
        if raw and not info['comments'] and not note:
            note = 'Komentar yang tersedia tidak berisi teks.'
    meta = _tiktok_meta(info, url)
    if note:
        meta['note'] = note
    return meta, _tiktok_items(info, url)


async def _tiktok_oembed(url):
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=20) as c:
            r = await c.get('https://www.tiktok.com/oembed', params={'url': _tt_canon(url)})
    except httpx.HTTPError as e:
        raise SourceError('TikTok tidak bisa dihubungi: ' + e.__class__.__name__)
    if r.status_code != 200:
        raise SourceError(f'TikTok menolak URL ini (status {r.status_code}); pastikan postingan publik')
    d = r.json()
    author = d.get('author_name') or 'tiktok'
    m = re.search(r'data-video-id="(\d+)"', d.get('html') or '') or re.search(r'/video/(\d+)', url)
    vid = m.group(1) if m else ''
    pv = {'kind': 'video', 'thumbnail': d.get('thumbnail_url') or '',
          'embed_url': f'https://www.tiktok.com/embed/v2/{vid}' if vid else ''}
    items = [_mk('TikTok', author, author, d.get('title'), _now_min(), url, kind='post')]
    return _meta('TikTok', url, author, d.get('title'), 1,
                 'Hanya caption; komentar tidak berhasil diambil.', preview=pv,
                 caption=d.get('title'), media_url=url, media_kind='video'), items


# ---------- Instagram (instaloader) ----------
def _ig_profile(p):
    try:
        followers = int(p.followers)
    except Exception:
        followers = 0
    try:
        following = int(p.followees)
    except Exception:
        following = 0
    return {'ageDays': 365.0, 'followers': followers, 'following': following}


def _ig_meta(post, url, preview=None):
    try:
        owner = post.owner_profile.username
    except Exception:
        owner = ''
    pv = preview or {}
    cap = getattr(post, 'caption', '') or ''
    stats = {'likes': getattr(post, 'likes', None), 'comments': getattr(post, 'comments', None),
             'views': getattr(post, 'video_view_count', None)}
    try:
        media_url = post.video_url if getattr(post, 'is_video', False) else ''
    except Exception:
        media_url = ''
    try:
        duration = getattr(post, 'video_duration', None)
    except Exception:
        duration = None
    return _meta('Instagram', url, owner, cap, 1, preview=pv, caption=cap, duration=duration,
                 stats=stats, posted_at=_dt_min(getattr(post, 'date_utc', None)),
                 media_url=media_url, media_kind=pv.get('kind') or 'image')


def _ig_items(post, url, maxc=200, deadline=None):
    owner = post.owner_profile
    try:
        prof = _ig_profile(owner)
    except Exception:
        prof = None
    items = [_mk('Instagram', owner.userid, '@' + owner.username, getattr(post, 'caption', ''),
                 _dt_min(getattr(post, 'date_utc', None)), url,
                 profile=prof, kind='post')]
    try:
        for c in post.get_comments():
            if len(items) > maxc or (deadline and time.time() > deadline):
                break
            text, ct = getattr(c, 'text', ''), _dt_min(getattr(c, 'created_at_utc', None))
            if not text or ct is None:
                continue
            o = c.owner
            items.append(_mk('Instagram', o.userid, '@' + o.username, text, ct, url, reply=False))
    except Exception:
        pass  # rate-limit di tengah jalan: pakai komentar yang sudah terkumpul
    return items


def _instagram_fetch(url, cfg):
    try:
        import instaloader
    except ImportError:
        raise SourceError('Instagram butuh pustaka open-source: pip install instaloader')
    m = re.search(r'instagram\.com/(?:p|reel|reels|tv)/([A-Za-z0-9_-]+)', url)
    if not m:
        raise SourceError('URL Instagram tidak dikenali (butuh tautan /p/ atau /reel/)')
    L = instaloader.Instaloader(download_pictures=False, download_videos=False, download_comments=False,
                                save_metadata=False, quiet=True,
                                request_timeout=15, max_connection_attempts=1)
    if cfg.get('IG_USERNAME') and cfg.get('IG_PASSWORD'):
        try:
            L.login(cfg['IG_USERNAME'], cfg['IG_PASSWORD'])
        except Exception as e:
            raise SourceError('Login Instagram gagal: ' + e.__class__.__name__)
    elif cfg.get('IG_SESSIONFILE'):
        try:
            L.load_session_from_file(cfg['IG_SESSIONFILE'])
        except Exception as e:
            raise SourceError('Sesi Instagram tidak bisa dimuat: ' + e.__class__.__name__)
    try:
        post = instaloader.Post.from_shortcode(L.context, m.group(1))
    except Exception as e:
        raise SourceError('Instagram menolak (post privat/dihapus/limit login): ' + e.__class__.__name__)
    try:
        is_video = bool(post.is_video)
        thumb = '' if is_video else (post.url or '')
    except Exception:
        is_video, thumb = False, ''
    pv = {'kind': 'video' if is_video else 'image', 'thumbnail': thumb,
          'embed_url': f'https://www.instagram.com/p/{m.group(1)}/embed/'}
    maxc = max(0, int(cfg.get('PUBLIC_MAX_COMMENTS') or 200))
    return _ig_meta(post, url, pv), _ig_items(post, url, maxc, time.time() + 45)


# ---------- Facebook ----------
def _facebook_fetch(url, cfg):
    raise SourceError('Facebook belum didukung di EdgeOne: pengambil komentar Facebook butuh pustaka '
                      'berat dan sesi login yang tidak muat di serverless. Gunakan tautan TikTok atau Instagram.')


async def _ensure_thumb(meta, url):
    """Lengkapi thumbnail TikTok lewat oEmbed bila belum ada (best effort, maks 8 dtk)."""
    pv = meta.setdefault('preview', {})
    if pv.get('thumbnail'):
        return
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=8) as c:
            r = await c.get('https://www.tiktok.com/oembed', params={'url': _tt_canon(url)})
        if r.status_code == 200:
            pv['thumbnail'] = r.json().get('thumbnail_url') or ''
    except Exception:
        pass


async def fetch_public_post(url, cfg=None):
    meta, items = await _fetch_public_post(url, cfg)
    if meta.get('platform') == 'TikTok':
        await _ensure_thumb(meta, url)
    return meta, items


async def _fetch_public_post(url, cfg=None):
    """Kembalikan (meta, items) siap masuk engine.analyze_items().

    Melempar SourceError bila platform tidak didukung atau data publik tidak bisa diambil.
    Total waktu dibatasi (< 100 dtk) agar selalu di bawah batas 120 dtk Cloud Functions.
    """
    cfg = cfg or {}
    platform = detect(url)
    if platform == 'tiktok':
        reasons = []
        for name, fn, limit in (('yt-dlp', _tiktok_fetch, 50), ('langsung', _tiktok_direct, 45)):
            try:
                return await asyncio.wait_for(asyncio.to_thread(fn, url, cfg), limit)
            except asyncio.TimeoutError:
                reasons.append(f'{name}: melebihi batas waktu')
            except (_NoLib, SourceError) as e:
                reasons.append(f'{name}: {e}')
        try:
            meta, items = await _tiktok_oembed(url)
        except SourceError as e:
            raise SourceError('TikTok gagal diambil. ' + ' | '.join(reasons + [f'oEmbed: {e}'])[:600])
        meta['note'] = ('Komentar tidak tersedia. ' + ' | '.join(reasons))[:300]
        return meta, items
    if platform == 'instagram':
        try:
            return await asyncio.wait_for(asyncio.to_thread(_instagram_fetch, url, cfg), 80)
        except asyncio.TimeoutError:
            raise SourceError('Instagram terlalu lama merespons; coba lagi beberapa saat.')
    if platform == 'facebook':
        return await asyncio.to_thread(_facebook_fetch, url, cfg)
    raise SourceError('URL harus tautan publik TikTok atau Instagram')
