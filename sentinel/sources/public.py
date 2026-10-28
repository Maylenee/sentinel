"""Analisis postingan publik Facebook/Instagram/TikTok memakai pustaka open-source (opsional).

Tidak ada API key dan tidak menyentuh akun sendiri: hanya membaca konten yang memang
tampil publik. Pustaka yang dipakai: yt-dlp (TikTok, MIT/Unlicense), instaloader
(Instagram, MIT), facebook-scraper (Facebook, MIT). Patuhi ToS platform dan UU PDP;
gunakan untuk riset/kajian, bukan untuk membuka data privat.
"""
import asyncio
import re
import time
from datetime import timezone
from urllib.parse import quote
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
    for name, mod in (('tiktok', 'yt_dlp'), ('instagram', 'instaloader'), ('facebook', 'facebook_scraper')):
        try:
            __import__(mod)
            out[name] = True
        except Exception:
            out[name] = False
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


def _tiktok_comments(page_url, cookies, aweme_id, maxc):
    """Komentar publik TikTok lewat endpoint web, memakai cookie hasil tantangan yt-dlp."""
    if not aweme_id:
        return [], 'ID video TikTok tidak ditemukan'
    try:
        from curl_cffi import requests as creq
    except ImportError:
        return [], 'Pasang curl_cffi untuk mengambil komentar: pip install curl_cffi'
    out, cursor = [], 0
    while len(out) < maxc:
        try:
            r = creq.get('https://www.tiktok.com/api/comment/list/',
                         params={'aweme_id': aweme_id, 'count': max(1, min(50, maxc - len(out))),
                                 'cursor': cursor, 'aid': '1988'},
                         cookies=cookies, impersonate='chrome', timeout=30,
                         headers={'referer': page_url, 'accept': 'application/json, text/plain, */*'})
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


def _tiktok_fetch(url, cfg):
    try:
        import yt_dlp
    except ImportError:
        raise _NoLib('yt-dlp')
    maxc = max(0, int(cfg.get('PUBLIC_MAX_COMMENTS') or 200))
    opts = {'quiet': True, 'no_warnings': True, 'skip_download': True}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False) or {}
            cookies = {c.name: c.value for c in ydl.cookiejar}
    except Exception as e:
        raise SourceError('TikTok gagal diambil (post privat/dihapus/limit): ' + _clean_err(e))
    note = ''
    if maxc and not info.get('comments'):
        raw, note = _tiktok_comments(info.get('webpage_url') or url, cookies, info.get('id'), maxc)
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
            r = await c.get('https://www.tiktok.com/oembed', params={'url': url})
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
                 'Pasang yt-dlp untuk ikut mengambil komentar: pip install yt-dlp', preview=pv,
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


def _ig_items(post, url):
    owner = post.owner_profile
    try:
        prof = _ig_profile(owner)
    except Exception:
        prof = None
    items = [_mk('Instagram', owner.userid, '@' + owner.username, getattr(post, 'caption', ''),
                 _dt_min(getattr(post, 'date_utc', None)), url,
                 profile=prof, kind='post')]
    for c in post.get_comments():
        text, ct = getattr(c, 'text', ''), _dt_min(getattr(c, 'created_at_utc', None))
        if not text or ct is None:
            continue
        o = c.owner
        items.append(_mk('Instagram', o.userid, '@' + o.username, text, ct, url, reply=False))
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
                                save_metadata=False, quiet=True)
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
    return _ig_meta(post, url, pv), _ig_items(post, url)


# ---------- Facebook (facebook-scraper) ----------
def _fb_meta(post, url):
    n = 0
    for c in post.get('comments_full') or []:
        n += 1
        if isinstance(c, dict) and isinstance(c.get('replies'), list):
            n += len(c['replies'])
    img = post.get('image')
    if isinstance(img, list):
        img = img[0] if img else ''
    if not isinstance(img, str):
        img = ''
    post_url = post.get('post_url') or url
    video = post.get('video')
    pv = {'kind': 'video' if video else 'image', 'thumbnail': img,
          'embed_url': 'https://www.facebook.com/plugins/post.php?href=' + quote(post_url, safe='') +
                       '&show_text=false&width=500'}
    stats = {'likes': post.get('likes'), 'comments': post.get('comments'), 'shares': post.get('shares')}
    return _meta('Facebook', post_url, post.get('username') or post.get('user_id'),
                 post.get('text') or post.get('post_text'), n + 1, preview=pv,
                 caption=post.get('text') or post.get('post_text'),
                 duration=post.get('video_duration'), stats=stats, posted_at=_dt_min(post.get('time')),
                 media_url=(video if isinstance(video, str) else (post.get('video_url') or '')),
                 media_kind=pv['kind'])


def _fb_items(post, url):
    author = post.get('username') or post.get('user_id') or 'facebook'
    items = [_mk('Facebook', post.get('user_id') or post.get('post_id') or author, author,
                 post.get('text') or post.get('post_text'), _dt_min(post.get('time')),
                 post.get('post_url') or url, kind='post')]

    def add(c, reply=False):
        if not c:
            return
        text, t = c.get('comment_text'), _dt_min(c.get('comment_time'))
        if not text or t is None:
            return
        uid = c.get('commenter_id') or c.get('commenter_name') or 'unknown'
        items.append(_mk('Facebook', uid, c.get('commenter_name') or uid, text, t,
                         c.get('commenter_url') or url, reply=reply))

    for c in post.get('comments_full') or []:
        add(c)
        try:
            for r in list(c.get('replies') or []):
                add(r, True)
        except TypeError:
            pass
    return items


def _facebook_fetch(url, cfg):
    try:
        import facebook_scraper as fs
    except ImportError:
        raise SourceError('Facebook butuh pustaka open-source: pip install facebook-scraper')
    maxc = int(cfg.get('PUBLIC_MAX_COMMENTS') or 200)
    try:
        gen = fs.get_posts(post_urls=[url], options={'comments': maxc, 'progress': False})
        post = next(iter(gen))
    except StopIteration:
        raise SourceError('Facebook tidak mengembalikan data; pastikan postingan publik dan bukan grup tertutup')
    except Exception as e:
        raise SourceError('Facebook menolak/gagal: ' + str(e).splitlines()[0][:200])
    return _fb_meta(post, url), _fb_items(post, url)


async def fetch_public_post(url, cfg=None):
    """Kembalikan (meta, items) siap masuk engine.analyze_items().

    Melempar SourceError bila platform tidak didukung atau data publik tidak bisa diambil.
    """
    cfg = cfg or {}
    platform = detect(url)
    if platform == 'tiktok':
        try:
            return await asyncio.to_thread(_tiktok_fetch, url, cfg)
        except _NoLib:
            return await _tiktok_oembed(url)
        except SourceError as e:
            try:
                meta, items = await _tiktok_oembed(url)
                meta['note'] = ((meta.get('note') or '') + ' Data lengkap gagal: ' + str(e)).strip()[:300]
                return meta, items
            except SourceError:
                raise e
    if platform == 'instagram':
        return await asyncio.to_thread(_instagram_fetch, url, cfg)
    if platform == 'facebook':
        return await asyncio.to_thread(_facebook_fetch, url, cfg)
    raise SourceError('URL harus tautan publik TikTok, Instagram, atau Facebook')
