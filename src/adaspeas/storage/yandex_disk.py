from __future__ import annotations

from typing import AsyncIterator

import httpx


class YandexDiskClient:
    def __init__(self, oauth_token: str):
        self._headers = {"Authorization": f"OAuth {oauth_token}"}
        self._base = "https://cloud-api.yandex.net/v1/disk"

    async def get_download_url(self, path: str) -> str:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{self._base}/resources/download",
                headers=self._headers,
                params={"path": path},
            )
            resp.raise_for_status()
            data = resp.json()
            href = data.get("href")
            if not href:
                raise RuntimeError("Yandex Disk: missing href")
            return str(href)

    async def stream_download(self, path: str, chunk_size: int = 1024 * 1024) -> AsyncIterator[bytes]:
        url = await self.get_download_url(path)
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream("GET", url) as resp:
                resp.raise_for_status()
                async for chunk in resp.aiter_bytes(chunk_size):
                    yield chunk
