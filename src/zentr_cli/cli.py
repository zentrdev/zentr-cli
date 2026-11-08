"""Command-line entry point."""
import argparse
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import webbrowser

import httpx

from . import __version__, auth
from .client import Client, ZentrError


def clean(value):
    return ''.join(c if c.isprintable() else '?' for c in str(value))


def emit(value, as_json=False):
    if as_json or isinstance(value, (dict, list)):
        print(json.dumps(value, ensure_ascii=True, indent=2))
    else:
        print(clean(value))


def table(rows):
    rows = [[clean(v) for v in row] for row in rows]
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    for row in rows:
        print('  '.join(v.ljust(w) for v, w in zip(row, widths)).rstrip())


def run_drop(args):
    node = shutil.which('node')
    if not node:
        raise ZentrError('Drop requires Node.js 20.11 or newer. Install Node.js, then retry.')
    version = subprocess.run([node, '--version'], capture_output=True, text=True, check=True).stdout.strip()
    if tuple(map(int, version.lstrip('v').split('.')[:2])) < (20, 11):
        raise ZentrError('Drop requires Node.js 20.11 or newer.')
    script = Path(__file__).parent / 'vendor' / 'drop' / 'drop.mjs'
    env = os.environ.copy()
    # Account credentials have no audience in the anonymous Drop API.
    env.pop('ZENTR_ACCESS_TOKEN', None)
    return subprocess.call([node, str(script), *(args or ['help'])], env=env)


def parser():
    p = argparse.ArgumentParser(prog='zentr', description='Your terminal companion for zentr.dev.',
        epilog='Examples: zentr --login | zentr status | zentr drop upload photo.png')
    p.add_argument('--version', action='version', version=f'zentr {__version__}')
    modes = p.add_mutually_exclusive_group()
    modes.add_argument('--login', action='store_true', help='Sign in through your browser')
    modes.add_argument('--logout', action='store_true', help='Remove your local sign-in session')
    p.add_argument('--json', action='store_true', help='JSON output (place before command; excludes bundled Drop)')
    p.add_argument('--timeout', type=float, default=60, help='HTTP timeout in seconds (default: 60; excludes Drop)')
    sub = p.add_subparsers(dest='command')
    sub.add_parser('ui', aliases=['tui'], help='Open the interactive terminal interface')
    services = sub.add_parser('services', help='List the live Zentr project registry')
    services.add_argument('query', nargs='?', default='', help='Filter names')
    status = sub.add_parser('status', help='Service health and uptime')
    status.add_argument('service', nargs='?', help='Filter by name or ID')
    op = sub.add_parser('open', help='Open a registered service in your browser')
    op.add_argument('service', nargs='?')
    docs = sub.add_parser('docs', help='Open Zentr documentation')
    docs.add_argument('project', nargs='?')
    sub.add_parser('whoami', help='Show your signed-in account')
    auth_parser = sub.add_parser('auth', help='Sign-in and identity commands')
    auth_parser.set_defaults(group_parser=auth_parser)
    ac = auth_parser.add_subparsers(dest='auth_command')
    for name in ('login', 'logout', 'whoami', 'discovery'):
        ac.add_parser(name)
    drop = sub.add_parser('drop', help='Bundled Drop CLI: upload, text, get, status, shorten', add_help=False)
    drop.description = 'Commands: upload <file...>, text [message], get <URL> [-o folder], status <code>, shorten <URL>, help'
    drop.set_defaults(group_parser=drop)
    drop.add_argument('-h', '--help', action='store_true', dest='drop_help')
    drop.add_argument('args', nargs=argparse.REMAINDER)
    convert_parser = sub.add_parser('convert', help='Server-side file conversion')
    convert_parser.set_defaults(group_parser=convert_parser)
    cv = convert_parser.add_subparsers(dest='convert_command')
    cv.add_parser('formats', help='List currently available conversions')
    run = cv.add_parser('file', help='Upload and convert a file')
    run.add_argument('input', nargs='?')
    run.add_argument('--to', help='Conversion ID from convert formats')
    run.add_argument('-o', '--output', help='New destination file; never overwritten')
    run.add_argument('--options', default='{}', help='Converter options as a JSON object')
    return p


