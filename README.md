# gemini-cli

A full terminal chat client for **Google Gemini** (the web app, not the API
key) built on [`gemini-webapi`](https://github.com/HanaokaYuzu/Gemini-API) with
a [Textual](https://textual.textualize.io/) TUI — streaming replies, markdown
rendering, file attachments, generated-image saving, and persistent chats.

## Install

Requires **Python 3.11+**.

```sh
git clone <this-repo>
cd gemini-cli
pip install -e .
```

## Cookies

1. Log in to <https://gemini.google.com> in your browser.
2. Export the cookies for the `google.com` domain. Supported formats:
   - **Netscape `cookies.txt`** (e.g. "Get cookies.txt" extension)
   - **JSON** array (e.g. EditThisCookie export)
3. Save the file as `gemini.google.com_cookies.txt` next to where you run the
   CLI, or pass the path explicitly:

```sh
gemini-cli --cookies /path/to/gemini.google.com_cookies.txt
# or
export GEMINI_COOKIES=/path/to/cookies.txt
gemini-cli
```

The client automatically refreshes `__Secure-1PSIDTS` in the background while
it runs. For the longest-lived sessions, export cookies from a fresh/private
browser session and close it afterwards.

## Usage

```sh
gemini-cli
```

Type a message and press **Enter**. `gemini-webapi` streams the reply and the
TUI renders it as markdown.

### Commands

| Command | Description |
| --- | --- |
| `/help` | Show all commands |
| `/new` | Start a new conversation |
| `/save [name]` | Persist the current chat locally (`~/.gemini-cli/chats`) |
| `/resume <name>` | Resume a saved chat (`/chats` lists them) |
| `/model [name]` | Show or switch the language model (`/models` lists them) |
| `/tmp [on\|off]` | Toggle temporary mode (not saved to Gemini history) |
| `/attach <paths>` | Attach files to the next message |
| `/lines <n>` | Limit displayed reply lines (`0` = unlimited) |
| `/status` | Show session info (cid, model, mode) |
| `/clear` | Clear the screen, keep the conversation |
| `/exit` | Quit |

### Attaching files

Three ways:

- `/attach report.pdf image.png`
- `@report.pdf` inline in your message
- paste a bare existing file path in your message

Files are uploaded to Gemini and included in the prompt.

### Receiving files

When Gemini generates images, videos, or audio, they are saved automatically
to `./gemini_output/` and the paths are printed in the chat.

### Keyboard

- **Enter** — send message
- **Ctrl+X** — cancel the in-flight request

## Project layout

```
src/gemini_cli/
  cookies.py   # Netscape + JSON cookie export parser
  client.py    # async wrapper around gemini_webapi
  app.py       # Textual TUI
```
