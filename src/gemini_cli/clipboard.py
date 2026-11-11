"""Clipboard utilities with proper TTY handling for OSC 52.

Follows Gemini CLI's approach: write to /dev/tty when available,
handle tmux/screen passthrough, fall back to stderr/stdout.
"""

from __future__ import annotations

import base64
import os
import sys
from pathlib import Path

ESC = "\x1b"
BEL = "\x07"
OSC52_HEADER = f"{ESC}]52;c;"
OSC52_FOOTER = BEL
MAX_OSC52_DATA_BYTES = 50000  # conservative limit


def _in_tmux() -> bool:
    return bool(
        os.environ.get("TMUX")
        or (os.environ.get("TERM") or "").startswith("tmux")
    )


def _in_screen() -> bool:
    return bool(
        os.environ.get("STY")
        or (os.environ.get("TERM") or "").startswith("screen")
    )


def _is_ssh() -> bool:
    return bool(
        os.environ.get("SSH_TTY")
        or os.environ.get("SSH_CONNECTION")
        or os.environ.get("SSH_CLIENT")
    )


def _is_wsl() -> bool:
    return bool(
        os.environ.get("WSL_DISTRO_NAME")
        or os.environ.get("WSLENV")
        or os.environ.get("WSL_INTEROP")
    )


def _is_windows_terminal() -> bool:
    return sys.platform == "win32" and bool(os.environ.get("WT_SESSION"))


def _get_tty_stream():
    """Get the best stream to write OSC 52 to."""
    # Try /dev/tty first (Unix only) — bypasses TUI capture
    if sys.platform != "win32":
        try:
            tty_path = Path("/dev/tty")
            if tty_path.exists():
                return open(tty_path, "w", encoding="utf-8", errors="replace")
        except Exception:
            pass

    # Fall back to stderr/stdout
    if sys.stderr and hasattr(sys.stderr, "isatty") and sys.stderr.isatty():
        return sys.stderr
    if sys.stdout and hasattr(sys.stdout, "isatty") and sys.stdout.isatty():
        return sys.stdout
    return None


def copy_to_clipboard_osc52(text: str) -> bool:
    """Copy text to clipboard via OSC 52 escape sequence.

    Returns True if the sequence was written successfully.
    """
    stream = _get_tty_stream()
    if not stream:
        return False

    # Truncate if needed (UTF-8 safe)
    encoded = text.encode("utf-8")
    if len(encoded) > MAX_OSC52_DATA_BYTES:
        # Truncate on UTF-8 boundary
        truncated = encoded[:MAX_OSC52_DATA_BYTES]
        while truncated and (truncated[-1] & 0xC0) == 0x80:
            truncated = truncated[:-1]
        text = truncated.decode("utf-8", errors="ignore")

    b64 = base64.b64encode(text.encode("utf-8")).decode("ascii")
    seq = f"{OSC52_HEADER}{b64}{OSC52_FOOTER}"

    try:
        # Handle tmux passthrough (wrap in DCS, double ESC)
        if _in_tmux():
            dcs_seq = f"\x1bPtmux;\x1b{seq.replace(ESC, ESC + ESC)}\x1b\\"
            stream.write(dcs_seq)
        # Handle screen passthrough (wrap in DCS, chunk)
        elif _in_screen():
            # Screen needs chunked DCS
            chunk_size = 240
            for i in range(0, len(seq), chunk_size):
                chunk = seq[i : i + chunk_size]
                stream.write(f"\x1bP{chunk}\x1b\\")
        else:
            stream.write(seq)

        stream.flush()
        # Close if we opened /dev/tty
        if hasattr(stream, "close") and str(getattr(stream, "name", "")) == "/dev/tty":
            stream.close()
        return True
    except Exception:
        return False


def copy_to_clipboard(text: str) -> tuple[bool, str]:
    """Try multiple clipboard methods. Returns (success, method_used)."""
    # Try pyperclip first (local clipboard)
    try:
        import pyperclip
        pyperclip.copy(text)
        return True, "pyperclip"
    except Exception:
        pass

    # Try OSC 52 (works over SSH, tmux, screen, Azure Cloud Shell)
    if copy_to_clipboard_osc52(text):
        return True, "osc52"

    return False, "none"
