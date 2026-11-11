"""Async wrapper around gemini_webapi for the TUI."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from gemini_webapi import GeminiClient

from .cookies import parse_cookies

CHATS_DIR = Path.home() / ".gemini-cli" / "chats"


@dataclass
class SessionMeta:
    cid: str = ""
    metadata: dict = field(default_factory=dict)


class GeminiSession:
    def __init__(self, cookies_path: str | Path):
        psid, psidts = parse_cookies(cookies_path)
        self.client = GeminiClient(psid, psidts, proxy=None)
        self.chat = None
        self.model: str | None = None
        self.temporary = False
        self._initialized = False

    async def init(self) -> None:
        await self.client.init(timeout=30, auto_close=False, auto_refresh=True)
        self._initialized = True
        self.new_chat()

    def new_chat(self, metadata: dict | None = None) -> None:
        kwargs = {}
        if metadata:
            kwargs["metadata"] = metadata
        if self.model:
            kwargs["model"] = self.model
        self.chat = self.client.start_chat(**kwargs)

    def current_meta(self) -> SessionMeta:
        meta = getattr(self.chat, "metadata", None) or {}
        cid = getattr(self.chat, "cid", "") or ""
        return SessionMeta(cid=str(cid), metadata=meta if isinstance(meta, dict) else {})

    async def set_model(self, name: str | None) -> list[str]:
        models = self.client.list_models() or []
        names = [m.model_name for m in models if getattr(m, "is_available", True)]
        if name:
            resolved = self.client.resolve_model(name)
            self.model = getattr(resolved, "model_name", name)
        else:
            self.model = None
        return names

    async def send(self, prompt: str, files: list[str | Path] | None = None):
        kwargs = {"temporary": self.temporary}
        if files:
            kwargs["files"] = [str(f) for f in files]
        return await self.chat.send_message(prompt, **kwargs)

    async def send_stream(self, prompt: str, files: list[str | Path] | None = None):
        kwargs = {"temporary": self.temporary}
        if files:
            kwargs["files"] = [str(f) for f in files]
        async for chunk in self.chat.send_message_stream(prompt, **kwargs):
            yield chunk

    # ---- persistence -------------------------------------------------

    @staticmethod
    def _chats_file() -> Path:
        CHATS_DIR.mkdir(parents=True, exist_ok=True)
        return CHATS_DIR / "chats.json"

    @staticmethod
    def list_saved() -> dict:
        f = GeminiSession._chats_file()
        if not f.is_file():
            return {}
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            return {}

    @staticmethod
    def _write_saved(data: dict) -> None:
        GeminiSession._chats_file().write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def save_chat(self, name: str) -> str:
        meta = self.current_meta()
        data = self.list_saved()
        data[name] = {"cid": meta.cid, "metadata": meta.metadata, "model": self.model}
        self._write_saved(data)
        return meta.cid

    def resume_chat(self, name: str) -> bool:
        data = self.list_saved()
        entry = data.get(name)
        if not entry:
            return False
        if self.model is None and entry.get("model"):
            self.model = entry["model"]
        self.new_chat(metadata=entry.get("metadata") or None)
        return True

    async def delete_remote_chat(self) -> None:
        cid = getattr(self.chat, "cid", None)
        if cid:
            try:
                await self.client.delete_chat(cid)
            except Exception:
                pass

    async def close(self) -> None:
        try:
            await self.client.close()
        except Exception:
            pass
