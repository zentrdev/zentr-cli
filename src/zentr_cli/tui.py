"""Interactive terminal launcher; command implementations remain shared with CLI."""
import os
import shutil
import sys
from pathlib import Path

from prompt_toolkit import prompt
from prompt_toolkit.application import Application
from prompt_toolkit.completion import PathCompleter
from prompt_toolkit.filters import has_focus
from prompt_toolkit.key_binding import KeyBindings, merge_key_bindings
from prompt_toolkit.layout import Layout, HSplit
from prompt_toolkit.shortcuts import input_dialog
from prompt_toolkit.styles import Style
from prompt_toolkit.widgets import Button, Dialog, Label, RadioList

from . import __version__
from .client import ZentrError

BANNER = r""" _____  _____  _   _  _____  ____
|__  / | ____|| \ | ||_   _||  _ \
  / /  |  _|  |  \| |  | |  | |_) |
 / /_  | |___ | |\  |  | |  |  _ <
/____| |_____||_| \_|  |_|  |_| \_\
""".rstrip()

STYLE = Style.from_dict({
    'dialog': 'bg:#000000 #f3f1f7',
    'dialog.body': 'bg:#000000 #f3f1f7',
    'dialog frame.label': 'bg:#000000 #a77bff bold',
    'dialog frame.border': '#7447d8',
    'dialog shadow': 'bg:#000000',
    'radio': '#9893a4',
    'radio-selected': '#a77bff bold',
    'radio-checked': '#a77bff bold',
    'button': 'bg:#23202a #f3f1f7',
    'button.focused': 'bg:#7447d8 #ffffff bold',
    'text-area': 'bg:#0e0b14 #f3f1f7',
})

MENU = [
    ('status', 'STATUS     Service health, latency and uptime'),
    ('services', 'EXPLORE    List or open Zentr services'),
    ('drop', 'DROP       Encrypt, share and download'),
    ('convert', 'CONVERT    Upload a file and convert it'),
    ('account', 'ACCOUNT    Browser sign-in and profile'),
    ('docs', 'DOCS       Open Zentr documentation'),
    ('quit', 'QUIT       Return to your shell'),
]


def style():
    # Respect explicit monochrome preferences.
    return Style.from_dict({}) if 'NO_COLOR' in os.environ else STYLE


def choose(title, description, values, home=False):
    width, height = shutil.get_terminal_size((80, 24))
    art = BANNER if home and width >= 55 and height >= 28 else 'Z E N T R  /  TERMINAL'
    text = (art + f'\n\nv{__version__}  |  zentr.dev\n\n' if home else '') + description
    choices = RadioList(values, select_on_focus=True, show_scrollbar=False)
    keys = KeyBindings()

    @keys.add('enter', filter=has_focus(choices), eager=True)
    def accept(event):
        event.app.exit(result=choices.current_value)

    dialog = Dialog(title=title, body=HSplit([Label(text), choices], padding=1),
                    buttons=[Button('Open', handler=lambda: app.exit(result=choices.current_value)),
                             Button('Quit' if home else 'Back', handler=lambda: app.exit())],
                    with_background=True)
    app = Application(layout=Layout(dialog, focused_element=choices), key_bindings=keys,
                      full_screen=True, mouse_support=True, style=style())
    return run_dialog(app)


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
    result = run_dialog(input_dialog(title=title, text=text + '\nCancel to go back.',
                          ok_text='Continue', cancel_text='Back',
                          completer=PathCompleter(expanduser=True) if path else None,
                          style=style()))
    if result is None or not result.strip():
        return None
    return str(Path(result).expanduser()) if path else result.strip()


def perform(run, args):
    # Full-screen dialogs restore the terminal before commands run. Links, files,
    # login messages and transfer progress retain their original stdout/stderr.
    print('\n' + '-' * min(shutil.get_terminal_size().columns, 68))
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
