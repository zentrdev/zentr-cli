import base64
import hashlib
import json
import threading
import time
from http.server import HTTPServer
from urllib.parse import parse_qs, urlsplit

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from zentr_cli import auth
from zentr_cli.client import Client, ZentrError, safe_url
from zentr_cli.cli import main


def client(handler):
    return Client(transport=httpx.MockTransport(handler))


def test_registry_base64_and_url_validation():
    payload = base64.b64encode(json.dumps([{'name': 'drop', 'url': 'https://drop.zentr.dev', 'logo': 'large'}]).encode()).decode()
    with client(lambda r: httpx.Response(200, json={'data': payload})) as c:
        assert c.services() == [{'name': 'drop', 'url': 'https://drop.zentr.dev'}]
    for url in ('https://zentr.dev.evil.test', 'http://drop.zentr.dev', 'https://user@drop.zentr.dev', 'https://drop.zentr.dev:88'):
        with pytest.raises(ZentrError):
            safe_url(url)


def test_errors_do_not_leak_response_or_redirect():
    for status in (302, 401, 429, 500):
        with client(lambda r: httpx.Response(status, text='secret-token', headers={'Location': 'https://evil.test'})) as c:
            with pytest.raises(ZentrError) as caught:
                c.status()
            assert 'secret-token' not in str(caught.value)


def test_bad_json_and_size_limit():
    with client(lambda r: httpx.Response(200, text='not-json')) as c:
        with pytest.raises(ZentrError, match='JSON'):
            c.status()
    with client(lambda r: httpx.Response(200, content=b'123456')) as c:
        with pytest.raises(ZentrError, match='size'):
            c.request('GET', 'status', '/api/status', limit=3)


def test_conversion_multipart_and_no_overwrite(tmp_path):
    src = tmp_path / 'a.wav'; src.write_bytes(b'RIFFfake')
    dst = tmp_path / 'a.mp3'
    calls = []
    def handler(r):
        calls.append(r)
        if r.method == 'GET':
            return httpx.Response(200, json={'audio-wav-mp3': True})
        body = r.read()
        assert b'name="conversion"' in body and b'audio-wav-mp3' in body
        assert b'RIFFfake' in body
        return httpx.Response(200, content=b'converted')
    with client(handler) as c:
        c.convert(src, 'audio-wav-mp3', dst, {})
        assert dst.read_bytes() == b'converted'
        with pytest.raises(FileExistsError):
            c.convert(src, 'audio-wav-mp3', dst, {})
    assert len([r for r in calls if r.method == 'POST']) == 1


def test_conversion_failure_cleans_output(tmp_path):
    src = tmp_path / 'a'; src.write_bytes(b'input')
    dst = tmp_path / 'out'
    with client(lambda r: httpx.Response(200, json={'a-b': True}) if r.method == 'GET' else httpx.Response(503)) as c:
        with pytest.raises(ZentrError):
            c.convert(src, 'a-b', dst, {})
    assert not dst.exists()


def signed_tokens(nonce='nonce', **overrides):
    private = ec.generate_private_key(ec.SECP256R1())
    jwk = json.loads(jwt.algorithms.ECAlgorithm.to_jwk(private.public_key()))
    jwk['kid'] = 'test'
    claims = {'iss': auth.ISSUER, 'aud': auth.CLIENT_ID, 'sub': 'user',
              'iat': int(time.time()), 'exp': int(time.time()) + 900, 'nonce': nonce}
    claims.update(overrides)
    token = jwt.encode(claims, private, algorithm='ES256', headers={'kid': 'test'})
    return {'id_token': token, 'access_token': 'access', 'token_type': 'Bearer', 'expires_in': 900}, {'keys': [jwk]}


def test_valid_id_token():
    tokens, keys = signed_tokens()
    with client(lambda r: httpx.Response(200, json=keys)) as c:
        session = auth.validate_tokens(c, tokens, 'nonce')
    assert session['profile'] == {'sub': 'user'}


