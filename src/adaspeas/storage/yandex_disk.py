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


    async def list_dir(self, path: str) -> list[dict]:
        """List items in a Yandex.Disk folder (one level), with pagination.

        The API supports limit/offset; the default limit is small.
        We use a larger limit and paginate until all items are fetched.
        """
        out: list[dict] = []
        limit = 200
        offset = 0
        async with httpx.AsyncClient(timeout=30.0) as client:
            while True:
                resp = await client.get(
                    f"{self._base}/resources",
                    headers=self._headers,
                    params={"path": path, "limit": limit, "offset": offset},
                )
                resp.raise_for_status()
                data = resp.json()
                embedded = data.get("_embedded") or {}
                items = embedded.get("items") or []
                if not items:
                    break
                out.extend(list(items))
                if len(items) < limit:
                    break
                offset += limit
        return out

    async def stream_download(self, path: str, chunk_size: int = 1024 * 1024) -> AsyncIterator[bytes]:
        url = await self.get_download_url(path)
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream("GET", url) as resp:
                resp.raise_for_status()
                async for chunk in resp.aiter_bytes(chunk_size):
                    yield chunk
