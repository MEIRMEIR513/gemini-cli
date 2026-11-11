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
| `/chats` | List saved local chats |
| `/model [name]` | Show or switch the language model (`/models` lists them) |
| `/models` | List available models |
| `/cookies` | Set cookies interactively (no file needed) |
| `/history` | List chats from Gemini's server history |
| `/read <cid>` | Read a Gemini chat's history (10 turns) |
| `/resume-gemini <cid>` | Resume a Gemini chat by cid |
| `/tmp [on\|off]` | Toggle temporary mode (not saved to Gemini history) |
| `/attach <paths>` | Attach files to the next message |
| `/lines <n>` | Limit displayed reply lines (`0` = unlimited) |
| `/copy` | Copy all recent messages (status, saved files, responses) |
| `/print` | Print all recent messages to terminal for selection (suspends TUI) |
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
- **Shift+Enter** or **Ctrl+J** — insert newline (multiline input)
- **Ctrl+C** — copy selected text (click on response first)
- **Ctrl+X** — cancel the in-flight request
- **Ctrl+Z** — suspend app (Unix only, resume with `fg`)

### Copying text

- **Click** on the response text to select it (Textual's built-in selection)
- **Ctrl+C** to copy the selection
- `/copy` — copy last reply (tries pyperclip → OSC 52 → suspend TUI print)
- `/print` — suspend TUI and print reply to terminal for native selection

**For Azure Cloud Shell / SSH:** Use `/print` — it suspends the TUI and prints
the text directly to the terminal, allowing you to use the terminal's native
selection (mouse drag) to copy text. This works in any terminal that supports
basic text selection.

**Note:** Hebrew/Arabic text may appear reversed depending on your terminal emulator. This is a terminal limitation, not the app. WezTerm, kitty, and iTerm handle bidirectional (BiDi) text correctly.

## Project layout

```
src/gemini_cli/
  cookies.py   # Netscape + JSON cookie export parser
  client.py    # async wrapper around gemini_webapi
  app.py       # Textual TUI with BiDi support
```

## BiDi (Hebrew/Arabic) support

The app automatically applies the Unicode Bidirectional Algorithm (UAX #9) via `python-bidi` to all displayed text. This ensures Hebrew/Arabic text renders correctly even in terminals that don't support BiDi natively.
