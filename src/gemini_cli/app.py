"""Textual TUI chat client for Google Gemini via gemini-webapi."""

from __future__ import annotations

import asyncio
import os
import shlex
import sys
import time
from pathlib import Path

import pyperclip
from bidi.algorithm import get_display
from textual import events, on
from textual.app import App, ComposeResult
from textual.containers import VerticalScroll
from textual.message import Message
from textual.widgets import Footer, Header, Markdown, Static, TextArea

from .client import GeminiSession

OUTPUT_DIR = Path("gemini_output")

HELP = """\
Commands:
  /help               show this help
  /new                start a new conversation
  /save [name]        persist current chat (default name: "last")
  /resume <name>      resume a saved chat (/chats lists them)
  /chats              list saved chats
  /model [name]       show or switch model (/models lists them)
  /models             list available models
  /cookies            set cookies interactively (no file needed)
  /history            list chats from Gemini's server history
  /read <cid>         read a Gemini chat's history
  /resume-gemini <cid> resume a Gemini chat by cid
  /tmp [on|off]       toggle temporary mode (not saved to Gemini history)
  /attach <paths>     attach files to the next message
  /lines <n>          max lines shown per reply (0 = unlimited)
  /copy               copy the last Gemini reply to the clipboard
  /status             show session info
  /clear              clear the screen (keeps the conversation)
  /exit, /quit        exit

Tips:
  - Enter sends. Shift+Enter (or Ctrl+J) inserts a newline — on terminals
    that can't tell them apart, a backslash followed quickly by Enter works too.
  - To copy text: click on the response text to select it, then press Ctrl+C.
    This uses Textual's built-in selection (works in most modern terminals).
  - Prefix a file path with @ (e.g. @report.pdf) or paste a bare path
    to attach it to your message automatically.
  - Press Ctrl+X while Gemini is replying to cancel the request.
  - Note: Hebrew/Arabic text may appear reversed depending on your terminal.
    This is a terminal limitation — WezTerm/kitty/iTerm handle BiDi correctly.
"""


class ChatInput(TextArea):
    """Multiline input: Enter submits, Shift+Enter / Ctrl+J inserts newline.

    Some terminals can't distinguish Shift+Enter and send a literal backslash
    followed by Enter instead (e.g. VSCode's built-in terminal) — that pair is
    detected by timestamp and converted into a newline as well.
    """

    _BACKSLASH_ENTER_GAP = 0.15

    class Submitted(Message):
        def __init__(self, input: "ChatInput", value: str) -> None:
            super().__init__()
            self.input = input
            self.value = value

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._backslash_time: float | None = None

    def action_insert_newline(self) -> None:
        self.insert("\n")

    async def _on_key(self, event: events.Key) -> None:
        now = time.monotonic()
        if event.key == "enter":
            event.stop()
            event.prevent_default()
            # Terminal workaround: '\\' + Enter (emitted for Shift+Enter)
            if (
                self._backslash_time is not None
                and now - self._backslash_time <= self._BACKSLASH_ENTER_GAP
                and self.text.endswith("\\")
            ):
                self._backslash_time = None
                self.action_delete_left()  # remove the stray backslash
                self.action_insert_newline()
                return
            self._backslash_time = None
            text = self.text.strip()
            if text:
                self.post_message(self.Submitted(input=self, value=text))
            return
        if event.key == "\\":
            self._backslash_time = now
        if event.key in ("shift+enter", "ctrl+j", "alt+enter"):
            event.stop()
            event.prevent_default()
            self.action_insert_newline()
            return
        await super()._on_key(event)


