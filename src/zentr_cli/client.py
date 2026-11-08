"""Small service client: fixed origins, bounded reads, no redirect forwarding."""
import base64
import json
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

import httpx

ORIGINS = {name: f'https://{name}.zentr.dev' for name in
           ('api', 'status', 'convert', 'drop', 'auth', 'docs')}


class ZentrError(Exception):
    """An actionable error suitable for terminal output."""


def safe_url(value):
    p = urlsplit(value)
    if (p.scheme != 'https' or not p.hostname or p.username or p.password
            or p.port not in (None, 443)
            or not (p.hostname == 'zentr.dev' or p.hostname.endswith('.zentr.dev'))):
        raise ZentrError('Expected an HTTPS zentr.dev URL.')
    return value


def encode(data):
    return base64.urlsafe_b64encode(data).decode().rstrip('=')


def decode(value):
    return base64.b64decode(value + '=' * (-len(value) % 4), altchars=b'-_', validate=True)


@contextmanager
def new_output(path):
    """Create exclusively; remove partial output if a transfer fails."""
    target = Path(path)
    with target.open('xb') as handle:
        try:
            yield handle
        except BaseException:
            handle.close()
            target.unlink(missing_ok=True)
            raise


class Client:
    def __init__(self, timeout=60, transport=None):
        self.http = httpx.Client(timeout=timeout, follow_redirects=False,
                                 headers={'User-Agent': 'zentr-cli/0.1.0'}, transport=transport)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.http.close()

    @contextmanager
    def stream(self, method, service, path, **kwargs):
        with self.http.stream(method, ORIGINS[service] + path, **kwargs) as response:
            if not 200 <= response.status_code < 300:
                # Never echo response bodies or URLs: they may contain secrets.
                code = response.status_code
                hint = {401: 'Access token missing or expired.', 403: 'Access denied.',
                        404: 'Not found or expired.', 413: 'Upload is too large.',
                        429: 'Rate limited; try again later.'}.get(code, 'Service request failed.')
                raise ZentrError(f'{service}: HTTP {code}. {hint}')
            yield response

    def request(self, method, service, path, *, raw=False, limit=8 * 1024 * 1024, **kwargs):
        with self.stream(method, service, path, **kwargs) as response:
            data = bytearray()
            for chunk in response.iter_bytes():
                data.extend(chunk)
                if len(data) > limit:
                    raise ZentrError('Service response exceeds the expected size.')
            if raw:
                return bytes(data)
            try:
                return json.loads(data)
            except (ValueError, UnicodeError) as exc:
                raise ZentrError(f'{service}: expected a JSON response.') from exc

    def services(self):
        data = self.request('GET', 'api', '/h/main')
        if isinstance(data, dict) and isinstance(data.get('data'), str):
            try:
                data = json.loads(decode(data['data']))
            except (ValueError, UnicodeError) as exc:
                raise ZentrError('Invalid service registry encoding.') from exc
        if not isinstance(data, list):
            raise ZentrError('Unexpected service registry format.')
        result = []
        for row in data:
            if not isinstance(row, dict) or not isinstance(row.get('name'), str) or not isinstance(row.get('url'), str):
                raise ZentrError('Invalid service registry entry.')
            result.append({'name': row['name'], 'url': safe_url(row['url'])})
        return result

    def status(self):
        return self.request('GET', 'status', '/api/status')

    def capabilities(self):
        result = self.request('GET', 'convert', '/api/capabilities')
        if not isinstance(result, dict):
            raise ZentrError('Unexpected conversion capabilities.')
        return result

    def convert(self, source, conversion, output, options):
        if not self.capabilities().get(conversion):
            raise ZentrError(f'Conversion unavailable: {conversion}. Run zentr convert formats.')
        if Path(source).resolve() == Path(output).resolve():
            raise ZentrError('Input and output must be different files.')
        # Opening output first prevents any upload when the destination exists.
        with Path(source).open('rb') as src, new_output(output) as dst:
            with self.stream('POST', 'convert', '/api/convert',
                             files={'file': (Path(source).name, src, 'application/octet-stream')},
                             data={'conversion': conversion, 'options': json.dumps(options)}) as response:
                for chunk in response.iter_bytes():
                    dst.write(chunk)
        return {'output': str(Path(output).resolve()), 'bytes': Path(output).stat().st_size}

