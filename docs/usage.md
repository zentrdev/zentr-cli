# Zentr CLI

A local, installable Python CLI for zentr.dev: browser sign-in, service discovery,
live status, conversion, and the existing encrypted Drop CLI bundled as `zentr drop`.

## Install for testing

Requires Python 3.10+. Drop commands additionally require Node.js 20.11+ on PATH.
No separate Drop installation is needed.

From this directory:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
zentr --help
```

On Windows use `.venv\Scripts\activate` instead. If you already use pipx or uv,
`pipx install .` or `uv tool install .` makes `zentr` available outside a virtual environment.
GitHub is the distribution source. The package is not published to PyPI.

## Interactive terminal interface

The whole CLI supports guided use. Run `zentr` in a terminal for the home screen,
or enter a command group directly:

```sh
zentr drop       # Sharing menu
zentr convert    # Conversion menu
zentr auth       # Account menu
zentr services   # Browse, search, or open services
zentr status     # All services or one service
zentr docs       # Documentation home or a project
zentr open       # Prompts for a service name
zentr drop upload  # Prompts for a file
zentr convert file recording.wav  # Prompts for format and output
```

Incomplete commands ask only for missing required values. Fully specified commands
run directly. `zentr ui` and `zentr tui` explicitly open the home interface.
The black-and-purple menu includes a spaced Zentr wordmark, service status, service
browsing, account controls, Drop uploads/downloads/text/shortening, and conversion
prompts. Use arrow keys and Enter to open an item, Escape to go back, and Ctrl-C
to dismiss a dialog. Tab moves through menu rows. Path prompts support Tab completion;
enter paths and URLs directly, without shell quotes. Output remains visible in your
terminal; press Enter after a command to return to the menu.

Menus and forms use the same terminal panel. On narrow terminals, rows use shorter
descriptions or just the command name. Set `NO_COLOR=1` for a monochrome interface.
If stdin or stdout is not a terminal, or `TERM=dumb`, there are no prompts:
`zentr` and empty command groups print the relevant command list; incomplete
commands return an argument error. Explicit `zentr ui` also falls back to help.
Piped Drop text still reads stdin normally. `--json` commands never
launch the interface or include decorative output.

## Sign in

```sh
zentr --login
zentr whoami
zentr --logout
```

`zentr --login` opens auth.zentr.dev in your browser. Sign in and approve **Zentr CLI**.
The CLI listens only on `127.0.0.1:8787`, with the exact registered redirect
`http://localhost:8787/oauth/callback`. Keep this port free. The browser and CLI
must run on the same computer. Login waits up to three minutes; Ctrl-C cancels it.

The flow uses one-time state, S256 PKCE, nonce, and ES256 ID-token validation
(signature, issuer, audience, expiration, and nonce). Tokens are stored through
Python keyring in your OS credential store, not in project files. macOS uses Keychain;
Windows and Linux need a working keyring backend. There is no plaintext fallback.
Sessions currently expire after about 15 minutes; the service does not advertise
refresh tokens. Run `zentr --login` again when prompted. Logout removes only the
CLI's local session; it does not sign out your browser or revoke issued tokens.

Equivalent commands: `zentr auth login`, `zentr auth whoami`, `zentr auth logout`.
`zentr auth discovery` prints public OIDC discovery metadata.
For automation, `ZENTR_ACCESS_TOKEN` can supply an existing userinfo access token;
it overrides the stored session and is not removed by logout.

The CLI OAuth client was registered and verified on auth.zentr.dev on November 1,
2026. The scoped SQL is in `integration/register-cli.sql` at the repository root.

## Services and status

```sh
zentr services
zentr services drop
zentr status
zentr status convert
zentr --json status
zentr open tools
zentr docs
zentr docs drop
```

Services come from the live Zentr registry. Status uses the public status service,
including its observation timestamps; it is not a fresh probe performed by the CLI.
A failed/unavailable status or selected down service returns exit code 1.
Browser commands open the website; they do not emulate browser-only tools or games.

## Drop — the existing CLI, merged into Zentr

```sh
zentr drop upload photo.png notes.pdf
zentr drop --upload photo.png  # Alias for upload
zentr drop text "hello from my terminal"
echo "hello" | zentr drop text
zentr drop get 'https://drop.zentr.dev/f/CODE5#KEY' -o downloads
zentr drop get 'https://drop.zentr.dev/t/CODE5#KEY'
zentr drop status CODE5
zentr drop shorten 'https://example.com'
zentr drop help
```

Fully specified uploads work with stdin closed:

```sh
zentr drop --upload "$HOME/zentr.html" </dev/null
zsh -c 'zentr drop --upload "$HOME/zentr.html"' </dev/null
```

With `zsh -c`, quote the entire command; unquoted words after the command string
become shell positional arguments instead of arguments to Zentr.

This bundles the existing Drop JavaScript CLI and its shared crypto implementation,
not a reimplementation of the file protocol. It supports up to 20 files / 10 GiB,
32 MiB encrypted chunks, and 4 MiB transport parts. Files and text use local
AES-256-GCM encryption. The complete output link is the decryption capability;
keep its fragment private. Quote links in your shell.

File downloads verify encrypted content before publishing each file and never
overwrite existing files. If a later file fails, earlier completed files remain.
Text downloads go to stdout; file downloads default to the current directory.
Upload links go to stdout and progress to stderr. Shortening retains fragments
locally and sends only the fragment-free URL to the shortening API. Downloading
requires a full direct Drop link; shortened links can be opened in a browser.

Drop uploads in this release remain anonymous, temporary uploads. CLI account
login does not grant permanent Drop storage or attach uploads to your account:
the current Drop CLI does not implement that service's browser-session flow.
`DROP_ORIGIN` retains the original CLI's development-server override.
`--json` and `--timeout` do not apply to bundled Drop commands.

## Convert

```sh
zentr convert formats
zentr convert file recording.wav --to audio-wav-mp3 -o recording.mp3
zentr --timeout 300 convert file photo.heic --to heic-jpeg -o photo.jpg
zentr convert file photo.heic --to heic-jpeg -o photo.jpg --options '{"quality":90}'
```

Use a conversion ID reported by `formats`. Files are uploaded to Zentr Convert's
server; this command is not local conversion. Options are passed to the converter
as a JSON object, and supported options depend on that converter. Output paths
must be new files. Failed transfers remove their partial output. Input and output
are streamed, and server upload limits/rate limits still apply.

## Scripting and errors

Place global options before the subcommand: `zentr --json services`.
JSON is supported for Python commands. Normal errors go to stderr without HTTP
response bodies, authorization codes, or access tokens. Exit codes are 0 for
success, 1 for service/runtime failure (or down status), 2 for argument errors,
and 130 for interrupted Python operations. Drop preserves its existing exit behavior.

## Development

```sh
python -m pip install -e . pytest build
python -m pytest tests -q
node --test tests/drop.test.mjs
python -m build
```

Tests cover registry decoding, unsafe URLs, response limits, conversion multipart
requests, no-overwrite behavior, failed-download cleanup, OAuth state/Host checks,
one-time callbacks, PKCE exchange, signatures and identity claims, session expiry,
and bundled Drop cryptography. Loopback tests require permission to bind localhost.
Live smoke checks additionally exercised registry/status/discovery, registered-client
lookup, WAV → MP3 conversion, encrypted Drop text/file round trips, and URL shortening
using disposable samples. Real browser account consent remains for your interactive test.

Package name: `zentr-cli`; terminal command: `zentr`.