class GeminiTUI(App):
    TITLE = "Gemini CLI"
    ALLOW_SELECT = True
    CSS = """
    #chat { height: 1fr; }
    #status { height: 1; padding: 0 1; color: $text-muted; }
    #input { dock: bottom; height: auto; max-height: 40%; min-height: 3; }
    .msg-user { margin: 1 0 0 0; }
    .msg-user > .lbl { color: $accent; text-style: bold; }
    .msg-ai > .lbl { color: $success; text-style: bold; }
    .msg-meta { color: $text-muted; height: auto; }
    .msg-err { color: $error; }
    """
    BINDINGS = [("ctrl+x", "cancel_worker", "Cancel")]

    def __init__(self, cookies_path: str, **kwargs):
        super().__init__(**kwargs)
        self.session = GeminiSession(cookies_path)
        self.pending_files: list[str] = []
        self.max_lines = 0
        self.busy = False
        self._worker = None
        self._last_stream_update = 0.0
        self.last_response = ""
        self._cookie_prompt_state = None  # None, "psid", "psidts"

    # ---- layout -----------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll(id="chat"):
            yield Static("Connecting to Gemini...", id="boot")
        yield Static("", id="status")
        yield ChatInput(id="input")
        yield Footer()

    async def on_mount(self) -> None:
        ta = self.query_one("#input", ChatInput)
        ta.soft_wrap = True
        ta.show_line_numbers = False
        ta.placeholder = "Message Gemini... (Enter=send, Shift+Enter=newline)"
        ta.focus()
        await self._init_session()

    async def _init_session(self) -> None:
        try:
            await self.session.init()
        except Exception as e:
            self._say(f"Failed to initialize: {e}", error=True)
            self._set_status("init failed — check cookies file")
            return
        boot = self.query_one("#boot", Static)
        if boot:
            await boot.remove()
        models = await self.session.set_model(None)
        self._set_status(
            f"model: {self.session.model or 'account default'} | "
            f"models: {len(models)} | /help for commands"
        )
        self.notify("Connected to Gemini")

    # ---- helpers ----------------------------------------------------

    def _set_status(self, text: str) -> None:
        self.query_one("#status", Static).update(text)

    async def _chat_area(self) -> VerticalScroll:
        return self.query_one("#chat", VerticalScroll)

    async def _say(self, text: str, *, error: bool = False, cls: str = "") -> None:
        area = await self._chat_area()
        style = "msg-err" if error else ""
        await area.mount(
            Static(self._bidi(text), classes=f"msg-meta {style} {cls}".strip())
        )
        area.scroll_end(animate=False)

    async def _say_user(self, text: str) -> None:
        area = await self._chat_area()
        await area.mount(
            Static(f"\nYou:\n{self._bidi(text)}", classes="msg-user")
        )
        area.scroll_end(animate=False)

    async def _say_ai_start(self) -> Markdown:
        area = await self._chat_area()
        md = Markdown("", classes="msg-ai")
        await area.mount(md)
        area.scroll_end(animate=False)
        return md

    def _truncate_lines(self, text: str) -> str:
        if self.max_lines <= 0:
            return text
        lines = text.splitlines()
        if len(lines) <= self.max_lines:
            return text
        return "\n".join(lines[: self.max_lines]) + (
            f"\n\n... ({len(lines) - self.max_lines} more lines — "
            f"raise with /lines {self.max_lines * 2} or set 0)"
        )

    def _bidi(self, text: str) -> str:
        """Apply Unicode Bidirectional Algorithm for correct RTL display."""
        try:
            return get_display(text)
        except Exception:
            return text

    # ---- input handling ----------------------------------------------

    @on(ChatInput.Submitted)
    async def on_submit(self, event: ChatInput.Submitted) -> None:
        raw = event.value.strip()
        event.input.clear()
        if not raw:
            return
        # Cookie prompt intercepts input
        if self._cookie_prompt_state:
            await self._handle_cookie_input(raw)
            return
        if raw.startswith("/"):
            await self._handle_command(raw)
        else:
            await self._send_message(raw)

    async def _start_cookie_prompt(self) -> None:
        self._cookie_prompt_state = "psid"
        self._cookie_psid = ""
        self._cookie_psidts = ""
        self._set_status("Cookies: paste __Secure-1PSID value, then Enter")
        await self._say(
            "Cookie setup — paste the value of **__Secure-1PSID** and press Enter.\n"
            "(Find it in DevTools → Application → Cookies → gemini.google.com)"
        )

    async def _handle_cookie_input(self, value: str) -> None:
        if self._cookie_prompt_state == "psid":
            self._cookie_psid = value.strip()
            if not self._cookie_psid:
                await self._say("Empty value — try again.", error=True)
                return
            self._cookie_prompt_state = "psidts"
            self._set_status("Cookies: paste __Secure-1PSIDTS value, then Enter")
            await self._say(
                "Now paste the value of **__Secure-1PSIDTS** and press Enter.\n"
                "(Leave empty and press Enter to skip — some accounts don't have it)"
            )
        elif self._cookie_prompt_state == "psidts":
            self._cookie_psidts = value.strip()
            await self._save_and_apply_cookies()

    async def _save_and_apply_cookies(self) -> None:
        try:
            # Save as Netscape-format file in ~/.gemini-cli/
            cookies_dir = Path.home() / ".gemini-cli"
            cookies_dir.mkdir(parents=True, exist_ok=True)
            cookies_file = cookies_dir / "cookies.txt"

            # Write minimal Netscape format
            lines = [
                "# Netscape HTTP Cookie File",
                f".google.com\tTRUE\t/\tTRUE\t0\t__Secure-1PSID\t{self._cookie_psid}",
            ]
            if self._cookie_psidts:
                lines.append(
                    f".google.com\tTRUE\t/\tTRUE\t0\t__Secure-1PSIDTS\t{self._cookie_psidts}"
                )
            cookies_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

            # Re-init session with new cookies
            self.session = GeminiSession(cookies_file)
            await self.session.init()
            self._cookie_prompt_state = None
            self._set_status("Cookies updated — reconnected")
            await self._say(f"Cookies saved to {cookies_file} and applied.")
        except Exception as e:
            self._cookie_prompt_state = None
            await self._say(f"Failed to apply cookies: {e}", error=True)

    async def _extract_files(self, text: str) -> tuple[str, list[str]]:
        """Pull @path tokens and bare existing paths out of the message."""
        files = list(self.pending_files)
        self.pending_files.clear()
        kept: list[str] = []
        for token in shlex.split(text, posix=False):
            candidate = token[1:] if token.startswith("@") else token
            candidate = candidate.strip("'\"`")
            path = Path(candidate).expanduser()
            if path.is_file():
                files.append(str(path))
            else:
                kept.append(token)
        return " ".join(kept), files

    # ---- commands ----------------------------------------------------

    async def _handle_command(self, raw: str) -> None:
        parts = raw[1:].split(None, 1)
        cmd = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""

        if cmd in ("exit", "quit"):
            self.exit()
        elif cmd == "help":
            await self._say(HELP)
        elif cmd == "clear":
            area = await self._chat_area()
            await area.remove_children()
        elif cmd == "status":
            meta = self.session.current_meta()
            await self._say(
                f"cid: {meta.cid or '(new chat)'}\n"
                f"model: {self.session.model or 'account default'}\n"
                f"temporary: {self.session.temporary}\n"
                f"max lines: {self.max_lines or 'unlimited'}\n"
                f"pending attachments: {len(self.pending_files)}"
            )
        elif cmd == "new":
            self.session.new_chat()
            await self._say("Started a new conversation.")
        elif cmd == "tmp":
            if arg in ("on", "off"):
                self.session.temporary = arg == "on"
            else:
                self.session.temporary = not self.session.temporary
            await self._say(f"Temporary mode: {'ON' if self.session.temporary else 'OFF'}")
        elif cmd == "lines":
            try:
                self.max_lines = max(0, int(arg or "0"))
            except ValueError:
                await self._say("Usage: /lines <n>", error=True)
                return
            await self._say(f"Max reply lines: {self.max_lines or 'unlimited'}")
        elif cmd == "copy":
            if not self.last_response:
                await self._say("Nothing to copy yet.", error=True)
            else:
                copied = False
                # Try pyperclip first (local clipboard)
                try:
                    pyperclip.copy(self.last_response)
                    copied = True
                    await self._say("Copied to clipboard (local).")
                except Exception:
                    pass
                # Try OSC 52 (terminal clipboard, works over SSH)
                if not copied:
                    try:
                        self.set_clipboard(self.last_response)
                        copied = True
                        await self._say("Copied to clipboard (OSC 52).")
                    except Exception:
                        pass
                # Fallback: save to file
                if not copied:
                    OUTPUT_DIR.mkdir(exist_ok=True)
                    name = f"reply_{int(time.time())}.txt"
                    path = OUTPUT_DIR / name
                    path.write_text(self.last_response, encoding="utf-8")
                    await self._say(
                        f"Clipboard unavailable. Saved to {path} instead."
                    )
        elif cmd == "print":
            if not self.last_response:
                await self._say("Nothing to print yet.", error=True)
            else:
                # Write to a temp file and print path — avoids TUI capture issues
                OUTPUT_DIR.mkdir(exist_ok=True)
                name = f"reply_{int(time.time())}.txt"
                path = OUTPUT_DIR / name
                path.write_text(self.last_response, encoding="utf-8")
                await self._say(f"Saved to {path}")
        elif cmd == "attach":
            if not arg:
                await self._say("Usage: /attach <path> [path...]", error=True)
                return
            ok, bad = [], []
            for p in shlex.split(arg):
                fp = Path(p).expanduser()
                (ok if fp.is_file() else bad).append(str(fp))
            self.pending_files.extend(ok)
            msg = f"Attached {len(ok)} file(s)." if ok else ""
            if bad:
                msg += (" " if msg else "") + f"Not found: {', '.join(bad)}"
            await self._say(msg or "No files attached.", error=bool(bad) and not ok)
        elif cmd == "save":
            name = arg or "last"
            cid = self.session.save_chat(name)
            await self._say(f"Chat saved as '{name}' (cid: {cid})")
        elif cmd == "chats":
            saved = self.session.list_saved()
            if not saved:
                await self._say("No saved chats. Use /save <name>.")
            else:
                lines = [f"- {n}  (cid: {v.get('cid','?')[:12]})" for n, v in saved.items()]
                await self._say("Saved chats:\n" + "\n".join(lines))
        elif cmd == "resume":
            if not arg:
                await self._say("Usage: /resume <name>", error=True)
                return
            if self.session.resume_chat(arg):
                await self._say(f"Resumed chat '{arg}'.")
            else:
                await self._say(f"No saved chat named '{arg}'.", error=True)
        elif cmd == "model":
            if not arg:
                await self._say(f"Current model: {self.session.model or 'account default'}")
                return
            try:
                names = await self.session.set_model(arg)
                # model change applies to the NEXT chat
                self.session.new_chat()
                self._set_status(
                    f"model: {self.session.model or 'account default'} | switched to '{arg}'"
                )
                await self._say(
                    f"Switched to '{arg}'. Available: {', '.join(names[:8])}"
                    + (" ..." if len(names) > 8 else "")
                )
            except Exception as e:
                await self._say(f"Unknown model '{arg}': {e}", error=True)
        elif cmd == "models":
            try:
                models = self.session.client.list_models() or []
                lines = [
                    f"- {m.model_name} ({m.display_name})"
                    + ("" if getattr(m, "is_available", True) else " [unavailable]")
                    for m in models
                ]
                await self._say("\n".join(lines) or "No models discovered yet.")
            except Exception as e:
                await self._say(f"Could not list models: {e}", error=True)
        elif cmd == "cookies":
            await self._start_cookie_prompt()
        elif cmd == "history":
            chats = await self.session.list_gemini_chats()
            if not chats:
                await self._say("No chats found in Gemini history.")
            else:
                lines = [
                    f"- {c['cid'][:20]}... | {c['title']}"
                    for c in chats[:20]
                ]
                await self._say(
                    f"Gemini chats ({len(chats)} total):\n" + "\n".join(lines)
                )
        elif cmd == "read":
            if not arg:
                await self._say("Usage: /read <cid>", error=True)
                return
            chat = await self.session.read_gemini_chat(arg)
            if not chat:
                await self._say(f"Chat '{arg}' not found.", error=True)
                return
            for turn in chat["turns"][-10:]:  # last 10 turns
                role = "You" if turn["role"] == "user" else "Gemini"
                await self._say(f"{role}:\n{turn['text'][:500]}")
        elif cmd == "resume-gemini":
            if not arg:
                await self._say("Usage: /resume-gemini <cid>", error=True)
                return
            if await self.session.resume_gemini_chat(arg):
                await self._say(f"Resumed Gemini chat {arg[:20]}...")
            else:
                await self._say(f"Failed to resume chat '{arg}'.", error=True)
        else:
            await self._say(f"Unknown command '/{cmd}'. Try /help.", error=True)

    # ---- messaging ----------------------------------------------------

    async def _send_message(self, raw: str) -> None:
        if self.busy:
            await self._say("Gemini is still replying — press Ctrl+X to cancel.", error=True)
            return
        prompt, files = await self._extract_files(raw)
        if not prompt and not files:
            return
        await self._say_user(raw if not files else f"{prompt}\n[files: {', '.join(Path(f).name for f in files)}]")
        self.busy = True
        self._set_status("Gemini is thinking...  (Ctrl+X to cancel)")
        md = await self._say_ai_start()
        self._worker = self.run_worker(
            self._stream(md, prompt, files), group="chat", exclusive=True
        )

    async def _stream(self, md: Markdown, prompt: str, files: list[str]) -> None:
        full = ""
        try:
            if files:
                # Non-streaming path when files are attached (stream + files
                # works too, but keep it simple and reliable).
                resp = await self.session.send(prompt or "Describe these files.", files=files)
                text = getattr(resp, "text", "") or ""
                self.last_response = text
                full = self._truncate_lines(text)
                md.update(self._bidi(full) or "_(empty response)_")
                await self._handle_rich_output(resp)
            else:
                async for chunk in self.session.send_stream(prompt):
                    delta = getattr(chunk, "text_delta", "") or ""
                    full += delta
                    now = time.monotonic()
                    if now - self._last_stream_update > 0.08:
                        self._last_stream_update = now
                        shown = self._truncate_lines(full)
                        md.update(self._bidi(shown) or "...")
                self.last_response = full
                final = self._truncate_lines(full)
                md.update(self._bidi(final) or "_(empty response)_")
                # final chunk carries full metadata
                try:
                    await self._handle_rich_output(chunk)
                except Exception:
                    pass
        except asyncio.CancelledError:
            md.update((full + "\n\n_(cancelled)_") if full else "_(cancelled)_")
            raise
        except Exception as e:
            md.update(f"**Error:** {e}")
            await self._say(str(e), error=True)
        finally:
            self.busy = False
            meta = self.session.current_meta()
            cid = getattr(meta, "cid", "")
            self._set_status(
                f"model: {self.session.model or 'account default'} | "
                f"cid: {cid[:12] if cid else 'new'} | ready"
            )

    async def _handle_rich_output(self, resp) -> None:
        """Save generated images/videos/audio and report them."""
        OUTPUT_DIR.mkdir(exist_ok=True)
        saved: list[str] = []
        for image in getattr(resp, "images", []) or []:
            try:
                result = await image.save(path=str(OUTPUT_DIR))
                saved.append(str(result))
            except Exception as e:
                saved.append(f"(image save failed: {e})")
        for video in getattr(resp, "videos", []) or []:
            try:
                result = await video.save(path=str(OUTPUT_DIR))
                saved.append(str(result))
            except Exception as e:
                saved.append(f"(video save failed: {e})")
        for media in getattr(resp, "media", []) or []:
            try:
                result = await media.save(path=str(OUTPUT_DIR))
                saved.append(str(result))
            except Exception as e:
                saved.append(f"(media save failed: {e})")
        if saved:
            await self._say("Saved to gemini_output/:\n" + "\n".join(saved))
        thoughts = getattr(resp, "thoughts", None)
        if thoughts:
            text = thoughts if isinstance(thoughts, str) else str(thoughts)
            await self._say(f"_thinking:_\n{text[:2000]}", cls="msg-meta")

    # ---- actions ------------------------------------------------------

    def action_cancel_worker(self) -> None:
        if self._worker and self.busy:
            self._worker.cancel()
            self.notify("Cancelled")

    def on_unmount(self) -> None:
        try:
            asyncio.get_running_loop().create_task(self.session.close())
        except Exception:
            pass


def run() -> None:
    import argparse

    parser = argparse.ArgumentParser(prog="gemini-cli")
    parser.add_argument(
        "--cookies",
        default=None,
        help="Path to cookies export file "
        "(default: ./gemini.google.com_cookies.txt or $GEMINI_COOKIES)",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[2]
    candidates = [
        args.cookies,
        os.environ.get("GEMINI_COOKIES"),
        "gemini.google.com_cookies.txt",  # current directory
        repo_root / "gemini.google.com_cookies.txt",  # repo/install root
        Path.home() / ".gemini-cli" / "gemini.google.com_cookies.txt",
    ]
    cookies = next((str(c) for c in candidates if c and Path(c).is_file()), None)
    if not cookies:
        print(
            "Cookies file not found. Looked in:\n"
            + "\n".join(f"  - {c}" for c in candidates if c)
            + "\nExport cookies from https://gemini.google.com "
            "(Netscape cookies.txt or JSON) and pass --cookies <path>.",
            file=sys.stderr,
        )
        sys.exit(2)

    GeminiTUI(cookies).run()


if __name__ == "__main__":
    run()
