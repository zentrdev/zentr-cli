"""Loopback OAuth authorization-code login with PKCE and verified OIDC claims."""
import hashlib
import hmac
import json
import math
import os
import secrets
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlsplit

import jwt
import keyring
from keyring.errors import KeyringError

from .client import ZentrError, encode

ISSUER = 'https://auth.zentr.dev'
CLIENT_ID = 'zentr-cli'
REDIRECT = 'http://localhost:8787/oauth/callback'
SERVICE = 'zentr-cli'
ACCOUNT = 'oauth-session'


class LoopbackServer(HTTPServer):
    allow_reuse_port = False

    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(5)
        return connection, address


def store_session(value):
    try:
        keyring.set_password(SERVICE, ACCOUNT, json.dumps(value))
    except KeyringError as exc:
        raise ZentrError('No usable OS credential store. Configure a keyring backend before signing in.') from exc


def load_session():
    try:
        value = keyring.get_password(SERVICE, ACCOUNT)
        return json.loads(value) if value else None
    except (KeyringError, ValueError) as exc:
        raise ZentrError('Cannot read the OS credential store. Configure keyring or run zentr --logout.') from exc


def logout():
    try:
        if keyring.get_password(SERVICE, ACCOUNT):
            keyring.delete_password(SERVICE, ACCOUNT)
    except KeyringError as exc:
        raise ZentrError('Cannot remove the session from the OS credential store.') from exc


def access_token():
    token = os.environ.get('ZENTR_ACCESS_TOKEN')
    if token:
        return token
    session = load_session()
    if not session:
        raise ZentrError('Not signed in. Run zentr --login.')
    if session.get('expires_at', 0) <= time.time():
        raise ZentrError('Session expired. Run zentr --login again.')
    return session['access_token']


def discovery(client):
    info = client.request('GET', 'auth', '/.well-known/openid-configuration')
    expected = {'issuer': ISSUER, 'authorization_endpoint': ISSUER + '/authorize',
                'token_endpoint': ISSUER + '/oauth/token',
                'userinfo_endpoint': ISSUER + '/oauth/userinfo',
                'jwks_uri': ISSUER + '/.well-known/jwks.json'}
    if any(info.get(k) != v for k, v in expected.items()):
        raise ZentrError('Auth discovery changed; update the CLI before signing in.')
    return info


def validate_tokens(client, tokens, nonce):
    try:
        header = jwt.get_unverified_header(tokens['id_token'])
        keys = client.request('GET', 'auth', '/.well-known/jwks.json')['keys']
        matches = [key for key in keys if key.get('kid') == header.get('kid')]
        if header.get('alg') != 'ES256' or len(matches) != 1:
            raise ValueError('Invalid signing key')
        key = jwt.PyJWK.from_dict(matches[0], algorithm='ES256').key
        claims = jwt.decode(tokens['id_token'], key, algorithms=['ES256'],
                            audience=CLIENT_ID, issuer=ISSUER,
                            options={'require': ['exp', 'iat', 'iss', 'aud', 'sub', 'nonce']})
        if not isinstance(claims['sub'], str) or not claims['sub']:
            raise ValueError('Invalid subject')
        if not isinstance(claims['nonce'], str) or not hmac.compare_digest(claims['nonce'], nonce):
            raise ValueError('Invalid nonce')
        if claims.get('azp', CLIENT_ID) != CLIENT_ID:
            raise ValueError('Invalid authorized party')
        if tokens.get('token_type', '').lower() != 'bearer' or not isinstance(tokens.get('access_token'), str) or not tokens['access_token']:
            raise ValueError('Invalid access token')
        lifetime = float(tokens['expires_in'])
        if not math.isfinite(lifetime) or lifetime <= 0:
            raise ValueError('Invalid token lifetime')
        expiry = min(float(claims['exp']), time.time() + lifetime)
        if expiry <= time.time():
            raise ValueError('Expired tokens')
        return {'access_token': tokens['access_token'], 'expires_at': expiry,
                'profile': {k: claims[k] for k in ('sub', 'name', 'email', 'picture') if k in claims}}
    except (jwt.PyJWTError, KeyError, ValueError, TypeError) as exc:
        raise ZentrError('Sign-in token validation failed; no session was saved.') from exc


def callback_handler(state, result):
    class Callback(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # Callback URLs contain one-time codes; never log them.

        def do_GET(self):
            parsed = urlsplit(self.path)
            values = parse_qs(parsed.query)
            valid = (parsed.path == '/oauth/callback'
                     and self.headers.get('Host') == 'localhost:8787'
                     and len(values.get('state', [])) == 1
                     and hmac.compare_digest(values['state'][0], state))
            if not valid or result:
                self.send_error(400, 'Invalid sign-in callback')
                return
            if 'error' in values:
                result['error'] = 'Sign-in was cancelled or rejected.'
            elif len(values.get('code', [])) == 1:
                result['code'] = values['code'][0]
            else:
                self.send_error(400, 'Missing authorization code')
                return
            body = b'You may close this tab and return to Zentr CLI to finish sign-in.'
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
    return Callback


def login(client, announce=print, timeout=180):
    discovery(client)
    verifier, state, nonce = (secrets.token_urlsafe(32) for _ in range(3))
    query = urlencode({'response_type': 'code', 'client_id': CLIENT_ID,
                       'redirect_uri': REDIRECT, 'scope': 'openid profile email',
                       'state': state, 'nonce': nonce,
                       'code_challenge': encode(hashlib.sha256(verifier.encode()).digest()),
                       'code_challenge_method': 'S256'})
    result = {}
    try:
        server = LoopbackServer(('127.0.0.1', 8787), callback_handler(state, result))
    except OSError as exc:
        raise ZentrError('Login needs localhost port 8787. Stop the app using it and retry.') from exc
    with server:
        server.timeout = 0.5
        url = ISSUER + '/authorize?' + query
        announce('Opening your browser. Waiting up to three minutes for sign-in…')
        if not webbrowser.open(url):
            announce('Open this URL in your browser:\n' + url)
        deadline = time.monotonic() + timeout
        while not result and time.monotonic() < deadline:
            server.handle_request()
    if not result:
        raise ZentrError('Browser sign-in timed out. Run zentr --login to retry.')
    if result.get('error'):
        raise ZentrError(result['error'])
    tokens = client.request('POST', 'auth', '/oauth/token', data={
        'grant_type': 'authorization_code', 'client_id': CLIENT_ID,
        'redirect_uri': REDIRECT, 'code': result['code'], 'code_verifier': verifier})
    session = validate_tokens(client, tokens, nonce)
    store_session(session)
    return session['profile']


def whoami(client):
    result = client.request('GET', 'auth', '/oauth/userinfo',
                            headers={'Authorization': 'Bearer ' + access_token()})
    if not isinstance(result, dict) or not result.get('sub'):
        raise ZentrError('Auth returned an invalid user profile.')
    return result
