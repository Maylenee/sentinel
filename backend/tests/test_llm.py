import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
from sentinel.llm import advanced, makers  # noqa: E402


def parse_case():
    assert makers.extract_json('```json\n{"a": 1}\n```') == {'a': 1}
    assert makers.extract_json('jawaban: {"b": 2} selesai') == {'b': 2}
    print('llm parse: OK')


def payload_case():
    items = [
        {'id': 'u1', 'text': 'komentar satu', 'kind': 'comment'},
        {'id': 'u1', 'text': 'komentar dua', 'kind': 'comment'},
        {'id': 'u1', 'text': 'komentar tiga', 'kind': 'comment'},
        {'id': 'u1', 'text': 'caption', 'kind': 'post'},
    ]
    analysis = {
        'accounts': [{'id': 'u1', 'handle': '@satu', 'platform': 'TikTok', 'risk': 0.8,
                      'level': 'tinggi', 'score': 3.1, 'n_posts': 3, 'cluster': 0,
                      'breakdown': [{'label': 'clique', 'hit': True}, {'label': 'umur', 'hit': False}]}],
        'clusters': [{'size': 3, 'span_min': 4, 'edges': 3, 'p_value': 0.01, 'members': ['@a', '@b', '@c']}],
        'stats': {'posts': 4, 'accounts': 1},
        'coordination': {'p_value': 0.01},
    }
    p = advanced.build_payload(items, analysis, {'summary': 'ringkas', 'claims': [{'text': 'klaim'}]},
                               {'LLM_MAX_ACCOUNTS': '5', 'LLM_MAX_SAMPLES': '2'})
    assert p['accounts'][0]['id'] == 'u1' and len(p['accounts'][0]['samples']) == 2
    assert p['accounts'][0]['signals'] == ['clique']
    assert p['clusters'][0]['p_value'] == 0.01
    print('llm payload: OK')


def client_case():
    captured, responses = [], []

    class Resp:
        status_code = 200
        text = ''

        def __init__(self, payload):
            self.payload = payload

        def json(self):
            return self.payload

    class Client:
        def __init__(self, timeout=None):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, headers=None, json=None):
            captured.append(dict(json or {}))
            return Resp(responses.pop(0))

    ok = {'choices': [{'finish_reason': 'stop', 'message': {'content': '{"ok": true}'}}]}
    empty = {'choices': [{'finish_reason': 'length', 'message': {'content': '', 'reasoning_content': 'x'}}]}
    responses.extend([ok, empty, empty])
    old = makers.httpx.Client
    makers.httpx.Client = Client
    try:
        cfg = {'MAKERS_MODELS_KEY': 'test', 'LLM_ENABLED': '1', 'LLM_MAX_TOKENS': '4096'}
        assert makers.chat([{'role': 'user', 'content': 'x'}], cfg) == '{"ok": true}'
        assert captured[0]['max_tokens'] == 4096
        assert captured[0]['thinking'] == {'type': 'disabled'}
        try:
            makers.chat([{'role': 'user', 'content': 'x'}], cfg)
            raise AssertionError('seharusnya LLMError')
        except makers.LLMError as e:
            assert 'MAX_TOKENS' in str(e)
        assert captured[-1]['max_tokens'] == 8192
        assert captured[-1]['thinking'] == {'type': 'disabled'}
    finally:
        makers.httpx.Client = old
    print('llm client: OK')


def analyze_case():
    items = [{'id': 'u1', 'text': 'teks sama', 'kind': 'comment'},
             {'id': 'u2', 'text': 'teks lain', 'kind': 'comment'}]
    analysis = {
        'accounts': [
            {'id': 'u1', 'handle': '@satu', 'platform': 'TikTok', 'risk': 0.9, 'level': 'tinggi',
             'score': 3.5, 'n_posts': 1, 'cluster': 0, 'breakdown': [{'label': 'clique', 'hit': True}]},
            {'id': 'u2', 'handle': '@dua', 'platform': 'TikTok', 'risk': 0.1, 'level': 'rendah',
             'score': 0.5, 'n_posts': 1, 'cluster': None, 'breakdown': []},
        ],
        'clusters': [], 'stats': {}, 'coordination': {},
    }
    fake = {
        'summary': 'Satu akun menunjukkan pola terkoordinasi.',
        'overall_label': 'buzzer', 'overall_confidence': 0.8,
        'accounts': [
            {'id': 'u1', 'label': 'buzzer', 'confidence': 0.9, 'reasons': ['clique'], 'evidence': ['teks sama']},
            {'id': 'u2', 'label': 'organic', 'confidence': 0.7, 'reasons': ['wajar'], 'evidence': []},
            {'id': 'asing', 'label': 'bot', 'confidence': 0.99, 'reasons': ['x'], 'evidence': []},
        ],
        'caveats': ['Perlu verifikasi manusia.'],
    }
    old = makers.chat
    makers.chat = lambda *a, **k: json.dumps(fake)
    try:
        out = advanced.analyze(items, analysis, {}, {'MAKERS_MODELS_KEY': 'test', 'LLM_ENABLED': '1'})
    finally:
        makers.chat = old
    assert out['available'] is True and out['overall_label'] == 'buzzer'
    assert [a['id'] for a in out['accounts']] == ['u1', 'u2']
    assert out['accounts'][0]['label'] == 'buzzer' and out['accounts'][1]['label'] == 'organic'
    assert out['caveats'] == ['Perlu verifikasi manusia.']
    print('llm analyze: OK')


def disabled_case():
    out = advanced.analyze([], {}, {}, {'LLM_ENABLED': '0'})
    assert out['available'] is False and out['enabled'] is False
    print('llm disabled: OK')


def main():
    parse_case()
    payload_case()
    client_case()
    analyze_case()
    disabled_case()
    print('SEMUA TES LLM LULUS')


if __name__ == '__main__':
    main()
