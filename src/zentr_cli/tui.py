"""Interactive terminal launcher; command implementations remain shared with CLI."""
import os
import textwrap
import sys
from pathlib import Path

from prompt_toolkit import prompt
from prompt_toolkit.application import Application
from prompt_toolkit.completion import PathCompleter
from prompt_toolkit.application.current import get_app
from prompt_toolkit.filters import Condition
from prompt_toolkit.key_binding import KeyBindings, merge_key_bindings
from prompt_toolkit.layout import Layout, HSplit, VSplit, Window, ConditionalContainer, Dimension
from prompt_toolkit.layout.containers import HorizontalAlign, VerticalAlign
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.mouse_events import MouseEventType

from prompt_toolkit.styles import Style
from prompt_toolkit.widgets import TextArea

from . import __version__
from .client import ZentrError

BANNER = 'Z E N T R'

STYLE = Style.from_dict({
    'screen': 'bg:#000000 #f3f1f7', 'panel': 'bg:#08060c #f3f1f7',
    'muted': '#9893a4', 'accent': '#a77bff bold', 'edge': '#352747',
    'selected': 'bg:#20132f #f3f1f7', 'field': 'bg:#20132f #f3f1f7',
})
MONO = Style.from_dict({'selected': 'reverse', 'accent': 'bold', 'field': 'underline'})
MENU = [
    ('status', 'STATUS    Service health and uptime'),
    ('services', 'EXPLORE   Browse Zentr services'),
    ('drop', 'DROP      Encrypted file sharing'),
    ('convert', 'CONVERT   Convert a file'),
    ('account', 'ACCOUNT   Browser sign-in'),
    ('docs', 'DOCS      Project documentation'),
    ('quit', 'QUIT      Return to shell'),
]


def style():
    return MONO if 'NO_COLOR' in os.environ else STYLE


def _width():
    return max(1, min(66, get_app().output.get_size().columns - 4))


def _content_width():
    return max(1, _width() - 4)


def _line(text, css=''):
    return Window(FormattedTextControl(text), height=1, style=css)


def _screen(title, description, body, focus, keys, hint):
    # The same shell surrounds navigation and editable fields. Its fixed-width
    # column is centered on wide displays and shrinks with the terminal.
    roomy = Condition(lambda: get_app().output.get_size().rows >= 17)
    header = _line(lambda: [('class:accent', '● '), ('class:muted', '● '), ('class:accent', '●'),
                            ('class:muted', 'zentr / terminal'.rjust(max(16, _content_width() - 5)))])
    def wrapped():
        return textwrap.fill(description, width=_content_width())
    intro = Window(FormattedTextControl(wrapped), style='class:muted', dont_extend_height=True)
    items = [ConditionalContainer(_line(''), roomy), header, _line(lambda: '─' * _content_width(), 'class:edge'),
             ConditionalContainer(_line(''), roomy), _line(title, 'class:accent'), intro,
             ConditionalContainer(_line(''), roomy), body,
             ConditionalContainer(_line(''), roomy), _line(hint, 'class:muted'),
             ConditionalContainer(_line(''), roomy)]
    card = VSplit([Window(width=2), HSplit(items), Window(width=2)], width=_width,
                  style='class:panel', padding=0)
    canvas = HSplit([VSplit([card], align=HorizontalAlign.CENTER)], align=VerticalAlign.CENTER,
                    style='class:screen')
    app = Application(layout=Layout(canvas, focused_element=focus), key_bindings=keys,
                      full_screen=True, mouse_support=True, style=style(), include_default_pygments_style=False)
    return run_dialog(app)


