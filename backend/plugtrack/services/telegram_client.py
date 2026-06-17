# backend/plugtrack/services/telegram_client.py
"""Minimal async Telegram Bot API client over httpx.

Only the methods the ingest loop needs: long-poll getUpdates, getFile +
file download, sendMessage (with inline keyboard), and answerCallbackQuery.
"""
from __future__ import annotations

from typing import Any, Optional

import httpx

API = "https://api.telegram.org"


class TelegramClient:
    def __init__(self, token: str, http: Optional[httpx.AsyncClient] = None) -> None:
        self._token = token
        self._http = http or httpx.AsyncClient(timeout=70)
        self._owns = http is None

    async def aclose(self) -> None:
        if self._owns:
            await self._http.aclose()

    def _url(self, method: str) -> str:
        return f"{API}/bot{self._token}/{method}"

    async def get_updates(self, *, offset: int, timeout: int = 50) -> list[dict[str, Any]]:
        params = {"offset": offset, "timeout": timeout, "allowed_updates": '["message","callback_query"]'}
        resp = await self._http.get(self._url("getUpdates"), params=params)
        resp.raise_for_status()
        return resp.json().get("result", [])

    async def get_file_path(self, file_id: str) -> str:
        resp = await self._http.get(self._url("getFile"), params={"file_id": file_id})
        resp.raise_for_status()
        return resp.json()["result"]["file_path"]

    async def download_file(self, file_path: str) -> bytes:
        resp = await self._http.get(f"{API}/file/bot{self._token}/{file_path}")
        resp.raise_for_status()
        return resp.content

    async def send_message(
        self, *, chat_id: int, text: str, reply_markup: Optional[dict[str, Any]] = None
    ) -> Optional[int]:
        body: dict[str, Any] = {"chat_id": chat_id, "text": text}
        if reply_markup is not None:
            body["reply_markup"] = reply_markup
        resp = await self._http.post(self._url("sendMessage"), json=body)
        resp.raise_for_status()
        return (resp.json().get("result") or {}).get("message_id")

    async def edit_message_text(
        self, *, chat_id: int, message_id: int, text: str,
        reply_markup: Optional[dict[str, Any]] = None,
    ) -> None:
        body: dict[str, Any] = {"chat_id": chat_id, "message_id": message_id, "text": text}
        if reply_markup is not None:
            body["reply_markup"] = reply_markup
        resp = await self._http.post(self._url("editMessageText"), json=body)
        resp.raise_for_status()

    async def get_me(self) -> dict[str, Any]:
        resp = await self._http.get(self._url("getMe"))
        resp.raise_for_status()
        return resp.json().get("result", {})

    async def answer_callback(self, callback_id: str, text: str = "") -> None:
        resp = await self._http.post(
            self._url("answerCallbackQuery"), json={"callback_query_id": callback_id, "text": text}
        )
        resp.raise_for_status()
