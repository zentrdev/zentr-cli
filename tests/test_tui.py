import pytest
from zentr_cli import tui
from zentr_cli.cli import main
from zentr_cli.client import ZentrError


def interactive(monkeypatch):
    monkeypatch.setattr(tui.sys.stdin, 'isatty', lambda: True)
    monkeypatch.setattr(tui.sys.stdout, 'isatty', lambda: True)
    monkeypatch.setenv('TERM', 'xterm-256color')


def test_nonterminal_rejected(monkeypatch):
    monkeypatch.setattr(tui.sys.stdin, 'isatty', lambda: False)
    with pytest.raises(ZentrError, match='interactive terminal'):
        tui.launch(lambda _: 0)


def test_default_terminal_opens_menu(monkeypatch):
    interactive(monkeypatch)
    monkeypatch.setattr(tui, 'launch', lambda run, timeout: 7)
    assert main([]) == 7


def test_json_ui_rejected(capsys):
    assert main(['--json', 'ui']) == 1
    assert 'does not support --json' in capsys.readouterr().err


def test_upload_preserves_spaces_and_cancellation(monkeypatch):
    interactive(monkeypatch)
    choices = iter(['drop', 'upload', 'send', 'drop', 'upload', 'quit'])
    inputs = iter(['/tmp/my photo.png', None])
    calls = []
    monkeypatch.setattr(tui, 'choose', lambda *a, **k: next(choices))
    monkeypatch.setattr(tui, 'ask', lambda *a, **k: next(inputs))
    monkeypatch.setattr(tui, 'perform', lambda run, args: calls.append(args))
    assert tui.launch(lambda _: 0, timeout=90) == 0
    assert calls == [['--timeout', '90', 'drop', 'upload', '/tmp/my photo.png']]


def test_convert_and_account_dispatch(monkeypatch):
    interactive(monkeypatch)
    choices = iter(['convert', 'file', 'account', 'login', 'quit'])
    inputs = iter(['/tmp/input.wav', 'audio-wav-mp3', '/tmp/output.mp3'])
    calls = []
    monkeypatch.setattr(tui, 'choose', lambda *a, **k: next(choices))
    monkeypatch.setattr(tui, 'ask', lambda *a, **k: next(inputs))
    monkeypatch.setattr(tui, 'perform', lambda run, args: calls.append(args))
    assert tui.launch(lambda _: 0) == 0
    assert calls[0][2:] == ['convert', 'file', '/tmp/input.wav', '--to', 'audio-wav-mp3', '-o', '/tmp/output.mp3']
    assert calls[1][2:] == ['auth', 'login']


def test_menu_cancel_does_not_run_commands(monkeypatch):
    interactive(monkeypatch)
    monkeypatch.setattr(tui, 'choose', lambda *a, **k: None)
    assert tui.launch(lambda _: pytest.fail('unexpected command')) == 0


@pytest.mark.parametrize('stdin_tty,stdout_tty', [(False, True), (True, False), (False, False)])
def test_bare_noninteractive_prints_command_list(monkeypatch, capsys, stdin_tty, stdout_tty):
    monkeypatch.setattr(tui.sys.stdin, 'isatty', lambda: stdin_tty)
    monkeypatch.setattr(tui.sys.stdout, 'isatty', lambda: stdout_tty)
    monkeypatch.setattr(tui, 'launch', lambda *a, **k: pytest.fail('UI must not open'))
    assert main([]) == 0
    output = capsys.readouterr().out
    assert 'usage: zentr' in output and 'convert' in output and 'services' in output
    assert tui.BANNER not in output


@pytest.mark.parametrize('command,section', [('drop', 'drop'), ('convert', 'convert'), ('auth', 'account'), ('status', 'status'), ('services', 'services'), ('docs', 'docs')])
def test_each_group_is_interactive(monkeypatch, command, section):
    interactive(monkeypatch)
    calls = []
    monkeypatch.setattr(tui, 'launch', lambda run, timeout, section: calls.append(section) or 0)
    assert main([command]) == 0
    assert calls == [section]