def choose(title, description, values, home=False):
    selected = 0
    keys = KeyBindings()
    def move(delta):
        nonlocal selected
        selected = (selected + delta) % len(values)
    for key, delta in [('up', -1), ('down', 1), ('s-tab', -1), ('tab', 1), ('k', -1), ('j', 1)]:
        keys.add(key)(lambda event, delta=delta: move(delta))
    @keys.add('enter', eager=True)
    def accept(event):
        event.app.exit(result=values[selected][0])
    @keys.add('q')
    def back(event):
        event.app.exit()

    def render():
        lines = []
        width = _content_width()
        for index, (value, label) in enumerate(values):
            active = index == selected
            name, desc = (label.split(None, 1) if home else (label, ''))
            marker = '› ' if active else '  '
            name = (name.ljust(10) if desc and width >= 22 else name)[:max(0, width-2)]
            space = max(0, width - 2 - len(name))
            short = {'status': 'Health & uptime', 'services': 'Find services', 'drop': 'File sharing',
                     'convert': 'File conversion', 'account': 'Sign in', 'docs': 'Project guides', 'quit': 'Exit'}
            detail = desc if len(desc) <= space else short.get(value, '')
            if len(detail) > space or width < 22:
                detail = ''
            row = 'class:selected ' if active else ''
            def click(event, value=value):
                if event.event_type == MouseEventType.MOUSE_UP:
                    get_app().exit(result=value)
            if active:
                lines.append(('[SetCursorPosition]', ''))
            lines.extend([(row + ('class:accent' if active else ''), marker + name, click),
                          (row + ('' if active else 'class:muted'), detail, click),
                          (row, ' ' * max(0, width-2-len(name)-len(detail)), click)])
            if index < len(values) - 1:
                lines.append(('', '\n'))
        return lines
    control = FormattedTextControl(render, focusable=True, show_cursor=False)
    rows = Window(control, height=Dimension(preferred=len(values), max=len(values)), wrap_lines=False)
    return _screen(BANNER if home else f'ZENTR  /  {title.upper()}',
                   'ARROWS TO MOVE · ENTER TO OPEN' if home else description, rows, control, keys,
                   f'v{__version__}   ·   q quit' if home else '↑↓ move   ·   Enter open   ·   Esc back')


def run_dialog(app):
    keys = KeyBindings()

    @keys.add('c-c', eager=True)
    @keys.add('c-d', eager=True)
    @keys.add('escape', eager=True)
    def cancel(event):
        event.app.exit(result=None)

    app.key_bindings = merge_key_bindings([app.key_bindings or KeyBindings(), keys])
    return app.run()


def ask(title, text, path=False):
    keys = KeyBindings()
    def submit(buffer):
        get_app().exit(result=buffer.text)
        return True
    field = TextArea(multiline=False, prompt='› ', style='class:field', height=1,
                     completer=PathCompleter(expanduser=True) if path else None,
                     accept_handler=submit)
    @keys.add('tab', eager=True)
    def complete(event):
        if path:
            if field.buffer.complete_state:
                field.buffer.complete_next()
            else:
                field.buffer.start_completion(select_first=True)
    hint = 'Enter continue   ·   Esc back' + ('   ·   Tab complete' if path else '')
    result = _screen(f'ZENTR  /  {title.upper()}', text, field, field, keys, hint)
    if result is None or not result.strip():
        return None
    return str(Path(result).expanduser()) if path else result.strip()


def perform(run, args):
    # Full-screen dialogs restore the terminal before commands run. Links, files,
    # login messages and transfer progress retain their original stdout/stderr.
    print('\nZ E N T R   /   ' + args[2].upper())
    result = run(args)
    print('\n' + ('[OK] Finished.' if result == 0 else '[!] Command did not complete successfully.'))
    prompt('Press Enter to return to Zentr… ')