@pytest.mark.parametrize('overrides', [{'nonce': 'wrong'}, {'aud': 'other'}, {'iss': 'https://evil.test'}, {'exp': 1}, {'sub': ''}, {'iat': int(time.time()) + 600}])
def test_invalid_claims_rejected(overrides):
    tokens, keys = signed_tokens(**overrides)
    with client(lambda r: httpx.Response(200, json=keys)) as c:
        with pytest.raises(ZentrError, match='validation failed'):
            auth.validate_tokens(c, tokens, 'nonce')


def test_invalid_signature_rejected():
    tokens, _ = signed_tokens()
    _, keys = signed_tokens()
    with client(lambda r: httpx.Response(200, json=keys)) as c:
        with pytest.raises(ZentrError):
            auth.validate_tokens(c, tokens, 'nonce')


def test_callback_state_host_and_single_use():
    result = {}
    server = HTTPServer(('127.0.0.1', 0), auth.callback_handler('expected', result))
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        with httpx.Client(trust_env=False) as h:
            url = f'http://127.0.0.1:{server.server_port}/oauth/callback'
            for query in ('code=x', 'state=wrong&code=x', 'state=expected&state=wrong&code=x'):
                assert h.get(url + '?' + query, headers={'Host': 'localhost:8787'}).status_code == 400
            assert not result
            assert h.get(url + '?state=expected&code=x').status_code == 400
            assert h.get(url + '?state=expected&code=x', headers={'Host': 'localhost:8787'}).status_code == 200
            assert result == {'code': 'x'}
            assert h.get(url + '?state=expected&code=x', headers={'Host': 'localhost:8787'}).status_code == 400
    finally:
        server.shutdown(); server.server_close(); thread.join()


def test_complete_login_with_mock_browser(monkeypatch):
    flow = {}; saved = {}; threads = []
    def browser(url):
        q = parse_qs(urlsplit(url).query); flow.update(q)
        def callback():
            with httpx.Client(trust_env=False) as h:
                h.get(auth.REDIRECT, params={'state': q['state'][0], 'code': 'one-time'})
        t = threading.Thread(target=callback); t.start(); threads.append(t)
        return True
    def handler(r):
        if r.url.path.endswith('openid-configuration'):
            return httpx.Response(200, json={'issuer': auth.ISSUER, 'authorization_endpoint': auth.ISSUER + '/authorize', 'token_endpoint': auth.ISSUER + '/oauth/token', 'userinfo_endpoint': auth.ISSUER + '/oauth/userinfo', 'jwks_uri': auth.ISSUER + '/.well-known/jwks.json'})
        if r.url.path == '/oauth/token':
            fields = parse_qs(r.read().decode())
            assert auth.encode(hashlib.sha256(fields['code_verifier'][0].encode()).digest()) == flow['code_challenge'][0]
            assert fields['redirect_uri'] == [auth.REDIRECT]
            tokens, keys = signed_tokens(nonce=flow['nonce'][0]); saved['keys'] = keys
            return httpx.Response(200, json=tokens)
        return httpx.Response(200, json=saved['keys'])
    monkeypatch.setattr(auth.webbrowser, 'open', browser)
    monkeypatch.setattr(auth, 'store_session', lambda session: saved.update(session=session))
    with client(handler) as c:
        assert auth.login(c, announce=lambda x: None, timeout=3) == {'sub': 'user'}
    for t in threads: t.join()
    assert saved['session']['access_token'] == 'access'


def test_expired_session(monkeypatch):
    monkeypatch.delenv('ZENTR_ACCESS_TOKEN', raising=False)
    monkeypatch.setattr(auth, 'load_session', lambda: {'expires_at': 1})
    with pytest.raises(ZentrError, match='expired'):
        auth.access_token()


def test_no_node_has_helpful_error(monkeypatch, capsys):
    monkeypatch.setattr('zentr_cli.cli.shutil.which', lambda _: None)
    assert main(['drop', 'help']) == 1
    assert 'Node.js' in capsys.readouterr().err


def test_help_and_version(capsys):
    assert main([]) == 0
    assert '--login' in capsys.readouterr().out