def main(argv=None, *, interactive=True):
    argv = list(sys.argv[1:] if argv is None else argv)
    # Accept the flag-style upload spelling without changing file arguments.
    index = 0
    while index < len(argv):
        if argv[index] == '--timeout':
            index += 2
        elif argv[index] == '--json' or argv[index].startswith('--timeout='):
            index += 1
        else:
            break
    if argv[index:index + 2] == ['drop', '--upload']:
        argv[index + 1] = 'upload'
    p = parser()
    args = p.parse_args(argv)
    if args.command and (args.login or args.logout):
        p.error('--login and --logout must be used without a subcommand')
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        p.error('--timeout must be a positive finite number')
    try:
        can_prompt = (interactive and not args.json and sys.stdin.isatty() and sys.stdout.isatty()
                      and os.environ.get('TERM') != 'dumb')
        runner = lambda values: main(values, interactive=False)
        interactive_default = (args.command is None and not args.login and not args.logout and can_prompt)
        if args.command in ('ui', 'tui') or interactive_default:
            if args.json:
                raise ZentrError('The terminal UI does not support --json. Use a service command instead.')
            if not can_prompt:
                p.print_help()
                return 0
            from .tui import launch
            return launch(runner, timeout=args.timeout)
        empty_group = ((args.command == 'auth' and not args.auth_command)
                       or (args.command == 'convert' and not args.convert_command)
                       or (args.command == 'drop' and not args.args and not args.drop_help))
        section = {'auth': 'account'}.get(args.command, args.command)
        browse_menu = ((args.command == 'status' and not args.service)
                       or (args.command == 'services' and not args.query)
                       or (args.command == 'docs' and not args.project))
        if can_prompt and (empty_group or browse_menu):
            from .tui import launch
            return launch(runner, timeout=args.timeout, section=section)
        if empty_group:
            args.group_parser.print_help()
            return 0
        if args.command == 'open' and not args.service:
            if not can_prompt:
                p.error('open requires a service name; run zentr services to list names')
            from .tui import ask
            args.service = ask('Open service', 'Service name:')
            if args.service is None:
                return 0
        if args.command == 'convert' and args.convert_command == 'file':
            fields = [('input', 'Input file path (Tab completes paths):', True),
                      ('to', 'Conversion ID (run zentr convert formats to list IDs):', False),
                      ('output', 'New output file path:', True)]
            missing = [name for name, _, _ in fields if not getattr(args, name)]
            if missing and not can_prompt:
                p.error('convert file requires an input file, --to and --output')
            for name, label, is_path in fields:
                if not getattr(args, name):
                    from .tui import ask
                    value = ask('Convert / ' + name, label, path=is_path)
                    if value is None:
                        return 0
                    setattr(args, name, value)
        if args.command == 'drop':
            if args.json:
                raise ZentrError('Bundled Drop has its own output format; omit --json.')
            if can_prompt and len(args.args) == 1 and args.args[0] in ('upload', 'text', 'get', 'status', 'shorten'):
                from .tui import ask
                operation = args.args[0]
                labels = {'upload': 'File path (Tab completes paths):', 'text': 'Text to encrypt and share:',
                          'get': 'Full direct Drop URL, including #key:', 'status': 'Drop code or full URL:',
                          'shorten': 'HTTP(S) URL to shorten:'}
                value = ask('Drop / ' + operation, labels[operation], path=operation == 'upload')
                if value is None:
                    return 0
                args.args.append(value)
                if operation == 'get':
                    destination = ask('Drop / destination', 'Destination directory (use . for current folder):', path=True)
                    if destination is None:
                        return 0
                    args.args.extend(['-o', destination])
            return run_drop(['help'] if args.drop_help else args.args)
        with Client(timeout=args.timeout) as client:
            action = getattr(args, 'auth_command', None)
            if args.login or action == 'login':
                profile = auth.login(client, announce=lambda s: print(s, file=sys.stderr))
                emit(profile if args.json else 'Signed in as ' + profile.get('name', profile['sub']), args.json)
            elif args.logout or action == 'logout':
                auth.logout()
                emit({'signed_in': False} if args.json else 'Local session removed. Browser sign-in is unchanged.', args.json)
            elif args.command == 'whoami' or action == 'whoami':
                emit(auth.whoami(client), args.json)
            elif action == 'discovery':
                emit(auth.discovery(client), True)
            elif args.command == 'services':
                rows = [r for r in client.services() if args.query.lower() in r['name'].lower()]
                if args.json:
                    emit(rows, True)
                else:
                    table([['SERVICE', 'URL']] + [[r['name'], r['url']] for r in rows])
            elif args.command == 'status':
                data = client.status()
                services = data['services']
                if args.service:
                    services = [r for r in services if args.service.lower() in (r['name'].lower(), r['id'].lower())]
                    if not services:
                        raise ZentrError('Service not found in status data.')
                if args.json:
                    emit({**data, 'services': services}, True)
                else:
                    emit(f"Overall: {data['overall']} | Updated: {data['updatedAt']}")
                    table([['SERVICE', 'STATE', 'LATENCY', 'UPTIME / 24H']] + [
                        [r['name'], 'UP' if r['up'] else 'DOWN', f"{r.get('latencyMs', '?')} ms", f"{r.get('uptime24h', '?')}%"] for r in services])
                return 0 if data.get('available', True) and all(r['up'] for r in services) else 1
            elif args.command in ('open', 'docs'):
                if args.command == 'docs':
                    if args.project and not all(c.isalnum() or c == '-' for c in args.project):
                        raise ZentrError('Use a project slug such as drop or convert.')
                    url = 'https://docs.zentr.dev' + ('/projects/' + args.project if args.project else '')
                else:
                    matches = [r for r in client.services() if r['name'].lower() == args.service.lower()]
                    if not matches:
                        raise ZentrError('Unknown service. Run zentr services.')
                    url = matches[0]['url']
                if not webbrowser.open(url):
                    raise ZentrError(f'Could not open a browser. Open {url}')
                emit({'url': url} if args.json else url, args.json)
            elif args.command == 'convert':
                if args.convert_command == 'formats':
                    caps = client.capabilities()
                    if args.json:
                        emit(caps, True)
                    else:
                        table([['CONVERSION', 'AVAILABLE']] + [[k, 'yes' if v else 'no'] for k, v in caps.items()])
                else:
                    options = json.loads(args.options)
                    if not isinstance(options, dict):
                        raise ZentrError('--options must be a JSON object.')
                    emit(client.convert(args.input, args.to, args.output, options), args.json)
            else:
                p.print_help()
        return 0
    except BrokenPipeError:
        return 0
    except (ZentrError, OSError, ValueError, httpx.HTTPError, subprocess.SubprocessError) as exc:
        message = ('Network request failed. Check your connection or try a longer --timeout.'
                   if isinstance(exc, httpx.HTTPError) else str(exc))
        if args.json:
            print(json.dumps({'error': message}), file=sys.stderr)
        else:
            print('zentr: ' + clean(message), file=sys.stderr)
        return 1
    except (KeyError, TypeError) as exc:
        print('zentr: Unexpected service response; update the CLI or retry later.', file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print('zentr: Cancelled.', file=sys.stderr)
        return 130