def launch(run, timeout=60, section=None):
    if not (sys.stdin.isatty() and sys.stdout.isatty()) or os.environ.get('TERM') == 'dumb':
        raise ZentrError('The terminal UI needs an interactive terminal. Use zentr --help for commands.')

    def execute(args):
        perform(run, ['--timeout', str(timeout), *args])

    try:
        while True:
            action = section or choose('Zentr', 'Arrows: move   Enter: open   Esc: back   Ctrl-C: close', MENU, home=True)
            if action in (None, 'quit'):
                return 0
            if action == 'status':
                selected = choose('Status', 'View the last public service observations.', [
                    ('all', 'Show all service health'), ('one', 'Check a specific service')])
                if selected is None and section:
                    return 0
                if selected == 'all':
                    execute(['status'])
                elif selected == 'one':
                    value = ask('Service status', 'Service name or ID:')
                    if value:
                        execute(['status', value])
            elif action == 'services':
                selected = choose('Explore', 'Find a service or launch its website.', [
                    ('list', 'List all services'), ('filter', 'Search services'), ('open', 'Open a service in the browser')])
                if selected is None and section:
                    return 0
                if selected == 'list':
                    execute(['services'])
                elif selected == 'filter':
                    query = ask('Find services', 'Search service names:')
                    if query:
                        execute(['services', query])
                elif selected == 'open':
                    name = ask('Open service', 'Service name (for example: tools, drop, convert):')
                    if name:
                        execute(['open', name])
            elif action == 'account':
                selected = choose('Account', 'Sign-in is stored in your OS credential store.', [
                    ('login', 'Sign in through your browser'), ('whoami', 'View your profile'),
                    ('logout', 'Sign out of the CLI'), ('discovery', 'View public sign-in configuration')])
                if selected is None and section:
                    return 0
                if selected:
                    execute(['auth', selected])
            elif action == 'docs':
                selected = choose('Documentation', 'Open documentation in your browser.', [
                    ('all', 'Open documentation home'), ('project', 'Open project documentation')])
                if selected is None and section:
                    return 0
                if selected == 'all':
                    execute(['docs'])
                elif selected == 'project':
                    project = ask('Project documentation', 'Project slug (for example: drop):')
                    if project:
                        execute(['docs', project])
            elif action == 'convert':
                selected = choose('Convert', 'Conversion uploads your file to the Zentr server.', [
                    ('formats', 'List available conversion IDs'), ('file', 'Convert a file')])
                if selected is None and section:
                    return 0
                if selected == 'formats':
                    execute(['convert', 'formats'])
                elif selected == 'file':
                    source = ask('Convert / input', 'Path to the input file (Tab completes paths):', path=True)
                    if source is None:
                        continue
                    conversion = ask('Convert / format', 'Conversion ID (for example: audio-wav-mp3):')
                    if conversion is None:
                        continue
                    output = ask('Convert / output', 'New output file path (existing files are never overwritten):', path=True)
                    if output:
                        execute(['convert', 'file', source, '--to', conversion, '-o', output])
            elif action == 'drop':
                selected = choose('Drop', 'Encrypted, anonymous temporary sharing. Keep the full link private.', [
                    ('upload', 'Upload files'), ('text', 'Share text'), ('get', 'Download a drop'),
                    ('status', 'Check a drop'), ('shorten', 'Shorten a URL')])
                if selected is None and section:
                    return 0
                if selected == 'upload':
                    paths = []
                    while len(paths) < 20:
                        value = ask('Drop / upload', f'File {len(paths) + 1} path (Tab completes paths):', path=True)
                        if value is None:
                            paths = []
                            break
                        paths.append(value)
                        next_action = choose('Drop / upload', f'{len(paths)} file(s) selected.', [
                            ('send', 'Encrypt and upload now'), ('add', 'Add another file')])
                        if next_action is None:
                            paths = []
                            break
                        if next_action == 'send':
                            break
                    if paths:
                        execute(['drop', 'upload', *paths])
                elif selected == 'get':
                    url = ask('Drop / download', 'Full direct Drop URL, including #key (no shell quotes):')
                    if url:
                        directory = ask('Drop / destination', 'Destination folder for files (use . for current folder):', path=True)
                        if directory:
                            execute(['drop', 'get', url, '-o', directory])
                elif selected:
                    labels = {'text': 'Text to encrypt and share:', 'status': 'Drop code or full URL:',
                              'shorten': 'HTTP(S) URL to shorten:'}
                    value = ask('Drop / ' + selected, labels[selected])
                    if value:
                        execute(['drop', selected, value])
    except (KeyboardInterrupt, EOFError):
        return 0