@pytest.mark.parametrize('command', ['auth', 'convert'])
def test_noninteractive_groups_show_help(monkeypatch, capsys, command):
    monkeypatch.setattr(tui.sys.stdin, 'isatty', lambda: False)
    assert main([command]) == 0
    assert f'usage: zentr {command}' in capsys.readouterr().out


def test_partial_conversion_asks_only_missing_fields(monkeypatch):
    interactive(monkeypatch)
    asked = []
    def ask(title, label, path=False):
        asked.append(title)
        return '/tmp/new output.mp3'
    monkeypatch.setattr(tui, 'ask', ask)
    calls = []
    monkeypatch.setattr('zentr_cli.cli.Client.convert', lambda self, *a: calls.append(a) or {'ok': True})
    assert main(['convert', 'file', '/tmp/input.wav', '--to', 'audio-wav-mp3']) == 0
    assert asked == ['Convert / output']
    assert calls[0] == ('/tmp/input.wav', 'audio-wav-mp3', '/tmp/new output.mp3', {})


def test_partial_noninteractive_conversion_errors_without_prompt(monkeypatch):
    monkeypatch.setattr(tui.sys.stdin, 'isatty', lambda: False)
    monkeypatch.setattr(tui, 'ask', lambda *a, **k: pytest.fail('unexpected prompt'))
    with pytest.raises(SystemExit) as error:
        main(['convert', 'file', 'input.wav'])
    assert error.value.code == 2


@pytest.mark.parametrize('operation', ['upload', 'text', 'get', 'status', 'shorten'])
def test_drop_commands_prompt_for_missing_value(monkeypatch, operation):
    interactive(monkeypatch)
    answers = iter(['value with spaces', '/tmp/output'])
    monkeypatch.setattr(tui, 'ask', lambda *a, **k: next(answers))
    calls = []
    monkeypatch.setattr('zentr_cli.cli.run_drop', lambda args: calls.append(args) or 0)
    assert main(['drop', operation]) == 0
    expected = [operation, 'value with spaces']
    if operation == 'get':
        expected.extend(['-o', '/tmp/output'])
    assert calls == [expected]


def test_piped_drop_text_is_not_prompted(monkeypatch):
    monkeypatch.setattr(tui.sys.stdin, 'isatty', lambda: False)
    monkeypatch.setattr(tui, 'ask', lambda *a, **k: pytest.fail('unexpected prompt'))
    calls = []
    monkeypatch.setattr('zentr_cli.cli.run_drop', lambda args: calls.append(args) or 0)
    assert main(['drop', 'text']) == 0
    assert calls == [['text']]


def test_scoped_menu_returns_without_root(monkeypatch):
    interactive(monkeypatch)
    monkeypatch.setattr(tui, 'choose', lambda *a, **k: None)
    assert tui.launch(lambda _: pytest.fail('unexpected command'), section='account') == 0


def test_ui_command_runner_does_not_reopen_menus(monkeypatch):
    interactive(monkeypatch)
    def launch(run, timeout, section):
        assert section == 'services'
        return run(['services'])
    monkeypatch.setattr(tui, 'launch', launch)
    monkeypatch.setattr('zentr_cli.cli.Client.services', lambda self: [])
    assert main(['services']) == 0


@pytest.mark.parametrize('prefix', [[], ['--timeout', '30'], ['--timeout=30']])
@pytest.mark.parametrize('spelling', ['upload', '--upload'])
def test_noninteractive_upload_dispatches_without_help(monkeypatch, capsys, prefix, spelling):
    monkeypatch.setattr(tui.sys.stdin, 'isatty', lambda: False)
    calls = []
    monkeypatch.setattr('zentr_cli.cli.run_drop', lambda args: calls.append(args) or 0)
    assert main([*prefix, 'drop', spelling, '/tmp/my file.html']) == 0
    assert calls == [['upload', '/tmp/my file.html']]
    assert 'usage:' not in capsys.readouterr().out


def test_upload_alias_does_not_rewrite_text(monkeypatch):
    monkeypatch.setattr(tui.sys.stdin, 'isatty', lambda: False)
    calls = []
    monkeypatch.setattr('zentr_cli.cli.run_drop', lambda args: calls.append(args) or 0)
    assert main(['drop', 'text', 'drop', '--upload']) == 0
    assert calls == [['text', 'drop', '--upload']]
