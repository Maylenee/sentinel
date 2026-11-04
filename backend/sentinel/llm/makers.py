"""Klien EdgeOne Makers Models (endpoint OpenAI-compatible).

Hanya memakai httpx yang sudah menjadi dependensi inti. Kunci API dibaca dari
MAKERS_MODELS_KEY (env/.env) dan tidak pernah dikirim ke frontend.
"""
import json
import os
import re

import httpx

DEFAULT_BASE_URL = 'https://ai-gateway.edgeone.link/v1'
DEFAULT_MODEL = '@makers/deepseek-v4-flash'


class LLMError(Exception):
    pass


def _cfg(cfg=None):
    return cfg if isinstance(cfg, dict) else {}


def _get(cfg, name, default=''):
    v = _cfg(cfg).get(name)
    if v is None:
        v = os.environ.get(name, default)
    return v


def api_key(cfg=None):
    return str(_get(cfg, 'MAKERS_MODELS_KEY', '') or '').strip()


def enabled(cfg=None):
    v = _get(cfg, 'LLM_ENABLED', '1')
    return str(v).strip().lower() not in ('0', 'false', 'no', 'off', '')


def available(cfg=None):
    return enabled(cfg) and bool(api_key(cfg))


def model(cfg=None):
    return str(_get(cfg, 'LLM_MODEL', DEFAULT_MODEL) or DEFAULT_MODEL).strip()


def base_url(cfg=None):
    return str(_get(cfg, 'LLM_BASE_URL', DEFAULT_BASE_URL) or DEFAULT_BASE_URL).strip().rstrip('/')


def timeout(cfg=None):
    try:
        return max(5.0, float(_get(cfg, 'LLM_TIMEOUT', 60)))
    except (TypeError, ValueError):
        return 60.0


def max_tokens(cfg=None, default=6144):
    try:
        return max(256, min(8192, int(float(_get(cfg, 'LLM_MAX_TOKENS', default)))))
    except (TypeError, ValueError):
        return default


def thinking_disabled(cfg=None):
    v = _get(cfg, 'LLM_DISABLE_THINKING', '1')
    return str(v).strip().lower() not in ('0', 'false', 'no', 'off', '')


def chat(messages, cfg=None, temperature=0.2, max_tokens_limit=None):
    """Kirim chat completion ke Makers Models dan kembalikan teks jawaban.

    Model reasoning seperti deepseek-v4-flash memakai token untuk
    `reasoning_content`. Secara default thinking dimatikan agar token tidak
    habis sebelum jawaban JSON selesai (bisa diubah via LLM_DISABLE_THINKING).
    """
    if not available(cfg):
        raise LLMError('MAKERS_MODELS_KEY belum diisi atau LLM_ENABLED=0.')
    payload = {
        'model': model(cfg),
        'messages': messages,
        'temperature': temperature,
        'max_tokens': max_tokens(cfg, max_tokens_limit or 6144),
    }
    if thinking_disabled(cfg):
        payload['thinking'] = {'type': 'disabled'}
    url = base_url(cfg) + '/chat/completions'
    headers = {
        'Authorization': 'Bearer ' + api_key(cfg),
        'Content-Type': 'application/json',
    }

    def request(body):
        try:
            with httpx.Client(timeout=timeout(cfg)) as client:
                resp = client.post(url, headers=headers, json=body)
                if resp.status_code == 400 and 'thinking' in body and 'thinking' in resp.text.lower():
                    # Sebagian model/vendor tidak mengenal parameter thinking.
                    retry = {k: v for k, v in body.items() if k != 'thinking'}
                    resp = client.post(url, headers=headers, json=retry)
                return resp
        except httpx.HTTPError as e:
            raise LLMError('LLM tidak bisa dihubungi: ' + e.__class__.__name__)

    def read(resp):
        if resp.status_code != 200:
            raise LLMError(f'LLM menolak (status {resp.status_code}): {resp.text[:200]}')
        try:
            data = resp.json()
            choice = data['choices'][0]
            message = choice['message']
            content = message.get('content')
        except (ValueError, KeyError, IndexError, TypeError):
            raise LLMError('Format respons LLM tidak dikenali.')
        if isinstance(content, list):
            content = ''.join(p.get('text', '') for p in content if isinstance(p, dict))
        return str(content or '').strip(), str(choice.get('finish_reason') or ''), data

    out, finish, data = read(request(payload))
    if not out and finish == 'length':
        # Token habis sebelum jawaban dimulai: ulangi dengan plafon lebih besar.
        retry = dict(payload)
        retry['max_tokens'] = min(8192, max(1024, int(payload['max_tokens'])) * 2)
        retry['thinking'] = {'type': 'disabled'}
        out, finish, data = read(request(retry))
    if not out:
        hint = ' (kemungkinan token habis untuk reasoning; coba naikkan LLM_MAX_TOKENS)' if finish == 'length' else ''
        raise LLMError(f'LLM mengembalikan jawaban kosong (finish={finish or "?"})' + hint + '.')
    return out


def extract_json(text):
    """Ambil objek JSON dari jawaban model, termasuk bila dibungkus markdown."""
    t = str(text or '').strip()
    t = re.sub(r'^```(?:json)?\s*', '', t, flags=re.IGNORECASE)
    t = re.sub(r'\s*```$', '', t)
    try:
        return json.loads(t)
    except ValueError:
        pass
    start = t.find('{')
    end = t.rfind('}')
    if start != -1 and end > start:
        try:
            return json.loads(t[start:end + 1])
        except ValueError as e:
            raise LLMError('JSON dari LLM tidak valid: ' + str(e)[:120])
    raise LLMError('LLM tidak mengembalikan objek JSON.')
