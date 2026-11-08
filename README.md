<div align="center">

![Zentr CLI — your services, one terminal](assets/hero.svg)

**I built one terminal command for my zentr.dev services.**

[![Checks](https://github.com/zentrdev/zentr-cli/actions/workflows/check.yml/badge.svg)](https://github.com/zentrdev/zentr-cli/actions/workflows/check.yml)
![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-a77bff?style=flat-square&labelColor=08060c)
![Node 20.11+ for Drop](https://img.shields.io/badge/drop-Node.js%2020.11%2B-9893a4?style=flat-square&labelColor=08060c)
[![GitHub releases](https://img.shields.io/github/v/release/zentrdev/zentr-cli?style=flat-square&color=a77bff&labelColor=08060c)](https://github.com/zentrdev/zentr-cli/releases)

[**Get started**](#get-started) · [**The commands**](#the-commands) · [**Full guide**](docs/usage.md) · [**zentr.dev ↗**](https://zentr.dev)

</div>

---

## Why I built it

I wanted to send someone a file, check whether one of my services was down, or convert a recording without opening three browser tabs. That’s what `zentr` is for. When I don’t remember a command, I run `zentr` and pick from the menu. When I do, I type it directly.

```text
● ● ●                                      zentr / terminal
───────────────────────────────────────────────────────────
Z E N T R
ARROWS TO MOVE · ENTER TO OPEN

› STATUS     Service health and uptime
  EXPLORE    Browse Zentr services
  DROP       Encrypted file sharing
  CONVERT    Convert a file
  ACCOUNT    Browser sign-in
  DOCS       Project documentation
  QUIT       Return to shell
```

I used the terminal in the banner as the design reference: a purple bar follows the selection, descriptions line up beside the commands, and file prompts stay in the same panel. On a narrow screen I shorten the descriptions so the command names stay readable.

## Get started

I publish the CLI on [GitHub Releases](https://github.com/zentrdev/zentr-cli/releases). You’ll need **Python 3.10+**. For Drop, you’ll also need **Node.js 20.11+** on your PATH; I bundle the Drop CLI itself.

With **uv**:

```sh
uv tool install 'git+https://github.com/zentrdev/zentr-cli.git@v0.4.0'
zentr
```

With **pipx**:

```sh
pipx install 'git+https://github.com/zentrdev/zentr-cli.git@v0.4.0'
zentr
```

<details>
<summary>How I run it from a checkout</summary>

```sh
git clone https://github.com/zentrdev/zentr-cli.git
cd zentr-cli
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
zentr
```

On Windows, activate with `.venv\Scripts\activate`. I haven’t published the package to PyPI.

</details>

## How I use it

**For sharing**, I can upload a file and get its encrypted link on stdout, or pipe text straight into Drop:

```sh
zentr drop --upload "$HOME/report.html" </dev/null
printf 'Meet me at 7' | zentr drop text
```

**For conversion**, I check which formats the server currently offers, then choose one by ID:

```sh
zentr convert formats
zentr convert file voice.wav --to audio-wav-mp3 -o voice.mp3
```

**For service health**, I use the menu when I’m exploring and JSON when I want a record:

```sh
zentr status
zentr --json status > status.json
```

I kept the shell behavior predictable: fully specified commands run immediately. With stdin or stdout redirected, or `TERM=dumb`, the CLI won’t prompt. Bare `zentr` prints the command list, and omitted required inputs produce an argument error. In the menu, use **↑ ↓** to move, **Enter** to open, and **Esc** to go back. **Tab** cycles through menu rows or completes paths in file fields. Set `NO_COLOR=1` for monochrome.

## The commands

| When I want to… | I run… |
| :--- | :--- |
| Open the home screen | `zentr` |
| Sign in through my browser | `zentr --login` |
| Check which account I’m using | `zentr whoami` |
| Remove my local session | `zentr --logout` |
| Find a service or open its website | `zentr services` · `zentr open tools` |
| Check a specific service | `zentr status convert` |
| Read a project’s docs | `zentr docs drop` |
| Share several files | `zentr drop upload photo.png notes.pdf` |
| Download an encrypted file | `zentr drop get 'https://drop.zentr.dev/f/CODE5#KEY' -o downloads` |
| Check a drop or shorten a URL | `zentr drop status CODE5` · `zentr drop shorten 'https://example.com'` |
| See all options | `zentr --help` |

I put global options before the command, as in `zentr --timeout 300 convert file photo.heic --to heic-jpeg -o photo.jpg`. The bundled Drop commands keep their own output and timeout behavior.

## What happens to my data?

<details>
<summary><strong>Drop: what I share with the recipient</strong></summary>

I encrypt files and text locally with the original Drop CLI’s AES-256-GCM implementation. The full link, including its `#KEY`, gives the recipient access. Keep that fragment private and quote the link in your shell. When shortening a link, the CLI sends only the fragment-free URL and reattaches the fragment locally.

I can upload up to **20 files / 10 GiB**, subject to service limits. Downloads verify each file and never overwrite existing files. CLI drops are anonymous and temporary, even when I’m signed into Zentr.

</details>

<details>
<summary><strong>Sign-in: where I keep the session</strong></summary>

I use browser sign-in with S256 PKCE, one-time state, nonce checks, and verified ES256 ID tokens. Run `zentr --login` on the same computer as your browser and leave localhost port **8787** free for the callback. The CLI stores the session through your OS keyring. A working keyring backend is required.

Sessions currently last about 15 minutes. `zentr --logout` removes the local CLI session; it doesn’t sign out your browser. For scripts, `ZENTR_ACCESS_TOKEN` can supply an existing userinfo token instead.

</details>

<details>
<summary><strong>Convert: where I send the file</strong></summary>

I send the input file to Zentr Convert for server-side conversion. The destination must be a new file. If a transfer fails, the CLI removes the partial output. Check `zentr convert formats` before picking a conversion ID.

</details>

## Development

These are the checks I run from a local checkout:

```sh
python -m pip install -e . pytest build
python -m pytest tests -q
node --test tests/drop.test.mjs
python -m build
```

I keep the longer examples, shell quoting notes, and exit codes in the [usage guide](docs/usage.md). If something breaks, [open an issue](https://github.com/zentrdev/zentr-cli/issues) with the command you ran and what happened. Please leave out tokens and private Drop links.

---

<div align="center">

**My main account:** [@z-alexanderr](https://github.com/z-alexanderr) · **My services:** [zentr.dev](https://zentr.dev)

</div>
